"""Create a reproducible run from the Web's input form in one transaction."""

import hashlib
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import SourceSnapshotCreate
from hypertest.application.services import (
    NotFoundError,
    canonical_json_sha256,
    source_fingerprint,
)
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.domain.models import (
    AuditEvent,
    OutboxEvent,
    PolicySnapshot,
    Project,
    SourceSnapshot,
    TestRun,
)


async def bootstrap_run(session: AsyncSession, project_id: UUID, payload: RunBootstrap) -> TestRun:
    project = await session.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise NotFoundError("project not found")
    if not payload.prd_text.strip():
        raise ValueError("PRD text must not be blank")
    if payload.idempotency_key:
        existing = await session.scalar(
            select(TestRun).where(
                TestRun.project_id == project.id,
                TestRun.trigger_type == "WEB",
                TestRun.trigger_ref == payload.idempotency_key,
            )
        )
        if existing is not None:
            return existing
    prd = payload.prd_text.encode("utf-8")
    digest = hashlib.sha256(prd).hexdigest()
    root = Path(get_settings().artifact_root).resolve()
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    if not inputs.resolve().is_relative_to(root):
        raise ValueError("input store must remain under the configured artifact root")
    artifact = inputs / f"{digest}.txt"
    if artifact.is_symlink():
        raise ValueError("input artifact must be a regular file")
    if artifact.exists():
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
            raise ValueError("existing PRD artifact failed integrity verification")
    else:
        with artifact.open("xb") as output:
            output.write(prd)
    configuration = payload.configuration_text.encode("utf-8")
    configuration_digest = hashlib.sha256(configuration).hexdigest()
    configuration_artifact = inputs / f"{configuration_digest}.txt"
    if configuration_artifact.is_symlink():
        raise ValueError("configuration artifact must be a regular file")
    if configuration_artifact.exists():
        if hashlib.sha256(configuration_artifact.read_bytes()).hexdigest() != configuration_digest:
            raise ValueError("configuration artifact failed integrity verification")
    else:
        with configuration_artifact.open("xb") as output:
            output.write(configuration)
    source = SourceSnapshotCreate(
        repository_url=payload.repository_url.strip(),
        commit_sha=payload.commit_sha.lower(),
        branch=payload.branch,
        prd_sha256=digest,
        prd_artifact_uri=str(artifact),
        configuration_sha256=configuration_digest,
    )
    fingerprint = source_fingerprint(project.id, source)
    snapshot = await session.scalar(
        select(SourceSnapshot).where(
            SourceSnapshot.project_id == project.id,
            SourceSnapshot.source_fingerprint == fingerprint,
        )
    )
    if snapshot is None:
        snapshot = SourceSnapshot(
            project_id=project.id, source_fingerprint=fingerprint, **source.model_dump()
        )
        session.add(snapshot)
        await session.flush()
    policy_content = {"gate_version": "mvp/v1", **payload.policy}
    policy_hash = canonical_json_sha256(policy_content)
    policy = await session.scalar(
        select(PolicySnapshot).where(
            PolicySnapshot.project_id == project.id,
            PolicySnapshot.content_sha256 == policy_hash,
        )
    )
    if policy is None:
        policy = PolicySnapshot(
            project_id=project.id,
            policy_name="Web policy",
            policy_version="mvp/v1",
            content_sha256=policy_hash,
            compiled_policy=policy_content,
        )
        session.add(policy)
        await session.flush()
    run = TestRun(
        key=public_key("TR"),
        project_id=project.id,
        source_snapshot_id=snapshot.id,
        policy_snapshot_id=policy.id,
        trigger_type="WEB",
        trigger_ref=payload.idempotency_key,
        created_by="user",
    )
    session.add(run)
    await session.flush()
    session.add(
        AuditEvent(
            project_id=project.id,
            test_run_id=run.id,
            actor_type="USER",
            actor_ref="web",
            action="test_run.created",
            entity_type="TestRun",
            entity_id=run.id,
            after_state={
                "source_snapshot_id": str(snapshot.id),
                "policy_snapshot_id": str(policy.id),
            },
            event_metadata={"channel": "web"},
        )
    )
    session.add(
        OutboxEvent(
            aggregate_type="TestRun",
            aggregate_id=run.id,
            event_type="test_run.created",
            payload={"test_run_id": str(run.id), "source_snapshot_id": str(snapshot.id)},
        )
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(run)
    return run
