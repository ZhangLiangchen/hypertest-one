"""Build a pinned, private SDK overlay for the native Cordis preset.

The SDK profile does not run the Web session controller that mounts presets.
This overlay selects the exact official preset from the pinned SDK's shipped
Web profile, and installs a root-only agent-created listener.  The caller must
check the listener's private registration receipt before sending a prompt.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

import yaml

from .errors import CloudBlocked

_RUNTIME_SHA256 = "949a925e1e9f1aaf40c6a7e6365197895ccecb87a4c489ea1d8ceb77a6bcf415"
_DISABLE_BASE = (
    "tool-bash", "tool-pwsh", "tool-jobs", "tool-fs", "tool-fs-search",
    "skill-filesystem", "tool-skill", "command-goal", "tool-goal", "plan-mode",
    "compaction-basic", "command-compact", "tool-result-pruner", "tool-subagent-control",
    "tool-subagent", "tool-subagent-fork", "tool-workflow", "tool-ask-user", "tool-todo",
    "tool-web",
)

_HOOK = r'''import {openSync, writeFileSync, closeSync} from "node:fs";
import {isAbsolute} from "node:path";
export const name = "hypertest-cordis-root";
export const inject = ["agentPresets", "sessionProjections", "sessionTitle"];
export function apply(ctx, config) {
  const root = process.env.DSH_SDK_CORDIS_ROOT;
  const nonce = process.env.DSH_SDK_CORDIS_NONCE;
  const receipt = process.env.DSH_SDK_CORDIS_HANDSHAKE;
  if (!root || !/^[0-9a-f]{64}$/.test(nonce || "") || !receipt || !isAbsolute(receipt) ||
      typeof config?.title !== "string" || !config.title.trim()) {
    throw new Error("Cordis admission context unavailable");
  }
  ctx.on("agent/created", async ({agent}) => {
    if (agent.id !== root) return;
    await ctx.agentPresets.select(agent, "cordis");
    if (ctx.agentPresets.composedPreset(agent.ctx) !== "cordis" ||
        ctx.sessionProjections.stateOf(agent.session, "agentPreset") !== "cordis") {
      throw new Error("Cordis root preset not applied");
    }
    // Native user titles are durable metadata and pinned against automatic
    // generation. This does not add model input or rename child sessions.
    ctx.sessionTitle.rename(agent.session, config.title);
  });
  const fd = openSync(receipt, "wx", 0o600);
  try { writeFileSync(fd, JSON.stringify({phase:"registered", nonce, root})); }
  finally { closeSync(fd); }
}
'''


class _Expression(str):
    pass


class _Loader(yaml.SafeLoader):
    pass


class _Dumper(yaml.SafeDumper):
    pass


_Loader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: _Expression(loader.construct_scalar(node)))
_Dumper.add_representer(_Expression, lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:js", str(value)))


def prepare_cordis_overlay(directory: Path, *, title: str) -> Path:
    """Create a per-invocation overlay without changing an operator's profile.

    Only the exact audited runtime is accepted.  Its built-in Web template is
    rendered in a throwaway DSH_HOME with no credentials or user profile.
    """
    try:
        from deepseek_harness_runtime import resolve_bundled_launch_args

        if not isinstance(title, str) or not title.strip() or len(title) > 512:
            raise ValueError("invalid task title")
        directory = Path(directory).resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("invalid overlay directory")
        launch = resolve_bundled_launch_args()
        executable = Path(launch[0]).resolve(strict=True)
        with executable.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != _RUNTIME_SHA256:
                raise ValueError("unsupported SDK runtime")
        with tempfile.TemporaryDirectory(prefix="preset-seed-", dir=directory) as seed:
            env = {"HOME": seed, "DSH_HOME": seed, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
            result = subprocess.run(
                [*launch, "--profile", "hypertest-preset-seed", "--from-default-profile", "web", "--dump-default-config"],
                cwd=seed, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=30, check=True,
            )
            if len(result.stdout) > 4 * 1024 * 1024:
                raise ValueError("preset config too large")
            rows = yaml.load(result.stdout, Loader=_Loader)
        if not isinstance(rows, list):
            raise ValueError("invalid official preset")
        preset = [r for r in rows if isinstance(r, dict) and r.get("id") == "preset-cordis"]
        if (len(preset) != 1 or preset[0].get("name") != "@deepseek-ai/dsh-agent-preset"
                or preset[0].get("config", {}).get("id") != "cordis"):
            raise ValueError("official preset unavailable")
        hook = directory / "hypertest-cordis-root.mjs"
        hook.write_text(_HOOK, encoding="utf-8")
        hook.chmod(0o600)
        entries = [{"id": item, "disabled": True} for item in _DISABLE_BASE]
        # The pinned native default is only 80 UTF-8 bytes. Allow the complete
        # Cloud task title (at most 512 Unicode characters) for this invocation.
        entries.append({"id": "session-title", "config": {
            "fallbackMaxWords": 5, "fallbackMaxBytes": 40, "maxTitleBytes": 2048}})
        entries.append({"insert": [
            {"id": "agent-preset-registry", "name": "@deepseek-ai/dsh-agent-preset-registry", "config": {"default": "cordis"}},
            {"id": "cordis-host-runner", "name": "@deepseek-ai/dsh-cordis-host-runner"},
            {"id": "cordis-inspect-providers", "name": "@deepseek-ai/dsh-tool-cordis/host"},
            preset[0],
            {"id": "hypertest-cordis-root", "name": str(hook), "config": {"title": title}},
        ]})
        overlay = directory / "hypertest-cordis-overlay.yml"
        overlay.write_text(yaml.dump(entries, Dumper=_Dumper, sort_keys=False), encoding="utf-8")
        overlay.chmod(0o600)
        return overlay
    except (OSError, ValueError, KeyError, TypeError, ImportError, yaml.YAMLError, subprocess.SubprocessError):
        raise CloudBlocked("HARNESS_CORDIS_UNAVAILABLE", "The pinned Cordis preset could not be prepared") from None
