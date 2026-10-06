/** Quattro-owned bounded test recovery. Pi sees results; Python owns commands. */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const helper = fileURLToPath(new URL("../tool_cli.py", import.meta.url));

export default function quattroRecovery(pi: ExtensionAPI) {
  if (process.env.QUATTRO_TEST_ALLOWED !== "1") return;
  pi.registerTool({
    name: "quattro_test", label: "Quattro test",
    description: "Run one unit test file in tests/. Supply test_flaky.py or tests/test_flaky.py, never an absolute path. Run one bounded invocation; failures return to the native model for a decision-specific follow-up.",
    promptSnippet: "Use quattro_test to run an existing tests/test_*.py file when validating work.",
    parameters: Type.Object({ test_file: Type.String({ pattern: "^(tests/)?test_[A-Za-z0-9_]{1,60}\\.py$" }) }),
    async execute(_id, params, signal) {
      const environment: NodeJS.ProcessEnv = {};
      for (const name of ["PATH", "HOME", "XDG_CONFIG_HOME", "QUATTRO_PYTHON",
                          "QUATTRO_JEV_TEST_MODE", "QUATTRO_TEST_ALLOWED"]) {
        if (process.env[name]) environment[name] = process.env[name];
      }
      const child = spawn(process.env.QUATTRO_PYTHON || "/usr/bin/python3", [helper],
        { cwd: process.cwd(), env: environment,
        stdio: ["pipe", "pipe", "ignore"] });
      let output = "";
      const done = new Promise<string>((resolve) => {
        child.stdout.on("data", (data: Buffer) => { if (output.length < 65536) output += data.toString(); });
        child.on("error", () => resolve(""));
        child.on("close", () => resolve(output));
      });
      const timeout = setTimeout(() => child.kill("SIGKILL"), 45000);
      signal?.addEventListener("abort", () => child.kill("SIGKILL"), { once: true });
      child.stdin.end(JSON.stringify({ tool: "test", test_file: params.test_file }));
      const raw = await done;
      clearTimeout(timeout);
      let result: any;
      try { result = JSON.parse(raw); } catch { result = { status: "error", fallback: "helper_failure" }; }
      return { content: [{ type: "text" as const, text: JSON.stringify(result) }],
        isError: result.status === "error" || result.status === "invalid" };
    },
  });
}
