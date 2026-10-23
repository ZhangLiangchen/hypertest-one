import type { LocalHarness } from "@/lib/local-mode-install";

export const TASK_BINDING_CLIENT_SOURCE_COMMIT = "86f7659254cf2253de6376e64b287352e6df7f89";

export type BindingClientOptions = { sourceCommit: string; venvDirectory: string; installDirectory: string; clientConfig: string; harness: LocalHarness };

function quote(value: string): string { return "'" + value.replace(/'/g, "'\"'\"'") + "'"; }
function privatePath(value: string): string {
  if (!value.startsWith("/") || value === "/" || value !== value.trim() || value.length > 2048 || /[\u0000-\u001f\u007f]/.test(value)) throw new Error("absolute-private-path");
  return value.replace(/\/$/, "");
}

/** Commands are displayed for explicit execution; the browser reads no private file. */
export function taskBindingClientCommands(options: BindingClientOptions) {
  if (!/^[a-f0-9]{40}$/.test(options.sourceCommit)) throw new Error("fixed-source-commit-required");
  if (options.harness !== "codex") throw new Error("task-binding-host-unsupported");
  const venv = privatePath(options.venvDirectory);
  const directory = privatePath(options.installDirectory);
  const config = privatePath(options.clientConfig);
  if (venv === directory || venv === config || directory === config) throw new Error("distinct-private-paths");
  const python = quote(`${venv}/bin/python`);
  const spec = `hypertest-one[interactive] @ git+https://github.com/ZhangLiangchen/hypertest-one.git@${options.sourceCommit}`;
  const capabilityCheck = [
    "import json, sys",
    "doc = json.load(sys.stdin)",
    "local = doc.get('local_capabilities', {})",
    "caller = local.get('task_binding_callers', {}).get('codex', {})",
    "tools = {item.get('name'): item for item in doc.get('tools', []) if isinstance(item, dict)}",
    "required = {'hypertest_bind_task', 'hypertest_get_task_binding', 'hypertest_get_task', 'hypertest_sync_task'}",
    "ok = (local.get('explicit_task_binding') is True and local.get('query_only_binding_recovery') is True and local.get('target_task_id_reads') is True and caller.get('support') == 'NATIVE_THREAD_ID_REQUIRED' and caller.get('harness_version') == '0.144.6' and caller.get('metadata_key') == 'threadId' and caller.get('per_call_check') is True and required <= tools.keys() and 'task_id' in tools.get('hypertest_get_task', {}).get('inputSchema', {}).get('properties', {}))",
    "print('CONFIGURATION_SUPPORTED; CURRENT_NATIVE_MCP_CALL_STILL_REQUIRED' if ok else 'CONFIGURATION_UNSUPPORTED')",
    "sys.exit(0 if ok else 1)",
  ].join("\n");
  return {
    prepare: ["(", "set -eu", "umask 077", `if [ -e ${quote(venv)} ]; then`, "  printf '%s\\n' 'Choose a new private virtual environment directory.' >&2", "  exit 1", "fi", `python3.13 -m venv ${quote(venv)}`, `${python} -m pip install ${quote(spec)}`, ")"].join("\n"),
    stop: `${python} -I -m hypertest.interactive_client stop --config ${quote(config)}`,
    upgrade: `${python} -I -m hypertest.local_sync upgrade-owned --directory ${quote(directory)} --harness ${options.harness} --version local-v0.1.0-source.${options.sourceCommit} --python ${python}`,
    capabilities: `${python} -I -m hypertest.local_sync capabilities --config ${quote(config)} | ${python} -I -c ${quote(capabilityCheck)}`,
  };
}
