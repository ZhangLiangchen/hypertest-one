"""Dedicated opt-in Cloud worker. API and Local sync never run this entry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from hypertest.application import cloud_tasks as service
from hypertest.sync_core import digest

from .artifacts import write_workspace_receipt
from .broker import CloudBroker
from .delegate_broker import CodexOAuthBroker, read_cloud_codex_identity
from .delegation import DelegationObservations, native_profile, request_limits, verify_payload
from .errors import CloudBlocked
from .git import GitResolver
from .handoff_rejections import HandoffRejected
from .manifests import MANIFEST_PROFILE, Handoff, load_handoff, task_prompt
from .model_broker import REFUSED_CATEGORIES, ModelBroker
from .private_file import read_private_file
from .reporter import CloudTaskReporter
from .resources import inspect_resource_envelope
from .runtime_activity import project_finish_reason, project_runtime_activity
from .sandbox import (
    NATIVE_CODEX_ADDRESS_SPACE_BYTES,
    ROOT_ADDRESS_SPACE_BYTES,
    BubblewrapSandbox,
    SandboxPolicy,
    capability_report,
    require_cloud_environment_route,
)
from .sdk import SDK_PHASES, SdkOperationError, inspect_sdk, project_sdk_error
from .ssh_profile import validate_profile
from .worker_admission import inspect_ssh_client, inspect_ssh_local_identity, read_ssh_authority
from .worker_diagnostics import attach_failure, exception_metadata, failure_code, failure_metadata


def runtime_diagnostic_metadata(source: dict) -> dict:
    """A reported SDK failure helps diagnosis; it cannot establish a test result."""
    result = {}
    phase = source.get("last_phase")
    if isinstance(phase, str) and phase in SDK_PHASES:
        result["last_phase"] = phase
    if "first_sdk_error" in source:
        result["first_sdk_error"] = project_sdk_error(source["first_sdk_error"])
    counts = source.get("activity_counts")
    if isinstance(counts, dict):
        projected = {}
        for kind, count in counts.items():
            if type(count) is int and count >= 0:
                fixed = project_runtime_activity({"kind": kind})["kind"]
                projected[fixed] = min(projected.get(fixed, 0) + count, 1000000)
        result["activity_counts"] = projected
    recent = source.get("recent_activity")
    if isinstance(recent, list):
        result["recent_activity"] = [project_runtime_activity(value) for value in recent[-64:]]
    if "idle_finish_reason" in source:
        result["idle_finish_reason"] = project_finish_reason(source["idle_finish_reason"])
    return {"source": "sandbox-runtime-reported", **result} if result else {}


def host_model_metadata(scopes: dict, stopped: dict) -> dict:
    observations = []
    for scope, broker in scopes.items():
        if scope not in {"ROOT", "CODEX", "CLAUDE_CODE"}:
            continue
        try:
            raw = broker.observation()
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        counts = {}
        for name in ("requests", "upstream_successes", "upstream_completed", "inflight", "refused_scope_count"):
            value = raw.get(name)
            counts[name] = min(value, 1000000) if type(value) is int and value >= 0 else None
        # Do not copy provider dictionaries: only fixed HTTP status numbers and
        # the broker's closed diagnostic vocabulary may reach durable metadata.
        for name, allowed in (
            ("upstream_status_counts", tuple(str(code) for code in range(100, 600)) + ("OTHER",)),
            ("transport_failure_counts", ("DNS", "TLS", "TIMEOUT", "CONNECT", "OTHER")),
            ("refused_category_counts", tuple(sorted(REFUSED_CATEGORIES))),
        ):
            values = raw.get(name)
            projected = {}
            if isinstance(values, dict):
                for key in allowed:
                    count = values.get(key)
                    if type(count) is int and count >= 0:
                        projected[key] = min(count, 1000000)
            counts[name] = projected
        observations.append({"scope": scope, **counts, "closed": raw.get("closed") is True,
            "drained": raw.get("drained") is True})
    return {"source": "host-managed-model-brokers", "scopes": observations,
        "namespace_stopped": stopped.get("local_processes_stopped") is True}


def private_root(path: str | Path) -> Path:
    root = Path(path).absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if root.is_symlink() or root.resolve() != root or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise CloudBlocked("RUNTIME_ROOT_UNSAFE", "Cloud state requires a private non-symlink directory")
    return root


def save_once(path: Path, document: dict) -> None:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_model_key(path: str | Path) -> bytes:
    try:
        content = read_private_file(path, max_bytes=65536).strip()
    except CloudBlocked as error:
        code = "MODEL_KEY_PERMISSIONS" if error.code == "PRIVATE_FILE_UNSAFE" else "MODEL_KEY_UNAVAILABLE"
        raise CloudBlocked(code, "Model service identity is unavailable or outside its private file profile") from None
    if not content:
        raise CloudBlocked("MODEL_KEY_UNAVAILABLE", "Model service identity is unavailable")
    return content


class CloudWorker:
    def __init__(self, sessions, settings, worker_id: str):
        self.sessions, self.settings, self.worker_id = sessions, settings, worker_id
        self.resolver = GitResolver()

    def enabled(self):
        if not self.settings.cloud_enabled or not self.settings.cloud_worker_enabled:
            raise CloudBlocked("CLOUD_WORKER_DISABLED", "Cloud scheduling and this worker must both be explicitly enabled")

    async def run_once(self) -> bool:
        self.enabled()
        if getattr(self.settings, "cloud_ssh_enabled", False):
            inspect_ssh_local_identity()
        inspect_resource_envelope()
        async with self.sessions() as db:
            await service.expire_leases(db)
        async with self.sessions() as db:
            resolution = await service.claim_resolution(db, self.worker_id,
                lease_seconds=self.settings.cloud_worker_lease_seconds)
        if resolution:
            await self.resolve(resolution)
            return True
        async with self.sessions() as db:
            claim = await service.claim_attempt(db, self.worker_id,
                lease_seconds=self.settings.cloud_worker_lease_seconds)
        if not claim:
            return False
        await self.execute(claim)
        return True

    async def resolve(self, claim: dict):
        """No Harness/test execution and no automatic retry of moving refs."""
        root = private_root(self.settings.cloud_runtime_root) / ("resolution-" + claim["resolution"]["id"])
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            raise CloudBlocked("RESOLUTION_RECOVERY_REQUIRED", "Original resolution state must be reconciled; Git is not repeated") from None
        save_once(root / "claimed.json", {"resolution_id": claim["resolution"]["id"], "worker_id": self.worker_id})
        async with self.sessions() as db:
            credentials = await service.materialize_resolution_credentials(db,
                UUID(claim["resolution"]["id"]), self.worker_id, claim["lease_token"], claim["work_token"])
        repositories = {}
        async with asyncio.timeout(self.settings.cloud_worker_lease_seconds - 5):
            for role in ("sut", "framework"):
                # Check the same resolution capability before every new access;
                # expiration/revocation never starts another repository action.
                async with self.sessions() as db:
                    credentials = await service.materialize_resolution_credentials(db,
                        UUID(claim["resolution"]["id"]), self.worker_id, claim["lease_token"], claim["work_token"])
                repositories[role] = await self.resolver.resolve(claim["configuration"][role]["url"],
                    claim["task"]["inputs"][role + "_selector"], token=credentials.get(role.upper()))
        result = {"repositories": repositories, "observed_at": datetime.now(UTC).isoformat(),
            "source": "cloud-worker-fixed-git-resolution", "environment_observation": {
                "state": "UNOBSERVED", "reason": "Git preflight does not execute or attest the SUT environment"}}
        save_once(root / "result.json", result)
        async with self.sessions() as db:
            # An interrupted acceptance leaves result.json and the original key;
            # it never re-enters the resolver or follows a newer branch.
            await service.accept_resolution(db, UUID(claim["resolution"]["id"]),
                self.worker_id, claim["lease_token"], result, work_token=claim["work_token"])

    async def execute(self, claim: dict):
        broker = CloudBroker(self.sessions, claim, self.worker_id)
        task, attempt = claim["task"], claim["attempt"]
        root = private_root(self.settings.cloud_runtime_root) / ("attempt-" + attempt["id"])
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            # A service restart must never reuse an existing runtime directory
            # as a fresh prompt. Remove this claim's write rights immediately.
            try:
                await asyncio.wait_for(broker.fence_for_recovery("ATTEMPT_RECOVERY_REQUIRED"), 3)
            except Exception:
                pass  # The unchanged lease will expire; no execution is begun.
            raise CloudBlocked("ATTEMPT_RECOVERY_REQUIRED", "Existing runtime state requires explicit reconciliation; no prompt is replayed") from None
        workspace, home = root / "workspace", root / "dsh-home"
        workspace.mkdir(mode=0o700)
        home.mkdir(mode=0o700)
        reporter = CloudTaskReporter(broker=broker, private_root=root / "reporting", workspace=workspace)
        sandbox = None
        finished = asyncio.Event()
        lease_failure = None
        started = time.monotonic()
        prompt_sent = False
        model_broker = None
        accepted_keys: dict[str, str] = {}
        stdout_reader = None
        runtime_diagnostics: dict = {}
        terminal_accepted = False
        preparing = None
        native_enabled = getattr(self.settings, "cloud_codex_enabled", False)
        delegations = DelegationObservations() if native_enabled else None
        submitted_delegations: set[str] = set()
        scope_brokers: dict[str, ModelBroker] = {}
        limits: list[dict] = []
        accounting_unit = "CONSERVATIVE_MICROUNITS"
        primary_failure = None
        primary_metadata = None
        secondary_failures = []
        model_observation_attempted = False
        runtime_diagnostics_attempted = False
        ssh_broker = None
        ssh_authority = None
        ssh_cleanup_attempted = False
        ssh_observation = None
        ssh_deadline = None
        http_broker = None
        http_authority = None
        http_deadline = None
        writes_suspended = False
        safety_fence_done = asyncio.Event()
        memory_bridge = None
        memory_task = None
        models = ExitStack()

        async def safety_fence(reason, metadata=None):
            nonlocal writes_suspended
            if writes_suspended:
                await safety_fence_done.wait()
                return
            writes_suspended = True
            broker.suspend_writes()
            try:
                # A DB/network failure cannot postpone local process cleanup.
                # This narrow operation only removes this original ownership.
                await asyncio.wait_for(broker.fence_for_recovery(reason, metadata=metadata), 3)
            except (Exception, asyncio.CancelledError) as secondary:
                secondary_failure("SAFETY_FENCE", secondary)
            finally:
                safety_fence_done.set()

        async def close_ssh():
            nonlocal ssh_cleanup_attempted, ssh_observation
            if ssh_broker is None or ssh_observation is not None:
                return
            if not ssh_cleanup_attempted:
                ssh_cleanup_attempted = True
                await ssh_broker.close()
            raw = ssh_broker.observation()
            # Only fixed host metadata is persisted; outputs and credentials
            # belong to the independent canonical operation ledger, not here.
            pending = raw.get("pending_operations")
            try:
                valid_ids = isinstance(pending, list) and all(isinstance(value, str)
                    and str(UUID(value)) == value for value in pending)
            except ValueError:
                valid_ids = False
            if (not valid_ids or type(raw.get("inflight")) is not int or raw["inflight"] < 0):
                raise CloudBlocked("SSH_OBSERVATION_INVALID", "SSH cleanup metadata is not a bounded host observation")
            ssh_observation = {"source": "host-ssh-broker", "closed": raw.get("closed") is True,
                "remote_closed": raw.get("remote_closed") is True,
                "pending_operations": pending[:8], "inflight": raw["inflight"]}
            if len(pending) > 8:
                raise CloudBlocked("SSH_OBSERVATION_INVALID", "SSH operation count exceeds its frozen capability")
            save_once(root / "ssh-observations.json", ssh_observation)

        async def remote_operations_closed() -> bool:
            if http_broker is not None:
                return http_broker.drained and (await http_authority.remote_closed()) is True
            if ssh_broker is None:
                return True  # Only the admitted workspace-local profile.
            return bool(ssh_observation and ssh_observation["closed"]
                and ssh_observation["remote_closed"] and not ssh_observation["pending_operations"]
                and ssh_observation["inflight"] == 0 and (await ssh_authority.remote_closed()) is True)

        def secondary_failure(stage, error):
            if len(secondary_failures) < 8:
                secondary_failures.append({"stage": stage, "error": exception_metadata(error)})
            if primary_failure is not None:
                attach_failure(primary_failure, primary_metadata, secondary_failures)

        def persist_model_observation(stopped):
            nonlocal model_observation_attempted
            if model_observation_attempted:
                return
            model_observation_attempted = True
            try:
                save_once(root / "model-observations.json", host_model_metadata(scope_brokers, stopped))
            except Exception as secondary:
                secondary_failure("WORKER_DIAGNOSTIC_WRITE", secondary)

        def persist_runtime_diagnostics():
            nonlocal runtime_diagnostics_attempted
            observed = runtime_diagnostic_metadata(runtime_diagnostics)
            if runtime_diagnostics_attempted or not observed:
                return
            runtime_diagnostics_attempted = True
            try:
                save_once(root / "runtime-diagnostics.json", observed)
            except Exception as secondary:
                secondary_failure("RUNTIME_DIAGNOSTIC_WRITE", secondary)

        def observed_cost():
            rates = {item["scope"]: item["cost_per_request_microunits"] for item in limits}
            return sum(item.requests * rates[scope] for scope, item in scope_brokers.items())

        async def heartbeat():
            nonlocal lease_failure
            while not finished.is_set():
                try:
                    await asyncio.wait_for(finished.wait(), self.settings.cloud_worker_lease_seconds / 3)
                except TimeoutError:
                    try:
                        await broker.renew(self.settings.cloud_worker_lease_seconds)
                    except Exception:
                        lease_failure = CloudBlocked("WORKER_FENCED", "Worker ownership or authorization is no longer current")
                        # Renewal loss is uncertain, not permission to keep
                        # reporting until the server eventually expires a lease.
                        broker.suspend_writes()
                        if preparing is not None:
                            preparing.cancel()
                        await safety_fence("WORKER_LEASE_UNCONFIRMED")
                        if sandbox is not None:
                            await sandbox.stop()
                        return

        async def host_transition(status, code, metadata=None, *, reservation=None):
            payload = {"status": status, "reason": code, "runtime_metadata": metadata or {},
                "usage_seconds": int(time.monotonic() - started), "cost_microunits": observed_cost()}
            if reservation is not None:
                payload["budget_reservation"] = reservation
            handoff = Handoff(profile=MANIFEST_PROFILE, task_id=broker.task_id, attempt_id=broker.attempt_id,
                key="worker-" + status.lower(), operation="TRANSITION", payload=payload)
            result = await reporter.submit_handoff(handoff, digest(handoff.model_dump(mode="json")))
            if not result.synced:
                raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Worker transition requires original receipt/readback reconciliation")

        monitor = asyncio.create_task(heartbeat())
        try:
            await reporter.recover()
            await broker.assert_current()
            if getattr(self.settings, "cloud_memory_enabled", False):
                try:
                    from .memory import CloudMemoryBridge, CloudMemoryTransport
                    memory_transport = CloudMemoryTransport(broker, self.settings)
                    memory_bridge = CloudMemoryBridge(broker, memory_transport, root / "memory", workspace,
                        timeout_seconds=self.settings.cloud_memory_timeout_seconds)
                except Exception:
                    # Independent optional credentials/configuration failure
                    # never changes the mission admission or reported result.
                    memory_bridge = None
            manifest = task["frozen_manifest"]
            if not manifest or digest(manifest) != task["input_digest"] or task["input_digest"] != attempt["input_digest"]:
                raise CloudBlocked("FROZEN_INPUT_MISMATCH", "Attempt does not match its frozen task input")
            if attempt.get("checkpoint"):
                raise CloudBlocked("SDK_RESUME_UNSUPPORTED", "Historical checkpoints require explicit reconciled resume support")
            remaining = claim.get("budget_remaining", {})
            if not remaining or self.settings.cloud_model_request_cost_microunits <= 0:
                raise CloudBlocked("MODEL_COST_UNCONFIGURED", "A conservative model request cost and cumulative budget are required")
            seconds = min(self.settings.cloud_attempt_timeout_seconds, remaining["seconds"])
            # Convert the same whole-attempt monotonic deadline once. Git
            # preparation does not grant a fresh SSH or model time window.
            ssh_deadline = int(time.time() + max(0, started + seconds - time.monotonic()))
            accounting_unit = manifest["inputs"]["budgets"].get("accounting_unit", "CONSERVATIVE_MICROUNITS")
            if native_enabled and accounting_unit != "REQUEST_CREDITS":
                raise CloudBlocked("CODEX_ACCOUNTING_UNSUPPORTED", "Cloud Codex OAuth requires a task explicitly frozen in REQUEST_CREDITS, not a monetary-price claim")
            limits = request_limits(self.settings, remaining=remaining["cost_microunits"], allow_codex=native_enabled)
            requests = limits[0]["max_requests"]
            environment = manifest.get("configuration", {}).get("environment", {})
            require_cloud_environment_route(environment)
            ssh_profile = None
            http_profile = None
            if environment.get("connection", "NONE") == "HTTPS":
                if not getattr(self.settings, "cloud_https_enabled", False):
                    raise CloudBlocked("HTTPS_DISABLED", "Controlled HTTPS reads require an explicit Worker opt-in")
                from .http_profile import validate_profile as validate_http_profile
                http_profile = validate_http_profile(environment)
            if environment.get("connection", "NONE") == "SSH":
                if not getattr(self.settings, "cloud_ssh_enabled", False):
                    raise CloudBlocked("SSH_DISABLED", "Fixed SSH diagnostics require a separate explicit Worker opt-in")
                ssh_profile = validate_profile(environment)
                # All remote STOP/QUERY work remains inside the original total
                # budget; the model deadline and non-SSH path do not move.
                ssh_deadline -= 30
                if time.time() >= ssh_deadline:
                    raise CloudBlocked("SSH_CLEANUP_WINDOW_EXHAUSTED", "Remaining attempt time cannot reserve bounded SSH cleanup")
                inspect_ssh_client(self.settings)
            policy = SandboxPolicy(seconds, requests, self.settings.cloud_model_max_tokens,
                memory_bytes=NATIVE_CODEX_ADDRESS_SPACE_BYTES if native_enabled else ROOT_ADDRESS_SPACE_BYTES,
                ssh_profile=ssh_profile, http_profile=http_profile)
            policy.validate(manifest)
            metadata = inspect_sdk()
            payload_root = None
            oauth_identity = None
            if native_enabled:
                native_profile(model=self.settings.cloud_codex_model, codex_base_url="http://127.0.0.1:1")
                payload_root = Path(self.settings.cloud_codex_payload)
                metadata["native_codex"] = verify_payload(payload_root, self.settings.cloud_codex_payload_sha256)
                oauth_identity = read_cloud_codex_identity(self.settings.cloud_codex_oauth_file, required_seconds=seconds + 60)
            credentials = await broker.credentials()
            if ssh_profile is not None:
                from hypertest.application.cloud_ssh import WorkerSshAuthority

                from .ssh_broker import SshBroker
                from .ssh_tickets import signer_public_key

                ssh_key = credentials.get("ENVIRONMENT")
                if not isinstance(ssh_key, (str, bytes)) or not ssh_key:
                    raise CloudBlocked("SSH_CREDENTIAL_UNAVAILABLE", "Fixed SSH diagnostics require their authorized environment identity")
                signing_key = read_ssh_authority(self.settings)
                if signer_public_key(signing_key) != ssh_profile.authority_public_key:
                    raise CloudBlocked("SSH_AUTHORITY_MISMATCH", "Frozen SSH authority does not match the independent host signing identity")
                ssh_authority = WorkerSshAuthority(self.sessions, task_id=broker.task_id,
                    attempt_id=broker.attempt_id, identity=broker.identity)
                ssh_broker = SshBroker(root / "ssh.sock", profile=ssh_profile, authority=ssh_authority,
                    ssh_key=ssh_key.encode() if isinstance(ssh_key, str) else ssh_key,
                    signing_key=signing_key, private_root=root / "ssh",
                    deadline=ssh_deadline,
                    ssh_executable=Path(self.settings.cloud_ssh_executable),
                    ssh_executable_sha256=self.settings.cloud_ssh_executable_sha256)
                del ssh_key, signing_key
            if http_profile is not None:
                from hypertest.application.cloud_http import WorkerHttpAuthority

                from .http_broker import HttpBroker
                http_authority = WorkerHttpAuthority(self.sessions, task_id=broker.task_id,
                    attempt_id=broker.attempt_id, identity=broker.identity)
                http_deadline = int(time.time() + max(0, started + seconds - time.monotonic()))
                http_broker = HttpBroker(root / "https.sock", profile=http_profile, authority=http_authority,
                    private_root=root / "https", deadline=http_deadline)
            for role in ("sut", "framework"):
                await broker.assert_current()
                async with asyncio.timeout(max(0.01, started + seconds - time.monotonic())):
                    preparing = asyncio.create_task(self.resolver.checkout(manifest["resolution"]["repositories"][role],
                        workspace / role, token=credentials.get(role.upper())))
                    try:
                        await preparing
                    finally:
                        preparing = None
            credentials.clear()
            await broker.assert_current()
            framework_runtime = None
            if manifest["inputs"].get("framework_runtime") is not None:
                from .framework_runtime import inspect_framework_runtime
                framework_runtime = await inspect_framework_runtime(workspace / "framework",
                    manifest["inputs"]["framework_runtime"], manifest["inputs"]["framework_entrypoints"])
                save_once(root / "framework-runtime.json", framework_runtime)
            if time.monotonic() - started >= seconds:
                raise CloudBlocked("RUNTIME_BUDGET_EXHAUSTED", "Input preparation exhausted the remaining task time budget")
            if ssh_profile is not None and time.time() >= ssh_deadline:
                raise CloudBlocked("SSH_CLEANUP_WINDOW_EXHAUSTED", "Input preparation consumed the fixed SSH action window; no fresh deadline is granted")
            session_id = "cloud-" + attempt["id"]
            metadata = {key: value for key, value in metadata.items()
                if key not in {"launch_executable", "launch_paths", "model_started"}}
            metadata.update(capabilities=capability_report(ssh_admitted=ssh_profile is not None,
                https_admitted=http_profile is not None), native_session_id=session_id)
            if framework_runtime is not None:
                metadata["framework_runtime"] = framework_runtime
            if http_profile is not None:
                metadata["https"] = {"profile": "HTTPS_CONTROLLED_API_V1", "hard_deadline_epoch": http_deadline}
            if ssh_profile is not None:
                metadata["ssh"] = {"profile": "SSH_FIXED_DIAGNOSTICS_V1",
                    "hard_deadline_epoch": ssh_deadline}
            metadata["runtime_limits"] = policy.resource_metadata(inspect_resource_envelope(
                max_memory_bytes=policy.aggregate_memory_bytes, max_processes=policy.aggregate_processes))
            metadata["capabilities"] = {**metadata["capabilities"], "external_cli_delegation": native_enabled,
                "codex": {"enabled": native_enabled, "configured": native_enabled,
                          "observed": False, "model": self.settings.cloud_codex_model if native_enabled else None},
                "claude_code": "PLACEHOLDER"}
            metadata["capabilities"]["memory"] = {"configured": memory_bridge is not None,
                "requires_separate_project_grant": True, "human_publication_required": True}
            model_broker = ModelBroker(root / "model.sock", base_url=self.settings.cloud_model_base_url,
                api_key=read_model_key(self.settings.cloud_model_key_file), model=self.settings.cloud_model,
                max_requests=requests, max_tokens=policy.max_tokens, deadline=started + seconds)
            scope_brokers["ROOT"] = models.enter_context(model_broker)
            sockets = {}
            if native_enabled:
                child_limit = next(item for item in limits if item["scope"] == "CODEX")
                scope_brokers["CODEX"] = models.enter_context(CodexOAuthBroker(root / "codex.sock",
                    identity=oauth_identity, model=self.settings.cloud_codex_model,
                    max_requests=child_limit["max_requests"], deadline=started + seconds))
                sockets["codex"] = root / "codex.sock"
            if ssh_broker is not None:
                await ssh_broker.start()
            if http_broker is not None:
                await http_broker.start()
            sandbox = BubblewrapSandbox(workspace=workspace, dsh_home=home,
                broker_socket=root / "model.sock", policy=policy,
                delegate_payload=payload_root, delegate_sockets=sockets,
                ssh_socket=root / "ssh.sock" if ssh_broker is not None else None,
                http_socket=root / "https.sock" if http_broker is not None else None)
            sandbox.command()  # Fail admission before recording a prompt intent.
            await host_transition("RUNNING", "Pinned SDK runtime admitted", metadata,
                reservation={"accounting_unit": accounting_unit, "reserved_seconds": seconds,
                             "request_limits": limits})
            await broker.assert_current()
            require_cloud_environment_route(environment)
            prompt = task_prompt(task, attempt, allow_delegation=native_enabled, ssh_profile=ssh_profile,
                memory_enabled=memory_bridge is not None, http_profile=http_profile)
            configuration = {"workspace": "/workspace", "dsh_home": "/home/agent/dsh",
                "session_id": session_id, "model": self.settings.cloud_model,
                "max_tokens": policy.max_tokens, "timeout_seconds": seconds, "prompt": prompt}
            if native_enabled:
                configuration["native_delegation"] = {"codex_model": self.settings.cloud_codex_model}
            save_once(root / "prompt-intent.json", {"state": "SENT", "session_id": session_id,
                "generation": broker.identity.generation, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "runtime_limits": {"model": configuration["model"], "max_tokens": configuration["max_tokens"],
                    **metadata["runtime_limits"],
                    "timeout_seconds": configuration["timeout_seconds"],
                    "reasoning_effort": configuration.get("reasoning_effort"),
                    "codex_model": configuration.get("native_delegation", {}).get("codex_model"),
                    "request_limits": [{"scope": item["scope"], "max_requests": item["max_requests"]} for item in limits]}})
            prompt_sent = True
            process = await sandbox.start(configuration)
            if memory_bridge is not None:
                memory_task = asyncio.create_task(memory_bridge.run())
            stdout_reader = asyncio.create_task(self.consume_runtime(process, delegations=delegations,
                diagnostics=runtime_diagnostics))
            deadline = started + seconds
            terminal = None
            while process.returncode is None:
                if lease_failure:
                    raise lease_failure
                if time.monotonic() >= deadline:
                    await safety_fence("RUNTIME_TIMEOUT")
                    raise CloudBlocked("RUNTIME_TIMEOUT", "Attempt exceeded its remaining execution budget")
                if ssh_broker is not None and not ssh_cleanup_attempted and time.time() >= ssh_deadline:
                    # Fence just this scope while the root can still finish
                    # workspace work within its unchanged original budget.
                    await close_ssh()
                    if not await remote_operations_closed():
                        raise CloudBlocked("SSH_RECONCILIATION_REQUIRED", "SSH cleanup did not confirm remote stopping inside its reserved window")
                if stdout_reader.done() and stdout_reader.exception() is not None:
                    raise stdout_reader.exception()
                terminal = await self.collect(reporter, workspace, accepted_keys, stopped=False,
                    delegations=delegations, submitted_delegations=submitted_delegations)
                if terminal:
                    await sandbox.stop()
                    break
                await asyncio.sleep(0.2)
            if lease_failure:
                raise lease_failure
            await asyncio.wait_for(process.wait(), 3)
            await asyncio.wait_for(stdout_reader, 3)
            stopped = await sandbox.stop()
            persist_runtime_diagnostics()
            await broker.assert_current()
            terminal = terminal or await self.collect(reporter, workspace, accepted_keys, stopped=False,
                delegations=delegations, submitted_delegations=submitted_delegations)
            if not terminal:
                raise CloudBlocked("EXPLICIT_HANDOFF_MISSING", "SDK activity ended without an explicit terminal handoff")
            handoff, handoff_digest = terminal
            if delegations is not None and (not delegations.channel_closed or not delegations.all_terminal or
                    {item["native_ref"] for item in delegations.runs.values()} != submitted_delegations):
                raise CloudBlocked("DELEGATION_RECONCILIATION_REQUIRED", "Native delegates need observed terminals and accepted parent contributions")
            # Listener shutdown alone does not prove upstream requests ended.
            # Stop every model scope and observe all in-flight work before
            # accounting or accepting a task terminal.
            models.close()
            persist_model_observation(stopped)
            if not all(item.observation()["drained"] for item in scope_brokers.values()):
                raise CloudBlocked("MODEL_DRAIN_UNCONFIRMED", "Model requests remain in flight; keep the original budget reservation and reconcile")
            await close_ssh()
            if http_broker is not None:
                await http_broker.close()
            if not await remote_operations_closed():
                raise CloudBlocked("SSH_RECONCILIATION_REQUIRED", "Canonical remote operations are not all observed stopped; retain the original reservation")
            usage = int(time.monotonic() - started)
            settlement = {"accounting_unit": accounting_unit, "observed_seconds": usage,
                "namespace_stopped": stopped["local_processes_stopped"], "brokers_drained": True,
                "requests": [{"scope": scope, "requests": item.requests} for scope, item in scope_brokers.items()]}
            result = await reporter.submit_handoff(handoff, handoff_digest,
                runtime_stopped=stopped["local_processes_stopped"],
                external_operations_reconciled=await remote_operations_closed(),
                usage_seconds=usage, cost_microunits=observed_cost(), budget_settlement=settlement)
            if not result.synced:
                raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Terminal handoff needs original receipt/readback reconciliation")
            terminal_accepted = True
            write_workspace_receipt(workspace, handoff.key, result.receipt)
        except (Exception, asyncio.CancelledError) as error:
            # Capture the business/SDK first failure before any stop, disk write,
            # DB query or failure-report path can itself throw.
            primary_metadata = exception_metadata(error)
            diagnostics = runtime_diagnostic_metadata(runtime_diagnostics)
            sdk_error = diagnostics.get("first_sdk_error")
            cancelled = isinstance(error, asyncio.CancelledError)
            if cancelled and lease_failure is not None:
                primary_failure = lease_failure
            elif sdk_error is not None and lease_failure is None and not terminal_accepted:
                primary_failure = SdkOperationError(sdk_error)
            else:
                primary_failure = error
            attach_failure(primary_failure, primary_metadata, secondary_failures)
            pending = None
            try:
                pending = reporter.pending()
            except Exception as secondary:
                secondary_failure("REPORT_PENDING_READ", secondary)
            if not terminal_accepted and not writes_suspended and (prompt_sent or cancelled or pending is None or pending):
                recovery_metadata = {"worker_diagnostics": failure_metadata(primary_failure),
                                     "interruption_reason": failure_code(primary_failure)}
                if diagnostics:
                    recovery_metadata["sdk_diagnostics"] = diagnostics
                await safety_fence("WORKER_INTERRUPTED" if cancelled else
                    "REPORT_RECONCILIATION_PENDING" if pending is None or pending else "WORKER_RUNTIME_FAILED",
                    recovery_metadata)
            if writes_suspended:
                # Renewal failure can cancel preparation while its bounded
                # safety-fence request is still in flight in the heartbeat.
                await safety_fence_done.wait()
            try:
                save_once(root / "worker-error.json", failure_metadata(primary_failure))
            except Exception as secondary:
                secondary_failure("WORKER_DIAGNOSTIC_WRITE", secondary)
            stopped = {"local_processes_stopped": sandbox is None}
            if sandbox is not None:
                try:
                    stopped = await sandbox.stop()
                except (Exception, asyncio.CancelledError) as secondary:
                    secondary_failure("NAMESPACE_STOP", secondary)
            persist_runtime_diagnostics()
            if http_broker is not None:
                try:
                    await http_broker.close()
                except (Exception, asyncio.CancelledError) as secondary:
                    secondary_failure("HTTPS_BROKER_CLOSE", secondary)
            try:
                await close_ssh()
            except (Exception, asyncio.CancelledError) as secondary:
                secondary_failure("SSH_REMOTE_CLEANUP", secondary)
            try:
                models.close()
            except (Exception, asyncio.CancelledError) as secondary:
                secondary_failure("MODEL_BROKER_CLOSE", secondary)
            observed_models = host_model_metadata(scope_brokers, stopped)
            persist_model_observation(stopped)
            if pending == [] and lease_failure is None and not terminal_accepted and not writes_suspended:
                metadata = {"worker_diagnostics": failure_metadata(primary_failure),
                    "host_model_observation": observed_models}
                if diagnostics:
                    metadata["sdk_diagnostics"] = diagnostics
                if ssh_observation is not None:
                    metadata["ssh_observation"] = ssh_observation
                code = "WORKER_INTERRUPTED" if cancelled else failure_code(primary_failure)
                status = "RECOVERY_REQUIRED" if prompt_sent or not stopped.get("local_processes_stopped") else "FAILED"
                try:
                    await host_transition(status, code, metadata)
                except (Exception, asyncio.CancelledError) as secondary:
                    secondary_failure("REPORT_TRANSITION", secondary)
            try:
                save_once(root / "worker-cleanup.json", {**failure_metadata(primary_failure),
                    "host_model_observation": observed_models})
            except Exception as secondary:
                secondary_failure("WORKER_DIAGNOSTIC_WRITE", secondary)
            if primary_failure is error:
                raise
            raise primary_failure from None
        finally:
            if http_broker is not None:
                try:
                    await http_broker.close()
                except (Exception, asyncio.CancelledError) as secondary:
                    if primary_failure is None:
                        raise
                    secondary_failure("HTTPS_BROKER_CLOSE", secondary)
            if memory_task is not None:
                memory_task.cancel()
                await asyncio.gather(memory_task, return_exceptions=True)
            if memory_bridge is not None:
                try:
                    await memory_bridge.close()
                except Exception:
                    pass  # Independent memory cleanup cannot rewrite a result.
            models.close()
            finished.set()
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            if stdout_reader is not None:
                stdout_reader.cancel()
                await asyncio.gather(stdout_reader, return_exceptions=True)
            if ssh_broker is not None and not ssh_cleanup_attempted:
                try:
                    await close_ssh()
                except (Exception, asyncio.CancelledError) as secondary:
                    if primary_failure is None:
                        raise
                    secondary_failure("SSH_REMOTE_CLEANUP", secondary)
            try:
                reporter.close()
            except Exception as secondary:
                if primary_failure is None:
                    attach_failure(secondary, exception_metadata(secondary), [])
                    raise
                secondary_failure("REPORTER_CLOSE", secondary)

    async def collect(self, reporter, workspace, accepted_keys, *, stopped,
                      delegations=None, submitted_delegations=None):
        ready = workspace / ".hypertest-cloud" / "ready"
        if not ready.exists():
            return None
        if ready.is_symlink() or not ready.resolve().is_relative_to(workspace.resolve()):
            raise CloudBlocked("HANDOFF_PATH_INVALID", "Handoff directory escapes the approved workspace")
        files = sorted(ready.iterdir())
        if len(files) > 1000:
            raise CloudBlocked("HANDOFF_COUNT_LIMIT", "Attempt exceeds its bounded handoff count")
        terminal = None
        for path in files:
            if not path.name.endswith(".json"):
                continue
            relative = ".hypertest-cloud/ready/" + path.name
            handoff, source_digest = load_handoff(workspace, relative,
                task_id=reporter.broker.task_id, attempt_id=reporter.broker.attempt_id)
            if handoff.key in accepted_keys:
                if accepted_keys[handoff.key] != source_digest:
                    raise CloudBlocked("HANDOFF_CHANGED", "A published handoff changed after acceptance")
                continue
            if reporter.rejected(handoff.key):
                continue  # A rejected key is immutable; only a new key can revise it.
            if handoff.operation == "SUBMIT_DELEGATION" and delegations is None:
                raise CloudBlocked("DELEGATION_CAPABILITY_UNSUPPORTED", "Native delegation is not admitted for this attempt")
            await reporter.broker.assert_current()
            try:
                reporter.prevalidate_handoff(handoff, source_digest)
            except HandoffRejected:
                continue  # Only local, pre-journal schema failures reach here.
            if handoff.operation in {"COMPLETE_ATTEMPT", "REQUEST_INPUT"}:
                if terminal is not None:
                    raise CloudBlocked("TERMINAL_HANDOFF_CONFLICT", "Attempt has competing terminal handoffs")
                if delegations is None or (delegations.channel_closed and delegations.all_terminal and
                        {item["native_ref"] for item in delegations.runs.values()} == submitted_delegations):
                    terminal = handoff, source_digest
                continue
            observation = None
            if handoff.operation == "SUBMIT_DELEGATION":
                if delegations is None:
                    raise CloudBlocked("DELEGATION_CAPABILITY_UNSUPPORTED", "Native delegation is not admitted for this attempt")
                try:
                    observation = delegations.terminal(handoff.payload.get("native_ref"))
                except CloudBlocked as error:
                    if error.code == "DELEGATION_NOT_TERMINAL":
                        continue
                    raise
            await reporter.broker.assert_current()
            options = {"delegation_observation": observation} if observation is not None else {}
            try:
                result = await reporter.submit_handoff(handoff, source_digest, **options)
            except HandoffRejected:
                continue
            if not result.synced:
                raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Original handoff must be reconciled before later reports")
            write_workspace_receipt(workspace, handoff.key, result.receipt)
            accepted_keys[handoff.key] = source_digest
            if observation is not None:
                submitted_delegations.add(observation["native_ref"])
        return terminal

    @staticmethod
    async def consume_runtime(process, *, delegations=None, diagnostics=None):
        total = 0
        while line := await process.stdout.readline():
            total += len(line)
            if total > 2 * 1024 * 1024 or len(line) > 65536:
                raise CloudBlocked("RUNTIME_OBSERVATION_LIMIT", "Runtime activity exceeded its bounded metadata stream")
            try:
                observation = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                raise CloudBlocked("RUNTIME_OBSERVATION_INVALID", "Runtime emitted an unsupported metadata frame") from None
            if isinstance(observation, dict) and diagnostics is not None:
                phase = observation.get("runtime_phase")
                if isinstance(phase, str) and phase in SDK_PHASES:
                    diagnostics["last_phase"] = phase
                if observation.get("runtime_observation") == "ERROR" and "first_sdk_error" not in diagnostics:
                    diagnostics["first_sdk_error"] = project_sdk_error(observation.get("sdk_error"))
                if "runtime_activity" in observation:
                    activity = project_runtime_activity(observation["runtime_activity"])
                    counts = diagnostics.setdefault("activity_counts", {})
                    kind = activity["kind"]
                    counts[kind] = min(counts.get(kind, 0) + 1, 1000000)
                    recent = diagnostics.setdefault("recent_activity", [])
                    recent.append(activity)
                    del recent[:-64]
                if observation.get("runtime_observation") == "IDLE":
                    diagnostics["idle_finish_reason"] = project_finish_reason(observation.get("finish_reason"))
            if isinstance(observation, dict) and "delegation" in observation:
                if delegations is None or set(observation) != {"delegation"}:
                    raise CloudBlocked("DELEGATION_CAPABILITY_UNSUPPORTED", "Unadmitted native delegate observation")
                delegations.accept(observation["delegation"])
            if isinstance(observation, dict) and "native_delegation_closed" in observation:
                if (delegations is None or observation != {"native_delegation_closed": True}
                        or delegations.channel_closed or not delegations.all_terminal):
                    raise CloudBlocked("DELEGATION_METADATA_INCOMPLETE", "Native lifecycle metadata has no complete terminal boundary")
                delegations.channel_closed = True
            # Only fixed diagnostic metadata may be retained. Runtime activity
            # never supplies a testing result or an authoritative task terminal.
