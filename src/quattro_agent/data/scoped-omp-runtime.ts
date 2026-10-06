/** OMP-only SDK bootstrap. Deployment pins Bun and the official package closure.
 * No Pi SDK, ambient tools, extensions, MCP, commands, or host approval bypass.
 */
import { isAbsolute, join, resolve, relative } from "node:path";
import { pathToFileURL } from "node:url";
import { lstatSync, readFileSync, realpathSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";

function verifiedCatalog(manifestPath: string, catalogRoot: string, manifestDigest: string) {
  const hash = (path: string) => {
    if (!isAbsolute(path) || realpathSync(path) !== path) throw new Error();
    for (let part = path; ; part = resolve(part, "..")) {
      if (lstatSync(part).isSymbolicLink()) throw new Error();
      if (resolve(part, "..") === part) break;
    }
    const info = lstatSync(path);
    if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid!() || (info.mode & 0o022) || info.size > 16 * 1024 * 1024) throw new Error();
    return createHash("sha256").update(readFileSync(path)).digest("hex");
  };
  if (!/^[a-f0-9]{64}$/.test(manifestDigest) || hash(manifestPath) !== manifestDigest || realpathSync(catalogRoot) !== catalogRoot) throw new Error();
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (manifest.version !== 1 || !Array.isArray(manifest.skills) || !manifest.skills.length || manifest.skills.length > 4096) throw new Error();
  const expected = new Map<string, { path: string; files: Record<string, string> }>();
  for (const entry of manifest.skills) {
    const name = entry.omp_name;
    if (typeof name !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(name) || expected.has(name) || entry.staged !== join(catalogRoot, name)) throw new Error();
    const files = { ...entry.files };
    if (files["SKILL.md"] !== entry.staged_loader_sha256) {
      if (Object.hasOwn(files, "SKILL.original.md")) throw new Error();
      files["SKILL.original.md"] = files["SKILL.md"];
    }
    files["SKILL.md"] = entry.staged_loader_sha256;
    for (const [name, digest] of Object.entries(files)) {
      if (isAbsolute(name) || name.includes("\\") || name.split("/").some(part => !part || part === "." || part === ".." || ["auth.json", "auth.db", "credentials.json", ".env", "sessions", "history", "prompts", "responses"].includes(part.toLowerCase())) || !/^[a-f0-9]{64}$/.test(String(digest))) throw new Error();
    }
    expected.set(name, { path: entry.staged, files });
  }
  const verify = () => {
    if (hash(manifestPath) !== manifestDigest || readdirSync(catalogRoot).sort().join("\0") !== [...expected.keys()].sort().join("\0")) throw new Error();
    for (const entry of expected.values()) {
      const found: string[] = [];
      const walk = (directory: string) => {
        for (const name of readdirSync(directory)) {
          const path = join(directory, name), info = lstatSync(path);
          if (info.isSymbolicLink()) throw new Error();
          if (info.isDirectory()) walk(path);
          else if (info.isFile()) found.push(relative(entry.path, path));
          else throw new Error();
        }
      };
      walk(entry.path);
      if (found.sort().join("\0") !== Object.keys(entry.files).sort().join("\0")) throw new Error();
      for (const [name, digest] of Object.entries(entry.files)) if (hash(join(entry.path, name)) !== digest) throw new Error();
    }
  };
  verify();
  return { expected, verify };
}

async function main() {
  const [root, cwd, agentDir, sessionDir, manifestPath, catalogRoot, manifestDigest] = process.argv.slice(2);
  if (![6, 9].includes(process.argv.length) || ![root, cwd, agentDir, sessionDir].every(p => p && isAbsolute(p)) || cwd !== process.cwd()) throw new Error();
  const metadata = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  if (metadata.name !== "@oh-my-pi/pi-coding-agent" || metadata.version !== "18.6.3") throw new Error();
  const sdk = await import(pathToFileURL(join(root, "src/index.ts")).href);
  sdk.logger.setTransports({ file: false, console: false });
  const utils = await import(Bun.resolveSync("@oh-my-pi/pi-utils", join(root, "src")));
  const logs = utils.getLogsDir();
  const info = lstatSync(logs);
  if (logs !== resolve(process.env.HOME!, ".omp/logs") || realpathSync(logs) !== logs || !info.isFile() || info.nlink !== 1 || info.uid !== process.getuid!() || (info.mode & 0o777) !== 0o600) throw new Error();
  const { runRpcMode } = await import(pathToFileURL(join(root, "src/modes/rpc/rpc-mode.ts")).href);
  const settings = sdk.Settings.isolated({
    "advisor.enabled": false, "autolearn.enabled": false,
    "includeWorkspaceTree": false, "providers.cacheWarming": "off",
    "skills.enableSkillCommands": Boolean(manifestPath),
  });
  const catalog = manifestPath ? verifiedCatalog(manifestPath, catalogRoot, manifestDigest) : undefined;
  const loaded = catalog ? await sdk.loadSkillsFromDir({ dir: catalogRoot, source: "custom:user" }) : { skills: [], warnings: [] };
  if (loaded.warnings.length || loaded.skills.length !== (catalog?.expected.size ?? 0)) throw new Error();
  for (const skill of loaded.skills) {
    if (skill.filePath !== join(catalog!.expected.get(skill.name)?.path ?? "", "SKILL.md")) throw new Error();
  }
  // The native runtime owns native auth. No Pi/Codex credential migration.
  const authStorage = await sdk.discoverAuthStorage(agentDir, { settings, cwd });
  const modelRegistry = new sdk.ModelRegistry(authStorage, undefined, {
    settings, ignoreLocalModelConfig: true,
  });
  const model = modelRegistry.find("openai-codex", "gpt-6.1-sol");
  if (!model || model.api !== "openai-codex-responses") throw new Error();
  const { session, modelFallbackMessage } = await sdk.createAgentSession({
    cwd, agentDir, settings, authStorage, modelRegistry, model,
    thinkingLevel: "medium", sessionManager: sdk.SessionManager.inMemory(cwd),
    toolNames: [], restrictToolNames: true, enableMCP: false, enableLsp: false,
    disableExtensionDiscovery: true, preloadedPreparedExtensions: [],
    skills: loaded.skills, rules: [], contextFiles: [], promptTemplates: [], slashCommands: [],
    spawns: "", hasUI: false, autoApprove: false,
  });
  const boundId = session.sessionId;
  const matches = () => session.sessionId === boundId && session.model?.provider === "openai-codex" && session.model?.id === "gpt-6.1-sol" && session.thinkingLevel === "medium";
  if (modelFallbackMessage || !matches() || session.getActiveToolNames().length) throw new Error();
  const guard = () => {
    const current = lstatSync(logs);
    if (current.dev !== info.dev || current.ino !== info.ino || !current.isFile() || !matches()) throw new Error("fixed Quattro route required");
    catalog?.verify();
  };
  const prompt = session.prompt.bind(session);
  session.prompt = async (text: string, ...rest: any[]) => {
    guard();
    // Known skill commands use OMP's native promptCustomMessage branch. All
    // slash commands reaching ordinary prompt are denied, including unknowns.
    if (typeof text !== "string" || text.trimStart().startsWith("/") || text.trimStart().startsWith("!") || /(^|\s)\^[^\s]+/.test(text)) throw new Error("fixed Quattro route required");
    return prompt(text, ...rest);
  };
  const customPrompt = session.promptCustomMessage.bind(session);
  session.promptCustomMessage = async (...args: any[]) => { guard(); return customPrompt(...args); };
  await runRpcMode(session, { headless: true });
}
main().catch(() => { process.stderr.write("Closed OMP runtime unavailable.\n"); process.exit(125); });
