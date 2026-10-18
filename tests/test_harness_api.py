"""Safe operational Web views; report bytes remain hash-verified plaintext."""
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from test_run_bindings import bound_run as _bound_run
from test_test_design import create_run

from hypertest.api.harness_routes import _issue_url
from hypertest.application.bindings import transition_binding
from hypertest.common.ids import uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.harness import RunHarnessState, RunReport
from hypertest.main import app
from hypertest.runner.artifacts import artifact_root, store_content

bound_run = _bound_run


@pytest.mark.asyncio
async def test_harness_projection_and_verified_report_content_exclude_private_fields(bound_run):
    bound = bound_run
    content = "# 已保存的测试报告\n<script>not executable</script>\n"
    digest, uri = store_content(content.encode())
    async with AsyncSessionLocal() as session:
        session.add(RunHarnessState(binding_id=bound["binding_id"], first_job_id=bound["job_id"],
            source_workspace="/PRIVATE_WORKSPACE", max_steps=12, timeout_seconds=300,
            last_call_id="PRIVATE_CALL", last_job_id=bound["job_id"], last_call_epoch=1))
        report = RunReport(id=uuid7(), test_run_id=bound["run_id"], binding_id=bound["binding_id"],
            durable_job_id=bound["job_id"], idempotency_key="report-api", envelope={"internal": "PRIVATE_ENVELOPE"},
            artifact_uri=uri, content_sha256=digest)
        session.add(report)
        await session.commit()
        report_id = report.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/test-runs/{bound['run_id']}/harness")
        assert response.status_code == 200
        value = response.json()
        assert value["binding"]["primary_agent_session_id"] == str(bound["agent_id"])
        assert value["state"]["max_steps"] == 12 and value["reports"][0]["content_sha256"] == digest
        assert value["state"]["harness_budget_seconds"] == 3600
        for private in ("PRIVATE_", bound["native"], bound["workspace"], "harness_host_id", "provider_session_id"):
            assert private not in response.text
        listing = await client.get(f"/api/v1/test-runs/{bound['run_id']}/reports")
        assert listing.status_code == 200 and listing.json()[0]["id"] == str(report_id)
        artifact = await client.get(f"/api/v1/reports/{report_id}/content")
        assert artifact.status_code == 200 and artifact.text == content
        assert artifact.headers["content-type"].startswith("text/plain")
        assert artifact.headers["x-content-type-options"] == "nosniff"
        file: Path = artifact_root() / "sha256" / digest[:2] / digest
        file.chmod(0o600)
        file.write_text("tampered")
        invalid = await client.get(f"/api/v1/reports/{report_id}/content")
        assert invalid.status_code == 409 and "tampered" not in invalid.text


@pytest.mark.asyncio
async def test_legacy_run_has_explicit_empty_harness_view_and_missing_records_are_404():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        run_id = run.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/test-runs/{run_id}/harness")
        assert response.status_code == 200 and response.json() == {"binding": None, "state": None, "reports": [], "issues": []}
        assert (await client.get(f"/api/v1/test-runs/{uuid7()}/harness")).status_code == 404
        assert (await client.get(f"/api/v1/reports/{uuid7()}/content")).status_code == 404


@pytest.mark.asyncio
async def test_recovery_api_checks_expected_state_and_dispatches_only_to_worker(bound_run, monkeypatch):
    import hypertest.application.runtime_control as control

    bound = bound_run
    captured = []

    async def request_control(db, operation, payload):
        assert not db.in_transaction()
        captured.append((operation, payload))
        return {"status": "VERIFIED"}

    monkeypatch.setattr(control, "request_control", request_control)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        endpoint = f"/api/v1/bindings/{bound['binding_id']}/recover"
        assert (await client.post(endpoint, json={"expected_epoch": 1, "expected_row_version": 2})).status_code == 409
        assert not captured
        async with AsyncSessionLocal() as session:
            binding = await session.get(RunExecutionBinding, bound["binding_id"])
            await transition_binding(session, binding, BindingStatus.RECOVERY_REQUIRED, reason="test_worker_loss")
            await session.commit()
            version = binding.row_version
        assert (await client.post(endpoint, json={"expected_epoch": 2, "expected_row_version": version})).status_code == 409
        good = await client.post(endpoint, json={"expected_epoch": 1, "expected_row_version": version})
        assert good.status_code == 200
        assert captured == [("RECOVER_BINDING", {"binding_id": str(bound["binding_id"]), "expected_epoch": 1, "expected_row_version": version})]
        invalid = await client.post(endpoint, json={"expected_epoch": 1, "expected_row_version": version, "workspace": "/arbitrary"})
        assert invalid.status_code == 422 and "/arbitrary" not in invalid.text


@pytest.mark.parametrize("value", ["javascript:alert(1)", "https://token:secret@example.org/issue/1", "file:///tmp/report", "//example.org/issue/1", "https://[invalid/issue", "http://example.org/issue/1", "https://example.org/issue/1?token=private", "https://example.org/issue/1#private", "https://example.org/issue/1\n"])
def test_issue_projection_drops_unsafe_or_credentialed_urls(value):
    assert _issue_url(value) is None


def test_issue_projection_preserves_actual_http_issue_reference():
    assert _issue_url("https://gitlab.example.test/group/project/-/issues/123") == "https://gitlab.example.test/group/project/-/issues/123"
