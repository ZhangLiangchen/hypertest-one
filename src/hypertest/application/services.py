from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import (
    MissionCreate,
    PolicySnapshotCreate,
    ProjectCreate,
    SourceSnapshotCreate,
    TestRunCreate,
)
from hypertest.common.ids import public_key
from hypertest.domain.models import (
    Mission,
    PolicySnapshot,
    Project,
    Requirement,
    RequirementRisk,
    Risk,
    SourceSnapshot,
    TestRun,
)


class ConflictError(RuntimeError):
    pass


class NotFoundError(RuntimeError):
    pass


def canonical_json_sha256(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_fingerprint(project_id: UUID, payload: SourceSnapshotCreate) -> str:
    canonical = {
        "project_id": str(project_id),
        "repository_url": payload.repository_url,
        "commit_sha": payload.commit_sha,
        "prd_sha256": payload.prd_sha256,
        "configuration_sha256": payload.configuration_sha256,
    }
    return canonical_json_sha256(canonical)


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("resource conflicts with an existing canonical object") from exc


async def create_project(session: AsyncSession, payload: ProjectCreate) -> Project:
    project = Project(**payload.model_dump())
    session.add(project)
    await _commit(session)
    await session.refresh(project)
    return project


async def list_projects(session: AsyncSession) -> list[Project]:
    result = await session.scalars(select(Project).order_by(Project.updated_at.desc()))
    return list(result)


async def get_project(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("project not found")
    return project


async def create_source_snapshot(
    session: AsyncSession, project_id: UUID, payload: SourceSnapshotCreate
) -> SourceSnapshot:
    await get_project(session, project_id)
    fingerprint = source_fingerprint(project_id, payload)

    existing = await session.scalar(
        select(SourceSnapshot).where(
            SourceSnapshot.project_id == project_id,
            SourceSnapshot.source_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return existing

    snapshot = SourceSnapshot(
        project_id=project_id,
        source_fingerprint=fingerprint,
        **payload.model_dump(),
    )
    session.add(snapshot)
    await _commit(session)
    await session.refresh(snapshot)
    return snapshot


async def create_policy_snapshot(
    session: AsyncSession, payload: PolicySnapshotCreate
) -> PolicySnapshot:
    await get_project(session, payload.project_id)
    existing = await session.scalar(
        select(PolicySnapshot).where(
            PolicySnapshot.project_id == payload.project_id,
            PolicySnapshot.content_sha256 == payload.content_sha256,
        )
    )
    if existing is not None:
        return existing

    snapshot = PolicySnapshot(**payload.model_dump())
    session.add(snapshot)
    await _commit(session)
    await session.refresh(snapshot)
    return snapshot


async def create_test_run(session: AsyncSession, payload: TestRunCreate) -> TestRun:
    project = await get_project(session, payload.project_id)
    source_snapshot = await session.get(SourceSnapshot, payload.source_snapshot_id)
    policy_snapshot = await session.get(PolicySnapshot, payload.policy_snapshot_id)
    if source_snapshot is None or source_snapshot.project_id != project.id:
        raise NotFoundError("source snapshot not found for project")
    if policy_snapshot is None or policy_snapshot.project_id != project.id:
        raise NotFoundError("policy snapshot not found for project")

    test_run = TestRun(key=public_key("TR"), **payload.model_dump())
    session.add(test_run)
    await _commit(session)
    await session.refresh(test_run)
    return test_run


async def get_test_run(session: AsyncSession, test_run_id: UUID) -> TestRun:
    test_run = await session.get(TestRun, test_run_id)
    if test_run is None:
        raise NotFoundError("test run not found")
    return test_run


async def list_test_runs_for_project(
    session: AsyncSession, project_id: UUID
) -> list[TestRun]:
    await get_project(session, project_id)
    result = await session.scalars(
        select(TestRun)
        .where(TestRun.project_id == project_id)
        .order_by(TestRun.created_at.desc())
    )
    return list(result)


async def create_mission(
    session: AsyncSession, test_run_id: UUID, payload: MissionCreate
) -> Mission:
    await get_test_run(session, test_run_id)

    existing = await session.scalar(
        select(Mission).where(
            Mission.test_run_id == test_run_id,
            Mission.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing

    spec_sha256 = canonical_json_sha256(payload.spec)
    mission = Mission(
        key=public_key("MIS"),
        test_run_id=test_run_id,
        spec_sha256=spec_sha256,
        **payload.model_dump(),
    )
    session.add(mission)
    await _commit(session)
    await session.refresh(mission)
    return mission


async def get_mission(session: AsyncSession, mission_id: UUID) -> Mission:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise NotFoundError("mission not found")
    return mission


async def list_missions_for_test_run(
    session: AsyncSession, test_run_id: UUID
) -> list[Mission]:
    await get_test_run(session, test_run_id)
    result = await session.scalars(
        select(Mission)
        .where(Mission.test_run_id == test_run_id)
        .order_by(Mission.created_at)
    )
    return list(result)


async def list_requirements_for_test_run(
    session: AsyncSession, test_run_id: UUID
) -> list[Requirement]:
    test_run = await get_test_run(session, test_run_id)
    result = await session.scalars(
        select(Requirement)
        .where(Requirement.source_snapshot_id == test_run.source_snapshot_id)
        .order_by(Requirement.created_at, Requirement.key)
    )
    return list(result)


async def list_risks_for_test_run(
    session: AsyncSession, test_run_id: UUID
) -> list[tuple[Risk, list[str]]]:
    test_run = await get_test_run(session, test_run_id)
    risks = list(
        await session.scalars(
            select(Risk)
            .where(Risk.source_snapshot_id == test_run.source_snapshot_id)
            .order_by(Risk.created_at, Risk.key)
        )
    )
    if not risks:
        return []

    rows = (
        await session.execute(
            select(RequirementRisk.risk_id, Requirement.key)
            .join(Requirement, Requirement.id == RequirementRisk.requirement_id)
            .where(RequirementRisk.risk_id.in_([risk.id for risk in risks]))
            .order_by(Requirement.key)
        )
    ).all()
    keys_by_risk: dict[UUID, list[str]] = {risk.id: [] for risk in risks}
    for risk_id, requirement_key in rows:
        keys_by_risk[risk_id].append(requirement_key)
    return [(risk, keys_by_risk[risk.id]) for risk in risks]
