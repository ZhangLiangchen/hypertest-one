"""Host-native Cloud worker using a separately authenticated platform API.

The SDK executes as the current host user; it receives neither this Worker's
platform credential nor the per-claim lease capabilities through its env or
stdin. Same-user OS access is not a security boundary.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

from .errors import CloudBlocked
from .private_file import read_private_file
from .worker import CloudWorker, private_root, save_once


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


def prepare_claim(state: Path, worker_id: str) -> Path:
    """Never send another claim after an unconfirmed original request."""
    pending = state / "claim-pending.json"
    if pending.exists() or pending.is_symlink():
        raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Original claim must be reconciled before another claim")
    try:
        save_once(pending, {"status": "SENT", "worker_id": worker_id, "local_key": secrets.token_hex(16)})
    except FileExistsError:
        raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Original claim must be reconciled before another claim") from None
    return pending


def complete_claim(pending: Path):
    pending.unlink()
    directory = os.open(pending.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


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
    async with asyncio.timeout(args.lease_seconds - 5):
        for role in ("sut", "framework"):
            await api.request("resolution/assert", body)
            repositories[role] = await resolver.resolve(claim["configuration"][role]["url"],
                task["inputs"][role + "_selector"])
    result = {"repositories": repositories, "observed_at": datetime.now(UTC).isoformat(),
              "source": "cloud-worker-fixed-git-resolution", "environment_observation": {
                  "state": "UNOBSERVED", "reason": "Git preflight does not execute or attest the SUT environment"}}
    save_once(root / "result.json", result)
    await api.request("resolution/accept", {**body, "result": result})


def native_prompt(task: dict, attempt: dict, workspace: Path, *, retry_snapshot: bool = False) -> str:
    from .manifests import task_prompt

    value = json.loads(task_prompt(task, attempt, native_harness=True))
    value["capabilities"].update(remote_network="HOST_USER_NETWORK_UNVERIFIED",
        ssh="HOST_USER_ACCESS_UNVERIFIED", https_controlled_api="HOST_USER_ACCESS_UNVERIFIED")
    value["instructions"] = [line.replace("/workspace", str(workspace))
        for line in value["instructions"] if not any(phrase in line for phrase in (
            "General remote shell, CI and Git writes are unavailable", "SSH diagnostics are unavailable"))]
    value["instructions"].append(
        "This Harness runs as the host user with that user's configured access. "
        "Never retry an external operation whose outcome is unknown; report its original identity and uncertainty.")
    if retry_snapshot:
        value["instructions"].append(
            "This is a new attempt with an independently confirmed execution snapshot. "
            "The current objective, test scope, basic flow, framework entrypoints and authorization in that snapshot "
            "are the user's only authorized instructions for this attempt. The original PRD is historical context; "
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
        if task["inputs"].get("budgets") is not None:
            raise CloudBlocked("LEGACY_ATTEMPT_UNSUPPORTED", "Frozen legacy budgets require their original runtime")
        resolver = NativeGitResolver()
        for role in ("sut", "framework"):
            await broker.assert_current()
            await resolver.checkout(manifest["resolution"]["repositories"][role], workspace / role)
        await broker.assert_current()
        transition = Handoff(profile=MANIFEST_PROFILE, task_id=task["id"], attempt_id=attempt["id"],
            key="worker-running", operation="TRANSITION", payload={"status": "RUNNING", "reason": "Native SDK runtime admitted",
            "runtime_metadata": {}, "usage_seconds": 0, "cost_microunits": 0})
        result = await reporter.submit_handoff(transition, digest(transition.model_dump(mode="json")))
        if not result.synced:
            raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Original transition needs reconciliation")
        prompt = native_prompt(task, attempt, workspace, retry_snapshot=retry_snapshot)
        save_once(root / "prompt-intent.json", {"state": "SENT", "session_id": "cloud-" + attempt["id"],
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
        session_id = "cloud-" + attempt["id"]
        process = await adapter.start(session_id=session_id, prompt=prompt, interaction_enabled=True)
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
    except BaseException:
        broker.suspend_writes()
        try:
            # A lost fence is still unknown. Let it propagate so claim-pending stays.
            await asyncio.wait_for(broker.fence_for_recovery("WORKER_RUNTIME_FAILED"), 3)
        finally:
            await adapter.stop()
        raise
    finally:
        finished.set()
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        if reader is not None and not reader.done():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if bridge is not None:
            await bridge.close()
        reporter.close()


async def run(args) -> int:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", args.worker_id):
        raise CloudBlocked("WORKER_IDENTITY_INVALID", "Worker ID must match the provisioned identity")
    state = private_root(args.state_dir)
    # Detect missing/incompatible local runtime before taking any task lease.
    from .native_profile import check_sdk_profile
    from .sdk import inspect_native_sdk

    inspect_native_sdk()
    check_sdk_profile(args.dsh_home)
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

    auth_monitor = asyncio.create_task(observe_auth())
    try:
        while True:
            pending = prepare_claim(state, args.worker_id)
            claim_result = await api.request("claim", {"worker_id": args.worker_id, "lease_seconds": args.lease_seconds,
                                                       "supports_attempt_manifest": True})
            if not isinstance(claim_result, dict):
                raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Unexpected claim response cannot be replayed")
            kind = claim_result.get("kind")
            if kind == "EMPTY":
                complete_claim(pending)
                if args.once:
                    return 0
                await asyncio.sleep(args.poll_seconds)
                continue
            if kind not in {"RESOLUTION", "ATTEMPT"} or not isinstance(claim_result.get("claim"), dict):
                raise CloudBlocked("CLAIM_RECONCILIATION_REQUIRED", "Unexpected claim response cannot be replayed")
            claim = claim_result["claim"]
            if kind == "RESOLUTION":
                await resolve(api, args, state, claim)
            else:
                await execute(api, args, state, claim)
            complete_claim(pending)
            if args.once:
                return 0
    finally:
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
        code = error.code if isinstance(error, CloudBlocked) else (
            "WORKER_INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "WORKER_RUNTIME_FAILED")
        print(json.dumps({"code": code}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
