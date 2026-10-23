"""Operator-managed native intake, append-only observations and conservative Gate.

No command is executed here. Native materials never enter legacy trusted Evidence.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from hypertest.application.native_verifier import verify_reports
from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.domain.models import AuditEvent, OutboxEvent, Project
from hypertest.domain.native import (
    NativeCase,
    NativeConclusion,
    NativeConclusionExecution,
    NativeContributor,
    NativeExecutionCase,
    NativeExecutionRecord,
    NativeHandoffRecord,
    NativeMaterial,
    NativeOperation,
    NativeTestRun,
    NativeVerification,
)
from hypertest.native_protocol import POLICY, PROFILE
from hypertest.runner.artifacts import ArtifactIntegrityError, read_evidence_content, store_content


def public(row) -> dict:
    def value(v):
        return str(v) if isinstance(v, UUID) else v.isoformat() if isinstance(v, datetime) else v
    return {c.name: value(getattr(row, c.name)) for c in row.__table__.columns
            if c.name != "writer_token_hash"}


async def project_scope(db, project_id, *, lock=False):
    settings = get_settings()
    if not settings.native_intake_enabled:
        raise HTTPException(503, "Native intake is not enabled")
    project = await db.get(Project, project_id, with_for_update=lock)
    if not project or project.deleted_at is not None or project.key not in settings.native_project_keys:
        raise HTTPException(403, "Native project scope is not authorized")
    return project


async def load_run(db, run_id, *, lock=False):
    row = await db.get(NativeTestRun, run_id, with_for_update=lock, populate_existing=True)
    if row is None:
        raise HTTPException(404, "Native run not found")
    await project_scope(db, row.project_id)
    return row


async def current_contributor(db, run):
    return await db.scalar(select(NativeContributor).where(
        NativeContributor.run_id == run.id, NativeContributor.generation == run.generation))


async def writer(db, run, payload, actor, token, *, management=False):
    contributor = await current_contributor(db, run)
    if not contributor or contributor.id != payload.contributor_id or run.generation != payload.generation:
        raise HTTPException(409, "Native writer generation is stale")
    if not management and (contributor.actor_ref != actor or not token or not secrets.compare_digest(
            contributor.writer_token_hash, hashlib.sha256(token.encode()).hexdigest())):
        raise HTTPException(403, "Current native writer capability is required")
    operation_count = await db.scalar(select(func.count()).select_from(NativeOperation).where(NativeOperation.run_id == run.id))
    if operation_count >= (1024 if management else 512):
        raise HTTPException(409, "Native operation history limit reached; preserve this run and begin an explicit new round")
    return contributor


def audit(db, run, actor, action, data):
    db.add(AuditEvent(project_id=run.project_id, actor_type="OPERATOR", actor_ref=actor,
        action="native." + action, entity_type="NativeTestRun", entity_id=run.id,
        event_metadata=data))
    db.add(OutboxEvent(aggregate_type="NativeTestRun", aggregate_id=run.id,
        event_type="native." + action, payload={"run_id": str(run.id), **data}))


async def prior_operation(db, run, key, kind, digest):
    old = await db.scalar(select(NativeOperation).where(
        NativeOperation.run_id == run.id, NativeOperation.idempotency_key == key))
    if old:
        if old.kind != kind or old.input_digest != digest:
            raise HTTPException(409, "Native idempotency key conflicts with original input")
        return old.result
    return None


async def no_uncertainty(db, run):
    if await db.scalar(select(NativeOperation.id).where(
            NativeOperation.run_id == run.id, NativeOperation.status == "UNKNOWN").limit(1)):
        raise HTTPException(409, "Reconcile original UNKNOWN operation before new execution or handoff")


def record_operation(db, run, contributor, payload, kind, result, *, status="SUCCEEDED"):
    original = payload.model_dump(mode="json")
    compact = {k: v for k, v in original.items() if k not in {"materials", "material"}}
    if "materials" in original:
        compact["materials"] = [{k: v for k, v in m.items() if k != "content_base64"} for m in original["materials"]]
    if "material" in original:
        compact["material"] = {k: v for k, v in original["material"].items() if k != "content_base64"}
    row = NativeOperation(run_id=run.id, contributor_id=contributor.id,
        idempotency_key=payload.idempotency_key, kind=kind,
        input_digest=canonical_json_sha256(original), payload=compact, status=status, result=result)
    db.add(row)
    return row


async def create_native_run(db, payload, actor):
    # Project row serializes admission/duplicate submissions. No external I/O.
    await project_scope(db, payload.project_id, lock=True)
    original = payload.model_dump(mode="json")
    digest = canonical_json_sha256(original)
    existing = await db.scalar(select(NativeTestRun).where(
        NativeTestRun.project_id == payload.project_id,
        NativeTestRun.idempotency_key == payload.idempotency_key))
    if existing:
        if existing.proposal_digest != digest:
            raise HTTPException(409, "Native submission key conflicts with original proposal")
        return await submission_receipt(db, existing)
    run = NativeTestRun(id=uuid7(), project_id=payload.project_id, profile=PROFILE,
        idempotency_key=payload.idempotency_key, proposal_digest=digest, proposal=original,
        policy_version=POLICY, actor_ref=actor, generation=1)
    db.add(run)
    await db.flush()
    token = secrets.token_urlsafe(48)
    contributor = NativeContributor(id=uuid7(), run_id=run.id, actor_ref=actor,
        session_ref=payload.session_ref, generation=1,
        writer_token_hash=hashlib.sha256(token.encode()).hexdigest())
    db.add(contributor)
    db.add_all([NativeCase(run_id=run.id, case_key=c.key, accepted_payload=c.model_dump(mode="json"))
                for c in payload.plan.cases])
    await db.flush()
    result = {"status": "ACCEPTED", "profile": PROFILE, "run_id": str(run.id),
        "contributor_id": str(contributor.id), "generation": 1,
        "proposal_digest": digest, "quality_result": "NOT_EVALUATED"}
    record_operation(db, run, contributor, payload, "CREATE", result)
    audit(db, run, actor, "proposal.accepted", {"proposal_digest": digest, "case_count": len(payload.plan.cases)})
    await db.commit()
    # Never persist or replay a writer token in a receipt, view, audit or outbox.
    return {**result, "writer_token": token}


async def submission_receipt(db, run):
    operation = await db.scalar(select(NativeOperation).where(
        NativeOperation.run_id == run.id, NativeOperation.kind == "CREATE"))
    return operation.result


async def find_submission(db, project_id, key):
    await project_scope(db, project_id)
    run = await db.scalar(select(NativeTestRun).where(
        NativeTestRun.project_id == project_id, NativeTestRun.idempotency_key == key))
    if run is None:
        raise HTTPException(404, "Native submission not found; this does not authorize resubmission")
    return await submission_receipt(db, run)


def prepare_material(payload):
    content = payload.content()
    digest, uri = store_content(content)
    return digest, uri, content


def store_material(db, run_id, execution_id, payload, prepared):
    digest, uri, content = prepared
    material = NativeMaterial(id=uuid7(), run_id=run_id, execution_id=execution_id,
        name=payload.name, kind=payload.kind, format=payload.format,
        sha256=digest, size_bytes=len(content), artifact_uri=uri)
    db.add(material)
    return material, content


async def submit_execution(db, run_id, payload, actor, token):
    run = await load_run(db, run_id)
    digest = canonical_json_sha256(payload.model_dump(mode="json"))
    prior = await prior_operation(db, run, payload.idempotency_key, "EXECUTION", digest)
    if prior is not None:
        return prior
    contributor = await writer(db, run, payload, actor, token)
    await no_uncertainty(db, run)
    await db.commit()
    prepared = [prepare_material(m) for m in payload.materials]
    run = await load_run(db, run_id, lock=True)
    prior = await prior_operation(db, run, payload.idempotency_key, "EXECUTION", digest)
    if prior is not None:
        return prior
    contributor = await writer(db, run, payload, actor, token)
    await no_uncertainty(db, run)
    cases = {c.case_key: c for c in await db.scalars(select(NativeCase).where(NativeCase.run_id == run.id))}
    if any(r.case_key not in cases for r in payload.results):
        raise HTTPException(422, "Execution references a case outside this native plan")
    if payload.retry_of_execution_id:
        previous = await db.get(NativeExecutionRecord, payload.retry_of_execution_id)
        if not previous or previous.run_id != run.id:
            raise HTTPException(422, "Retry must reference an original execution in this native run")
    if len(list(await db.scalars(select(NativeExecutionRecord.id).where(NativeExecutionRecord.run_id == run.id)))) >= 128:
        raise HTTPException(409, "Native run execution limit reached")
    execution = NativeExecutionRecord(id=uuid7(), run_id=run.id, contributor_id=contributor.id,
        idempotency_key=payload.idempotency_key, retry_of_execution_id=payload.retry_of_execution_id,
        observation=payload.model_dump(mode="json", exclude={"materials"}))
    db.add(execution)
    await db.flush()
    raw = []
    for material, staged in zip(payload.materials, prepared, strict=True):
        _, content = store_material(db, run.id, execution.id, material, staged)
        raw.append((material.format, content))
    observed = {}
    for result in payload.results:
        case = cases[result.case_key]
        db.add(NativeExecutionCase(execution_id=execution.id, case_id=case.id, observed_result=result.result))
        observed[case.accepted_payload["implementation_ref"]] = result.result
    checks = verify_reports(raw, observed, payload.exit_code)
    db.add(NativeVerification(execution_id=execution.id, verifier_version="native-report-consistency/v1alpha1",
        provenance="UNVERIFIED", checks=checks))
    result = {"status": "MATERIAL_RECEIVED", "execution_id": str(execution.id),
              "provenance": "UNVERIFIED", "checks": checks, "formal_evidence": False}
    record_operation(db, run, contributor, payload, "EXECUTION", result)
    audit(db, run, actor, "execution.material_received", {"execution_id": str(execution.id), "input_digest": digest})
    await db.commit()
    return result


async def run_view(db, run_id):
    run = await load_run(db, run_id)
    executions = list(await db.scalars(select(NativeExecutionRecord).where(
        NativeExecutionRecord.run_id == run.id).order_by(NativeExecutionRecord.created_at, NativeExecutionRecord.id)))
    execution_ids = [e.id for e in executions]
    async def collection(model, condition):
        return [public(r) for r in await db.scalars(select(model).where(condition).order_by(model.created_at, model.id))]
    result = {"run": public(run), "current_contributor": public(await current_contributor(db, run)),
        "cases": await collection(NativeCase, NativeCase.run_id == run.id),
        "contributors": await collection(NativeContributor, NativeContributor.run_id == run.id),
        "executions": [public(e) for e in executions],
        "materials": await collection(NativeMaterial, NativeMaterial.run_id == run.id),
        "verifications": await collection(NativeVerification, NativeVerification.execution_id.in_(execution_ids)),
        "conclusions": await collection(NativeConclusion, NativeConclusion.run_id == run.id),
        "handoffs": await collection(NativeHandoffRecord, NativeHandoffRecord.run_id == run.id),
        "operations": await collection(NativeOperation, NativeOperation.run_id == run.id)}
    if len(json.dumps(result, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
        raise HTTPException(409, "Native state exceeds bounded view limit")
    return result


async def evaluate(db, run_id, payload, actor, token):
    run = await load_run(db, run_id)
    digest = canonical_json_sha256(payload.model_dump(mode="json"))
    prior = await prior_operation(db, run, payload.idempotency_key, "EVALUATE", digest)
    if prior is not None:
        return prior
    contributor = await writer(db, run, payload, actor, token)
    view = await run_view(db, run_id)
    await db.commit()
    reasons = []
    observed_keys = set()
    for execution in view["executions"]:
        observation = execution["observation"]
        observed_keys.update(r["case_key"] for r in observation["results"])
        if observation["exit_code"] != 0 or any(r["result"] != "PASS" for r in observation["results"]):
            reasons.append("OBSERVED_FAILURE_ERROR_OR_INCOMPLETE_CASES")
    if observed_keys != {c["case_key"] for c in view["cases"]}:
        reasons.append("REQUIRED_CASES_NOT_OBSERVED")
    if any(v["checks"]["report_consistency"] == "INVALID" for v in view["verifications"]):
        reasons.append("REPORT_CONTRADICTION")
    if any(o["status"] == "UNKNOWN" for o in view["operations"]):
        reasons.append("UNRESOLVED_EXTERNAL_OPERATION")
    integrity = "CHECKED"
    for material in view["materials"]:
        try:
            read_evidence_content(SimpleNamespace(**material))
        except ArtifactIntegrityError:
            integrity = "INVALID"
            reasons.append("RAW_MATERIAL_MISSING_OR_CHANGED")
    # File I/O completes before aggregate locking; reject a concurrently changed
    # owner or state instead of publishing a conclusion about mixed generations.
    run = await load_run(db, run_id, lock=True)
    prior = await prior_operation(db, run, payload.idempotency_key, "EVALUATE", digest)
    if prior is not None:
        return prior
    contributor = await writer(db, run, payload, actor, token)
    if canonical_json_sha256(await run_view(db, run_id)) != canonical_json_sha256(view):
        raise HTTPException(409, "Native state changed during material verification")
    reasons.append("NATIVE_EXECUTION_PROVENANCE_UNVERIFIED")
    decision = "BLOCKED" if len(set(reasons) - {"NATIVE_EXECUTION_PROVENANCE_UNVERIFIED"}) else "UNKNOWN"
    state_digest = canonical_json_sha256(view)
    conclusion = NativeConclusion(id=uuid7(), run_id=run.id, contributor_id=contributor.id,
        policy_version=POLICY, decision=decision, state_digest=state_digest, reasons=sorted(set(reasons)))
    db.add(conclusion)
    await db.flush()
    db.add_all([NativeConclusionExecution(conclusion_id=conclusion.id, execution_id=UUID(e["id"])) for e in view["executions"]])
    result = {"conclusion_id": str(conclusion.id), "decision": decision,
              "reasons": conclusion.reasons, "state_digest": state_digest, "integrity": integrity,
              "policy_version": POLICY, "formal_evidence": False}
    record_operation(db, run, contributor, payload, "EVALUATE", result)
    audit(db, run, actor, "conclusion.recorded", result)
    await db.commit()
    return result


async def handoff(db, run_id, payload, actor):
    run = await load_run(db, run_id)
    digest = canonical_json_sha256(payload.model_dump(mode="json"))
    prior = await prior_operation(db, run, payload.idempotency_key, "HANDOFF", digest)
    if prior is not None:
        return prior
    previous = await writer(db, run, payload, actor, None, management=True)
    await no_uncertainty(db, run)
    if payload.successor_session_ref == previous.session_ref:
        raise HTTPException(422, "Handoff must explicitly identify a successor contribution")
    snapshot = await run_view(db, run_id)
    await db.commit()
    state_digest, uri = store_content(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
    run = await load_run(db, run_id, lock=True)
    prior = await prior_operation(db, run, payload.idempotency_key, "HANDOFF", digest)
    if prior is not None:
        return prior
    previous = await writer(db, run, payload, actor, None, management=True)
    await no_uncertainty(db, run)
    if canonical_json_sha256(await run_view(db, run_id)) != canonical_json_sha256(snapshot):
        raise HTTPException(409, "Native state changed during handoff preparation")
    token = secrets.token_urlsafe(48)
    successor = NativeContributor(id=uuid7(), run_id=run.id, actor_ref=actor,
        session_ref=payload.successor_session_ref, generation=run.generation + 1,
        writer_token_hash=hashlib.sha256(token.encode()).hexdigest())
    db.add(successor)
    await db.flush()
    record = NativeHandoffRecord(id=uuid7(), run_id=run.id, from_contributor_id=previous.id,
        to_contributor_id=successor.id, from_generation=run.generation, to_generation=run.generation + 1,
        actor_ref=actor, state_digest=state_digest, state_artifact_uri=uri,
        remaining_work=payload.remaining_work, reason=payload.reason)
    db.add(record)
    await db.flush()
    result = {"handoff_id": str(record.id), "run_id": str(run.id), "contributor_id": str(successor.id),
              "generation": run.generation + 1, "state_digest": state_digest, "state_artifact_uri": uri}
    # Save the original generation's operation before the atomic generation step.
    record_operation(db, run, previous, payload, "HANDOFF", result)
    await db.flush()
    run.generation += 1
    audit(db, run, actor, "contribution.handed_off", result)
    await db.commit()
    return {**result, "writer_token": token}


async def uncertainty(db, run_id, payload, actor, token):
    run = await load_run(db, run_id, lock=True)
    prior = await prior_operation(db, run, payload.idempotency_key, "UNCERTAINTY", canonical_json_sha256(payload.model_dump(mode="json")))
    if prior is not None:
        return prior
    contributor = await writer(db, run, payload, actor, token)
    result = {"status": "UNKNOWN", "external_operation_ref": payload.external_operation_ref,
              "instruction": "Read back the original operation; do not execute it again."}
    record_operation(db, run, contributor, payload, "UNCERTAINTY", result, status="UNKNOWN")
    audit(db, run, actor, "operation.unknown", result)
    await db.commit()
    return result


async def reconcile(db, run_id, unknown_key, payload, actor):
    run = await load_run(db, run_id)
    digest = canonical_json_sha256({"unknown_key": unknown_key, **payload.model_dump(mode="json")})
    prior = await prior_operation(db, run, payload.idempotency_key, "RECONCILE", digest)
    if prior is not None:
        return prior
    contributor = await writer(db, run, payload, actor, None, management=True)
    original = await db.scalar(select(NativeOperation).where(
        NativeOperation.run_id == run.id, NativeOperation.idempotency_key == unknown_key))
    if not original or original.kind != "UNCERTAINTY" or original.status != "UNKNOWN":
        raise HTTPException(409, "Original UNKNOWN operation is required")
    if payload.observed_operation_ref != original.payload["external_operation_ref"]:
        raise HTTPException(422, "Reconciliation must match the original external operation")
    if payload.material.kind != "CONTEXT" or payload.material.format != "TEXT" or not payload.material.content():
        raise HTTPException(422, "Reconciliation requires original nonempty readback material")
    # The explicit Operator attestation is a manual management decision. Neither
    # its JSON shape nor these bytes establish independently verified execution.
    await db.commit()
    prepared = prepare_material(payload.material)
    run = await load_run(db, run_id, lock=True)
    prior = await prior_operation(db, run, payload.idempotency_key, "RECONCILE", digest)
    if prior is not None:
        return prior
    contributor = await writer(db, run, payload, actor, None, management=True)
    original = await db.scalar(select(NativeOperation).where(
        NativeOperation.run_id == run.id, NativeOperation.idempotency_key == unknown_key))
    if not original or original.kind != "UNCERTAINTY" or original.status != "UNKNOWN":
        raise HTTPException(409, "Original operation changed during reconciliation")
    if payload.observed_operation_ref != original.payload["external_operation_ref"]:
        raise HTTPException(409, "Original operation identity changed")
    material, _ = store_material(db, run.id, None, payload.material, prepared)
    await db.flush()
    confirmed = payload.resolution not in {"UNKNOWN", "NOT_FOUND"}
    result = {"original_key": unknown_key, "resolution": payload.resolution,
              "status": "RESOLVED" if confirmed else "UNKNOWN", "material_id": str(material.id),
              "basis": "OPERATOR_RECONCILIATION", "provenance": "UNVERIFIED"}
    operation = record_operation(db, run, contributor, payload, "RECONCILE", result)
    operation.input_digest = digest
    operation.payload = {"unknown_key": unknown_key, **operation.payload}
    if confirmed:
        original.status, original.result, original.reconciled_material_id = "RESOLVED", result, material.id
    audit(db, run, actor, "operation.reconciled", result)
    await db.commit()
    return result


async def read_material(db, run_id, material_id):
    await load_run(db, run_id)
    material = await db.get(NativeMaterial, material_id)
    if not material or material.run_id != run_id:
        raise HTTPException(404, "Native material not found for this run")
    try:
        content = read_evidence_content(material)
    except ArtifactIntegrityError:
        raise HTTPException(409, "Native raw material integrity check failed") from None
    return {**public(material), "content_base64": base64.b64encode(content).decode(),
            "provenance": "UNVERIFIED", "formal_evidence": False}


async def read_handoff_state(db, run_id, handoff_id):
    await load_run(db, run_id)
    record = await db.get(NativeHandoffRecord, handoff_id)
    if not record or record.run_id != run_id:
        raise HTTPException(404, "Native handoff not found for this run")
    from hypertest.runner.artifacts import _path
    try:
        if _path(record.state_digest).stat().st_size > 8 * 1024 * 1024:
            raise ArtifactIntegrityError("handoff snapshot exceeds limit")
        content = read_evidence_content(SimpleNamespace(artifact_uri=record.state_artifact_uri,
            sha256=record.state_digest, size_bytes=None))
    except (ArtifactIntegrityError, OSError):
        raise HTTPException(409, "Native handoff state integrity check failed") from None
    return {"handoff_id": str(record.id), "state_digest": record.state_digest,
            "size_bytes": len(content), "state": json.loads(content)}
