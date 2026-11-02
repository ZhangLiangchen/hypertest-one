"""Authentication projection is separate from Agent, task, and capability admission."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from hypertest.application import cloud_agent_auth
from hypertest.config import get_settings
from hypertest.db.session import get_db
from hypertest.main import app


def observation(status="VALID"):
    return SimpleNamespace(status=status, checked_at=datetime(2026, 11, 2, tzinfo=UTC))


def test_projection_fails_closed_for_disabled_missing_and_multiple_workers():
    view = cloud_agent_auth.project_status
    valid = view([observation()], enabled=True)["agents"]
    assert valid["deepseek"] == {"status": "VALID", "checked_at": "2026-11-02T00:00:00+00:00"}
    assert valid["codex"]["status"] == "UNKNOWN"
    assert valid["claude_code"]["status"] == "NOT_SUPPORTED"
    for records, enabled in [([], True), ([observation(), observation("INVALID")], True), ([observation()], False)]:
        assert view(records, enabled=enabled)["agents"]["deepseek"] == {"status": "UNKNOWN", "checked_at": None}
    assert view([observation("INVALID")], enabled=True)["agents"]["deepseek"]["status"] == "INVALID"


async def test_status_requires_operator_and_never_probes_provider(monkeypatch):
    from hypertest.api import cloud_routes
    settings = get_settings()
    monkeypatch.setattr(settings, "connector_operator_key", "synthetic-operator-key")
    monkeypatch.setattr(settings, "cloud_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    calls = []

    async def fake_read(db, *, enabled):
        calls.append((db, enabled))
        return cloud_agent_auth.project_status([observation()], enabled=enabled)

    async def fake_db():
        yield "synthetic-db"

    monkeypatch.setattr(cloud_routes.cloud_agent_auth, "read_auth_status", fake_read)
    app.dependency_overrides[get_db] = fake_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
            rejected = await client.get("/api/v1/cloud/agent-auth-status")
            assert rejected.status_code == 401
            assert calls == []
            accepted = await client.get("/api/v1/cloud/agent-auth-status", headers={"X-Hypertest-Operator-Key": "synthetic-operator-key"})
            assert accepted.status_code == 200
            assert accepted.headers["cache-control"] == "no-store"
            assert accepted.json()["agents"]["deepseek"]["status"] == "VALID"
            assert calls == [("synthetic-db", True)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://untrusted.invalid") as client:
            rejected = await client.get("/api/v1/cloud/agent-auth-status", headers={"X-Hypertest-Operator-Key": "synthetic-operator-key"})
            assert rejected.status_code == 403
            assert len(calls) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("worker_id,status", [("other", "VALID"), ("cloud-worker-" + "a" * 32, "SECRET"),
                                             ("cloud-worker-" + "a" * 32, None)])
async def test_worker_rejects_untrusted_observation_values_before_database(worker_id, status):
    def no_session():
        raise AssertionError("database must not be opened")
    with pytest.raises(ValueError):
        await cloud_agent_auth.record_worker_auth_status(no_session, worker_id, status)


async def test_worker_cleanup_is_limited_to_expired_auth_observations():
    from datetime import timedelta

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.dml import Delete

    class Session:
        def __init__(self):
            self.statements = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            self.statements.append(statement)

        async def commit(self):
            self.committed = True

    session = Session()
    await cloud_agent_auth.record_worker_auth_status(lambda: session, "cloud-worker-" + "a" * 32, "VALID")
    assert session.committed
    assert len(session.statements) == 2
    cleanup = session.statements[1]
    assert isinstance(cleanup, Delete)
    assert cleanup.table.name == "cloud_agent_auth_observations"
    compiled = cleanup.compile(dialect=postgresql.dialect())
    assert "cloud_agent_auth_observations.checked_at < clock_timestamp()" in str(compiled)
    assert list(compiled.params.values()) == [timedelta(days=1)]
