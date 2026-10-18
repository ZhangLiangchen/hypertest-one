"""Versioned, authenticated local transport shared by Worker and host Bridge."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

TRANSPORT = "hypertest.harness-bridge/v1alpha1"
PROTOCOL = "hypertest.tmp/v1alpha2"
PROFILE = "run-persistent-harness/v1"
MAX_MESSAGE = 4_000_000
MAX_GRANT_SECONDS = 120
TOOLS = frozenset({
    "get_state", "request_mission", "complete_mission", "request_execution", "ask_user",
    "evaluate_gate", "submit_report", "request_gitlab_issue", "get_issue",
})
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
WORKSPACE = re.compile(r"^[a-f0-9]{32}$")


class BridgeError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    binding_id: str
    logical_worker_id: str
    session_id: str
    workspace_id: str
    harness_host_id: str
    job_id: str
    claim_token: str
    binding_epoch: int
    expires_at: float
    mission_id: str | None = None
    attempt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sign(request: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical(request), hashlib.sha256).hexdigest()


def verify(request: dict[str, Any], key: bytes) -> dict[str, Any]:
    body = dict(request)
    signature = body.pop("signature", "")
    if not isinstance(signature, str) or not hmac.compare_digest(signature, sign(body, key)):
        raise BridgeError("AUTHORIZATION_REJECTED")
    if body.get("transport") != TRANSPORT or body.get("protocol") != PROTOCOL or body.get("profile") != PROFILE:
        raise BridgeError("CAPABILITY_UNSUPPORTED")
    timestamp = body.get("issued_at")
    if not isinstance(timestamp, (float, int)) or abs(time.time() - timestamp) > 30:
        raise BridgeError("AUTHORIZATION_EXPIRED")
    return body


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise BridgeError("INVALID_IDENTITY")
    return value


def context_from(value: dict[str, Any], *, execution: bool = True) -> ExecutionContext:
    try:
        context = ExecutionContext(**value)
        for field in (context.run_id, context.binding_id, context.logical_worker_id, context.session_id,
                      context.harness_host_id, context.job_id, context.claim_token):
            identifier(field)
        if (not WORKSPACE.fullmatch(context.workspace_id)
                or type(context.binding_epoch) is not int or context.binding_epoch < 1):
            raise ValueError
        if execution and not time.time() < context.expires_at <= time.time() + MAX_GRANT_SECONDS:
            raise BridgeError("AUTHORIZATION_EXPIRED")
        return context
    except (ValueError, TypeError, KeyError) as exc:
        raise BridgeError("INVALID_CONTEXT") from exc
