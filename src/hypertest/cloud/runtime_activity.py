"""Live official SDK metadata only; never tool inputs, outputs or conversation."""
from __future__ import annotations

FINISH_REASONS = frozenset({"completed", "aborted", "blocked", "error", "max-tokens",
    "interrupted", "forked", "OTHER"})
TOOL_ERROR_CODES = frozenset({"NONE", "SANDBOX_UNAVAILABLE", "UNKNOWN_TOOL", "INVALID_TOOL_OUTPUT",
    "ABORTED", "ABORTED_BEFORE_DISPATCH", "OTHER"})
TOOL_CATEGORIES = frozenset({"BASH", "READ_FILE", "WRITE_FILE", "EDIT_FILE", "GLOB", "GREP",
    "CODEX", "RUN_CODE", "WORKFLOW", "JOB", "OTHER"})
_TOOLS = {"bash": "BASH", "read_file": "READ_FILE", "write_file": "WRITE_FILE", "edit_file": "EDIT_FILE",
    "glob": "GLOB", "grep": "GREP", "subagent_codex": "CODEX", "run_code": "RUN_CODE",
    "workflow": "WORKFLOW", "job_output": "JOB", "job_kill": "JOB"}
_OUTCOMES = frozenset({"allowed-once", "rejected", "cancelled", "unavailable", "OTHER"})


def project_finish_reason(value: object) -> str | None:
    return value if isinstance(value, str) and value in FINISH_REASONS else (None if value is None else "OTHER")


def _number(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 1000000 else None


def _member(value: object, allowed: frozenset) -> str:
    return value if isinstance(value, str) and value in allowed else "OTHER"


def project_runtime_activity(value: object) -> dict:
    """Second projection at the Worker boundary drops every unknown field/value."""
    source = value if isinstance(value, dict) else {}
    kind = source.get("kind")
    if not isinstance(kind, str):
        return {"kind": "OTHER"}
    if kind == "STATUS":
        return {"kind": kind, "status": _member(source.get("status"), frozenset({"idle", "running"}))}
    if kind in {"STEP_START", "STEP_END"}:
        return {"kind": kind, "step": _number(source.get("step"))}
    if kind == "TOOL_CALL":
        return {"kind": kind, "tool": _member(source.get("tool"), TOOL_CATEGORIES),
            "sequence": _number(source.get("sequence"))}
    if kind == "TOOL_RESULT":
        flag = source.get("is_error")
        return {"kind": kind, "is_error": flag if type(flag) is bool else None,
            "error_code": _member(source.get("error_code"), TOOL_ERROR_CODES),
            "call_sequence": _number(source.get("call_sequence"))}
    if kind == "APPROVAL_ASKED":
        return {"kind": kind, "tool": _member(source.get("tool"), TOOL_CATEGORIES)}
    if kind == "APPROVAL_DECIDED":
        return {"kind": kind, "outcome": _member(source.get("outcome"), _OUTCOMES)}
    if kind == "TURN_END":
        return {"kind": kind, "reason": project_finish_reason(source.get("reason"))}
    return {"kind": "OTHER"}


def project_notification(notification, session_id: str) -> dict | None:
    """Inspect only named scalar fields from live notifications for this root."""
    payload = notification.payload
    if not isinstance(payload, dict) or payload.get("sessionId") != session_id:
        return None
    if notification.method == "session.status":
        return project_runtime_activity({"kind": "STATUS", "status": payload.get("status")})
    if notification.method != "session.event":
        return None
    event = payload.get("event")
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        return None
    data, kind = event["data"], event.get("type")
    if not isinstance(kind, str):
        return None
    if kind in {"step/start", "step/end"}:
        return project_runtime_activity({"kind": "STEP_START" if kind == "step/start" else "STEP_END", "step": data.get("step")})
    if kind == "tool/call":
        name = data.get("name")
        tool = _TOOLS.get(name, "OTHER") if isinstance(name, str) else "OTHER"
        return project_runtime_activity({"kind": "TOOL_CALL", "tool": tool, "sequence": event.get("seq")})
    if kind == "tool/result":
        message = data.get("message")
        error = data.get("error")
        sources = event.get("sourceEventSeqs")
        flag = message.get("isError") if isinstance(message, dict) else None
        code = error.get("code") if isinstance(error, dict) else ("NONE" if flag is False else "OTHER")
        return project_runtime_activity({"kind": "TOOL_RESULT", "is_error": flag, "error_code": code,
            "call_sequence": sources[0] if isinstance(sources, list) and len(sources) == 1 else None})
    if kind == "approval/asked":
        name = data.get("toolName")
        return project_runtime_activity({"kind": "APPROVAL_ASKED",
            "tool": _TOOLS.get(name, "OTHER") if isinstance(name, str) else "OTHER"})
    if kind == "approval/decided":
        return project_runtime_activity({"kind": "APPROVAL_DECIDED", "outcome": data.get("outcome")})
    if kind == "turn/end":
        reason = data.get("reason")
        return project_runtime_activity({"kind": "TURN_END", "reason": reason.get("kind") if isinstance(reason, dict) else "OTHER"})
    return None
