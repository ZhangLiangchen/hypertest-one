"""Fixed, argument-free SSH diagnostics; no credentials or process launch here."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import struct
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from .errors import CloudBlocked

SSH_ACCESS_PROFILE = "SSH_FIXED_DIAGNOSTICS_V1"
SSH_PROTOCOL = "hypertest-ssh-fixed-diagnostics/v1"
SSH_OBSERVATION = "hypertest-ssh-observation/v1"
SSH_SOCKET = "/run/hypertest-ssh.sock"
REMOTE_COMMAND = "/opt/hypertest-ssh/bin/control"
ACTION_ROOT = "/opt/hypertest-ssh/actions/"
STATES = frozenset({"SENT", "RUNNING", "STOP_REQUESTED", "COMPLETED", "FAILED", "CANCELLED", "UNKNOWN", "NOT_FOUND"})
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
REASONS = frozenset({"REGISTERED", "ACTIVE", "EXIT_OBSERVED", "STOP_OBSERVED", "NOT_FOUND", "START_UNCONFIRMED", "MANAGER_UNAVAILABLE", "IDENTITY_CHANGED", "OUTPUT_LIMIT", "TRANSPORT_UNKNOWN", "CONTROL_UNAVAILABLE"})
_HEX = re.compile(r"[a-f0-9]{64}")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_ACTION_FIELDS = {"key", "script_path", "script_sha256", "timeout_seconds", "stdout_limit_bytes", "stderr_limit_bytes"}


def blocked(code="SSH_CONTRACT_INVALID"):
    return CloudBlocked(code, "SSH input is outside the fixed diagnostic capability")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def exact(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise blocked()
    return value


def integer(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise blocked()
    return value


def uuid_text(value: object) -> str:
    if not isinstance(value, str):
        raise blocked()
    try:
        parsed = UUID(value)
    except ValueError:
        raise blocked() from None
    if str(parsed) != value:
        raise blocked()
    return value


def sha256_text(value: object) -> str:
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise blocked()
    return value


def public_key(value: object) -> str:
    """One complete Ed25519 public key, not a fingerprint, CA or known-host line."""
    try:
        if not isinstance(value, str) or len(value) > 256 or any(c in value for c in "\r\n\t"):
            raise ValueError
        kind, encoded = value.split(" ")
        raw = base64.b64decode(encoded, validate=True)
        if (kind != "ssh-ed25519" or raw[:4] != struct.pack(">I", 11)
                or raw[4:15] != b"ssh-ed25519" or raw[15:19] != struct.pack(">I", 32)
                or len(raw) != 51 or base64.b64encode(raw).decode() != encoded):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise blocked("SSH_PUBLIC_KEY_INVALID") from None


def canonical_target(host: str, port: int, user: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except (ValueError, TypeError):
        raise blocked("SSH_TARGET_INVALID") from None
    if (str(address) != host or "%" in host or not isinstance(user, str)
            or re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) is None or user == "root"):
        raise blocked("SSH_TARGET_INVALID")
    integer(port, 1, 65535)
    hostname = f"[{host}]" if address.version == 6 else host
    return f"ssh://{user}@{hostname}:{port}"


@dataclass(frozen=True)
class SshAction:
    key: str
    script_path: str
    script_sha256: str
    timeout_seconds: int
    stdout_limit_bytes: int
    stderr_limit_bytes: int

    def document(self) -> dict:
        return dict(vars(self))

    @classmethod
    def parse(cls, value: object) -> SshAction:
        data = exact(value, _ACTION_FIELDS)
        path = data["script_path"]
        if (not isinstance(data["key"], str) or _KEY.fullmatch(data["key"]) is None
                or not isinstance(path, str) or not path.startswith(ACTION_ROOT)
                or str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts
                or re.fullmatch(r"/opt/hypertest-ssh/actions/[A-Za-z0-9_.-]+", path) is None):
            raise blocked()
        sha256_text(data["script_sha256"])
        integer(data["timeout_seconds"], 1, 30)
        integer(data["stdout_limit_bytes"], 1, 65536)
        integer(data["stderr_limit_bytes"], 1, 65536)
        return cls(**data)


@dataclass(frozen=True)
class SshProfile:
    host: str
    port: int
    user: str
    host_key: str
    helper_sha256: str
    catalog_sha256: str
    authority_public_key: str
    actions: tuple[SshAction, ...]
    max_operations: int

    @property
    def target(self) -> str:
        return canonical_target(self.host, self.port, self.user)

    def action(self, key: str) -> SshAction:
        for action in self.actions:
            if action.key == key:
                return action
        raise blocked("SSH_ACTION_UNAVAILABLE")

    def catalog_document(self) -> dict:
        return {"profile": SSH_ACCESS_PROFILE, "target": self.target,
                "helper_sha256": self.helper_sha256, "authority_public_key": self.authority_public_key,
                "actions": [a.document() for a in self.actions], "max_operations": self.max_operations}


def validate_profile(environment: dict) -> SshProfile:
    if not isinstance(environment, dict) or environment.get("connection") != "SSH":
        raise blocked("SSH_PROFILE_UNAVAILABLE")
    access = exact(environment.get("ssh_access"), {"profile", "helper_sha256", "catalog_sha256", "authority_public_key", "actions", "max_operations"})
    if access["profile"] != SSH_ACCESS_PROFILE:
        raise blocked("SSH_PROFILE_UNAVAILABLE")
    host, port, user = environment.get("host"), environment.get("port"), environment.get("user")
    if not isinstance(host, str):
        raise blocked("SSH_TARGET_INVALID")
    canonical_target(host, port, user)
    actions = access["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 8:
        raise blocked()
    parsed = tuple(SshAction.parse(a) for a in actions)
    if len({a.key for a in parsed}) != len(parsed):
        raise blocked()
    profile = SshProfile(host, port, user, public_key(environment.get("host_key")),
        sha256_text(access["helper_sha256"]), sha256_text(access["catalog_sha256"]),
        public_key(access["authority_public_key"]), parsed, integer(access["max_operations"], 1, 8))
    if digest(profile.catalog_document()) != profile.catalog_sha256:
        raise blocked("SSH_CATALOG_DIGEST_MISMATCH")
    return profile


def request_document(*, operation_id: str, task_id: str, attempt_id: str, generation: int,
                     target: str, helper_sha256: str, catalog_sha256: str, action: dict,
                     hard_deadline: int) -> dict:
    return {"profile": SSH_PROTOCOL, "operation_id": uuid_text(operation_id),
            "task_id": uuid_text(task_id), "attempt_id": uuid_text(attempt_id),
            "generation": integer(generation, 1, 2**53 - 1), "target": target,
            "helper_sha256": sha256_text(helper_sha256), "catalog_sha256": sha256_text(catalog_sha256),
            "action": SshAction.parse(action).document(), "hard_deadline": integer(hard_deadline, 1, 2**53 - 1)}


def validate_request(value: object, profile: SshProfile) -> dict:
    fields = {"profile", "operation_id", "task_id", "attempt_id", "generation", "target", "helper_sha256", "catalog_sha256", "action", "hard_deadline"}
    data = exact(value, fields)
    request = request_document(**{k: v for k, v in data.items() if k != "profile"})
    if (data != request or data["target"] != profile.target or data["helper_sha256"] != profile.helper_sha256
            or data["catalog_sha256"] != profile.catalog_sha256
            or data["action"] != profile.action(data["action"]["key"]).document()):
        raise blocked("SSH_REQUEST_MISMATCH")
    return request


def unit_name(operation_id: str) -> str:
    return "hypertest-ssh-" + UUID(uuid_text(operation_id)).hex + ".service"


def project_observation(value: object, request: dict) -> dict:
    fields = {"profile", "operation_id", "request_digest", "target", "state", "remote_identity", "remote_started_at", "remote_finished_at", "exit_code", "signal", "remote_stopped", "stdout", "stderr", "reason"}
    data = exact(value, fields)
    if (data["profile"] != SSH_OBSERVATION or data["operation_id"] != request["operation_id"]
            or data["request_digest"] != digest(request) or data["target"] != request["target"]
            or not isinstance(data["state"], str) or data["state"] not in STATES
            or not isinstance(data["reason"], str) or data["reason"] not in REASONS
            or type(data["remote_stopped"]) is not bool):
        raise blocked("SSH_OBSERVATION_INVALID")
    identity = exact(data["remote_identity"], {"boot_id", "unit", "invocation_id"})
    if identity["boot_id"] is not None:
        uuid_text(identity["boot_id"])
    if identity["unit"] != unit_name(request["operation_id"]):
        raise blocked("SSH_OBSERVATION_INVALID")
    invocation = identity["invocation_id"]
    if invocation is not None and (not isinstance(invocation, str) or re.fullmatch(r"[a-f0-9]{32}", invocation) is None):
        raise blocked("SSH_OBSERVATION_INVALID")
    for field in ("remote_started_at", "remote_finished_at", "exit_code", "signal"):
        if data[field] is not None:
            integer(data[field], 0, 255 if field in {"exit_code", "signal"} else 2**53 - 1)
    for field in ("stdout", "stderr"):
        output = exact(data[field], {"byte_count", "sha256", "truncated"})
        integer(output["byte_count"], 0, request["action"][field + "_limit_bytes"])
        sha256_text(output["sha256"])
        if type(output["truncated"]) is not bool:
            raise blocked()
    if data["remote_stopped"] and (data["state"] not in TERMINAL_STATES or identity["boot_id"] is None
                                  or invocation is None or data["remote_finished_at"] is None):
        raise blocked("SSH_STOP_PROOF_INVALID")
    if data["state"] in TERMINAL_STATES and not data["remote_stopped"]:
        raise blocked("SSH_STOP_PROOF_INVALID")
    if (data["remote_started_at"] is not None and data["remote_finished_at"] is not None
            and data["remote_finished_at"] < data["remote_started_at"]):
        raise blocked("SSH_OBSERVATION_INVALID")
    if data["state"] == "COMPLETED" and (data["exit_code"] != 0 or data["signal"] is not None
            or data["stdout"]["truncated"] or data["stderr"]["truncated"]):
        raise blocked("SSH_OBSERVATION_INVALID")
    return json.loads(canonical_bytes(data))
