"""Explicit host event contracts. Metadata is attribution, never authentication."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hypertest.interactive_client.errors import ClientError

HOST_PROVIDERS = {"codex": "codex", "claude-code": "claude_code",
                  "deepseek-harness": "deepseek_harness"}
COMMON_EVENTS = frozenset({"SessionStart", "PostToolUse", "Stop", "SessionEnd",
                           "SubagentStart", "SubagentStop"})
# Codex CLI 0.144.6's native hooks/list exposes these events, but not
# SessionEnd. A newer documentation page alone cannot enable that capability.
CODEX_EVENTS = COMMON_EVENTS - {"SessionEnd"}
DEEPSEEK_EVENTS = frozenset({"SessionStart", "PostToolUse", "Stop"})
SUPPORTED_NATIVE_VERSIONS = {"codex": frozenset({"0.144.6"}),
                             "claude-code": frozenset({"2.1.218"})}


def probe_native_version(host: str, *, executable: Path | None = None) -> dict:
    if host not in SUPPORTED_NATIVE_VERSIONS:
        raise ClientError("LOCAL_HOST_UNSUPPORTED")
    selected = executable or shutil.which("claude" if host == "claude-code" else "codex")
    if selected is None:
        raise ClientError("LOCAL_HOST_EXECUTABLE_NOT_FOUND")
    try:
        binary = Path(selected).expanduser().resolve(strict=True)
        result = subprocess.run([str(binary), "--version"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
        if result.returncode or len(result.stdout) > 4096:
            raise ValueError
        pattern = (rb"codex-cli ([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?)\s*"
            if host == "codex" else rb"([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?) \(Claude Code\)\s*")
        match = re.fullmatch(pattern, result.stdout)
        if match is None:
            raise ValueError
        version = match.group(1).decode("ascii")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ClientError("LOCAL_HOST_VERSION_PROBE_FAILED") from None
    if version not in SUPPORTED_NATIVE_VERSIONS[host]:
        raise ClientError("LOCAL_HOST_AUTOMATIC_VERSION_UNSUPPORTED")
    return {"harness_version": version, "executable": str(binary), "probe": "NATIVE_VERSION_COMMAND"}


@dataclass(frozen=True)
class Trigger:
    host: str
    provider: str
    parent_session_id: str
    event: str
    tool_name: str | None = None

    def metadata(self):
        # No prompt, transcript_path, tool_input/output, answer or child body.
        return {"host": self.host, "provider": self.provider,
                "session_id": self.parent_session_id, "event": self.event}


def parse_trigger(host: str, event: dict, *, selected_parent: str,
                  bridge: str | None = None) -> Trigger | None:
    if host not in HOST_PROVIDERS or not isinstance(event, dict):
        raise ClientError("LOCAL_HOST_UNSUPPORTED")
    name, session = event.get("hook_event_name"), event.get("session_id")
    allowed = (DEEPSEEK_EVENTS if host == "deepseek-harness" else
               CODEX_EVENTS if host == "codex" else COMMON_EVENTS)
    if name not in allowed:
        raise ClientError("LOCAL_EVENT_UNSUPPORTED")
    if (not isinstance(session, str) or not session.strip() or len(session) > 512
            or not selected_parent or session != selected_parent):
        raise ClientError("REAL_PARENT_SESSION_REQUIRED")
    if host == "deepseek-harness" and bridge not in {"claude-code", "codex", "native-root"}:
        raise ClientError("DEEPSEEK_EVENT_BRIDGE_REQUIRED")
    tool = event.get("tool_name")
    if tool is not None and (not isinstance(tool, str) or len(tool) > 256):
        raise ClientError("INVALID_LOCAL_EVENT")
    # Refuse sync-tool recursion, including namespaced MCP names. Ignore raw
    # tool fields entirely; the explicit manifest alone selects artifacts.
    if tool and ("hypertest_sync_task" in tool or "hypertest_get_task" in tool
                 or tool.startswith("mcp__hypertest")):
        return None
    return Trigger(host, HOST_PROVIDERS[host], session, name, tool)
