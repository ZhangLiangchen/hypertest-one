import type { LocalHarness } from "@/lib/local-mode-install";

export type BindingClientOptions = { sourceCommit: string; venvDirectory: string; installDirectory: string; clientConfig: string; harness: LocalHarness };

function quote(value: string): string { return "'" + value.replace(/'/g, "'\"'\"'") + "'"; }
function privatePath(value: string): string {
  if (!value.startsWith("/") || value === "/" || value !== value.trim() || value.length > 2048 || /[\u0000-\u001f\u007f]/.test(value)) throw new Error("absolute-private-path");
  return value.replace(/\/$/, "");
}

/** Commands are displayed for explicit execution; the browser reads no private file. */
export function taskBindingClientCommands(options: BindingClientOptions) {
  if (!/^[a-f0-9]{40}$/.test(options.sourceCommit)) throw new Error("fixed-source-commit-required");
  if (!["codex", "claude-code", "deepseek-harness"].includes(options.harness)) throw new Error("harness");
  const venv = privatePath(options.venvDirectory);
  const directory = privatePath(options.installDirectory);
  const config = privatePath(options.clientConfig);
  if (venv === directory || venv === config || directory === config) throw new Error("distinct-private-paths");
  const python = quote(`${venv}/bin/python`);
  const spec = `hypertest-one[interactive] @ git+https://github.com/ZhangLiangchen/hypertest-one.git@${options.sourceCommit}`;
  return {
    prepare: ["(", "set -eu", "umask 077", `if [ -e ${quote(venv)} ]; then`, "  printf '%s\\n' 'Choose a new private virtual environment directory.' >&2", "  exit 1", "fi", `python3.13 -m venv ${quote(venv)}`, `${python} -m pip install ${quote(spec)}`, ")"].join("\n"),
    stop: `${python} -I -m hypertest.interactive_client stop --config ${quote(config)}`,
    upgrade: `${python} -I -m hypertest.local_sync upgrade-owned --directory ${quote(directory)} --harness ${options.harness} --version local-v0.1.0-source.${options.sourceCommit} --python ${python}`,
    capabilities: `${python} -I -m hypertest.local_sync capabilities --config ${quote(config)}`,
  };
}
