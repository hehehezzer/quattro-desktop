/** Pi 0.87 input interception: every submitted turn is consumed before agent startup.
 * Only the private Quattro server executes requests. Never throw from input: Pi's
 * extension runner catches errors and otherwise falls through to its native agent.
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export default function quattroTurnGate(pi: ExtensionAPI) {
  const rawURL = process.env.QUATTRO_TURN_GATE_URL;
  const token = process.env.QUATTRO_TURN_GATE_TOKEN;
  let endpoint: string | undefined;
  try {
    const url = new URL(rawURL || "");
    if (url.protocol === "http:" && url.hostname === "127.0.0.1" && url.port &&
        !url.username && !url.password && url.pathname === "/" && !url.search && !url.hash && token) {
      endpoint = url.origin;
    }
  } catch { /* Missing configuration fails closed at input. */ }
  let active: { controller: AbortController; sessionId: string; requestId: string } | undefined;
  let unsubscribe: (() => void) | undefined;
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token || ""}` };
  const notify = (ctx: ExtensionContext, text: string) => {
    try { ctx.ui.notify(text, "error"); } catch { /* Rendering cannot reopen input. */ }
  };
  const history = (ctx: ExtensionContext) => {
    const entries = ctx.sessionManager.getBranch?.() || [];
    const turns: { role: string; content: string }[] = [];
    let size = 0;
    let count = 0;
    for (let i = entries.length - 1; i >= 0 && count < 6; i--) {
      const entry = entries[i];
      if (entry.type !== "custom_message" || entry.customType !== "quattro-turn" ||
          typeof entry.content !== "string") continue;
      const chars = (entry.details as { questionChars?: number } | undefined)?.questionChars;
      if (!Number.isInteger(chars) || !chars || chars < 0 || chars >= entry.content.length ||
          entry.content.slice(chars, chars + 2) !== "\n\n") continue;
      if (size + entry.content.length > 32000) break;
      turns.unshift({ role: "user", content: entry.content.slice(0, chars) },
        { role: "assistant", content: entry.content.slice(chars + 2) });
      size += entry.content.length;
      count++;
    }
    return turns;
  };
  const cancel = async () => {
    const turn = active;
    if (!turn) return;
    turn.controller.abort();
    // Keep the busy guard until /turn settles; never overlap session turns.
    try {
      await fetch(`${endpoint}/cancel`, {
        method: "POST", headers, body: JSON.stringify({ session_id: turn.sessionId, request_id: turn.requestId }),
        signal: AbortSignal.timeout(5000), redirect: "error",
      });
    } catch { /* Server independently bounds work; never expose transport errors. */ }
  };
  pi.on("session_start", async (_event, ctx) => {
    pi.setActiveTools([]);
    unsubscribe?.();
    if (ctx.mode === "tui") {
      unsubscribe = ctx.ui.onTerminalInput((data) => {
        if (active && (data === "\u001b" || data === "\u0003")) {
          void cancel();
          return { consume: true };
        }
        return undefined;
      });
    }
  });
  pi.on("session_shutdown", async () => { unsubscribe?.(); await cancel(); });
  // Builtin maintenance must not start an unclassified native model/tool turn.
  pi.on("session_before_switch", async (event, ctx) => {
    if (event.reason === "new") {
      notify(ctx, "Start a new routed Pi session from Quattro to preserve conversation history.");
      return { cancel: true };
    }
    return undefined;
  });
  pi.on("session_before_fork", async (_event, ctx) => {
    notify(ctx, "Start a new routed Pi session from Quattro; native forks cannot persist routed-only history.");
    return { cancel: true };
  });
  pi.on("session_before_compact", async () => ({ cancel: true }));
  pi.on("session_before_tree", async () => ({ cancel: true }));
  pi.on("tool_call", async () => ({ block: true, reason: "Submit tool work through the Quattro turn gate." }));
  pi.on("cache_warming_decision", async () => ({ action: "stop" }));
  pi.on("user_bash", async () => ({ result: {
    output: "Quattro requires shell work to be submitted as a routed request.",
    exitCode: 1, cancelled: false, truncated: false,
  } }));
  pi.on("input", async (event, ctx) => {
    let turn: typeof active;
    try {
      if (!endpoint || !token) throw new Error("configuration");
      if (active) {
        notify(ctx, "A Quattro turn is active. Cancel it with Escape before submitting another turn.");
        return { action: "handled" };
      }
      if (event.images?.length) {
        notify(ctx, "Quattro's turn gate currently accepts text requests only.");
        return { action: "handled" };
      }
      if (!event.text.trim() || event.text.length > 131072) throw new Error("input bounds");
      turn = { controller: new AbortController(), sessionId: ctx.sessionManager.getSessionId(), requestId: crypto.randomUUID() };
      active = turn;
      ctx.ui.setWidget("quattro-sensitive-answer", undefined);
      ctx.ui.setStatus("quattro-turn", "Quattro is routing and executing this turn · Escape cancels");
      const response = await fetch(`${endpoint}/turn`, {
        method: "POST", headers,
        body: JSON.stringify({ frontend: "pi", session_id: turn.sessionId, request_id: turn.requestId, prompt: event.text, history: history(ctx) }),
        signal: turn.controller.signal, redirect: "error",
      });
      if (!response.ok) throw new Error("request failed");
      const payload = await response.json();
      if (turn.controller.signal.aborted) return { action: "handled" };
      if (!payload || !["DIRECT", "DELEGATE"].includes(payload.decision) ||
          typeof payload.response !== "string" || payload.response.length > 1048576 ||
          typeof payload.sensitive !== "boolean") throw new Error("invalid response");
      if (payload.sensitive) {
        // Widgets are transient: no prompt, answer, or credential reaches session JSONL.
        ctx.ui.setWidget("quattro-sensitive-answer", payload.response.split("\n"));
      } else {
        pi.sendMessage({ customType: "quattro-turn", content: event.text + "\n\n" + payload.response,
          display: true, details: { decision: payload.decision, questionChars: event.text.length } }, { triggerTurn: false });
      }
    } catch {
      notify(ctx, turn?.controller.signal.aborted ? "Quattro turn cancelled." :
        "Quattro could not complete this turn. No native Pi agent was started.");
    } finally {
      if (turn && active === turn) {
        active = undefined;
        try { ctx.ui.setStatus("quattro-turn", undefined); } catch { /* Fail closed. */ }
      }
    }
    return { action: "handled" };
  });
}
