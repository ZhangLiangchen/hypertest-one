"""Operational telemetry contracts; injected events are not model/Runner E2E."""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_codex_adapter import mission_contract
from test_mission_inputs import OwnedTurn, answer_and_claim, pause
from test_mission_inputs import owned_turn as owned_turn
from test_test_design import ProposalHarness, create_run, requirement_proposal

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.agent.codex import CodexCliAdapter, provider_activity_kind
from hypertest.application import activity
from hypertest.application.activity import (
    ActivityOwner,
    ActivityRecorder,
    persist_activity_batch,
    read_job_activity,
)
from hypertest.application.gate import evaluate_gate
from hypertest.application.jobs import FencedAsyncSession, finish_job, submit_job
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import MissionRuntimeError, execute_mission
from hypertest.common.ids import uuid7
from hypertest.db.session import AsyncSessionLocal, engine
from hypertest.domain.activity import ActivityKind as Kind
from hypertest.domain.activity import ActivitySource as Source
from hypertest.domain.activity import MissionActivityEvent
from hypertest.domain.enums import AgentSessionStatus, MissionAttemptStatus, MissionStatus
from hypertest.domain.enums import TestRunStatus as RunStatus
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import AgentSessionRecord, Mission, MissionAttempt, Requirement
from hypertest.domain.models import TestRun as Run
from hypertest.main import app


def owner(turn: OwnedTurn) -> ActivityOwner:
    return ActivityOwner(turn.run_id, turn.job_id, turn.mission_id, turn.attempt_id, turn.agent_id, turn.token)


async def write(turn: OwnedTurn, kind: Kind = Kind.SIGNAL_RECEIVED, count: int = 1) -> bool:
    return await persist_activity_batch(AsyncSessionLocal, owner(turn), {(Source.PROVIDER, kind): count})


@pytest.mark.asyncio
async def test_coalescing_keeps_count_latest_record_time_and_separates_provider_from_heartbeat(owned_turn, monkeypatch):
    turn = owned_turn
    monkeypatch.setattr(activity, "WINDOW_SECONDS", 3600)
    assert await write(turn, count=2)
    async with AsyncSessionLocal() as db:
        first = await db.scalar(select(MissionActivityEvent).where(MissionActivityEvent.attempt_id == turn.attempt_id))
        first_id, first_time = first.id, first.last_observed_at
    assert await write(turn, count=3)
    assert await persist_activity_batch(AsyncSessionLocal, owner(turn), {(Source.CONTROL_PLANE, Kind.MISSION_STARTED): 1})
    async with AsyncSessionLocal() as db:
        rows = list(await db.scalars(select(MissionActivityEvent).where(MissionActivityEvent.attempt_id == turn.attempt_id)))
        signal = next(row for row in rows if row.source == Source.PROVIDER)
        assert signal.id == first_id and signal.count == 5 and signal.last_observed_at >= first_time
        result = await read_job_activity(db, turn.job_id)
        assert result["summary"]["phase"] == "AGENT_RUNNING"
        assert result["summary"]["last_provider_signal_at"] == signal.last_observed_at
        assert result["summary"]["worker_heartbeat_at"] is not None
        assert len(result["items"]) == 2


@pytest.mark.asyncio
async def test_control_events_never_invent_provider_signal(owned_turn):
    turn = owned_turn
    assert await persist_activity_batch(AsyncSessionLocal, owner(turn), {(Source.CONTROL_PLANE, Kind.MISSION_STARTED): 1})
    async with AsyncSessionLocal() as db:
        result = await read_job_activity(db, turn.job_id)
        assert result["summary"]["last_provider_signal_at"] is None
        assert result["summary"]["provider_signal_age_seconds"] is None
        assert result["summary"]["turn_started_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [JobStatus.CANCEL_REQUESTED, JobStatus.WAITING_INPUT, JobStatus.SUCCEEDED,
                                   JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED])
async def test_late_events_after_cancel_wait_or_terminal_are_rejected(owned_turn, status):
    turn = owned_turn
    async with AsyncSessionLocal() as db:
        job = await db.get(DurableJob, turn.job_id)
        job.status = status
        await db.commit()
    assert await write(turn) is False
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MissionActivityEvent).where(
            MissionActivityEvent.attempt_id == turn.attempt_id)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["token", "expiry", "ownership", "attempt", "run_cancelled"])
async def test_token_database_clock_and_owned_attempt_fences(owned_turn, boundary):
    turn = owned_turn
    owned = owner(turn)
    if boundary == "token":
        owned = replace(owned, lease_token=uuid7())
    elif boundary == "ownership":
        owned = replace(owned, agent_session_id=uuid7())
    else:
        async with AsyncSessionLocal() as db:
            if boundary == "expiry":
                job = await db.get(DurableJob, turn.job_id)
                job.lease_expires_at = await db.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
            elif boundary == "attempt":
                attempt = await db.get(MissionAttempt, turn.attempt_id)
                attempt.status = MissionAttemptStatus.ACCEPTED
            else:
                run = await db.get(Run, turn.run_id)
                run.status = RunStatus.CANCELLED
            await db.commit()
    assert await persist_activity_batch(AsyncSessionLocal, owned, {(Source.PROVIDER, Kind.TOOL_STARTED): 1}) is False
    if boundary == "expiry":
        async with AsyncSessionLocal() as db:
            job = await db.get(DurableJob, turn.job_id)
            job.lease_expires_at = await db.scalar(select(func.clock_timestamp())) + timedelta(minutes=10)
            await db.commit()


@pytest.mark.asyncio
async def test_expiry_after_flush_rolls_back_observations(owned_turn):
    turn = owned_turn
    class SlowFlush(AsyncSession):
        async def flush(self, *a, **kw):
            await super().flush(*a, **kw)
            await asyncio.sleep(0.08)
    async with AsyncSessionLocal() as db:
        job = await db.get(DurableJob, turn.job_id)
        job.lease_expires_at = await db.scalar(select(func.clock_timestamp())) + timedelta(seconds=0.07)
        await db.commit()
    assert not await persist_activity_batch(async_sessionmaker(engine, class_=SlowFlush), owner(turn),
                                            {(Source.PROVIDER, Kind.SIGNAL_RECEIVED): 1})
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MissionActivityEvent).where(
            MissionActivityEvent.attempt_id == turn.attempt_id)) == 0
        job = await db.get(DurableJob, turn.job_id)
        job.lease_expires_at = await db.scalar(select(func.clock_timestamp())) + timedelta(minutes=10)
        await db.commit()


@pytest.mark.asyncio
async def test_retention_cursor_and_activity_do_not_change_gate_state(owned_turn):
    turn = owned_turn
    async with AsyncSessionLocal() as db:
        verdict = await evaluate_gate(db, turn.run_id, finalize=False)
        original = (verdict.id, verdict.state_snapshot_hash, verdict.evidence_manifest_sha256)
        now = await db.scalar(select(func.clock_timestamp()))
        for n in range(201):
            when = now - timedelta(seconds=1000 - n)
            db.add(MissionActivityEvent(test_run_id=turn.run_id, durable_job_id=turn.job_id,
                   mission_id=turn.mission_id, attempt_id=turn.attempt_id, agent_session_id=turn.agent_id,
                   source=Source.PROVIDER.value, kind=Kind.SIGNAL_RECEIVED.value, claim_no=1, window_id=n,
                   count=1, recorded_at=when, last_observed_at=when))
        await db.commit()
    assert await write(turn)
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MissionActivityEvent).where(
            MissionActivityEvent.attempt_id == turn.attempt_id)) == 200
        latest = await read_job_activity(db, turn.job_id, limit=100)
        earlier = await read_job_activity(db, turn.job_id, limit=100, before=latest["next_cursor"])
        assert latest["truncated"] and len(latest["items"]) == len(earlier["items"]) == 100
        assert not earlier["next_cursor"]
        assert not {e["id"] for e in latest["items"]} & {e["id"] for e in earlier["items"]}
        verdict = await evaluate_gate(db, turn.run_id, finalize=False)
        assert original == (verdict.id, verdict.state_snapshot_hash, verdict.evidence_manifest_sha256)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(f"/api/v1/jobs/{turn.job_id}/activity?limit=101")).status_code == 422
        expired = await client.get(f"/api/v1/jobs/{turn.job_id}/activity?before={uuid7()}")
        assert expired.status_code == 409 and expired.json()["detail"] == "Activity cursor expired"


@pytest.mark.asyncio
async def test_wait_resume_preserves_rows_but_new_claim_has_no_invented_signal(owned_turn):
    turn = owned_turn
    assert await write(turn)
    request_id = await pause(turn)
    async with AsyncSessionLocal() as db:
        paused = await read_job_activity(db, turn.job_id)
        assert paused["summary"]["phase"] == "WAITING_INPUT"
        assert paused["summary"]["current_attempt"] is None
    claimed = await answer_and_claim(turn, request_id)
    async with AsyncSessionLocal() as db:
        mission = await db.get(Mission, turn.mission_id)
        agent = await db.get(AgentSessionRecord, turn.agent_id)
        mission.status, agent.status = MissionStatus.RUNNING, AgentSessionStatus.RUNNING
        await db.commit()
    resumed_owner = replace(owner(turn), lease_token=claimed.lease_token)
    assert await persist_activity_batch(AsyncSessionLocal, resumed_owner, {(Source.CONTROL_PLANE, Kind.RESUMED): 1})
    async with AsyncSessionLocal() as db:
        resumed = await read_job_activity(db, turn.job_id)
        assert resumed["summary"]["last_provider_signal_at"] is None
        assert resumed["summary"]["turn_started_at"] is not None
        assert len(resumed["items"]) == 2
        assert {item["attempt_id"] for item in resumed["items"]} == {turn.attempt_id}
    assert not await write(turn)  # old claim token cannot append after resume


@pytest.mark.asyncio
async def test_busy_completion_lock_and_database_failure_cannot_hang_or_change_canonical(owned_turn, monkeypatch):
    turn = owned_turn
    recorder = ActivityRecorder(AsyncSessionLocal, owner(turn))
    recorder.start()
    recorder.observe("ACTIVITY", {"activity_kind": "TOOL_STARTED", "raw": "private command"})
    async with AsyncSessionLocal() as lock:
        await lock.scalar(select(Run).where(Run.id == turn.run_id).with_for_update())
        await asyncio.wait_for(recorder.close(), timeout=2)
        await lock.rollback()
    assert recorder.task.done()
    async def unavailable(*args):
        raise RuntimeError("secret database details")
    monkeypatch.setattr(activity, "persist_activity_batch", unavailable)
    failed = ActivityRecorder(AsyncSessionLocal, owner(turn))
    failed.start()
    for _ in range(1000):
        failed.observe("ACTIVITY", {"activity_kind": "evil secret"})
    assert len(failed.pending) <= 2
    await asyncio.wait_for(failed.close(), timeout=2)
    async with AsyncSessionLocal() as db:
        finished = await finish_job(db, turn.job_id, turn.token, result={"verified": True})
        assert finished.status is JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_caller_cancellation_during_drain_is_not_swallowed(owned_turn, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    async def blocked(*args):
        started.set()
        await release.wait()
    monkeypatch.setattr(activity, "persist_activity_batch", blocked)
    recorder = ActivityRecorder(AsyncSessionLocal, owner(owned_turn))
    recorder.start()
    closing = asyncio.create_task(recorder.close())
    await asyncio.wait_for(started.wait(), timeout=1)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    release.set()
    assert recorder.task.done()


@pytest.mark.parametrize(("raw", "expected"), [
    ({"type": "turn.started"}, Kind.TURN_STARTED),
    ({"type": "turn.completed"}, Kind.TURN_COMPLETED),
    ({"type": "item.started", "item": {"type": "command_execution", "command": "private"}}, Kind.TOOL_STARTED),
    ({"type": "item.updated", "item": {"type": "command_execution", "command": "private"}}, Kind.SIGNAL_RECEIVED),
    ({"type": "item.completed", "item": {"type": "mcp_tool_call", "arguments": {"token": "private"}}}, Kind.TOOL_COMPLETED),
    ({"type": "item.updated", "item": {"type": "reasoning", "text": "private reasoning"}}, Kind.MODEL_ACTIVITY),
    ({"type": "item.completed", "item": {"type": "file_change", "changes": ["private"]}}, Kind.FILE_ACTIVITY),
    ({"raw": "private malformed line"}, Kind.SIGNAL_RECEIVED),
    (["private"], Kind.SIGNAL_RECEIVED),
    ({"type": []}, Kind.SIGNAL_RECEIVED),
    ({"type": "item.started", "item": {"type": {"private": "value"}}}, Kind.SIGNAL_RECEIVED),
])
def test_provider_mapping_only_exposes_fixed_activity_codes(raw, expected):
    assert provider_activity_kind(raw) is expected


@pytest.mark.asyncio
async def test_cli_stream_stderr_and_untrusted_error_are_not_persisted_or_exposed(tmp_path, owned_turn):
    secret = "UNIQUE_PRIVATE_PROVIDER_VALUE_92857"
    script = tmp_path / "failing-provider.py"
    script.write_text(f'#!{sys.executable}\nimport sys,json\nsys.stdin.read()\nprint(json.dumps({{"type":"item.completed","item":{{"type":"reasoning","text":"{secret}"}}}}))\nprint("{secret}")\nprint("{secret}",file=sys.stderr)\nsys.exit(9)\n')
    script.chmod(0o700)
    adapter = CodexCliAdapter(binary=str(script))
    session = await adapter.create_session(str(tmp_path))
    events = [event async for event in adapter.execute(session, mission_contract("PRIVATE"))]
    assert secret not in json.dumps([event.payload for event in events])
    recorder = ActivityRecorder(AsyncSessionLocal, owner(owned_turn))
    recorder.start()
    for event in events:
        recorder.observe(event.type, event.payload)
    await recorder.close()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/jobs/{owned_turn.job_id}/activity")
        assert response.status_code == 200 and secret not in response.text
        assert "provider_metadata" not in response.text and "payload" not in response.text
    await adapter.close(session)


@pytest.mark.asyncio
async def test_malformed_telemetry_does_not_hide_valid_final_result(tmp_path):
    script = tmp_path / "malformed-provider.py"
    script.write_text(f'''#!{sys.executable}
import json,pathlib,sys
prompt=sys.stdin.read()
mission=json.loads(prompt.split("TEST_MISSION_JSON:\\n",1)[1])
pathlib.Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({{"protocol":mission["protocol"],"mission_id":mission["mission_id"],"status":"COMPLETED","proposals":[]}}))
for item in [{{"type":[]}},{{"type":"item.started","item":{{"type":{{}}}}}}]:print(json.dumps(item))
''')
    script.chmod(0o700)
    adapter = CodexCliAdapter(binary=str(script))
    session = await adapter.create_session(str(tmp_path))
    events = [event async for event in adapter.execute(session, mission_contract("MALFORMED"))]
    assert any(e.type == "RESULT_SUBMITTED" for e in events)
    assert [e.payload for e in events if e.type == "ACTIVITY"] == [{"activity_kind": "SIGNAL_RECEIVED"}] * 2
    await adapter.close(session)


@pytest.mark.asyncio
async def test_activity_database_rejects_identity_rewrite(owned_turn):
    turn = owned_turn
    assert await write(turn)
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(MissionActivityEvent).where(MissionActivityEvent.attempt_id == turn.attempt_id))
        row.kind = Kind.ERROR
        with pytest.raises(DBAPIError, match="identity"):
            await db.commit()


@pytest.mark.asyncio
async def test_real_fenced_runtime_survives_telemetry_failure_and_caps_event_metadata(monkeypatch):
    class BusyHarness(ProposalHarness):
        async def execute(self, session: AgentSession, mission: dict):
            for _ in range(300):
                yield AgentEvent(type="ACTIVITY", payload={"private": "do not persist"})
            async for event in super().execute(session, mission):
                yield event
    async def unavailable(*args):
        raise RuntimeError("private database details")
    monkeypatch.setattr(activity, "persist_activity_batch", unavailable)
    async with AsyncSessionLocal() as db:
        run = await create_run(db)
        mission = (await plan_next_mission(db, run.id)).mission
        job = await submit_job(db, run.id, JobType.EXECUTE_MISSION, payload={"workspace": "."},
                               idempotency_key="activity-failure", mission_id=mission.id)
        now, token = await db.scalar(select(func.clock_timestamp())), uuid7()
        job.status, job.worker_id, job.lease_token = JobStatus.RUNNING, "activity-test", token
        job.attempts, job.lease_expires_at = 1, now + timedelta(minutes=10)
        await db.commit()
        run_id, mission_id, job_id = run.id, mission.id, job.id
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=job_id,
                                  lease_token=token, test_run_id=run_id) as db:
        result = await execute_mission(db, mission_id, ".", harness=BusyHarness([requirement_proposal()]))
        assert result.attempt.status is MissionAttemptStatus.ACCEPTED
        assert len(result.attempt.provider_metadata["event_types"]) == 256
        assert result.requirements
    async with AsyncSessionLocal() as db:
        await finish_job(db, job_id, token, result={"verified": True})


async def running_mission_job():
    async with AsyncSessionLocal() as db:
        run = await create_run(db)
        mission = (await plan_next_mission(db, run.id)).mission
        job = await submit_job(db, run.id, JobType.EXECUTE_MISSION, payload={"workspace": "."},
                               idempotency_key="drain-window", mission_id=mission.id)
        now, token = await db.scalar(select(func.clock_timestamp())), uuid7()
        job.status, job.worker_id, job.lease_token = JobStatus.RUNNING, "drain-window", token
        job.attempts, job.lease_expires_at = 1, now + timedelta(minutes=10)
        await db.commit()
        return run.id, mission.id, job.id, token, run.source_snapshot_id


@pytest.mark.asyncio
async def test_runtime_cancellation_at_final_drain_does_not_accept_the_result(monkeypatch):
    started = asyncio.Event()
    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(activity, "persist_activity_batch", blocked)
    run_id, mission_id, job_id, token, snapshot_id = await running_mission_job()
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=job_id,
                                  lease_token=token, test_run_id=run_id) as db:
        executing = asyncio.create_task(execute_mission(
            db, mission_id, ".", harness=ProposalHarness([requirement_proposal()]),
        ))
        await asyncio.wait_for(started.wait(), timeout=3)
        executing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await executing
    async with AsyncSessionLocal() as db:
        attempt = await db.scalar(select(MissionAttempt).where(MissionAttempt.mission_id == mission_id))
        assert attempt.status is MissionAttemptStatus.FAILED and attempt.error_code == "EXECUTION_INTERRUPTED"
        assert await db.scalar(select(func.count()).select_from(Requirement).where(
            Requirement.source_snapshot_id == snapshot_id)) == 0
        await finish_job(db, job_id, token, error_code="WORKER_SHUTDOWN", interrupted=True)


@pytest.mark.asyncio
async def test_provider_error_persists_only_fixed_code_and_exit_summary():
    secret = "PRIVATE_COMMAND_REASONING_CREDENTIAL_83972"
    class ErrorHarness(ProposalHarness):
        async def execute(self, session, mission):
            yield AgentEvent(type="ERROR", payload={"error_code": "PROVIDER_ERROR", "stderr": secret,
                                                   "message": secret, "return_code": 9})
    run_id, mission_id, job_id, token, _ = await running_mission_job()
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=job_id,
                                  lease_token=token, test_run_id=run_id) as db:
        with pytest.raises(MissionRuntimeError, match="exit code 9"):
            await execute_mission(db, mission_id, ".", harness=ErrorHarness([]))
    async with AsyncSessionLocal() as db:
        attempt = await db.scalar(select(MissionAttempt).where(MissionAttempt.mission_id == mission_id))
        assert attempt.error_code == "PROVIDER_ERROR"
        assert secret not in attempt.error_message and "9" in attempt.error_message
        assert secret not in json.dumps(attempt.provider_metadata)
        await finish_job(db, job_id, token, error_code="MISSION_REJECTED", error_message=attempt.error_message)


@pytest.mark.asyncio
async def test_activity_api_uses_one_read_only_repeatable_read_snapshot(owned_turn, monkeypatch):
    from sqlalchemy import text

    from hypertest.api import job_routes
    actual = job_routes.read_job_activity
    async def checked(db, *args, **kwargs):
        assert await db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert await db.scalar(text("SHOW transaction_read_only")) == "on"
        return await actual(db, *args, **kwargs)
    monkeypatch.setattr(job_routes, "read_job_activity", checked)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get(f"/api/v1/jobs/{owned_turn.job_id}/activity")
        assert result.status_code == 200


@pytest.mark.asyncio
async def test_cancellation_resistant_writer_does_not_make_close_unbounded(owned_turn, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    async def stubborn(*args):
        started.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
    monkeypatch.setattr(activity, "persist_activity_batch", stubborn)
    recorder = ActivityRecorder(AsyncSessionLocal, owner(owned_turn))
    recorder.start()
    closing = asyncio.create_task(recorder.close())
    await asyncio.wait_for(started.wait(), timeout=1)
    try:
        await asyncio.wait_for(closing, timeout=2)
    finally:
        release.set()
        await asyncio.wait_for(recorder.task, timeout=2)


@pytest.mark.asyncio
async def test_database_writer_statement_timeout_releases_run_and_job_locks(owned_turn):
    turn = owned_turn
    suffix = turn.attempt_id.hex
    function, trigger = "activity_slow_" + suffix, "activity_slow_" + suffix
    async with AsyncSessionLocal() as db:
        await db.execute(text(f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.attempt_id='{turn.attempt_id}'::uuid THEN PERFORM pg_sleep(2); END IF; RETURN NEW; END $$"))
        await db.execute(text(f"CREATE TRIGGER {trigger} AFTER INSERT ON mission_activity_events FOR EACH ROW EXECUTE FUNCTION {function}()"))
        await db.commit()
    try:
        recorder = ActivityRecorder(AsyncSessionLocal, owner(turn))
        recorder.start()
        await asyncio.wait_for(recorder.close(), timeout=2)
        async with AsyncSessionLocal() as db:
            await db.scalar(select(Run).where(Run.id == turn.run_id).with_for_update(nowait=True))
            await db.scalar(select(DurableJob).where(DurableJob.id == turn.job_id).with_for_update(nowait=True))
            assert await db.scalar(select(func.count()).select_from(MissionActivityEvent).where(
                MissionActivityEvent.attempt_id == turn.attempt_id)) == 0
            await db.rollback()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(text(f"DROP TRIGGER {trigger} ON mission_activity_events"))
            await db.execute(text(f"DROP FUNCTION {function}()"))
            await db.commit()


@pytest.mark.asyncio
async def test_api_snapshot_does_not_mix_running_job_with_newly_paused_attempt(owned_turn, monkeypatch):
    from hypertest.api import job_routes
    entered, release = asyncio.Event(), asyncio.Event()
    actual = job_routes.read_job_activity
    async def interleaved(db, *args, **kwargs):
        assert (await db.get(DurableJob, owned_turn.job_id)).status is JobStatus.RUNNING
        entered.set()
        await release.wait()
        return await actual(db, *args, **kwargs)
    monkeypatch.setattr(job_routes, "read_job_activity", interleaved)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.get(f"/api/v1/jobs/{owned_turn.job_id}/activity"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(pause(owned_turn), timeout=2)
        release.set()
        response = await asyncio.wait_for(request, timeout=2)
        assert response.status_code == 200
        assert response.json()["summary"]["phase"] == "AGENT_RUNNING"
        assert response.json()["summary"]["current_attempt"]["attempt_id"] == str(owned_turn.attempt_id)
        monkeypatch.setattr(job_routes, "read_job_activity", actual)
        paused = await client.get(f"/api/v1/jobs/{owned_turn.job_id}/activity")
        assert paused.json()["summary"]["phase"] == "WAITING_INPUT"
        assert paused.json()["summary"]["current_attempt"] is None
