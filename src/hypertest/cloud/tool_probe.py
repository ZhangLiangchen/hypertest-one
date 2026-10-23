"""Fixed no-prompt ToolsService probe; no policy overrides or user commands."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .artifacts import read_workspace_file
from .errors import CloudBlocked
from .runtime_activity import TOOL_ERROR_CODES

PROBE_PROFILE = "hypertest-sdk-tool-probe/v1"
PROBE_FILE = ".hypertest-sdk-tool-probe.json"


def write_tool_probe_configuration(config: dict) -> Path:
    if (config.get("mode") != "SDK_TOOL_PROBE" or {"prompt", "resume", "patches", "native_delegation"} & config.keys()
            or config.get("workspace") != "/workspace" or config.get("dsh_home") != "/home/agent/dsh"
            or not isinstance(config.get("session_id"), str)
            or not re.fullmatch(r"tool-probe-[a-f0-9]{32}", config["session_id"])):
        raise CloudBlocked("TOOL_PROBE_CONFIGURATION_INVALID", "Only the fixed isolated no-prompt tool probe is supported")
    patch = Path(config["dsh_home"]).parent / "sdk-tool-probe.patch.json"
    rows = [{"insert": [{"id": "hypertest-sdk-tool-probe", "name": str(Path(__file__).with_name("sdk_tool_probe.mjs")),
        "config": {"sessionId": config["session_id"]}}]}]
    descriptor = os.open(patch, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(rows, stream)
    return patch


def project_tool_probe(value: object) -> dict:
    source = value if isinstance(value, dict) else {}
    keys = {"profile", "tool_registered", "executed", "is_error", "marker_match", "error_code", "sandbox_mode", "approval_policy"}
    if (set(source) != keys or source.get("profile") != PROBE_PROFILE
            or any(type(source.get(key)) is not bool for key in ("tool_registered", "executed", "marker_match"))
            or (source.get("is_error") is not None and type(source.get("is_error")) is not bool)
            or not isinstance(source.get("error_code"), str) or source["error_code"] not in TOOL_ERROR_CODES
            or not isinstance(source.get("sandbox_mode"), str)
            or source["sandbox_mode"] not in {"workspace-write", "read-only", "danger-full-access", "OTHER"}
            or not isinstance(source.get("approval_policy"), str) or source["approval_policy"] not in {"ask", "never", "OTHER"}):
        raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe returned an unsupported metadata shape")
    if source["marker_match"] and (not source["executed"] or not source["tool_registered"] or source["is_error"] is not False):
        raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe marker has no successful execution")
    return dict(source)


def read_tool_probe(workspace: Path) -> dict:
    raw = read_workspace_file(workspace, PROBE_FILE, max_bytes=4096)
    try:
        return project_tool_probe(json.loads(raw))
    except (ValueError, TypeError):
        raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe metadata is unavailable") from None
