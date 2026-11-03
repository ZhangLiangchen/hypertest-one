"""Host-native Cloud worker using a separately authenticated platform API.

The SDK executes as the current host user; it receives neither this Worker's
platform credential nor the per-claim lease capabilities through its env or
stdin. Same-user OS access is not a security boundary.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .errors import REPORT_CONTENT_REJECTED, CloudBlocked
from .private_file import read_private_file
from .worker import CloudWorker, private_root, save_once


def _recovery_reason(error: BaseException) -> str:
    if isinstance(error, CloudBlocked) and error.code in {
        REPORT_CONTENT_REJECTED, "WORKER_INTERRUPTED", "WORKER_LEASE_UNCONFIRMED",
        "RUNTIME_TIMEOUT", "REPORT_RECONCILIATION_PENDING", "ATTEMPT_RECOVERY_REQUIRED",
    }:
        return error.code
    return "WORKER_RUNTIME_FAILED"


class WorkerAPI:
    def __init__(self, base_url: str, token: bytes, *, ca_file: str | None = None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CloudBlocked("WORKER_ENDPOINT_INVALID", "Worker API needs HTTPS or an explicit loopback endpoint")
        try:
            credential = token.decode("ascii").strip()
        except UnicodeDecodeError:
            raise CloudBlocked("WORKER_IDENTITY_INVALID", "Worker credential is invalid") from None
        if not credential or any(c.isspace() for c in credential):
            raise CloudBlocked("WORKER_IDENTITY_INVALID", "Worker credential is invalid")
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", trust_env=False,
                                        verify=ca_file if ca_file else True, timeout=30,
                                        headers={"Authorization": "Bearer " + credential})

    async def request(self, operation: str, body: dict):
        try:
            response = await self.client.post("api/v1/cloud/worker/" + operation, json=body)
            if not response.is_success:
                if operation == "validate-payload" and response.status_code == 422:
                    try:
                        detail = response.json()
                    except ValueError:
                        detail = None
                    if detail == {"detail": REPORT_CONTENT_REJECTED}:
                        raise CloudBlocked(REPORT_CONTENT_REJECTED,
                            "A testing artifact was rejected by content admission")
                from .broker import BrokerFailure
                raise BrokerFailure(response.status_code, "CLOUD_OPERATION_REJECTED")
            return response.json()
        except (httpx.RequestError, ValueError):
            # Do not expose server body, URL, request payload or credentials.
            raise CloudBlocked("WORKER_API_UNCONFIRMED", "The original Worker API operation requires reconciliation") from None

    async def close(self):
        await self.client.aclose()


class RemoteBroker:
    def __init__(self, api: WorkerAPI, claim: dict, worker_id: str):
        task, attempt = claim["task"], claim["attempt"]
        self.api, self.task_id, self.project_id, self.attempt_id = api, task["id"], task["project_id"], attempt["id"]
        self.version = task["version"]
        self.identity = SimpleNamespace(worker_id=worker_id, lease_token=claim["lease_token"],
                                        work_token=claim["work_token"], generation=claim["generation"])
        self.writes_suspended = False

    def suspend_writes(self):
        self.writes_suspended = True

    def _body(self, **fields):
        return {"project_id": self.project_id, "task_id": self.task_id, "attempt_id": self.attempt_id,
                "identity": vars(self.identity), **fields}

    def _require_writes(self):
        if self.writes_suspended:
            raise CloudBlocked("WORKER_WRITES_SUSPENDED", "Only original operations may be read")

    async def assert_current(self):
        self._require_writes()
        return await self.api.request("assert", self._body())

    async def renew(self, lease_seconds):
        self._require_writes()
        return await self.api.request("renew", self._body(lease_seconds=lease_seconds))

    async def fence_for_recovery(self, reason, *, metadata=None):
        self.suspend_writes()
        return await self.api.request("fence", self._body(reason=reason))

    async def submit(self, payload):
        self._require_writes()
        return await self.api.request("submit", self._body(payload=payload))

    async def validate_payload(self, payload):
        self._require_writes()
        return await self.api.request("validate-payload", self._body(payload=payload))

    async def receipt(self, key):
        return await self.api.request("receipt", self._body(operation_key=key))

    async def page(self, *, version, offset, limit):
        return await self.api.request("page", self._body(version=version, offset=offset, limit=limit))

    async def artifact(self, artifact_id):
        value = await self.api.request("artifact", self._body(artifact_id=artifact_id))
        try:
            data = base64.b64decode(value["content_base64"], validate=True)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError
            return data
        except (ValueError, KeyError, TypeError):
            raise CloudBlocked("ARTIFACT_READBACK_MISMATCH", "Original artifact readback failed") from None


CLAIM_PROFILE = "hypertest-native-worker-claim/v2"
CLAIM_FIELDS = {"worker_id", "request_key", "sequence", "lease_seconds", "supports_attempt_manifest"}
INSPECTION_CLAIM_PROFILE = "hypertest-native-inspection-claim/v1"
INSPECTION_CLAIM_FIELDS = {"worker_id", "request_key", "sequence", "lease_seconds"}


def check_cordis_runtime() -> None:
    """Verify the pinned preset is available before claiming any new work."""
    from .native_cordis import prepare_cordis_overlay

    with tempfile.TemporaryDirectory(prefix="hypertest-cordis-preflight-") as directory:
        prepare_cordis_overlay(Path(directory), title="HyperTest Cordis preflight probe")


async def prepare_native_session_identity(*, root, workspace, args, task, attempt, manifest, broker, reporter, prompt):
    """Anchor an opt-in native session before RUNNING or any SDK prompt."""
    from .native_resume_identity import record_initial_identity
    from .native_sdk_adapter import host_environment
    from .native_selection import read_native_selection

    session_id = "cloud-" + attempt["id"]
    environment = host_environment(os.environ)
    selection = await asyncio.to_thread(read_native_selection, dsh_home=args.dsh_home,
                                        cwd=str(workspace), environment=environment)
    repos = manifest["resolution"]["repositories"]
    original = {"project_id": task["project_id"], "task_id": task["id"], "attempt_id": attempt["id"],
                "session_id": session_id, "worker_id": args.worker_id,
                "original_generation": broker.identity.generation, "input_digest": attempt["input_digest"],
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "title_sha256": hashlib.sha256(task["title"].encode()).hexdigest(),
                "workspace": str(workspace), "dsh_home": str(Path(args.dsh_home).absolute()),
                "sut_commit": repos["sut"]["commit_sha"], "framework_commit": repos["framework"]["commit_sha"]}
    snapshot = await asyncio.to_thread(record_initial_identity, root, **original,
                                       selection=selection, environment=environment)
    anchored = await reporter.submit_native_session_anchor(snapshot_sha256=snapshot,
                     input_digest=attempt["input_digest"], session_id=session_id)
    if not anchored.synced:
        raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Original session anchor requires reconciliation")
    original["selection"] = selection
    return {"attempt_root": str(root), "digest": snapshot, "original": original}


def _validate_claim_request(request: object, worker_id: str) -> dict:
    if (not isinstance(worker_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", worker_id)
            or not isinstance(request, dict) or set(request) != CLAIM_FIELDS
            or request.get("worker_id") != worker_id
            or not isinstance(request.get("request_key"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", request["request_key"])
            or type(request.get("sequence")) is not int or request["sequence"] < 1
            or type(request.get("lease_seconds")) is not int or not 15 <= request["lease_seconds"] <= 300
            or type(request.get("supports_attempt_manifest")) is not bool):
        raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Original claim request is invalid")
    return request


def _claim_digest(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare_claim(state: Path, request: dict) -> Path:
    """Never send another claim after an unconfirmed original request."""
    _validate_claim_request(request, request.get("worker_id"))
    pending = state / "claim-pending.json"
    if pending.exists() or pending.is_symlink():
        raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Original claim must be reconciled before another claim")
    try:
        save_once(pending, {"profile": CLAIM_PROFILE, "status": "SENT", "request": request,
                            "request_sha256": _claim_digest(request)})
    except FileExistsError:
        raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Original claim must be reconciled before another claim") from None
    return pending


def pending_claim(state: Path, worker_id: str) -> tuple[Path, dict] | None:
    pending = state / "claim-pending.json"
    if not pending.exists() and not pending.is_symlink():
        return None
    try:
        record = json.loads(read_private_file(pending, max_bytes=65536))
    except (ValueError, TypeError):
        raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Original claim record is invalid") from None
    if not isinstance(record, dict) or record.get("profile") != CLAIM_PROFILE:
        raise CloudBlocked("LEGACY_CLAIM_RECONCILIATION_REQUIRED", "Legacy claim requires explicit original-state reconciliation")
    request = _validate_claim_request(record.get("request"), worker_id)
    if (set(record) != {"profile", "status", "request", "request_sha256"}
            or record.get("status") != "SENT" or record.get("request_sha256") != _claim_digest(request)):
        raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Original claim record failed integrity verification")
    return pending, request


def _inspection_claim_request(request: object, worker_id: str) -> dict:
    if (not isinstance(request, dict) or set(request) != INSPECTION_CLAIM_FIELDS
            or request.get("worker_id") != worker_id
            or not isinstance(request.get("request_key"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{15,127}", request["request_key"])
            or type(request.get("sequence")) is not int or not 1 <= request["sequence"] <= 9223372036854775807
            or type(request.get("lease_seconds")) is not int or not 15 <= request["lease_seconds"] <= 300):
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection claim is invalid")
    return request


def prepare_inspection_claim(state: Path, request: dict) -> Path:
    _inspection_claim_request(request, request.get("worker_id"))
    pending = state / "inspection-claim-pending.json"
    if pending.exists() or pending.is_symlink():
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection claim must be reconciled")
    try:
        save_once(pending, {"profile": INSPECTION_CLAIM_PROFILE, "status": "SENT", "request": request,
                            "request_sha256": _claim_digest(request)})
    except FileExistsError:
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection claim must be reconciled") from None
    return pending


def pending_inspection_claim(state: Path, worker_id: str) -> tuple[Path, dict] | None:
    pending = state / "inspection-claim-pending.json"
    if not pending.exists() and not pending.is_symlink():
        return None
    try:
        record = json.loads(read_private_file(pending, max_bytes=65536))
        request = _inspection_claim_request(record["request"], worker_id)
        if (not isinstance(record, dict) or set(record) != {"profile", "status", "request", "request_sha256"}
                or record["profile"] != INSPECTION_CLAIM_PROFILE or record["status"] != "SENT"
                or record["request_sha256"] != _claim_digest(request)):
            raise ValueError("invalid original inspection claim")
    except (KeyError, TypeError, ValueError):
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection claim is invalid") from None
    return pending, request


@contextmanager
def worker_lock(state: Path):
    """Only one process may inspect, send, execute or close this private journal."""
    fd = os.open(state / "worker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise CloudBlocked("WORKER_LOCK_UNSAFE", "Worker lock requires a private regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CloudBlocked("WORKER_ALREADY_RUNNING", "Another Worker owns this state directory") from None
        yield
    finally:
        os.close(fd)


def complete_claim(pending: Path):
    pending.unlink()
    directory = os.open(pending.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _claim_response(value, worker_id, *, request=None, recovering=False):
    valid = (isinstance(value, dict) and value.get("worker_id") == worker_id
        and type(value.get("sequence")) is int and value["sequence"] >= 0
        and type(value.get("closed")) is bool
        and value.get("kind") in {"EMPTY", "RESOLUTION", "ATTEMPT", "ABANDONED", "RETIRED"})
    if valid:
        if value["sequence"] == 0:
            valid = value.get("request_key") is None and value["kind"] == "EMPTY" and value["closed"]
        else:
            valid = (isinstance(value.get("request_key"), str)
                and re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", value["request_key"]) is not None)
    if valid and request is not None:
        valid = value["sequence"] == request["sequence"] and value["request_key"] == request["request_key"]
        if recovering:
            valid = valid and value["closed"] and "claim" not in value
        else:
            valid = valid and ((value["kind"] == "EMPTY" and value["closed"] and value.get("claim") is None)
                or (value["kind"] in {"RESOLUTION", "ATTEMPT"} and not value["closed"] and isinstance(value.get("claim"), dict)))
    elif valid:
        valid = "claim" not in value
    if not valid:
        raise CloudBlocked("WORKER_API_UNCONFIRMED", "Original claim response requires reconciliation")
    return value


def _retryable_api_failure(error: Exception) -> bool:
    from .broker import BrokerFailure

    return ((isinstance(error, CloudBlocked) and error.code == "WORKER_API_UNCONFIRMED")
        or (isinstance(error, BrokerFailure) and 500 <= error.status < 600))


async def _claim_read(api, args, operation, request):
    """Retry only state reads or original-key closure, never a claim delivery."""
    failures = 0
    while True:
        try:
            value = await api.request(operation, request)
            return _claim_response(value, args.worker_id,
                request=request if operation == "claim/reconcile" else None,
                recovering=operation == "claim/reconcile")
        except Exception as error:
            if args.once or not _retryable_api_failure(error):
                raise
            await asyncio.sleep(min(max(args.poll_seconds, 0.25) * 2 ** min(failures, 7), 30))
            failures += 1


def _inspection_slot_response(value, worker_id, *, request=None, claimed=False):
    valid = (isinstance(value, dict) and value.get("worker_id") == worker_id
             and type(value.get("sequence")) is int and value["sequence"] >= 0
             and type(value.get("closed")) is bool
             and value.get("kind") in {"EMPTY", "INSPECTION", "ABANDONED", "RETIRED"})
    if valid and value["sequence"] == 0:
        valid = (value.get("request_key") is None and value["kind"] == "EMPTY"
                 and value["closed"] and value.get("inspection_id") is None)
    elif valid:
        valid = (isinstance(value.get("request_key"), str)
                 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{15,127}", value["request_key"]) is not None)
    if valid and value["kind"] == "INSPECTION":
        try:
            _inspection_uuid(value.get("inspection_id"))
        except (TypeError, ValueError):
            valid = False
    elif valid and value["kind"] in {"EMPTY", "ABANDONED"}:
        valid = value["closed"] and value.get("inspection_id") is None
    if valid and request is not None:
        valid = value["sequence"] == request["sequence"] and value.get("request_key") == request["request_key"]
    if valid and claimed:
        valid = ((value["kind"] == "EMPTY" and value["closed"] and value.get("inspection") is None)
                 or (value["kind"] == "INSPECTION" and not value["closed"]
                     and isinstance(value.get("inspection"), dict)))
    if not valid:
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection response is unconfirmed")
    return value


async def _reconcile_inspection_claim(api, args, pending: Path, request: dict) -> None:
    """Seal or query the one original claim; never obtain or replay its work."""
    result = _inspection_slot_response(await api.request("native-session-inspection/claim-reconcile", request),
                                       args.worker_id, request=request)
    if not result["closed"]:
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection remains unconfirmed")
    if result["kind"] in {"INSPECTION", "RETIRED"}:
        # A received or lost capability may have launched a child.  Only a
        # previously committed terminal result permits ordinary work to resume.
        observed = await api.request("native-session-inspection/claim-state",
                                     {"worker_id": args.worker_id, "claim_key": request["request_key"]})
        if (not isinstance(observed, dict) or observed.get("claim_key") != request["request_key"]
                or observed.get("state") not in {"RESTORED", "FAILED"}):
            raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection result is unknown")
    elif result["kind"] not in {"EMPTY", "ABANDONED"}:
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection result is unknown")
    complete_claim(pending)


def _inspection_uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("invalid inspection identity")
    return value


async def _perform_inspection(api, args, state: Path, request: dict, response: dict) -> None:
    """Run one isolated inspection; no capability is persisted or replayed."""
    from .native_sdk_adapter import host_environment
    from .native_session_restore import (
        anchored_identity_for_inspection,
        inspect_original_session_guarded,
    )

    item = response["inspection"]
    try:
        attempt_id = _inspection_uuid(item["attempt_id"])
        inspection_id = _inspection_uuid(item["id"])
        _inspection_uuid(item["project_id"])
        _inspection_uuid(item["task_id"])
        token = item["token"]
        source = item["source"]
        if (item["worker_id"] != args.worker_id or item["state"] != "STARTED"
                or response.get("inspection_id") != inspection_id
                or item["session_id"] != "cloud-" + attempt_id
                or not isinstance(token, str) or not 16 <= len(token) <= 512
                or not isinstance(source, dict) or set(source) != {"sut", "framework"}):
            raise ValueError("invalid inspection response")
    except (KeyError, TypeError, ValueError):
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection identity is invalid") from None

    authority = {"worker_id": args.worker_id, "inspection_id": inspection_id,
                 "claim_key": request["request_key"], "token": token}

    async def assert_active():
        value = await api.request("native-session-inspection/assert", authority)
        if value != {"active": True}:
            raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Inspection authority is unconfirmed")

    # Check current, scoped authority before opening the original private
    # identity record; the guarded child checks again and polls while alive.
    await asyncio.wait_for(assert_active(), 5)
    evidence = {**item, "sut_commit": source["sut"], "framework_commit": source["framework"]}
    root = state / ("attempt-" + attempt_id)
    identity = anchored_identity_for_inspection(attempt_root=root, dsh_home=Path(args.dsh_home).absolute(),
        inspection=evidence, worker_id=args.worker_id, environment=host_environment(os.environ))
    await inspect_original_session_guarded(attempt_root=root, expected_identity_digest=item["identity_digest"],
                                            identity=identity, assert_active=assert_active)
    # Finish is sent exactly once.  If its response is lost, only the original
    # claim's read-only status may be queried; no new capability is requested.
    try:
        result = await api.request("native-session-inspection/finish", {**authority, "status": "RESTORED"})
        if (not isinstance(result, dict) or result.get("id") != inspection_id
                or result.get("attempt_id") != attempt_id or result.get("state") != "RESTORED"):
            raise ValueError("inspection result mismatch")
    except Exception:
        observed = await api.request("native-session-inspection/claim-state",
                                     {"worker_id": args.worker_id, "claim_key": request["request_key"]})
        if (not isinstance(observed, dict) or observed.get("id") != inspection_id
                or observed.get("attempt_id") != attempt_id or observed.get("claim_key") != request["request_key"]
                or observed.get("state") != "RESTORED"):
            raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Original inspection result is unknown") from None


async def inspect_next_original_session(api, args, state: Path) -> bool:
    """Claim at most one original session inspection under the existing Worker lock."""
    current = _inspection_slot_response(await api.request("native-session-inspection/state",
                                                        {"worker_id": args.worker_id}), args.worker_id)
    if not current["closed"]:
        raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "An inspection claim remains outstanding")
    request = {"worker_id": args.worker_id, "request_key": secrets.token_hex(24),
               "sequence": current["sequence"] + 1, "lease_seconds": args.lease_seconds}
    pending = prepare_inspection_claim(state, request)
    try:
        response = _inspection_slot_response(await api.request("native-session-inspection/claim", request),
                                             args.worker_id, request=request, claimed=True)
    except Exception:
        # Original claim may have committed, even for a 5xx.  Never POST again.
        await _reconcile_inspection_claim(api, args, pending, request)
        return False
    if response["kind"] == "EMPTY":
        complete_claim(pending)
        return False
    try:
        await _perform_inspection(api, args, state, request, response)
    except Exception:
        await _reconcile_inspection_claim(api, args, pending, request)
        raise
    complete_claim(pending)
    return True


async def resolve(api, args, state: Path, claim: dict):
    from .native_git import NativeGitResolver

    resolution, task = claim["resolution"], claim["task"]
    root = state / ("resolution-" + resolution["id"])
    root.mkdir(mode=0o700)
    identity = {"worker_id": args.worker_id, "lease_token": claim["lease_token"],
                "work_token": claim["work_token"], "generation": claim["generation"]}
    body = {"identity": identity, "project_id": task["project_id"], "task_id": task["id"],
            "resolution_id": resolution["id"]}
    save_once(root / "claimed.json", {"resolution_id": resolution["id"], "worker_id": args.worker_id})
    resolver = NativeGitResolver()
    repositories = {}
    try:
        async with asyncio.timeout(args.lease_seconds - 5):
            for role in ("sut", "framework"):
                await api.request("resolution/assert", body)
                repositories[role] = await resolver.resolve(claim["configuration"][role]["url"],
                    task["inputs"][role + "_selector"])
    except TimeoutError:
        # The lease bounds both repositories, independently of each Git fetch.
        # Keep a finite diagnostic and never accept partial source resolution.
        raise CloudBlocked("RESOLUTION_TIMEOUT", "Repository resolution exceeded its lease window") from None
    result = {"repositories": repositories, "observed_at": datetime.now(UTC).isoformat(),
              "source": "cloud-worker-fixed-git-resolution"}
    if "environment" in claim["configuration"]:
        result["environment_observation"] = {"state": "UNOBSERVED",
            "reason": "Git preflight does not execute or attest the SUT environment"}
    save_once(root / "result.json", result)
    await api.request("resolution/accept", {**body, "result": result})


def native_prompt(task: dict, attempt: dict, workspace: Path, *, retry_snapshot: bool = False, memory_enabled: bool = False) -> str:
    from .manifests import task_prompt

    value = json.loads(task_prompt(task, attempt, native_harness=True, memory_enabled=memory_enabled))
    value["capabilities"].update(remote_network="HOST_USER_NETWORK_UNVERIFIED",
        ssh="HOST_USER_ACCESS_UNVERIFIED", https_controlled_api="HOST_USER_ACCESS_UNVERIFIED")
    value["instructions"] = [line.replace("/workspace", str(workspace))
        for line in value["instructions"] if not any(phrase in line for phrase in (
            "General remote shell, CI and Git writes are unavailable", "SSH diagnostics are unavailable"))]
    value["instructions"].append(
        "This Harness runs as the host user with that user's configured access. "
        "Never retry an external operation whose outcome is unknown; report its original identity and uncertainty.")
    value["instructions"].append(
        "Published artifacts must not contain credentials, tokens, private keys, or PEM private-key header markers, "
        "even when a marker is only a source-code example; artifact admission rejects such markers. "
        "Check artifacts before publishing, and describe any omission or redaction accurately rather than "
        "presenting a redacted file as an unchanged original.")
    if retry_snapshot:
        value["instructions"].append(
            "This is a new attempt with an independently confirmed execution snapshot. "
            "The current objective, test scope, basic flow, framework entrypoints and authorization in that snapshot "
            "are the user's only authorized instructions for this attempt. The original prompt and PRD are historical context; "
            "its prior one-time-only instruction applies to the original attempt, not the newly confirmed scope. "
            "Never resend an operation with an unknown outcome, even if this attempt has new instructions. "
            "Do not present a previous action identity or result as a new observation from this attempt.")
    value["instructions"].append(
        "The execution environment determines which tools, network paths and credentials are available; "
        "you must still honor any explicit task authorization and testing scope. "
        "The authorization fields git:read and framework:execute also support platform repository preflight; "
        "they are not an inventory of the host environment's capabilities. "
        "Do not infer extra authorization from the host's ability to perform an action.")
    value["instructions"].append(
        "When a user decision or clarification is necessary, use the native ask_user_question tool. "
        "The current SDK session waits for the answer; do not publish a REQUEST_INPUT handoff for live interaction. "
        "Ask only within the frozen task authorization, never include credentials, and do not infer additional authorization from a response. "
        "Native approval requests that would change execution permissions are not supported by this channel.")
    value["instructions"].append(
        "After publishing COMPLETE_ATTEMPT, end your turn immediately without waiting for its receipt. "
        "The Worker must observe the direct SDK process exit before accepting that terminal handoff.")
    return json.dumps(value, ensure_ascii=False)


def native_execution_task(task: dict, attempt: dict) -> tuple[dict, dict, bool]:
    """Validate the original task and select the immutable inputs for this attempt.

    A retry snapshot is a separate execution contract; never mutate the historical
    task or accidentally run it using the old task-level manifest or budget.
    """
    from hypertest.sync_core import digest

    original = task.get("frozen_manifest")
    if not isinstance(original, dict) or digest(original) != task.get("input_digest"):
        raise CloudBlocked("ATTEMPT_SNAPSHOT_MISMATCH", "Original task manifest does not match its digest")
    snapshot = attempt.get("execution_manifest")
    retry_snapshot = snapshot is not None
    manifest = snapshot if retry_snapshot else original
    if not isinstance(manifest, dict) or digest(manifest) != attempt.get("input_digest"):
        raise CloudBlocked("ATTEMPT_SNAPSHOT_MISMATCH", "Attempt manifest does not match its digest")
    if retry_snapshot:
        # Source identity and configuration remain the original fixed choices;
        # only the explicit testing inputs belong to the new attempt.
        fixed = ("profile", "project_id", "cloud_task_id", "config_id", "config_revision",
                 "configuration", "resolution", "resolution_id")
        if (any(manifest.get(key) != original.get(key) for key in fixed)
                or manifest.get("project_id") != task.get("project_id")
                or manifest.get("cloud_task_id") != task.get("id")
                or attempt.get("project_id") != task.get("project_id")
                or attempt.get("task_id") != task.get("id")
                or not isinstance(manifest.get("retry_of_attempt_id"), str)
                or not isinstance(manifest.get("previous_input_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", manifest["previous_input_digest"])
                or not isinstance(manifest.get("inputs"), dict)
                or manifest["inputs"].get("budgets") is not None
                or manifest["inputs"].get("controlled_actions") is not None):
            raise CloudBlocked("ATTEMPT_SNAPSHOT_MISMATCH", "Retry execution snapshot is incompatible")
        task = {**task, "frozen_manifest": manifest, "input_digest": attempt["input_digest"],
                "inputs": manifest["inputs"]}
    return task, manifest, retry_snapshot


async def execute(api, args, state: Path, claim: dict):
    from hypertest.config import get_settings
    from hypertest.sync_core import digest

    from .live_question_bridge import LiveQuestionBridge
    from .manifests import MANIFEST_PROFILE, Handoff
    from .native_git import NativeGitResolver
    from .native_sdk_adapter import NativeSdkAdapter
    from .reporter import CloudTaskReporter

    task, attempt = claim["task"], claim["attempt"]
    broker = RemoteBroker(api, claim, args.worker_id)
    try:
        task, manifest, retry_snapshot = native_execution_task(task, attempt)
    except CloudBlocked:
        await broker.fence_for_recovery("ATTEMPT_RECOVERY_REQUIRED")
        return
    root = state / ("attempt-" + attempt["id"])
    root.mkdir(mode=0o700)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    reporter = CloudTaskReporter(broker=broker, private_root=root / "reporting", workspace=workspace)
    adapter = NativeSdkAdapter(workspace=workspace, dsh_home=Path(args.dsh_home))
    finished = asyncio.Event()
    lease_failure = None
    started = time.monotonic()
    reader = None
    bridge = None
    memory_bridge = None
    memory_monitor = None

    async def heartbeat():
        nonlocal lease_failure
        while not finished.is_set():
            try:
                await asyncio.wait_for(finished.wait(), args.lease_seconds / 3)
            except TimeoutError:
                try:
                    await broker.renew(args.lease_seconds)
                except Exception as error:
                    lease_failure = error
                    broker.suspend_writes()
                    return

    monitor = asyncio.create_task(heartbeat())
    try:
        await reporter.recover()
        await broker.assert_current()
        settings = get_settings()
        if settings.cloud_memory_enabled:
            from .memory import CloudMemoryBridge, CloudMemoryTransport
            memory_transport = None
            try:
                memory_transport = CloudMemoryTransport(broker, settings)
                memory_bridge = CloudMemoryBridge(broker, memory_transport, root / "memory", workspace,
                    timeout_seconds=settings.cloud_memory_timeout_seconds)
                memory_monitor = asyncio.create_task(memory_bridge.run())
            except Exception:
                # Optional independent Memory credentials never block reports
                # or imply authorization from the platform Worker credential.
                if memory_transport is not None:
                    try:
                        await memory_transport.close()
                    except Exception:
                        pass
                memory_bridge = None
        if task["inputs"].get("budgets") is not None:
            raise CloudBlocked("LEGACY_ATTEMPT_UNSUPPORTED", "Frozen legacy budgets require their original runtime")
        resolver = NativeGitResolver()
        for role in ("sut", "framework"):
            await broker.assert_current()
            await resolver.checkout(manifest["resolution"]["repositories"][role], workspace / role)
        await broker.assert_current()
        prompt = native_prompt(task, attempt, workspace, retry_snapshot=retry_snapshot,
            memory_enabled=memory_bridge is not None)
        session_id = "cloud-" + attempt["id"]
        anchor_config = os.environ.get("HYPERTEST_CLOUD_NATIVE_RECOVERY_IDENTITY", "false").strip().lower()
        if anchor_config not in {"true", "false"}:
            raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Invalid native session identity setting")
        resume_identity = None
        if anchor_config == "true":
            resume_identity = await prepare_native_session_identity(root=root, workspace=workspace, args=args,
                task=task, attempt=attempt, manifest=manifest, broker=broker, reporter=reporter, prompt=prompt)
        transition = Handoff(profile=MANIFEST_PROFILE, task_id=task["id"], attempt_id=attempt["id"],
            key="worker-running", operation="TRANSITION", payload={"status": "RUNNING", "reason": "Native SDK runtime admitted",
            "runtime_metadata": {}, "usage_seconds": 0, "cost_microunits": 0})
        result = await reporter.submit_handoff(transition, digest(transition.model_dump(mode="json")))
        if not result.synced:
            raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Original transition needs reconciliation")
        save_once(root / "prompt-intent.json", {"state": "SENT", "session_id": "cloud-" + attempt["id"],
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
        options = {"resume_identity": resume_identity} if resume_identity is not None else {}
        process = await adapter.start(session_id=session_id, title=task["title"], prompt=prompt,
                                      interaction_enabled=True, **options)
        bridge = LiveQuestionBridge(broker, adapter, session_id)
        reader = asyncio.create_task(bridge.read(process))
        accepted_keys = {}
        terminal = None
        while process.returncode is None:
            if lease_failure is not None:
                raise CloudBlocked("WORKER_LEASE_UNCONFIRMED", "Original lease needs reconciliation")
            bridge.check()
            if reader.done() and reader.exception() is not None:
                raise reader.exception()
            observed = await CloudWorker.collect(None, reporter, workspace, accepted_keys, stopped=False)
            if terminal is not None and observed is not None and terminal != observed:
                raise CloudBlocked("TERMINAL_HANDOFF_CONFLICT", "A published terminal handoff changed")
            terminal = observed or terminal
            await asyncio.sleep(0.2)
        await process.wait()
        save_once(root / "runtime-exit.json", {"source": "DIRECT_SDK_PROCESS",
            "returncode": process.returncode, "observed_at": datetime.now(UTC).isoformat()})
        await reader
        bridge.check()
        if bridge.tasks:
            raise CloudBlocked("SDK_QUESTION_DELIVERY_UNKNOWN", "SDK exited with pending questions")
        if lease_failure is not None:
            raise CloudBlocked("WORKER_LEASE_UNCONFIRMED", "Original lease needs reconciliation")
        await broker.assert_current()
        observed = await CloudWorker.collect(None, reporter, workspace, accepted_keys, stopped=False)
        if terminal is not None and observed is not None and terminal != observed:
            raise CloudBlocked("TERMINAL_HANDOFF_CONFLICT", "A published terminal handoff changed")
        terminal = observed or terminal
        if process.returncode != 0 or terminal is None or terminal[0].operation != "COMPLETE_ATTEMPT":
            raise CloudBlocked("ATTEMPT_RECOVERY_REQUIRED", "An explicit native completion needs reconciliation")
        handoff, handoff_digest = terminal
        result = await reporter.submit_native_completion(handoff, handoff_digest,
                                                        usage_seconds=int(time.monotonic() - started))
        if not result.synced:
            raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Original completion needs reconciliation")
        from .artifacts import write_workspace_receipt
        write_workspace_receipt(workspace, handoff.key, result.receipt)
    except BaseException as error:
        broker.suspend_writes()
        try:
            # A lost fence is still unknown. Let it propagate so claim-pending stays.
            await asyncio.wait_for(broker.fence_for_recovery(_recovery_reason(error)), 3)
        finally:
            await adapter.stop()
        raise
    finally:
        finished.set()
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        if memory_monitor is not None:
            memory_monitor.cancel()
            await asyncio.gather(memory_monitor, return_exceptions=True)
        if memory_bridge is not None:
            try:
                await memory_bridge.close()
            except Exception:
                pass  # Memory cleanup must not change a task's accepted result.
        if reader is not None and not reader.done():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if bridge is not None:
            await bridge.close()
        reporter.close()


async def run(args) -> int:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", args.worker_id):
        raise CloudBlocked("WORKER_IDENTITY_INVALID", "Worker ID must match the provisioned identity")
    if not math.isfinite(args.poll_seconds) or args.poll_seconds <= 0:
        raise CloudBlocked("WORKER_POLL_INVALID", "Worker polling interval must be positive and finite")
    state = private_root(args.state_dir)
    with worker_lock(state):
        # Reject legacy or damaged journals before making any API request.
        original = pending_claim(state, args.worker_id)
        inspection = pending_inspection_claim(state, args.worker_id)
        if original is not None and inspection is not None:
            raise CloudBlocked("NATIVE_INSPECTION_RECONCILIATION_REQUIRED", "Conflicting original Worker claims")
        return await _run_locked(args, state)


async def _run_locked(args, state: Path) -> int:
    credential = read_private_file(args.worker_credential_file, max_bytes=65536)
    api = WorkerAPI(args.api_url, credential, ca_file=args.ca_file)
    del credential
    async def observe_auth():
        from .native_auth_probe import probe_native_auth

        while True:
            try:
                status = await asyncio.to_thread(probe_native_auth, args.dsh_home)
                await api.request("auth-observation", {"status": status})
            except Exception:
                # Authentication observations never stop an attempt or publish errors.
                pass
            await asyncio.sleep(60)

    auth_monitor = None
    try:
        runtime_checked = False
        while True:
            original = pending_claim(state, args.worker_id)
            if original is not None:
                pending, request = original
                await _claim_read(api, args, "claim/reconcile", request)
                complete_claim(pending)
                if args.once:
                    return 0
                continue
            original_inspection = pending_inspection_claim(state, args.worker_id)
            if original_inspection is not None:
                pending, request = original_inspection
                await _reconcile_inspection_claim(api, args, pending, request)
                if args.once:
                    return 0
                continue
            # Recovery never depends on an SDK installation. New work still
            # checks the runtime before creating any server-side task lease.
            if not runtime_checked:
                from .native_profile import check_sdk_profile
                from .sdk import inspect_native_sdk

                inspect_native_sdk()
                check_sdk_profile(args.dsh_home)
                check_cordis_runtime()
                runtime_checked = True
                auth_monitor = asyncio.create_task(observe_auth())
            from hypertest.config import get_settings
            if get_settings().cloud_native_session_inspection_enabled:
                if await inspect_next_original_session(api, args, state):
                    if args.once:
                        return 0
                    continue
            current = await _claim_read(api, args, "claim/state", {"worker_id": args.worker_id})
            if not current["closed"]:
                raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Server claim has no matching local intent; explicit recovery is required")
            request = {"worker_id": args.worker_id, "request_key": secrets.token_hex(24),
                "sequence": current["sequence"] + 1, "lease_seconds": args.lease_seconds,
                "supports_attempt_manifest": True}
            pending = prepare_claim(state, request)
            try:
                claim_result = _claim_response(await api.request("claim", request), args.worker_id, request=request)
            except Exception as error:
                # Even a 5xx may follow a committed claim. Never POST it again.
                if args.once or not _retryable_api_failure(error):
                    raise
                await asyncio.sleep(min(max(args.poll_seconds, 0.25), 30))
                continue
            kind = claim_result["kind"]
            if kind == "EMPTY":
                complete_claim(pending)
                if args.once:
                    return 0
                await asyncio.sleep(args.poll_seconds)
                continue
            claim = claim_result["claim"]
            work_error = None
            try:
                if kind == "RESOLUTION":
                    await resolve(api, args, state, claim)
                else:
                    await execute(api, args, state, claim)
            except Exception as error:
                work_error = error
            # Close the original scheduling slot even after normal completion;
            # closure cannot accept reports, restart work or erase UNKNOWN.
            await _claim_read(api, args, "claim/reconcile", request)
            complete_claim(pending)
            if work_error is not None:
                raise work_error
            if args.once:
                return 0
    finally:
        if auth_monitor is not None:
            auth_monitor.cancel()
            await asyncio.gather(auth_monitor, return_exceptions=True)
        await api.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Current-user native Harness Worker")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--worker-credential-file", required=True)
    parser.add_argument("--ca-file", help="CA bundle for the Worker API's TLS certificate")
    parser.add_argument("--dsh-home", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--lease-seconds", type=int, default=90, choices=range(15, 301))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as error:
        from .native_git import GitOperationFailure

        code = error.code if isinstance(error, CloudBlocked) else (
            "WORKER_INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "WORKER_RUNTIME_FAILED")
        diagnostic = {"code": code}
        if isinstance(error, GitOperationFailure):
            diagnostic["git_operation"] = error.operation
            diagnostic["git_exit_code"] = error.exit_code
        print(json.dumps(diagnostic), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
