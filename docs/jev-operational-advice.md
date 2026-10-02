# Jev operational advice

This implementation adds conservative advice, not a permission system or model
selector. Native host permissions, scoped retrieval, owner approvals, mandatory
checks and locked Quattro model plans remain authoritative.

## Coverage

- Codex: explicit `operational_guard` MCP tool for `preflight`, `rag`, `feedback`
  and `task`. This standalone MCP adapter does not install automatic tool interception.
  Its advice and loop feedback are voluntary. Codex 0.158 supports native hooks,
  but those hooks alone are not a complete enforcement boundary. MCP `search_knowledge` can apply
  advice to its own retrieval call; other Codex tools are not intercepted.
- Unmanaged Pi: supported `tool_call` can block a risky tool; `tool_result`
  hashes input/output locally and reports categorical failure or unchanged
  results. Three identical observations consult Jev once; a changed-plan or
  owner recommendation blocks that exact input until the session changes.
  The model receives intervention context. Managed Pi skips these hooks.
- Qiro: permitted project retrieval gets advice before search; uncertainty
  narrows to two results and 2,000 tokens. Its existing worker approval path
  gets a launch preflight after deterministic admission, before creating a
  process. This is a worker-launch boundary, not interception of tools inside
  a managed worker. Controlled isolated workers now use a separate mandatory host action relay
  and audited native receipt hooks; see the Hermes `GATED_WORKERS.md` for
  the strict tool coverage and conservative fallback policy.
- Lumi/parent: explicit local `host/consult_task.py --features '<boolean JSON>'`
  is a no-call preview. Add `--live` to request one consultation through the
  existing approved local DecisionSession. It does not change the cloud base
  model or intercept cloud tools. No persistent activation is needed for this
  explicit entry point.

## Data and strategies

Only allowlisted booleans, existing decision categories, phase and categorical
outcomes reach Jev. Prompts, code, tool arguments, output, paths, identifiers and
loop hashes never reach it. Hashes exist only in bounded session memory.
Advice uses existing supported `progress_strategy`, `context_strategy` and
`retry_strategy` choices. Provider output is checked for confidence, category,
finite values and existing hard constraints. It cannot invent a command, query,
source scope or permission.

`preflight` translates advice into proceed, safer alternative or ask owner.
Host denial stops without a call; sensitive/destructive work without owner
approval asks owner without a call. Opaque tools cannot receive a proceed grant.
Pi treats unknown tools and shell commands as opaque, conservatively blocking
them when this hook is enabled. Users should not enable this bundle expecting
automatic shell approval.

`rag` can stop, retain the existing bounded search, or narrow its budget/count.
Narrow advice uses local lexical refinement of the already-permitted query
(deduplicated terms, at most 24). Jev sees neither query nor terms and cannot
invent refinements. Semantic rewriting from private source content remains
unsupported. Enough-evidence boolean can stop further
retrieval; neither Pi nor Qiro claims automatic semantic evidence sufficiency.
Retrieved instructions remain untrusted and cannot set operational flags.

`feedback` never automatically retries. It recommends changing the plan or
asking owner after three same-signature failures/unchanged outcomes. Identical
consultations are suppressed and categorical advice has a 30-second cache and
failure cooldown; there is no global application call cap.
This is a synthetic intervention policy, not proof of improved real coding.

## Exact activation bundle requiring review

The following standalone activation bundle was separately approved in the
existing deployment. New installations still require that exact scope. The
controlled Qiro worker update preserves those grants:

1. Install the reviewed Quattro modules, shared helper/MCP adapter and Pi
   extension together; reload affected native sessions.
2. Set only `operationalEnabled: true` in native-intelligence.json.
3. Deploy the reviewed Qiro host source and set only
   `operational_jev_approved: true` in its private policy, then restart broker.

Keep existing Jev minimal-feature approval, owner/channel/project scope,
provider subscriptions, credentials and routing configuration unchanged.
Activation introduces persistent preflight and loop hooks, extra eligible Jev
calls, retrieval narrowing and conservative tool blocking. Approve that exact
behavior before installation. Do not copy staged source into runtime as a test.

## Evidence

Synthetic tests cover forged inputs, host denial, unavailable/uncertain advice,
retrieval denial/narrowing, session separation, recursive calls and loop
intervention versus an eight-failure baseline. Metadata distinguishes eligible,
requested, called, accepted and applied; returning accepted advice alone does
not prove application or model reliance. Live provider calls and real native
recovery remain unproven for these new hooks.
