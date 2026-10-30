"""Private container identity registration with synthetic Cloud DB fixtures."""
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import claimed, post, read_all, worker_submit

from hypertest.application import cloud_tasks as service
from hypertest.cloud.broker import BrokerFailure, CloudBroker
from hypertest.cloud.container_recovery import (
    RecoveryIdentity,
    create_recovery_capability,
    load_recovery_capability,
)
from hypertest.cloud.docker_attempt_spec import ResourceLimit, build_spec
from hypertest.cloud.errors import CloudBlocked
from hypertest.db.session import AsyncSessionLocal

pytest_plugins = ("test_cloud_tasks",)


@pytest.fixture
def candidate_enabled(monkeypatch):
    # Only the disposable synthetic DB exercises the unshipped candidate.
    monkeypatch.setattr(service, "container_intents_enabled", lambda: True)


def parameters(receipt, tmp_path):
    attempt = receipt["attempt_id"]
    volume = "hypertest-synthetic-volume"
    root = "attempt-" + attempt
    mounts = [{"Type": "volume", "Source": volume, "Target": target, "ReadOnly": readonly,
               "VolumeOptions": {"Subpath": root + "/" + path}}
              for target, readonly, path in (("/workspace", False, "workspace"), ("/workspace/sut", True, "workspace/sut"),
                  ("/home/agent", False, "dsh-home"), ("/run", True, "broker"))]
    spec = build_spec(project_id=receipt["project_id"], task_id=receipt["task_id"], attempt_id=attempt, generation=1,
        container_name="hypertest-attempt-" + UUID(attempt).hex + "-" + uuid4().hex, image_id="sha256:" + "a" * 64,
        image_revision="b" * 40, image_environment={"PATH": "/usr/bin"}, volume_name=volume, mounts=mounts,
        key_sha256="c" * 64, clock_sha256="f" * 64, deadline_epoch=int((datetime.now(UTC) + timedelta(seconds=30)).timestamp()),
        attempt_limit=ResourceLimit(1 << 30, 1 << 30, 80), worker_id="d" * 64,
        existing_limits={"d" * 64: ResourceLimit(1 << 30, 1 << 30, 80)})
    operation_key = "create-" + uuid4().hex
    root_path = tmp_path / ("recovery-" + uuid4().hex)
    root_path.mkdir(mode=0o700)
    cap = create_recovery_capability(root_path, RecoveryIdentity(receipt["project_id"], receipt["task_id"], attempt,
        operation_key, 1, "fixture-worker"))
    return {"operation_key": operation_key, "expected_version": receipt["version"],
        "container_name": spec["container_name"], "image_id": spec["image_id"], "spec_sha256": spec["spec_sha256"],
        "key_sha256": spec["scope"]["key_sha256"], "clock_sha256": spec["scope"]["clock_sha256"],
        "recovery_sha256": cap.sha256, "recovery_root": root_path,
        "hard_deadline": spec["scope"]["deadline_epoch"], "spec": spec}


async def running(context):
    receipt, claim, identity = await claimed(context)
    receipt = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 60, "request_limits": [
            {"scope": "ROOT", "max_requests": 1, "cost_per_request_microunits": 1}]})
    return receipt, claim, identity


async def test_original_intent_ack_loss_and_lifecycle_are_fenced(cloud_context, candidate_enabled, tmp_path):
    context = cloud_context
    running_receipt, claim, identity = await running(context)
    broker = CloudBroker(AsyncSessionLocal, claim, identity.worker_id)
    args = parameters(running_receipt, tmp_path)
    intent_receipt = await broker.prepare_container_create(**args)
    intent = intent_receipt["container_create_intent"]
    assert intent["container_id"] is None and intent["state"] == "UNCONFIRMED"
    assert intent["attempt_id"] == running_receipt["attempt_id"]
    assert intent["generation"] == identity.generation and intent["worker_id"] == identity.worker_id
    assert intent["spec_sha256"] == args["spec_sha256"] and intent["image_id"] == args["image_id"]
    assert "allow_create" not in intent_receipt
    # Simulate losing the POST response: only the original owner GET is safe.
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**args)
    assert await broker.receipt(args["operation_key"]) == intent_receipt
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**(args | {"spec_sha256": "d" * 64}))
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**parameters(intent_receipt, tmp_path))
    snapshot = await read_all(context, intent_receipt["task_id"], intent_receipt["version"])
    assert snapshot["container_create_intents"] == [intent]
    async with AsyncSessionLocal() as db:
        # The intent must not accidentally block an existing SSH/HTTPS action.
        from hypertest.application.cloud_ssh import ensure_remote_closed
        await ensure_remote_closed(db, task_id=UUID(intent_receipt["task_id"]))
    for op, fields in [
        ("TRANSITION", {"status": "FAILED"}),
        ("REQUEST_INPUT", {"question_key": "question", "question": "synthetic?", "required_action": "git:read",
                           "checkpoint": {"synthetic": True}, "local_processes_stopped": True,
                           "external_operations_reconciled": True}),
        ("COMPLETE_ATTEMPT", {"final_report_revision": str(uuid4()), "reported_result": "NOT_RUN",
            "usage_seconds": 0, "cost_microunits": 0, "completion_manifest": {"required_asset_ids": [str(uuid4())],
            "all_local_processes_stopped": True, "external_operations_reconciled": True,
            "scope_and_gaps": "synthetic"}}),
    ]:
        with pytest.raises(HTTPException, match="CLOUD_CONTAINER_UNRECONCILED"):
            await worker_submit(context, identity, intent_receipt, op, **fields)
    # Cancellation fences immediately even though the container remains unknown.
    cancelled = await post(context, "CANCEL_ATTEMPT", intent_receipt["version"], task_id=intent_receipt["task_id"],
        attempt_id=intent_receipt["attempt_id"], reason="synthetic cancellation")
    assert cancelled.status_code == 200
    summary = (await context["client"].get(f"/api/v1/cloud/tasks/{intent_receipt['task_id']}/summary",
        headers=context["headers"], params={"project_id": context["project_id"]})).json()
    assert summary["current_attempt"]["status"] == "RECOVERY_REQUIRED"
    assert not summary["recovery"]["can_reconcile"]
    assert "CLOUD_CONTAINER_UNRECONCILED" in summary["recovery"]["blocking_reasons"]
    assert summary["current_attempt"]["runtime_metadata"]["budget_reservation"]["state"] == "HELD"
    assert await broker.receipt(args["operation_key"]) == intent_receipt
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**parameters(cancelled.json(), tmp_path))
    reconciled = await post(context, "RECONCILE_ATTEMPT", cancelled.json()["version"], task_id=intent_receipt["task_id"],
        attempt_id=intent_receipt["attempt_id"], status="FAILED", reason="synthetic", reconciliation={
            "old_owner_fenced": True, "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "untrusted synthetic claim"})
    assert reconciled.status_code == 409 and "CLOUD_CONTAINER_UNRECONCILED" in reconciled.text
    retry = await post(context, "DISPATCH", cancelled.json()["version"], task_id=intent_receipt["task_id"],
        retry_of_attempt_id=intent_receipt["attempt_id"], reason="synthetic")
    assert retry.status_code == 409
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE cloud_operation_receipts SET response='{}'::jsonb WHERE project_id=:project AND operation_key=:key"),
                {"project": UUID(context["project_id"]), "key": args["operation_key"]})


async def test_intent_rejects_wrong_attempt_stale_owner_and_deadline(cloud_context, candidate_enabled, tmp_path):
    receipt, claim, identity = await running(cloud_context)
    broker = CloudBroker(AsyncSessionLocal, claim, identity.worker_id)
    args = parameters(receipt, tmp_path)
    response = await cloud_context["client"].post("/api/v1/cloud/operations", headers=cloud_context["headers"], json={
        "project_id": cloud_context["project_id"], "task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"],
        "operation": "PREPARE_CONTAINER_CREATE", **{k: v for k, v in args.items() if k != "recovery_root"}})
    assert response.status_code == 403
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**(args | {"container_name": "hypertest-attempt-" + uuid4().hex + "-" + uuid4().hex}))
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**(args | {"hard_deadline": int((datetime.now(UTC) + timedelta(days=1)).timestamp())}))
    wrong = CloudBroker(AsyncSessionLocal, claim, "wrong-worker")
    with pytest.raises(CloudBlocked):
        await wrong.prepare_container_create(**args)
    missing = parameters(receipt, tmp_path)
    (missing["recovery_root"] / "container-recovery.json").unlink()
    with pytest.raises(CloudBlocked):
        await broker.prepare_container_create(**missing)
    async with AsyncSessionLocal() as db:
        assert await service._container_intents(db, UUID(receipt["task_id"])) == []
    accepted = await broker.prepare_container_create(**args)
    assert accepted["container_create_intent"]["state"] == "UNCONFIRMED"
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE cloud_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"),
            {"id": UUID(receipt["attempt_id"])})
        await db.commit()
        await service.expire_leases(db)
    summary = (await cloud_context["client"].get(f"/api/v1/cloud/tasks/{receipt['task_id']}/summary",
        headers=cloud_context["headers"], params={"project_id": cloud_context["project_id"]})).json()
    assert summary["current_attempt"]["status"] == "RECOVERY_REQUIRED"
    assert summary["current_attempt"]["runtime_metadata"]["budget_reservation"]["state"] == "HELD"
    assert "CLOUD_CONTAINER_UNRECONCILED" in summary["recovery"]["blocking_reasons"]
    assert await broker.receipt(args["operation_key"]) == accepted
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**parameters(accepted, tmp_path))


async def test_intent_is_closed_in_current_release(cloud_context, tmp_path):
    receipt, claim, identity = await running(cloud_context)
    broker = CloudBroker(AsyncSessionLocal, claim, identity.worker_id)
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_create(**parameters(receipt, tmp_path))
    async with AsyncSessionLocal() as db:
        assert await service._container_intents(db, UUID(receipt["task_id"])) == []
    failed = await worker_submit(cloud_context, identity, receipt, "TRANSITION", status="FAILED")
    assert failed["status"] == "ACCEPTED"


async def test_confirm_and_stop_bind_original_attempt_and_allow_later_retry(cloud_context, candidate_enabled, tmp_path):
    from copy import deepcopy

    from test_cloud_docker_attempt_spec import inspect_fixture

    receipt, claim, identity = await running(cloud_context)
    broker = CloudBroker(AsyncSessionLocal, claim, identity.worker_id)
    before = time.monotonic_ns()
    heartbeat_until = await broker.container_authority_deadline_ns()
    assert time.monotonic_ns() + 1_000_000_000 < heartbeat_until <= before + 3_000_000_000
    args = parameters(receipt, tmp_path)
    intent_receipt = await broker.prepare_container_create(**args)
    raw = inspect_fixture(args["spec"])
    raw["State"] = {"Status": "created", "Running": False, "Pid": 0, "ExitCode": 0}

    class Engine:
        async def inspect_raw(self):
            return deepcopy(raw)

    engine = Engine()
    with pytest.raises(CloudBlocked) as rejected:
        await broker.observe_container(engine=engine, create_operation_key=args["operation_key"], container_id="f" * 64,
            operation_key="confirm-" + uuid4().hex, expected_version=intent_receipt["version"], stopped=False)
    assert rejected.value.code == "ENGINE_IDENTITY_MISMATCH"
    confirm_key = "confirm-" + uuid4().hex
    confirmed = await broker.observe_container(engine=engine, create_operation_key=args["operation_key"], container_id="e" * 64,
        operation_key=confirm_key, expected_version=intent_receipt["version"], stopped=False)
    assert confirmed["container_observation"]["state"] == "CONFIRMED"
    assert await broker.receipt(confirm_key) == confirmed
    with pytest.raises(CloudBlocked) as rejected:
        await broker.submit({"operation": "OBSERVE_CONTAINER_STOP", "project_id": receipt["project_id"],
            "task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"], "expected_version": confirmed["version"],
            "operation_key": "forged-" + uuid4().hex, "create_operation_key": args["operation_key"],
            "container_id": "e" * 64, "spec_sha256": args["spec_sha256"], "engine_status": "exited", "exit_code": 0})
    assert rejected.value.code == "ENGINE_OBSERVATION_REQUIRED"
    with pytest.raises(CloudBlocked) as rejected:
        await broker.observe_container(engine=engine, create_operation_key=args["operation_key"], container_id="e" * 64,
            operation_key="stop-" + uuid4().hex, expected_version=confirmed["version"], stopped=True)
    assert rejected.value.code == "ENGINE_STATE_UNCONFIRMED"
    start_key = "start-" + uuid4().hex
    started = await broker.prepare_container_start(engine=engine, create_operation_key=args["operation_key"],
        container_id="e" * 64, operation_key=start_key, expected_version=confirmed["version"])
    assert started["container_start_intent"]["state"] == "SENT"
    assert await broker.receipt(start_key) == started
    with pytest.raises(BrokerFailure):
        await broker.prepare_container_start(engine=engine, create_operation_key=args["operation_key"],
            container_id="e" * 64, operation_key=start_key, expected_version=confirmed["version"])
    raw["State"] = {"Status": "exited", "Running": False, "Pid": 0, "ExitCode": 0}
    stopped = await broker.observe_container(engine=engine, create_operation_key=args["operation_key"], container_id="e" * 64,
        operation_key="stop-" + uuid4().hex, expected_version=started["version"], stopped=True)
    assert stopped["container_observation"]["state"] == "STOPPED"
    assert stopped["container_observation"]["cgroup_independently_observed"] is False
    snapshot = await read_all(cloud_context, receipt["task_id"], stopped["version"])
    assert [entry["state"] for entry in snapshot["container_observations"]] == ["CONFIRMED", "STOPPED"]
    async with AsyncSessionLocal() as db:
        await service._ensure_container_closed(db, UUID(receipt["task_id"]))
    failed = await worker_submit(cloud_context, identity, stopped, "TRANSITION", status="FAILED")
    retry = await post(cloud_context, "DISPATCH", failed["version"], task_id=receipt["task_id"],
        retry_of_attempt_id=receipt["attempt_id"], reason="explicit synthetic retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["attempt_id"] != receipt["attempt_id"]


@pytest.mark.parametrize("fence_kind", ["cancel", "lease_expired"])
async def test_fenced_original_grant_can_only_append_original_stop_observation(cloud_context, candidate_enabled, fence_kind, tmp_path):
    from copy import deepcopy

    from test_cloud_docker_attempt_spec import inspect_fixture

    receipt, claim, identity = await running(cloud_context)
    broker = CloudBroker(AsyncSessionLocal, claim, identity.worker_id)
    args = parameters(receipt, tmp_path)
    intent = await broker.prepare_container_create(**args)
    raw = inspect_fixture(args["spec"])
    raw["State"] = {"Status": "created", "Running": False, "Pid": 0, "ExitCode": 0}

    class Engine:
        async def inspect_raw(self):
            return deepcopy(raw)

    engine = Engine()
    confirmed = await broker.observe_container(engine=engine, create_operation_key=args["operation_key"], container_id="e" * 64,
        operation_key="confirm-" + uuid4().hex, expected_version=intent["version"], stopped=False)
    started = await broker.prepare_container_start(engine=engine, create_operation_key=args["operation_key"], container_id="e" * 64,
        operation_key="start-" + uuid4().hex, expected_version=confirmed["version"])
    if fence_kind == "cancel":
        cancelled = await post(cloud_context, "CANCEL_ATTEMPT", started["version"], task_id=receipt["task_id"],
            attempt_id=receipt["attempt_id"], reason="synthetic")
        assert cancelled.status_code == 200
        fenced_version = cancelled.json()["version"]
    else:
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE cloud_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"),
                {"id": UUID(receipt["attempt_id"])})
            await db.commit()
            await service.expire_leases(db)
        fenced_version = started["version"]
    with pytest.raises(CloudBlocked):
        await broker.container_authority_deadline_ns()
    broker.suspend_writes()
    with pytest.raises(CloudBlocked):
        await broker.container_authority_deadline_ns()
    raw["State"] = {"Status": "exited", "Running": False, "Pid": 0, "ExitCode": 124}
    wrong = CloudBroker(AsyncSessionLocal, claim | {"work_token": "wrong-token"}, identity.worker_id)
    with pytest.raises(BrokerFailure):
        await wrong.observe_container(engine=engine, create_operation_key=args["operation_key"], container_id="e" * 64,
            operation_key="stop-" + uuid4().hex, expected_version=fenced_version, stopped=True, recovery=True,
            recovery_secret=b"w" * 32)
    recovery_broker = wrong if fence_kind == "lease_expired" else broker
    capability = load_recovery_capability(args["recovery_root"], RecoveryIdentity(receipt["project_id"], receipt["task_id"],
        receipt["attempt_id"], args["operation_key"], 1, identity.worker_id), args["recovery_sha256"])
    stopped = await recovery_broker.observe_container(engine=engine, create_operation_key=args["operation_key"], container_id="e" * 64,
        operation_key="stop-" + uuid4().hex, expected_version=fenced_version, stopped=True, recovery=True,
        recovery_secret=capability.secret if fence_kind == "lease_expired" else None)
    assert stopped["container_observation"]["authority"] == "ORIGINAL_RECOVERY"
    with pytest.raises(BrokerFailure):
        await wrong.prepare_container_create(**parameters(stopped, tmp_path))
    result = await post(cloud_context, "RECONCILE_ATTEMPT", stopped["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], status="FAILED", reason="synthetic", reconciliation={
            "old_owner_fenced": True, "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "Original synthetic Engine inspection"})
    assert result.status_code == 200, result.text
    snapshot = await read_all(cloud_context, receipt["task_id"], result.json()["version"])
    assert snapshot["attempts"][-1]["runtime_metadata"]["budget_reservation"]["state"] == "HELD"


@pytest.mark.parametrize("start_intent", [False, True])
async def test_original_name_recovery_only_closes_confirmed_never_started(cloud_context, candidate_enabled, tmp_path, start_intent):
    from copy import deepcopy

    from test_cloud_docker_attempt_spec import inspect_fixture

    receipt, claim, identity = await running(cloud_context)
    broker = CloudBroker(AsyncSessionLocal, claim, identity.worker_id)
    args = parameters(receipt, tmp_path)
    original = await broker.prepare_container_create(**args)
    raw = inspect_fixture(args["spec"])
    raw["State"] = {"Status": "created", "Running": False, "Pid": 0, "ExitCode": 0,
                    "StartedAt": "0001-01-01T00:00:00Z", "FinishedAt": "0001-01-01T00:00:00Z"}
    raw["RestartCount"] = 0

    class Engine:
        def __init__(self):
            self.reads = []
            self.missing = False
        async def inspect_raw(self):
            self.reads.append("name")
            if self.missing:
                raise CloudBlocked("DOCKER_INSPECT_UNCONFIRMED", "Original Engine observation is unavailable")
            return deepcopy(raw)
        async def inspect_raw_id(self, container_id):
            self.reads.append("id")
            assert container_id == "e" * 64
            return deepcopy(raw)

    engine = Engine()
    if start_intent:
        confirmed = await broker.observe_container(engine=engine, create_operation_key=args["operation_key"],
            container_id="e" * 64, operation_key="confirm-" + uuid4().hex, expected_version=original["version"], stopped=False)
        started = await broker.prepare_container_start(engine=engine, create_operation_key=args["operation_key"],
            container_id="e" * 64, operation_key="start-" + uuid4().hex, expected_version=confirmed["version"])
        current_version = started["version"]
    else:
        current_version = original["version"]
    cancelled = await post(cloud_context, "CANCEL_ATTEMPT", current_version, task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="synthetic recovery")
    assert cancelled.status_code == 200
    current_version = cancelled.json()["version"]
    resumed = CloudBroker(AsyncSessionLocal, claim | {"work_token": "not-recovered"}, identity.worker_id)
    resumed.suspend_writes()
    if not start_intent:
        with pytest.raises(CloudBlocked):
            await resumed.recover_created_container(engine=engine, create_operation_key=args["operation_key"],
                operation_key="confirm-" + uuid4().hex, expected_version=current_version,
                recovery_root=tmp_path / "missing")
        engine.missing = True
        with pytest.raises(CloudBlocked):
            await resumed.recover_created_container(engine=engine, create_operation_key=args["operation_key"],
                operation_key="confirm-" + uuid4().hex, expected_version=current_version,
                recovery_root=args["recovery_root"])
        engine.missing = False
        raw["Image"] = "sha256:" + "f" * 64
        with pytest.raises(CloudBlocked):
            await resumed.recover_created_container(engine=engine, create_operation_key=args["operation_key"],
                operation_key="confirm-" + uuid4().hex, expected_version=current_version,
                recovery_root=args["recovery_root"])
        raw["Image"] = args["image_id"]
        recovered = await resumed.recover_created_container(engine=engine, create_operation_key=args["operation_key"],
            operation_key="confirm-" + uuid4().hex, expected_version=current_version, recovery_root=args["recovery_root"])
        assert recovered["container_observation"]["container_id"] == "e" * 64
        assert recovered["container_observation"]["authority"] == "ORIGINAL_RECOVERY"
        current_version = recovered["version"]
    raw["State"]["StartedAt"] = "2026-10-29T00:00:00Z"
    with pytest.raises(CloudBlocked):
        await resumed.recover_created_container(engine=engine, create_operation_key=args["operation_key"],
            confirmed_id="e" * 64, operation_key="never-" + uuid4().hex, expected_version=current_version,
            recovery_root=args["recovery_root"])
    raw["State"]["StartedAt"] = "0001-01-01T00:00:00Z"
    kwargs = {"engine": engine, "create_operation_key": args["operation_key"], "confirmed_id": "e" * 64,
              "operation_key": "never-" + uuid4().hex, "expected_version": current_version,
              "recovery_root": args["recovery_root"]}
    if start_intent:
        with pytest.raises(BrokerFailure):
            await resumed.recover_created_container(**kwargs)
        async with AsyncSessionLocal() as db:
            with pytest.raises(HTTPException, match="CLOUD_CONTAINER_UNRECONCILED"):
                await service._ensure_container_closed(db, UUID(receipt["task_id"]))
    else:
        done = await resumed.recover_created_container(**kwargs)
        assert done["container_observation"]["state"] == "NEVER_STARTED"
        assert done["container_observation"]["engine_state"] == {"running": False, "pid": 0,
            "started_at": "0001-01-01T00:00:00Z", "finished_at": "0001-01-01T00:00:00Z", "restart_count": 0}
        assert engine.reads[-2:] == ["name", "id"]
        async with AsyncSessionLocal() as db:
            await service._ensure_container_closed(db, UUID(receipt["task_id"]))
        reconciled = await post(cloud_context, "RECONCILE_ATTEMPT", done["version"], task_id=receipt["task_id"],
            attempt_id=receipt["attempt_id"], status="FAILED", reason="synthetic", reconciliation={
                "old_owner_fenced": True, "local_processes_stopped": True, "external_operations_reconciled": True,
                "observations": "Original Engine observed never started"})
        assert reconciled.status_code == 200
        snapshot = await read_all(cloud_context, receipt["task_id"], reconciled.json()["version"])
        assert snapshot["attempts"][-1]["runtime_metadata"]["budget_reservation"]["state"] == "HELD"
