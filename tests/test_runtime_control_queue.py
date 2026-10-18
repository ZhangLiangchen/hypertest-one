"""Exercise Worker dispatch over PostgreSQL without giving the API host privileges."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from hypertest.application import runtime_control as control
from hypertest.application.jobs import record_worker_heartbeat
from hypertest.application.services import ConflictError
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.harness import RuntimeControlRequest
from hypertest.main import app


async def queue_request(*, expires_in=3.0, operation="CAPABILITIES"):
    async with AsyncSessionLocal() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        request = RuntimeControlRequest(id=uuid7(), operation=operation, payload={},
            created_at=now-timedelta(seconds=1), expires_at=now+timedelta(seconds=expires_in))
        session.add(request)
        await session.commit()
        return request.id


async def read_request(request_id):
    async with AsyncSessionLocal() as session:
        return await session.get(RuntimeControlRequest, request_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,codex_available,local", [
    ("legacy", True, True), ("legacy", False, False), ("bridge", True, True),
])
async def test_queued_api_capabilities_serializes_real_worker_datetime_on_worker_only(monkeypatch, mode, codex_available, local):
    from hypertest.api import delivery_routes
    from hypertest.application import persistent
    from hypertest.runner.backends import DockerRunner

    worker_context = ContextVar("trusted_worker", default=False)
    calls = []
    settings = get_settings()
    monkeypatch.setattr(settings, "execution_mode", "queued")
    monkeypatch.setattr(settings, "harness_mode", mode)
    monkeypatch.setattr(settings, "runner_allow_local", local)
    monkeypatch.setattr(settings, "runtime_control_timeout_seconds", 3)

    class Bridge:
        async def capabilities(self):
            assert worker_context.get(), "API attempted a privileged Bridge call"
            assert mode == "bridge", "legacy Worker attempted Bridge access"
            calls.append("bridge")
            return {"profile": "run-persistent-harness/v1", "host_id": settings.bridge_host_id}

    def bridge_client():
        assert worker_context.get(), "API attempted to read Bridge credentials"
        assert mode == "bridge", "legacy Worker attempted to read Bridge credentials"
        return Bridge()

    async def fingerprint(self):
        assert worker_context.get(), "API attempted Docker inspection"
        calls.append("docker")
        return {"engine": "test"}

    def check_local_binary(binary):
        assert worker_context.get(), "API attempted local host binary detection"
        assert mode == "legacy" and binary == settings.codex_binary
        calls.append("local_codex")
        return "/trusted/codex" if codex_available else None

    monkeypatch.setattr(persistent, "bridge_client", bridge_client)
    monkeypatch.setattr(DockerRunner, "fingerprint", fingerprint)
    monkeypatch.setattr(delivery_routes.shutil, "which", check_local_binary)
    async with AsyncSessionLocal() as session:
        await record_worker_heartbeat(session, "control-json-"+uuid7().hex)
    stopping = asyncio.Event()

    async def worker():
        worker_context.set(True)
        await control.serve_runtime_control(AsyncSessionLocal, stopping)

    task = asyncio.create_task(worker())
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.get("/api/v1/capabilities"), timeout=4)
        assert response.status_code == 200
        body = response.json()
        assert body["agent_providers"] == (["codex"] if codex_available else [])
        assert body["runner_backends"] == (["docker", "local"] if mode == "legacy" and local else ["docker"])
        if mode == "bridge":
            assert body["harness_bridge"] == "READY" and body["execution_profile"] == "run-persistent-harness/v1"
        else:
            assert "harness_bridge" not in body and "execution_profile" not in body
        assert body["worker"]["available"] is True
        assert datetime.fromisoformat(body["worker"]["last_seen_at"]).tzinfo is not None
        assert calls == (["bridge", "docker"] if mode == "bridge" else ["local_codex", "docker"])
    finally:
        stopping.set()
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["profile", "host"])
async def test_bridge_capabilities_require_the_configured_host_and_profile(monkeypatch, mismatch):
    from hypertest.application import persistent
    from hypertest.runner.backends import DockerRunner

    settings = get_settings()
    monkeypatch.setattr(settings, "harness_mode", "bridge")

    class Bridge:
        async def capabilities(self):
            return {"profile": "other-profile" if mismatch == "profile" else "run-persistent-harness/v1",
                    "host_id": "different-host" if mismatch == "host" else settings.bridge_host_id}

    async def fingerprint(self):
        return {"engine": "test"}

    def no_legacy_probe(*args):
        raise AssertionError("Bridge mode must not fall back to a local Codex binary")

    monkeypatch.setattr(persistent, "bridge_client", lambda: Bridge())
    monkeypatch.setattr(DockerRunner, "fingerprint", fingerprint)
    monkeypatch.setattr(control.shutil, "which", no_legacy_probe)
    request_id = await queue_request()
    assert await control.process_control_request(AsyncSessionLocal)
    request = await read_request(request_id)
    assert request.status == "SUCCEEDED"
    assert request.result["agent_providers"] == [] and request.result["harness_bridge"] == "UNAVAILABLE"
    assert request.result["runner_backends"] == ["docker"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "bridge"])
async def test_capability_failure_fallback_retains_configured_profile_without_api_host_access(monkeypatch, mode):
    from hypertest.application import persistent
    from hypertest.runner.backends import DockerRunner

    settings = get_settings()
    monkeypatch.setattr(settings, "execution_mode", "queued")
    monkeypatch.setattr(settings, "harness_mode", mode)
    monkeypatch.setattr(settings, "runtime_control_timeout_seconds", 3)
    dispatched = []

    def forbidden_host_access(*args):
        raise AssertionError("API fallback attempted a host capability check")

    async def failed_dispatch(session, operation, payload):
        dispatched.append(operation)
        raise ConflictError("test Worker cannot inspect capabilities")

    monkeypatch.setattr(persistent, "bridge_client", forbidden_host_access)
    monkeypatch.setattr(DockerRunner, "fingerprint", forbidden_host_access)
    monkeypatch.setattr(control.shutil, "which", forbidden_host_access)
    monkeypatch.setattr(control, "dispatch_control", failed_dispatch)
    stopping = asyncio.Event()
    task = asyncio.create_task(control.serve_runtime_control(AsyncSessionLocal, stopping))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.get("/api/v1/capabilities"), timeout=4)
        assert response.status_code == 200 and dispatched == ["CAPABILITIES"]
        body = response.json()
        assert body["agent_providers"] == [] and body["runner_backends"] == []
        if mode == "bridge":
            assert body["execution_profile"] == "run-persistent-harness/v1" and body["harness_bridge"] == "UNAVAILABLE"
        else:
            assert "execution_profile" not in body and "harness_bridge" not in body
    finally:
        stopping.set()
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_legacy_capabilities_do_not_advertise_docker_when_fingerprint_fails(monkeypatch):
    from hypertest.runner.backends import DockerRunner

    settings = get_settings()
    monkeypatch.setattr(settings, "harness_mode", "legacy")
    monkeypatch.setattr(settings, "runner_allow_local", True)
    monkeypatch.setattr(control.shutil, "which", lambda _: "/trusted/codex")

    async def unavailable(self):
        raise RuntimeError("Docker daemon unavailable")

    monkeypatch.setattr(DockerRunner, "fingerprint", unavailable)
    request_id = await queue_request()
    assert await control.process_control_request(AsyncSessionLocal)
    request = await read_request(request_id)
    assert request.status == "SUCCEEDED"
    assert request.result["agent_providers"] == ["codex"] and request.result["runner_backends"] == ["local"]
    assert "execution_profile" not in request.result


@pytest.mark.asyncio
async def test_claim_uses_remaining_deadline_and_timeout_is_unknown_never_replayed(monkeypatch):
    monkeypatch.setattr(get_settings(), "runtime_control_timeout_seconds", 20)
    request_id = await queue_request(expires_in=0.15, operation="RECOVER_BINDING")
    called, cancelled = [], asyncio.Event()

    async def dispatch(session, operation, payload):
        called.append(operation)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(control, "dispatch_control", dispatch)
    assert await asyncio.wait_for(control.process_control_request(AsyncSessionLocal), timeout=1)
    request = await read_request(request_id)
    assert cancelled.is_set()
    assert request.status == "UNKNOWN" and request.error_code == "CONTROL_DEADLINE_EXPIRED"
    assert request.result is None and request.finished_at is not None
    assert not await control.process_control_request(AsyncSessionLocal)
    assert called == ["RECOVER_BINDING"]


@pytest.mark.asyncio
async def test_expired_queued_request_is_not_dispatched(monkeypatch):
    request_id = await queue_request(expires_in=-0.01)

    async def forbidden_dispatch(*args):
        raise AssertionError("expired request was dispatched")

    monkeypatch.setattr(control, "dispatch_control", forbidden_dispatch)
    assert not await control.process_control_request(AsyncSessionLocal)
    request = await read_request(request_id)
    assert request.status == "UNKNOWN" and request.started_at is None
    assert request.error_code == "CONTROL_DEADLINE_EXPIRED"


@pytest.mark.asyncio
async def test_late_result_after_cancellation_cannot_be_reported_as_success(monkeypatch):
    request_id = await queue_request(expires_in=0.15)

    async def dispatch(*args):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {"possibly_completed": True}

    monkeypatch.setattr(control, "dispatch_control", dispatch)
    assert await asyncio.wait_for(control.process_control_request(AsyncSessionLocal), timeout=1)
    request = await read_request(request_id)
    assert request.status == "UNKNOWN" and request.result is None
    assert request.error_code == "CONTROL_DEADLINE_EXPIRED"


@pytest.mark.asyncio
async def test_expired_running_request_is_preserved_as_unknown_without_replay(monkeypatch):
    request_id = await queue_request(expires_in=0.05)
    async with AsyncSessionLocal() as session:
        request = await session.get(RuntimeControlRequest, request_id)
        request.started_at = await session.scalar(select(func.clock_timestamp()))
        request.status = "RUNNING"
        await session.commit()
    await asyncio.sleep(0.06)

    async def forbidden_dispatch(*args):
        raise AssertionError("an interrupted host operation was replayed")

    monkeypatch.setattr(control, "dispatch_control", forbidden_dispatch)
    assert not await control.process_control_request(AsyncSessionLocal)
    request = await read_request(request_id)
    assert request.status == "UNKNOWN" and request.started_at is not None
    assert request.error_code == "CONTROL_DEADLINE_EXPIRED"


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_unknown_host_outcome_and_definite_rejection_have_distinct_terminal_states(monkeypatch, uncertain):
    request_id = await queue_request()

    class UnknownOutcome(RuntimeError):
        code = "OUTCOME_UNKNOWN"

    async def dispatch(*args):
        raise UnknownOutcome("private host output") if uncertain else ConflictError("private rejected payload")

    monkeypatch.setattr(control, "dispatch_control", dispatch)
    assert await control.process_control_request(AsyncSessionLocal)
    request = await read_request(request_id)
    assert request.status == ("UNKNOWN" if uncertain else "FAILED")
    assert request.error_code == ("OUTCOME_UNKNOWN" if uncertain else "CONFLICTERROR")
    assert request.result is None and request.finished_at is not None
    assert not await control.process_control_request(AsyncSessionLocal)


@pytest.mark.asyncio
async def test_two_workers_cannot_dispatch_the_same_request(monkeypatch):
    request_id = await queue_request()
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def dispatch(*args):
        calls.append(True)
        started.set()
        await release.wait()
        return {"verified": True}

    monkeypatch.setattr(control, "dispatch_control", dispatch)
    first = asyncio.create_task(control.process_control_request(AsyncSessionLocal))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not await control.process_control_request(AsyncSessionLocal)
    finally:
        release.set()
        assert await asyncio.wait_for(first, timeout=1)
    request = await read_request(request_id)
    assert request.status == "SUCCEEDED" and request.result == {"verified": True}
    assert calls == [True]


@pytest.mark.asyncio
async def test_request_control_persists_json_compatible_result(monkeypatch):
    monkeypatch.setattr(get_settings(), "runtime_control_timeout_seconds", 3)
    async with AsyncSessionLocal() as session:
        queued = await control.request_control(session, "CAPABILITIES", {}, wait=False)
    request_id = UUID(queued["request_id"])
    assert (await read_request(request_id)).status == "QUEUED"

    async def dispatch(*args):
        return {"at": datetime.fromisoformat("2026-10-19T12:00:00+00:00")}

    monkeypatch.setattr(control, "dispatch_control", dispatch)
    assert await control.process_control_request(AsyncSessionLocal)
    request = await read_request(request_id)
    assert request.status == "SUCCEEDED" and request.result == {"at": "2026-10-19T12:00:00+00:00"}
