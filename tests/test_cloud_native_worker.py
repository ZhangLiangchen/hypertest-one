import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from hypertest.cloud.broker import BrokerFailure
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.manifests import MANIFEST_PROFILE, Handoff
from hypertest.cloud.native_worker import (
    WorkerAPI,
    complete_claim,
    pending_claim,
    prepare_claim,
    worker_lock,
)
from hypertest.cloud.reporter import CloudTaskReporter
from hypertest.cloud.worker import save_once


def claim_request(**changes):
    return {"worker_id": "native-fixture", "sequence": 1, "request_key": "original-claim-key-123456",
        "lease_seconds": 90, "supports_attempt_manifest": True, **changes}


def test_main_git_failure_emits_operation_and_exit_code_without_raw_error(monkeypatch, capsys):
    from hypertest.cloud import native_worker
    from hypertest.cloud.native_git import GitOperationFailure

    async def fail(args):
        error = GitOperationFailure("GIT_OPERATION_FAILED", "fetch", 128)
        error.args = ("private URL, credential and stderr",)
        raise error
    monkeypatch.setattr(native_worker, "run", fail)
    # main() uses asyncio.run(); keep its event-loop lifecycle isolated from
    # the pytest-asyncio loop used by the rest of the suite.
    with ThreadPoolExecutor(max_workers=1) as pool:
        code = pool.submit(native_worker.main, ["--api-url", "https://localhost:18444", "--worker-id", "fixture",
            "--worker-credential-file", "/unused", "--dsh-home", "/unused", "--state-dir", "/unused"]).result()
    assert code == 1
    assert json.loads(capsys.readouterr().out) == {
        "code": "GIT_OPERATION_FAILED", "git_operation": "fetch", "git_exit_code": 128}


def claim_response(request=None, *, kind="EMPTY", closed=True, **fields):
    return {"worker_id": "native-fixture", "sequence": request["sequence"] if request else 0,
        "request_key": request["request_key"] if request else None, "kind": kind, "closed": closed, **fields}


@pytest.fixture
def loop_args(tmp_path, monkeypatch):
    from hypertest.cloud import native_profile, native_worker, sdk

    credential = tmp_path / "worker-token"
    credential.write_text("test-only-worker-" + "x" * 40)
    credential.chmod(0o600)
    monkeypatch.setattr(sdk, "inspect_native_sdk", lambda: None)
    monkeypatch.setattr(native_profile, "check_sdk_profile", lambda _: None)
    monkeypatch.setattr(native_worker, "check_cordis_runtime", lambda: None)
    return SimpleNamespace(worker_id="native-fixture", state_dir=str(tmp_path), dsh_home="fixture",
        worker_credential_file=str(credential), api_url="https://example.invalid", ca_file=None,
        lease_seconds=90, once=True, poll_seconds=1)


@pytest.mark.asyncio
async def test_cordis_preflight_failure_does_not_claim_new_work(tmp_path, monkeypatch, loop_args):
    from hypertest.cloud import native_worker

    async def unexpected_request(*args):
        raise AssertionError("A failed Cordis preflight must not contact the claim API")

    def unavailable():
        raise CloudBlocked("HARNESS_CORDIS_UNAVAILABLE", "Preset unavailable")

    monkeypatch.setattr(native_worker, "check_cordis_runtime", unavailable)
    mock_worker_api(monkeypatch, unexpected_request)
    with pytest.raises(CloudBlocked) as error:
        await native_worker.run(loop_args)
    assert error.value.code == "HARNESS_CORDIS_UNAVAILABLE"
    assert not (tmp_path / "claim-pending.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("synced", [True, False])
async def test_native_identity_requires_anchor_readback(tmp_path, monkeypatch, synced):
    from hypertest.cloud import native_resume_identity, native_selection, native_worker

    calls = []
    def selection(**kwargs):
        calls.append("selection")
        assert "HYPERTEST_WORKER_TOKEN" not in kwargs["environment"]
        return {"provider": "deepseek-official", "model": "deepseek-flash"}
    def snapshot(root, **kwargs):
        calls.append("snapshot")
        assert kwargs["session_id"] == "cloud-attempt"
        assert kwargs["title_sha256"] == hashlib.sha256("任务标题".encode()).hexdigest()
        return "a" * 64
    class Reporter:
        async def submit_native_session_anchor(self, **kwargs):
            calls.append("anchor")
            assert kwargs["snapshot_sha256"] == "a" * 64
            return SimpleNamespace(synced=synced)
    monkeypatch.setenv("HYPERTEST_WORKER_TOKEN", "must-not-reach-sdk")
    monkeypatch.setattr(native_selection, "read_native_selection", selection)
    monkeypatch.setattr(native_resume_identity, "record_initial_identity", snapshot)
    kwargs = dict(root=tmp_path, workspace=tmp_path, args=SimpleNamespace(dsh_home=str(tmp_path), worker_id="worker"),
                  task={"project_id": "project", "id": "task", "title": "任务标题"}, attempt={"id": "attempt", "input_digest": "d" * 64},
                  manifest={"resolution": {"repositories": {"sut": {"commit_sha": "a" * 40},
                                                           "framework": {"commit_sha": "b" * 40}}}},
                  broker=SimpleNamespace(identity=SimpleNamespace(generation=1)), reporter=Reporter(), prompt="test")
    if synced:
        identity = await native_worker.prepare_native_session_identity(**kwargs)
        assert identity["digest"] == "a" * 64
        assert "environment" not in identity["original"]
    else:
        with pytest.raises(CloudBlocked) as error:
            await native_worker.prepare_native_session_identity(**kwargs)
        assert error.value.code == "REPORT_RECONCILIATION_PENDING"
    assert calls == ["selection", "snapshot", "anchor"]


def test_cordis_preflight_supplies_explicit_probe_title(monkeypatch):
    from hypertest.cloud import native_cordis, native_worker

    directories = []

    def prepare(directory, *, title):
        assert directory.is_dir()
        assert title == "HyperTest Cordis preflight probe"
        directories.append(directory)
        return directory / "overlay.yml"

    monkeypatch.setattr(native_cordis, "prepare_cordis_overlay", prepare)
    native_worker.check_cordis_runtime()
    assert directories and not directories[0].exists()


def mock_worker_api(monkeypatch, request):
    from hypertest.cloud import native_worker

    class API:
        def __init__(self, *args, **kwargs):
            pass

        async def request(self, operation, body):
            if operation == "auth-observation":
                return {"recorded": True}
            return await request(operation, body)

        async def close(self):
            pass

    monkeypatch.setattr(native_worker, "WorkerAPI", API)


def test_claim_must_not_be_replayed_after_unconfirmed_send(tmp_path):
    request = claim_request()
    pending = prepare_claim(tmp_path, request)
    assert pending_claim(tmp_path, "native-fixture") == (pending, request)
    with pytest.raises(CloudBlocked, match="Original claim"):
        prepare_claim(tmp_path, request)
    complete_claim(pending)
    assert prepare_claim(tmp_path, claim_request(sequence=2)).exists()


def test_worker_state_is_exclusive_and_lock_releases_after_exit(tmp_path):
    with worker_lock(tmp_path):
        with pytest.raises(CloudBlocked) as failure, worker_lock(tmp_path):
            pass
        assert failure.value.code == "WORKER_ALREADY_RUNNING"
    with worker_lock(tmp_path):
        pass


@pytest.mark.asyncio
async def test_http_rejection_is_distinct_from_unconfirmed_transport():
    client = WorkerAPI("https://example.invalid", b"a" * 32)
    await client.client.aclose()
    async def denied(request):
        return httpx.Response(409, json={"detail": "private response"})
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(denied), base_url="https://example.invalid/")
    with pytest.raises(BrokerFailure) as rejected:
        await client.request("submit", {})
    assert rejected.value.status == 409 and "private response" not in str(rejected.value)
    await client.client.aclose()
    async def lost(request):
        raise httpx.ReadTimeout("private transport content", request=request)
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(lost), base_url="https://example.invalid/")
    with pytest.raises(CloudBlocked) as unknown:
        await client.request("submit", {})
    assert unknown.value.code == "WORKER_API_UNCONFIRMED" and "private" not in str(unknown.value)
    await client.close()


@pytest.mark.asyncio
async def test_only_fixed_content_admission_response_has_specific_recovery_reason():
    from hypertest.cloud.native_worker import _recovery_reason

    client = WorkerAPI("https://example.invalid", b"a" * 32)
    await client.client.aclose()
    async def response_for(detail):
        async def respond(request):
            return httpx.Response(422, json=detail)
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="https://example.invalid/")
        try:
            with pytest.raises(CloudBlocked) as error:
                await client.request("validate-payload", {})
            return error.value
        finally:
            await client.client.aclose()

    error = await response_for({"detail": "REPORT_CONTENT_REJECTED"})
    assert error.code == _recovery_reason(error) == "REPORT_CONTENT_REJECTED"
    assert "private" not in str(error)
    for response in ({"detail": "private unknown 422"}, {"detail": "REPORT_CONTENT_REJECTED", "extra": "private"}):
        error = await response_for(response)
        assert isinstance(error, BrokerFailure) and error.status == 422
        assert _recovery_reason(error) == "WORKER_RUNTIME_FAILED" and "private" not in str(error)
    assert _recovery_reason(TimeoutError("private")) == "WORKER_RUNTIME_FAILED"


@pytest.mark.asyncio
async def test_legacy_worker_fences_retry_snapshot_before_runtime_creation(monkeypatch):
    from hypertest.cloud import worker as legacy

    observations = []

    class Broker:
        def __init__(self, sessions, claim, worker_id):
            pass

        async def fence_for_recovery(self, reason):
            observations.append(reason)

    def unexpected_root(_):
        raise AssertionError("unsupported retry must not create a runtime directory")

    monkeypatch.setattr(legacy, "CloudBroker", Broker)
    monkeypatch.setattr(legacy, "private_root", unexpected_root)
    worker = object.__new__(legacy.CloudWorker)
    worker.docker_runtime, worker.sessions, worker.worker_id = None, None, "legacy-worker"
    with pytest.raises(CloudBlocked) as failure:
        await worker.execute({"task": {}, "attempt": {"execution_manifest": {"inputs": {}}}})
    assert failure.value.code == "ATTEMPT_SNAPSHOT_UNSUPPORTED"
    assert observations == ["ATTEMPT_RECOVERY_REQUIRED"]


@pytest.mark.asyncio
async def test_native_worker_claim_advertises_attempt_snapshot_support(tmp_path, monkeypatch, loop_args):
    from hypertest.cloud import native_worker

    requests = []

    async def request(operation, body):
        requests.append((operation, body))
        if operation == "claim/state":
            return claim_response()
        assert pending_claim(tmp_path, "native-fixture")[1] == body
        return claim_response(body, claim=None)

    mock_worker_api(monkeypatch, request)
    assert await native_worker.run(loop_args) == 0
    assert [operation for operation, _ in requests] == ["claim/state", "claim"]
    sent = requests[-1][1]
    assert sent["sequence"] == 1 and sent["supports_attempt_manifest"] is True and sent["lease_seconds"] == 90
    assert len(sent["request_key"]) >= 16
    assert not (tmp_path / "claim-pending.json").exists()


@pytest.mark.parametrize("kind", ["ABANDONED", "RETIRED"])
async def test_pending_claim_restart_only_closes_original_without_runtime(tmp_path, monkeypatch, loop_args, kind):
    from hypertest.cloud import native_worker, sdk

    original = claim_request(lease_seconds=120)
    prepare_claim(tmp_path, original)
    requests = []

    def unexpected_runtime(*args, **kwargs):
        raise AssertionError("Recovering a claim must not load or start a runtime")

    monkeypatch.setattr(sdk, "inspect_native_sdk", unexpected_runtime)
    monkeypatch.setattr(native_worker, "check_cordis_runtime", unexpected_runtime)
    monkeypatch.setattr(native_worker, "execute", unexpected_runtime)
    monkeypatch.setattr(native_worker, "resolve", unexpected_runtime)

    async def request(operation, body):
        requests.append((operation, body))
        fields = {"current_sequence": body["sequence"] + 1} if kind == "RETIRED" else {}
        return claim_response(body, kind=kind, **fields)

    mock_worker_api(monkeypatch, request)
    assert await native_worker.run(loop_args) == 0
    assert requests == [("claim/reconcile", original)]
    assert pending_claim(tmp_path, loop_args.worker_id) is None


@pytest.mark.parametrize("damage", ["legacy", "digest", "worker"])
async def test_legacy_or_damaged_pending_never_gets_discarded(tmp_path, monkeypatch, loop_args, damage):
    from hypertest.cloud import native_worker

    if damage == "legacy":
        pending = tmp_path / "claim-pending.json"
        save_once(pending, {"status": "SENT", "worker_id": loop_args.worker_id, "local_key": "old-local-only-key"})
    else:
        pending = prepare_claim(tmp_path, claim_request())
        record = json.loads(pending.read_text())
        if damage == "digest":
            record["request"]["lease_seconds"] = 180
        else:
            record["request"]["worker_id"] = "different-worker"
        pending.write_text(json.dumps(record))
    before = pending.read_bytes()

    async def unexpected_request(*args):
        raise AssertionError("Unsafe journal must be rejected before API access")

    mock_worker_api(monkeypatch, unexpected_request)
    with pytest.raises(CloudBlocked):
        await native_worker.run(loop_args)
    assert pending.read_bytes() == before


@pytest.mark.parametrize("status", [None, 503, 401, 403])
async def test_once_unconfirmed_or_rejected_claim_keeps_exact_intent(tmp_path, monkeypatch, loop_args, status):
    from hypertest.cloud import native_worker

    requests = []

    async def request(operation, body):
        requests.append((operation, body))
        if operation == "claim/state":
            return claim_response()
        if status is None:
            raise CloudBlocked("WORKER_API_UNCONFIRMED", "Synthetic transport failure")
        raise BrokerFailure(status, "CLOUD_OPERATION_REJECTED")

    mock_worker_api(monkeypatch, request)
    with pytest.raises(CloudBlocked):
        await native_worker.run(loop_args)
    assert pending_claim(tmp_path, loop_args.worker_id)[1] == requests[-1][1]
    assert [operation for operation, _ in requests] == ["claim/state", "claim"]


async def test_idle_failure_recovers_original_key_then_polls_new_sequence(tmp_path, monkeypatch, loop_args):
    from hypertest.cloud import native_worker

    loop_args.once = False
    requests, delays = [], []
    original = None
    state_failures = reconcile_failures = 0

    async def request(operation, body):
        nonlocal original, state_failures, reconcile_failures
        requests.append((operation, dict(body)))
        if operation == "claim/state":
            if state_failures == 0:
                state_failures += 1
                raise BrokerFailure(503, "CLOUD_OPERATION_REJECTED")
            return claim_response(original, kind="ABANDONED" if original else "EMPTY")
        if operation == "claim":
            if original is None:
                original = dict(body)
                raise CloudBlocked("WORKER_API_UNCONFIRMED", "Synthetic lost response after delivery")
            assert body["sequence"] == original["sequence"] + 1 and body["request_key"] != original["request_key"]
            loop_args.once = True
            return claim_response(body, claim=None)
        assert operation == "claim/reconcile" and body == original
        if reconcile_failures == 0:
            reconcile_failures += 1
            raise BrokerFailure(502, "CLOUD_OPERATION_REJECTED")
        return claim_response(body, kind="ABANDONED")

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(native_worker.asyncio, "sleep", sleep)
    mock_worker_api(monkeypatch, request)
    assert await native_worker.run(loop_args) == 0
    claims = [body for operation, body in requests if operation == "claim"]
    assert [body["sequence"] for body in claims] == [1, 2]
    assert all(body == original for operation, body in requests if operation == "claim/reconcile")
    assert delays and all(0 < delay <= 30 for delay in delays)
    assert pending_claim(tmp_path, loop_args.worker_id) is None


@pytest.mark.parametrize("kind", ["ATTEMPT", "RESOLUTION"])
async def test_restart_after_work_started_never_replays_it(tmp_path, monkeypatch, loop_args, kind):
    from hypertest.cloud import native_worker

    requests, executions = [], []

    async def request(operation, body):
        requests.append((operation, dict(body)))
        if operation == "claim/state":
            return claim_response()
        if operation == "claim":
            return claim_response(body, kind=kind, closed=False, claim={"synthetic": True})
        assert operation == "claim/reconcile"
        return claim_response(body, kind=kind)

    async def interrupted(*args):
        executions.append(kind)
        raise asyncio.CancelledError()

    mock_worker_api(monkeypatch, request)
    monkeypatch.setattr(native_worker, "execute" if kind == "ATTEMPT" else "resolve", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await native_worker.run(loop_args)
    original = pending_claim(tmp_path, loop_args.worker_id)[1]
    assert await native_worker.run(loop_args) == 0
    assert executions == [kind]
    assert requests[-1] == ("claim/reconcile", original)
    assert len([operation for operation, _ in requests if operation == "claim"]) == 1


async def test_terminal_slot_close_retries_without_executing_again(tmp_path, monkeypatch, loop_args):
    from hypertest.cloud import native_worker

    loop_args.once = False
    executions, closes = [], []

    async def request(operation, body):
        if operation == "claim/state":
            return claim_response()
        if operation == "claim":
            return claim_response(body, kind="ATTEMPT", closed=False, claim={"synthetic": True})
        assert operation == "claim/reconcile"
        closes.append(dict(body))
        if len(closes) == 1:
            raise CloudBlocked("WORKER_API_UNCONFIRMED", "Synthetic lost close response")
        loop_args.once = True
        return claim_response(body, kind="ATTEMPT")

    async def execute(*args):
        executions.append("completed")

    async def sleep(_delay):
        pass

    monkeypatch.setattr(native_worker, "execute", execute)
    monkeypatch.setattr(native_worker.asyncio, "sleep", sleep)
    mock_worker_api(monkeypatch, request)
    assert await native_worker.run(loop_args) == 0
    assert executions == ["completed"] and closes[0] == closes[1]
    assert pending_claim(tmp_path, loop_args.worker_id) is None


async def test_runtime_failure_closes_original_slot_then_stops(tmp_path, monkeypatch, loop_args):
    from hypertest.cloud import native_worker

    loop_args.once = False
    requests = []

    async def request(operation, body):
        requests.append((operation, dict(body)))
        if operation == "claim/state":
            return claim_response()
        if operation == "claim":
            return claim_response(body, kind="ATTEMPT", closed=False, claim={"synthetic": True})
        assert operation == "claim/reconcile"
        return claim_response(body, kind="ATTEMPT")

    async def execute(*args):
        raise CloudBlocked("SYNTHETIC_RUNTIME_FAILED", "Synthetic runtime stopped")

    monkeypatch.setattr(native_worker, "execute", execute)
    mock_worker_api(monkeypatch, request)
    with pytest.raises(CloudBlocked) as failure:
        await native_worker.run(loop_args)
    assert failure.value.code == "SYNTHETIC_RUNTIME_FAILED"
    assert [operation for operation, _ in requests] == ["claim/state", "claim", "claim/reconcile"]
    assert requests[1][1] == requests[2][1] and pending_claim(tmp_path, loop_args.worker_id) is None


async def test_server_unclosed_claim_without_local_intent_stops_before_delivery(tmp_path, monkeypatch, loop_args):
    from hypertest.cloud import native_worker

    requests = []

    async def request(operation, body):
        requests.append(operation)
        return claim_response(claim_request(), kind="ATTEMPT", closed=False)

    mock_worker_api(monkeypatch, request)
    with pytest.raises(CloudBlocked) as failure:
        await native_worker.run(loop_args)
    assert failure.value.code == "CLAIM_RECONCILIATION_REQUIRED"
    assert requests == ["claim/state"] and pending_claim(tmp_path, loop_args.worker_id) is None


async def test_mismatched_recovery_response_never_clears_pending(tmp_path, monkeypatch, loop_args):
    from hypertest.cloud import native_worker

    original = claim_request()
    pending = prepare_claim(tmp_path, original)

    async def request(operation, body):
        assert operation == "claim/reconcile" and body == original
        return claim_response(claim_request(request_key="different-claim-key-123456"), kind="RETIRED", current_sequence=2)

    mock_worker_api(monkeypatch, request)
    with pytest.raises(CloudBlocked):
        await native_worker.run(loop_args)
    assert pending_claim(tmp_path, loop_args.worker_id) == (pending, original)


@pytest.mark.asyncio
async def test_native_completion_does_not_claim_unknown_processes_or_external_scope(tmp_path):
    ids = [str(uuid4()) for _ in range(5)]
    class Broker:
        project_id, task_id, attempt_id = ids[:3]
        version = 1
        identity = SimpleNamespace(generation=1)
        async def validate_payload(self, payload):
            self.payload = payload
    broker = Broker()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=workspace)
    async def deliver(intent):
        return SimpleNamespace(synced=False, intent=intent)
    reporter.core.deliver = deliver
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id=broker.task_id, attempt_id=broker.attempt_id,
        key="finish", operation="COMPLETE_ATTEMPT", payload={"final_report_revision": ids[3],
        "reported_result": "UNKNOWN", "completion_manifest": {"required_asset_ids": [ids[4]],
        "scope_and_gaps": "Native host execution", "pending_operation_keys": []}})
    outcome = await reporter.submit_native_completion(handoff, "a" * 64, usage_seconds=4)
    payload = outcome.intent.payload
    assert payload["operation"] == "COMPLETE_NATIVE_ATTEMPT"
    assert payload["runtime_observation"] == "DIRECT_SDK_PROCESS_EXITED"
    assert payload["completion_manifest"]["all_local_processes_stopped"] is False
    assert payload["completion_manifest"]["external_operations_reconciled"] is False
    reporter.close()


@pytest.mark.asyncio
async def test_native_completion_persists_receipt_and_full_original_readback(tmp_path):
    import hashlib
    import json

    from hypertest.api.cloud_schemas import PROFILE

    ids = [str(uuid4()) for _ in range(5)]
    class Broker:
        project_id, task_id, attempt_id = ids[:3]
        version = 1
        identity = SimpleNamespace(generation=1)
        async def validate_payload(self, payload):
            pass
        async def submit(self, payload):
            checkpoint = {"final_report_revision": ids[3], "completion_manifest": payload["completion_manifest"],
                "native_completion_observation": {"runtime": "DIRECT_SDK_PROCESS_EXITED",
                    "other_local_processes": "UNKNOWN", "external_operations": "NOT_OBSERVED"}}
            self.document = {"task": {"id": self.task_id, "project_id": self.project_id, "version": 2,
                "status": "COMPLETED", "reported_result": "UNKNOWN"},
                "attempts": [{"id": self.attempt_id, "status": "COMPLETED", "reported_result": "UNKNOWN",
                              "checkpoint": checkpoint}], "assets": []}
            return {"status": "ACCEPTED", "profile": PROFILE, "project_id": self.project_id,
                "task_id": self.task_id, "attempt_id": self.attempt_id, "operation": payload["operation"],
                "operation_key": payload["operation_key"], "version": 2, "checkpoint": checkpoint}
        async def page(self, *, version, offset, limit):
            content = json.dumps(self.document)
            page = content[offset:offset + limit]
            return {"task_id": self.task_id, "version": version, "offset": offset, "content": page,
                "total_characters": len(content), "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "next_offset": offset + len(page), "complete": offset + len(page) == len(content)}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    broker = Broker()
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=workspace)
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id=broker.task_id, attempt_id=broker.attempt_id,
        key="finish", operation="COMPLETE_ATTEMPT", payload={"final_report_revision": ids[3],
        "reported_result": "UNKNOWN", "completion_manifest": {"required_asset_ids": [ids[4]],
        "scope_and_gaps": "Host process and remote operations unobserved", "pending_operation_keys": []}})
    result = await reporter.submit_native_completion(handoff, "a" * 64, usage_seconds=4)
    assert result.synced and reporter.version == 2 and not reporter.pending()
    reporter.close()


@pytest.mark.asyncio
async def test_resolution_rechecks_original_authority_before_each_git_access(tmp_path, monkeypatch):
    from hypertest.cloud.native_git import NativeGitResolver
    from hypertest.cloud.native_worker import resolve

    ids = [str(uuid4()) for _ in range(3)]
    operations = []
    class API:
        async def request(self, operation, body):
            operations.append((operation, body))
            return {"current": True}
    async def fake_resolve(self, url, selector, *, token=None):
        operations.append(("git", {"url": url, "token": token}))
        return {"url": url, "selector": selector, "commit_sha": "a" * 40}
    monkeypatch.setattr(NativeGitResolver, "resolve", fake_resolve)
    claim = {"resolution": {"id": ids[2]}, "task": {"id": ids[1], "project_id": ids[0],
        "inputs": {"sut_selector": {"kind": "BRANCH", "value": "main"},
                   "framework_selector": {"kind": "BRANCH", "value": "main"}}},
        "configuration": {"sut": {"url": "https://example.invalid/sut"},
                          "framework": {"url": "ssh://git@example.invalid/framework"}},
        "lease_token": "lease", "work_token": "work", "generation": 1}
    await resolve(API(), SimpleNamespace(worker_id="worker-test", lease_seconds=90), tmp_path, claim)
    assert [operation for operation, _ in operations] == ["resolution/assert", "git", "resolution/assert", "git", "resolution/accept"]
    assert all(body["token"] is None for operation, body in operations if operation == "git")
    assert (tmp_path / ("resolution-" + ids[2]) / "result.json").exists()


@pytest.mark.asyncio
async def test_resolution_lease_timeout_cancels_git_without_accepting_partial_sources(tmp_path, monkeypatch):
    import asyncio

    from hypertest.cloud.errors import CloudBlocked
    from hypertest.cloud.native_git import NativeGitResolver
    from hypertest.cloud.native_worker import resolve

    operations = []
    cancelled = []
    class API:
        async def request(self, operation, body):
            operations.append(operation)
            return {"current": True}
    async def stalled_git(self, url, selector, *, token=None):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    monkeypatch.setattr(NativeGitResolver, "resolve", stalled_git)
    resolution_id = str(uuid4())
    claim = {"resolution": {"id": resolution_id}, "task": {"id": str(uuid4()), "project_id": str(uuid4()),
        "inputs": {"sut_selector": {"kind": "SHA", "value": "a" * 40},
                   "framework_selector": {"kind": "SHA", "value": "b" * 40}}},
        "configuration": {"sut": {"url": "https://example.invalid/sut"},
                          "framework": {"url": "https://example.invalid/framework"}},
        "lease_token": "lease", "work_token": "work", "generation": 1}
    with pytest.raises(CloudBlocked) as failure:
        await resolve(API(), SimpleNamespace(worker_id="worker-test", lease_seconds=5.01), tmp_path, claim)
    assert failure.value.code == "RESOLUTION_TIMEOUT"
    assert cancelled and operations == ["resolution/assert"]
    assert not (tmp_path / ("resolution-" + resolution_id) / "result.json").exists()


def test_native_prompt_describes_host_network_and_terminal_exit(tmp_path):
    import json

    from hypertest.cloud.native_worker import native_prompt

    task_id, attempt_id = str(uuid4()), str(uuid4())
    prompt = json.loads(native_prompt({"id": task_id, "frozen_manifest": {}}, {"id": attempt_id}, tmp_path))
    assert prompt["capabilities"]["remote_network"] == "HOST_USER_NETWORK_UNVERIFIED"
    assert prompt["capabilities"]["ssh"] == "HOST_USER_ACCESS_UNVERIFIED"
    assert prompt["capabilities"]["https_controlled_api"] == "HOST_USER_ACCESS_UNVERIFIED"
    assert any("end your turn immediately without waiting" in line for line in prompt["instructions"])
    assert any("native ask_user_question" in line and "do not publish a REQUEST_INPUT" in line for line in prompt["instructions"])
    assert any("PEM private-key header markers" in line and "redaction accurately" in line for line in prompt["instructions"])
    assert all("SSH diagnostics are unavailable" not in line for line in prompt["instructions"])
    assert any(str(tmp_path / "framework") in line for line in prompt["instructions"])
    assert prompt["capabilities"]["memory"]["configured"] is False
    shared = json.loads(native_prompt({"id": task_id, "frozen_manifest": {}}, {"id": attempt_id}, tmp_path, memory_enabled=True))
    assert shared["capabilities"]["memory"]["requires_separate_project_grant"] is True
    assert shared["memory_contract"]["response_directory"] == ".hypertest-cloud/memory-responses"
    assert any("external_results" in line and "not HyperTest human-reviewed" in line for line in shared["instructions"])


def test_native_retry_uses_its_verified_manifest_without_changing_the_original(tmp_path):
    import copy
    import json

    from hypertest.cloud.native_worker import native_execution_task, native_prompt
    from hypertest.sync_core import digest

    task_id, project_id, attempt_id = (str(uuid4()) for _ in range(3))
    original = {"profile": "test", "project_id": project_id, "cloud_task_id": task_id,
        "config_id": "config", "config_revision": 1, "configuration": {},
        "resolution": {"repositories": {}}, "resolution_id": "resolution",
        "inputs": {"budgets": {"max_attempts": 1}, "controlled_actions": {"old": True},
                   "basic_flow": "Do not repeat old work"}}
    snapshot = copy.deepcopy(original)
    snapshot["inputs"] = {"budgets": None, "basic_flow": "New scope", "test_scope": "Explicit new scope"}
    snapshot.update(retry_of_attempt_id=str(uuid4()), previous_input_digest=digest(original))
    task = {"id": task_id, "project_id": project_id, "frozen_manifest": original,
            "input_digest": digest(original), "inputs": original["inputs"]}
    attempt = {"id": attempt_id, "task_id": task_id, "project_id": project_id,
               "execution_manifest": snapshot, "input_digest": digest(snapshot)}
    untouched = copy.deepcopy(task)
    effective, selected, retry = native_execution_task(task, attempt)
    assert retry and selected == snapshot and effective["inputs"]["basic_flow"] == "New scope"
    assert task == untouched and task["inputs"]["budgets"]["max_attempts"] == 1
    prompt = json.loads(native_prompt(effective, attempt, tmp_path, retry_snapshot=retry))
    assert prompt["frozen_manifest"] == snapshot
    assert any("original prompt and PRD are historical context" in line for line in prompt["instructions"])
    assert any("Never resend an operation with an unknown outcome" in line for line in prompt["instructions"])


def test_native_original_attempt_uses_task_manifest():
    from hypertest.cloud.native_worker import native_execution_task
    from hypertest.sync_core import digest

    manifest = {"inputs": {"budgets": None}, "resolution": {}}
    task = {"frozen_manifest": manifest, "input_digest": digest(manifest), "inputs": manifest["inputs"]}
    result, effective_manifest, retry = native_execution_task(task, {"input_digest": digest(manifest)})
    assert result is task and effective_manifest is manifest and not retry
    with pytest.raises(CloudBlocked):
        native_execution_task(task, {"input_digest": "0" * 64})


@pytest.mark.parametrize("change", ["snapshot_digest", "source", "budget", "controlled_actions", "original_digest"])
def test_native_retry_rejects_mismatched_or_legacy_execution_snapshot(change):
    import copy

    from hypertest.cloud.native_worker import native_execution_task
    from hypertest.sync_core import digest

    task_id, project_id = str(uuid4()), str(uuid4())
    original = {"profile": "test", "project_id": project_id, "cloud_task_id": task_id,
        "config_id": "config", "config_revision": 1, "configuration": {},
        "resolution": {"repositories": {}}, "resolution_id": "resolution", "inputs": {"budgets": None}}
    snapshot = copy.deepcopy(original)
    snapshot.update(retry_of_attempt_id=str(uuid4()), previous_input_digest=digest(original))
    task = {"id": task_id, "project_id": project_id, "frozen_manifest": original,
            "input_digest": digest(original), "inputs": original["inputs"]}
    if change == "source":
        snapshot["resolution_id"] = "another-resolution"
    if change == "budget":
        snapshot["inputs"]["budgets"] = {"max_attempts": 1}
    if change == "controlled_actions":
        snapshot["inputs"]["controlled_actions"] = {"old": True}
    attempt = {"task_id": task_id, "project_id": project_id,
               "execution_manifest": snapshot, "input_digest": digest(snapshot)}
    if change == "snapshot_digest":
        attempt["input_digest"] = "0" * 64
    if change == "original_digest":
        task["input_digest"] = "0" * 64
    with pytest.raises(CloudBlocked, match="manifest|snapshot"):
        native_execution_task(task, attempt)


@pytest.mark.parametrize("authorization", [
    {"targets": ["https://example.invalid/sut"], "permitted_actions": ["git:read", "framework:execute"],
     "network_targets": [], "side_effect_limits": "Runtime tools, network access and credentials are managed by the execution environment; preserve unknown external operations.",
     "expires_at": "2036-11-01T00:00:00Z"},
    {"targets": ["https://example.invalid/sut", "https://explicit.invalid"],
     "permitted_actions": ["git:read", "framework:execute", "environment:read"],
     "network_targets": ["https://explicit.invalid"], "side_effect_limits": "Read only and do not modify data.",
     "expires_at": "2036-11-01T00:00:00Z"},
])
def test_native_prompt_preserves_frozen_authorization_and_explains_preflight(tmp_path, authorization):
    import copy
    import json

    from hypertest.cloud.native_worker import native_prompt
    from hypertest.sync_core import digest

    manifest = {"inputs": {"authorization": authorization}, "configuration": {}}
    original = copy.deepcopy(manifest)
    before = digest(manifest)
    prompt = json.loads(native_prompt({"id": str(uuid4()), "frozen_manifest": manifest},
                                      {"id": str(uuid4())}, tmp_path))
    assert manifest == original and digest(manifest) == before
    assert prompt["frozen_manifest"] == original
    assert any("not an inventory of the host environment's capabilities" in line for line in prompt["instructions"])
    assert any("honor any explicit task authorization" in line for line in prompt["instructions"])
    assert any("Do not infer extra authorization" in line for line in prompt["instructions"])
