from collections.abc import AsyncIterator

import pytest
from test_delivery_loop import GENERATED_TEST, PRD_TEXT, configure_workspace
from test_test_design import case_proposal, requirement_proposal, risk_proposal

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.controller import advance_run
from hypertest.application.planner import plan_next_mission
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus, VerdictDecision
from hypertest.domain.models import Verdict


class CycleHarness:
    """Agent intelligence fixture; every execution fact still comes from pytest."""

    async def create_session(self, workspace: str) -> AgentSession:
        return AgentSession(id=public_key("AS"), provider="fixture")

    async def execute(self, session: AgentSession, mission: dict) -> AsyncIterator[AgentEvent]:
        context = mission["context"]
        if mission["type"] == "ANALYZE_REQUIREMENTS":
            proposals = [requirement_proposal()]
        elif mission["type"] == "ANALYZE_RISKS":
            proposals = [risk_proposal(context["requirements"][0]["key"])]
        elif mission["type"] == "DESIGN_TESTS":
            key = context["risks"][0]["key"]
            proposals = [
                case_proposal(key),
                case_proposal(key, proposal_key="concurrent", test_type="CONCURRENCY"),
            ]
        elif mission["type"] == "IMPLEMENT_TESTS":
            proposals = [
                {
                    "proposal_type": "TEST_IMPLEMENTATION",
                    "operation": "CREATE",
                    "idempotency_key": "fixture-generated-test",
                    "object_payload": {
                        "test_case_keys": [item["key"] for item in context["test_cases"]],
                        "repository_url": context["repository_url"],
                        "commit_sha": context["commit_sha"],
                        "file_path": "tests/test_generated_cycle.py",
                        "symbol": "test_checkout_idempotency",
                        "code": GENERATED_TEST,
                    },
                }
            ]
        else:
            raise AssertionError(f"unexpected mission {mission['type']}")
        yield AgentEvent(
            type="RESULT_SUBMITTED",
            payload={
                "mission_id": mission["mission_id"],
                "status": "COMPLETED",
                "proposals": proposals,
            },
        )

    async def interrupt(self, session: AgentSession) -> None:
        pass

    async def close(self, session: AgentSession) -> None:
        pass


@pytest.mark.asyncio
async def test_one_click_cycle_persists_all_stages_and_real_execution_verdict(
    tmp_path, monkeypatch
):
    source, commit, origin = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        project = await create_project(
            session, ProjectCreate(key=f"CYCLE_{public_key('IT')[-12:]}", name="One click cycle")
        )
        run = await bootstrap_run(
            session,
            project.id,
            RunBootstrap(repository_url=origin, commit_sha=commit, prd_text=PRD_TEXT),
        )
        result = await advance_run(
            session, run.id, workspace=str(source), backend="local", harness=CycleHarness()
        )
        assert result["reason"] == "VERDICT_FINALIZED"
        assert [step["action"] for step in result["steps"]] == ["mission"] * 4 + [
            "execution",
            "verdict",
        ]
        from uuid import UUID

        verdict = await session.get(Verdict, UUID(result["verdict_id"]))
        assert verdict.decision is VerdictDecision.RELEASE_READY
        repeated = await advance_run(
            session, run.id, workspace=str(source), backend="local", harness=CycleHarness()
        )
        assert repeated["verdict_id"] == result["verdict_id"]
        assert [step["action"] for step in repeated["steps"]] == ["verdict"]


@pytest.mark.asyncio
async def test_cycle_step_limit_preserves_progress_and_resume(tmp_path, monkeypatch):
    source, commit, origin = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        project = await create_project(
            session, ProjectCreate(key=f"RESUME_{public_key('IT')[-12:]}", name="Resumable cycle")
        )
        run = await bootstrap_run(
            session,
            project.id,
            RunBootstrap(repository_url=origin, commit_sha=commit, prd_text=PRD_TEXT),
        )
        partial = await advance_run(
            session,
            run.id,
            workspace=str(source),
            backend="local",
            max_steps=1,
            harness=CycleHarness(),
        )
        assert partial["reason"] == "STEP_LIMIT_REACHED"
        assert len(partial["steps"]) == 1
        resumed = await advance_run(
            session, run.id, workspace=str(source), backend="local", harness=CycleHarness()
        )
        assert resumed["reason"] == "VERDICT_FINALIZED"
        assert len(resumed["steps"]) == 5


@pytest.mark.asyncio
async def test_cycle_replans_cancelled_work_and_preserves_old_mission(tmp_path, monkeypatch):
    source, commit, origin = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        project = await create_project(
            session,
            ProjectCreate(key=f"CANCEL_{public_key('IT')[-12:]}", name="Resume after cancellation"),
        )
        run = await bootstrap_run(
            session,
            project.id,
            RunBootstrap(repository_url=origin, commit_sha=commit, prd_text=PRD_TEXT),
        )
        first = await plan_next_mission(session, run.id)
        first.mission.status = MissionStatus.CANCELLED
        await session.commit()
        old_id = first.mission.id
        old_spec = dict(first.mission.spec)
        replacement = await plan_next_mission(session, run.id)
        assert replacement.mission.id != old_id
        repeated = await plan_next_mission(session, run.id)
        assert repeated.mission.id == replacement.mission.id
        result = await advance_run(
            session, run.id, workspace=str(source), backend="local", harness=CycleHarness()
        )
        assert result["reason"] == "VERDICT_FINALIZED"
        await session.refresh(first.mission)
        assert first.mission.status is MissionStatus.CANCELLED
        assert first.mission.spec == old_spec
