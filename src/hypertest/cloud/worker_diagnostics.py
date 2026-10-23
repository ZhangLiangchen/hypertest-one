"""Closed metadata for host failures: no messages, source lines, locals or paths."""
from __future__ import annotations

import re
from pathlib import Path

from hypertest.interactive_client.errors import ClientError
from hypertest.sync_core import SyncError

from .errors import CloudBlocked

_FILES = frozenset({"cloud/__main__.py", "cloud/worker.py", "cloud/reporter.py", "cloud/broker.py",
    "cloud/git.py", "cloud/sandbox.py", "cloud/artifacts.py", "cloud/delegation.py",
    "cloud/model_broker.py", "cloud/private_file.py", "cloud/handoff_rejections.py",
    "application/cloud_tasks.py", "interactive_client/journal.py", "interactive_client/security.py",
    "sync_core/core.py", "sync_core/storage.py", "api/cloud_schemas.py"})
_FUNCTIONS = frozenset({"run", "run_once", "resolve", "execute", "collect", "consume_runtime",
    "heartbeat", "host_transition", "observed_cost", "private_root", "save_once", "read_model_key",
    "__init__", "pending", "recover", "submit_handoff", "prevalidate_handoff", "_typed_request",
    "validate_payload", "assert_current", "credentials", "submit", "receipt", "page", "artifact",
    "readback", "validate_receipt", "deliver", "prepare", "save", "load", "mark", "intent", "close",
    "_git", "checkout", "_fetch", "git_environment", "start", "stop", "command", "require_readonly_shell",
    "apply_resource_limits", "write_workspace_receipt", "write_workspace_rejection", "_write_workspace_metadata",
    "read_workspace_file", "private_directory", "private_read", "private_create", "_reject_secrets",
    "worker_authority", "mutate", "_reserve_budget", "_settle_budget", "_state", "_usage", "_task",
    "_attempt", "claim_attempt", "claim_resolution", "expire_leases", "enabled", "_events", "get", "record"})
_TYPES = frozenset({"CloudBlocked", "BrokerFailure", "ClientError", "SyncError", "SdkOperationError",
    "ValidationError", "KeyError", "TypeError", "ValueError", "AssertionError", "AttributeError",
    "RuntimeError", "HTTPException", "OSError", "PermissionError", "FileExistsError", "FileNotFoundError",
    "IsADirectoryError", "NotADirectoryError", "UnicodeDecodeError", "TimeoutError", "CancelledError",
    "OperationalError", "IntegrityError", "DataError", "DBAPIError", "StatementError", "ProgrammingError",
    "InterfaceError", "MissingGreenlet", "InvalidRequestError", "JSONDecodeError", "BrokenPipeError",
    "ConnectionError", "OTHER"})
_STAGES = frozenset({"NAMESPACE_STOP", "RUNTIME_DIAGNOSTIC_WRITE", "WORKER_DIAGNOSTIC_WRITE",
    "REPORT_PENDING_READ", "REPORT_TRANSITION", "REPORTER_CLOSE", "ENGINE_DISPOSE", "SSH_REMOTE_CLEANUP"})
_ROOT = Path(__file__).resolve().parents[1]


def exception_metadata(error: BaseException) -> dict:
    kind = type(error).__name__
    frames = []
    trace = error.__traceback__
    for _ in range(128):
        if trace is None:
            break
        code = trace.tb_frame.f_code
        file = next((name for name in _FILES if str(_ROOT / name) == code.co_filename), None)
        if file is not None:
            function = code.co_name if code.co_name in _FUNCTIONS else "OTHER"
            frames.append({"file": file, "function": function, "line": trace.tb_lineno})
        trace = trace.tb_next
    return {"type": kind if kind in _TYPES else "OTHER", "frames": frames[-8:]}


def _project_exception(value: object) -> dict:
    source = value if isinstance(value, dict) else {}
    frames = []
    for frame in source.get("frames", ())[:8] if isinstance(source.get("frames"), (list, tuple)) else ():
        if (not isinstance(frame, dict) or not isinstance(frame.get("file"), str) or frame["file"] not in _FILES
                or type(frame.get("line")) is not int or not 1 <= frame["line"] <= 1000000):
            continue
        function = frame.get("function")
        frames.append({"file": frame["file"],
            "function": function if isinstance(function, str) and function in _FUNCTIONS else "OTHER", "line": frame["line"]})
    kind = source.get("type")
    return {"type": kind if isinstance(kind, str) and kind in _TYPES else "OTHER", "frames": frames}


def attach_failure(error: BaseException, primary: dict, secondary: list[dict]) -> None:
    error._hypertest_worker_failure = {"primary": primary, "secondary": secondary}


def failure_metadata(error: BaseException) -> dict:
    value = getattr(error, "_hypertest_worker_failure", None)
    if not isinstance(value, dict):
        return {"primary": exception_metadata(error), "secondary": []}
    secondary = []
    entries = value.get("secondary", ())
    for entry in entries[:8] if isinstance(entries, (list, tuple)) else ():
        if isinstance(entry, dict) and isinstance(entry.get("stage"), str) and entry["stage"] in _STAGES:
            secondary.append({"stage": entry["stage"], "error": _project_exception(entry.get("error"))})
    return {"primary": _project_exception(value.get("primary")), "secondary": secondary}


def failure_code(error: BaseException) -> str:
    if isinstance(error, (CloudBlocked, SyncError, ClientError)):
        code = vars(error).get("code")
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
            return code
    return "CLOUD_WORKER_FAILED"
