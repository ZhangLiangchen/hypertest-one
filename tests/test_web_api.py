from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_delivery_loop import (
    PRD_TEXT,
    configure_workspace,
    diagnose_failure,
    prepare_delivery,
)
from test_test_design import ProposalHarness, requirement_proposal

from hypertest.api import routes as api_routes
from hypertest.application.executions import execute_test_run
from hypertest.application.runtime import execute_mission
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus
from hypertest.domain.models import AuditEvent, Mission, OutboxEvent, SourceSnapshot
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app


async def bootstrap_from_web(
    client: AsyncClient,
    commit: str,
    repository_url: str,
) -> tuple[dict, dict]:
    response = await client.post(
        "/api/v1/projects",
        json={
            "key": f"WEB_{public_key('IT')[-12:]}",
            "name": "Web integration project",
            "repository_url": repository_url,
        },
    )
    assert response.status_code == 201, response.text
    project = response.json()
    response = await client.post(
        f"/api/v1/projects/{project['id']}/runs/bootstrap",
        json={
            "repository_url": repository_url,
            "commit_sha": commit,
            "branch": "main",
            "prd_text": PRD_TEXT,
            "idempotency_key": "wizard-submit:v1",
        },
    )
    assert response.status_code == 201, response.text
    return project, response.json()


@pytest.mark.asyncio
async def test_web_wizard_is_idempotent_and_materializes_prd_in_agent_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        project, run = await bootstrap_from_web(client, commit, repository_url)
        replay = await client.post(
            f"/api/v1/projects/{project['id']}/runs/bootstrap",
            json={
                "repository_url": repository_url,
                "commit_sha": commit,
                "branch": "main",
                "prd_text": PRD_TEXT,
                "idempotency_key": "wizard-submit:v1",
            },
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == run["id"]
        source_snapshot = await client.get(f"/api/v1/source-snapshots/{run['source_snapshot_id']}")
        assert source_snapshot.status_code == 200
        assert source_snapshot.json()["commit_sha"] == commit
        prd = await client.get(f"/api/v1/source-snapshots/{run['source_snapshot_id']}/prd")
        assert prd.status_code == 200
        assert prd.text == PRD_TEXT
        assert hashlib.sha256(prd.content).hexdigest() == source_snapshot.json()["prd_sha256"]
        policy = await client.get(f"/api/v1/policy-snapshots/{run['policy_snapshot_id']}")
        assert policy.status_code == 200
        assert policy.json()["compiled_policy"]["gate_version"] == "mvp/v1"
        async with AsyncSessionLocal() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(CanonicalRun)
                    .where(
                        CanonicalRun.project_id == UUID(project["id"]),
                    )
                )
                == 1
            )
            snapshot = await session.get(SourceSnapshot, UUID(run["source_snapshot_id"]))
            assert snapshot is not None
            assert snapshot.prd_sha256 == hashlib.sha256(PRD_TEXT.encode()).hexdigest()
            assert Path(snapshot.prd_artifact_uri).read_text() == PRD_TEXT

        plan = await client.post(f"/api/v1/test-runs/{run['id']}/plan-next")
        assert plan.status_code == 200, plan.text
        mission = plan.json()["mission"]
        harness = ProposalHarness([requirement_proposal()])

        async def execute_with_explicit_test_harness(
            session, mission_id, workspace, provider="codex"
        ):
            return await execute_mission(
                session,
                mission_id,
                workspace,
                provider=provider,
                harness=harness,
            )

        monkeypatch.setattr(api_routes, "execute_mission", execute_with_explicit_test_harness)
        executed = await client.post(
            f"/api/v1/missions/{mission['id']}/execute",
            json={
                "workspace": str(source),
                "provider": "codex",
            },
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["mission"]["status"] == "COMPLETED"
        assert harness.contract is not None
        assert harness.contract["context"]["prd_text"] == PRD_TEXT
        assert harness.contract["context"]["commit_sha"] == commit
        assert harness.contract["context"]["repository_url"] == repository_url
        attempts = await client.get(f"/api/v1/missions/{mission['id']}/attempts")
        assert attempts.status_code == 200
        assert attempts.json()[0]["status"] == "ACCEPTED"
        proposals = await client.get(f"/api/v1/missions/{mission['id']}/proposals")
        assert proposals.status_code == 200
        assert proposals.json()[0]["status"] == "ACCEPTED"
        requirements = await client.get(f"/api/v1/test-runs/{run['id']}/requirements")
        assert requirements.status_code == 200
        assert len(requirements.json()) == 1
        for endpoint in ("implementations", "executions", "evidence", "findings", "verdicts"):
            result = await client.get(f"/api/v1/test-runs/{run['id']}/{endpoint}")
            assert result.status_code == 200, result.text
            assert result.json() == []
        capabilities = await client.get("/api/v1/capabilities")
        assert capabilities.status_code == 200
        assert "fake" not in capabilities.json()["agent_providers"]
        assert "local" in capabilities.json()["runner_backends"]


@pytest.mark.asyncio
async def test_web_execution_evidence_and_verdict_are_real_and_traceable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        state = await prepare_delivery(session, source, commit, repository_url)
        run_id = state.run.id
        case_keys = {case.key for case in state.cases}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        implementations = await client.get(f"/api/v1/test-runs/{run_id}/implementations")
        assert implementations.status_code == 200
        assert len(implementations.json()) == 1
        assert set(implementations.json()[0]["test_case_keys"]) == case_keys
        assert implementations.json()[0]["validation_status"] == "PENDING"
        execution = await client.post(
            f"/api/v1/test-runs/{run_id}/executions",
            json={
                "workspace": str(source),
                "backend": "local",
                "idempotency_key": "web-official:v1",
            },
        )
        assert execution.status_code == 201, execution.text
        execution_id = execution.json()["id"]
        assert execution.json()["status"] == "COMPLETED"
        assert execution.json()["outcome"] == "PASS"
        replay = await client.post(
            f"/api/v1/test-runs/{run_id}/executions",
            json={
                "workspace": str(source),
                "backend": "local",
                "idempotency_key": "web-official:v1",
            },
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == execution_id
        executions = await client.get(f"/api/v1/test-runs/{run_id}/executions")
        assert executions.status_code == 200
        assert len(executions.json()) == 1
        detail = await client.get(f"/api/v1/executions/{execution_id}")
        assert detail.status_code == 200, detail.text
        assert {row["test_case_key"] for row in detail.json()["test_cases"]} == case_keys
        assert {row["result"] for row in detail.json()["test_cases"]} == {"PASS"}
        evidence = await client.get(f"/api/v1/test-runs/{run_id}/evidence")
        assert evidence.status_code == 200
        artifacts = evidence.json()
        assert len(artifacts) == 4
        for item in artifacts:
            assert item["status"] == "VERIFIED"
            assert item["trust_level"] == "RUNNER"
            content = await client.get(f"/api/v1/evidence/{item['id']}/content")
            assert content.status_code == 200
            assert hashlib.sha256(content.content).hexdigest() == item["sha256"]
            assert len(content.content) == item["size_bytes"]
            assert content.headers["x-content-type-options"] == "nosniff"
        evaluated = await client.post(f"/api/v1/test-runs/{run_id}/evaluate", json={})
        assert evaluated.status_code == 200, evaluated.text
        assert evaluated.json()["status"] == "FINAL"
        assert evaluated.json()["decision"] == "RELEASE_READY"
        assert set(evaluated.json()["evidence_keys"]) == {item["key"] for item in artifacts}
        verdicts = await client.get(f"/api/v1/test-runs/{run_id}/verdicts")
        assert verdicts.status_code == 200
        assert verdicts.json()[0]["id"] == evaluated.json()["id"]

        # The content endpoint checks bytes, even when the canonical row was verified earlier.
        metadata = next(item for item in artifacts if item["evidence_type"] == "EXECUTION_METADATA")
        digest = metadata["sha256"]
        content_path = Path(get_settings().artifact_root) / "sha256" / digest[:2] / digest
        content_path.chmod(0o600)
        content_path.write_bytes(b"modified after evidence verification")
        corrupted = await client.get(f"/api/v1/evidence/{metadata['id']}/content")
        assert corrupted.status_code == 409


@pytest.mark.asyncio
async def test_web_finding_transitions_require_review_and_current_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch, broken=True)
    async with AsyncSessionLocal() as session:
        state = await prepare_delivery(session, source, commit, repository_url)
        await execute_test_run(
            session,
            state.run.id,
            str(source),
            backend="local",
            idempotency_key="web-failure:v1",
        )
        finding = await diagnose_failure(session, state, source)
        finding_id, run_id, initial_version = finding.id, state.run.id, finding.row_version
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        invalid = await client.post(
            f"/api/v1/findings/{finding_id}/transition",
            json={
                "status": "CONFIRMED",
                "reason": "Attempt to skip triage",
                "expected_row_version": initial_version,
            },
        )
        assert invalid.status_code == 409
        triaged = await client.post(
            f"/api/v1/findings/{finding_id}/transition",
            json={
                "status": "TRIAGED",
                "reason": "Review trusted failure evidence",
                "expected_row_version": initial_version,
            },
        )
        assert triaged.status_code == 200, triaged.text
        assert triaged.json()["status"] == "TRIAGED"
        stale = await client.post(
            f"/api/v1/findings/{finding_id}/transition",
            json={
                "status": "CONFIRMED",
                "reason": "Stale browser submission",
                "expected_row_version": initial_version,
            },
        )
        assert stale.status_code == 409
        confirmed = await client.post(
            f"/api/v1/findings/{finding_id}/transition",
            json={
                "status": "CONFIRMED",
                "reason": "Reproduced against the immutable source commit",
                "expected_row_version": triaged.json()["row_version"],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "CONFIRMED"
        assert len(confirmed.json()["evidence_keys"]) == 2
        assert set(confirmed.json()["test_case_keys"]) == {case.key for case in state.cases}
        findings = await client.get(f"/api/v1/test-runs/{run_id}/findings")
        assert findings.status_code == 200
        assert findings.json()[0]["id"] == str(finding_id)
        verdict = await client.post(f"/api/v1/test-runs/{run_id}/evaluate", json={})
        assert verdict.status_code == 200
        assert verdict.json()["decision"] == "RELEASE_BLOCKED"
        assert finding.key in verdict.json()["finding_keys"]


@pytest.mark.asyncio
async def test_web_mission_retry_and_cancel_are_idempotent_audited_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        _, run = await bootstrap_from_web(client, commit, repository_url)
        planned = await client.post(f"/api/v1/test-runs/{run['id']}/plan-next")
        mission_id = planned.json()["mission"]["id"]
        invalid_retry = await client.post(f"/api/v1/missions/{mission_id}/retry")
        assert invalid_retry.status_code == 409
        cancelled = await client.post(f"/api/v1/missions/{mission_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"
        repeated_cancel = await client.post(f"/api/v1/missions/{mission_id}/cancel")
        assert repeated_cancel.status_code == 200
        assert repeated_cancel.json()["row_version"] == cancelled.json()["row_version"]
        assert (await client.post(f"/api/v1/missions/{mission_id}/retry")).status_code == 409

        failed = await client.post(
            f"/api/v1/test-runs/{run['id']}/missions",
            json={
                "mission_type": "ANALYZE_REQUIREMENTS",
                "objective": "Retry failed requirement analysis",
                "spec": {},
                "idempotency_key": "failed-control:v1",
            },
        )
        assert failed.status_code == 201
        failed_id = failed.json()["id"]
        # Seed a separate operational FAILED state, then exercise the Web retry path twice.
        async with AsyncSessionLocal() as session:
            mission = await session.get(Mission, UUID(failed_id))
            assert mission is not None
            mission.status = MissionStatus.FAILED
            await session.commit()
        retried = await client.post(f"/api/v1/missions/{failed_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "RETRYING"
        repeated_retry = await client.post(f"/api/v1/missions/{failed_id}/retry")
        assert repeated_retry.status_code == 200
        assert repeated_retry.json()["row_version"] == retried.json()["row_version"]
        async with AsyncSessionLocal() as session:
            for action, entity_id in (
                ("mission.cancelled", mission_id),
                ("mission.retry_requested", failed_id),
            ):
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.entity_id == UUID(entity_id),
                            AuditEvent.action == action,
                        )
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(
                            OutboxEvent.aggregate_id == UUID(entity_id),
                            OutboxEvent.event_type == action,
                        )
                    )
                    == 1
                )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource", ["implementations", "executions", "evidence", "findings", "verdicts"]
)
async def test_web_delivery_lists_return_not_found_for_unknown_run(resource: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        response = await client.get(f"/api/v1/test-runs/{uuid7()}/{resource}")
        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_input", [{"commit_sha": "main"}, {"prd_text": "  \n"}])
async def test_web_bootstrap_rejects_nonreproducible_or_empty_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_input: dict,
) -> None:
    _, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        project, _ = await bootstrap_from_web(client, commit, repository_url)
        response = await client.post(
            f"/api/v1/projects/{project['id']}/runs/bootstrap",
            json={
                "repository_url": repository_url,
                "commit_sha": commit,
                "prd_text": PRD_TEXT,
                **invalid_input,
            },
        )
        assert response.status_code == 422
