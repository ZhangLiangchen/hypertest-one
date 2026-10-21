"""ADR-017 real PostgreSQL acceptance, history and authority boundaries."""
import base64
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from hypertest.api.schemas import ProjectCreate
from hypertest.application.native_verifier import verify_reports
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.models import Evidence, OutboxEvent
from hypertest.domain.models import TestRun as LegacyRun
from hypertest.domain.native import NativeTestRun
from hypertest.main import app
from hypertest.runner.artifacts import _path


def raw_material(content, *, format="CONSUMER_PARITY_JSONL", name="report.jsonl", kind="REPORT"):
    if isinstance(content, str):
        content = content.encode()
    return {"name": name, "kind": kind, "format": format,
            "content_base64": base64.b64encode(content).decode(),
            "sha256": hashlib.sha256(content).hexdigest()}


def parity(*, result="PASS", step="PASS", business="UNKNOWN", summary_passed=1):
    return "\n".join(json.dumps(r) for r in [
        {"type": "step", "scenario": "negative-case", "verdict": step,
         "actual": {"acceptanceConclusion": business}},
        {"type": "scenario", "name": "negative-case", "verdict": result},
        {"type": "summary", "passed": summary_passed, "failed": int(result == "FAIL"),
         "errors": 0, "skipped": 0, "selected": 1}])


def proposal(project_id):
    return {"project_id": str(project_id), "idempotency_key": "plan-1", "session_ref": "contribution-A",
        "plan": {"objective": "Check existing native negative assertion", "scope": "Isolated existing framework",
                 "requirement_refs": ["requirement-doc@fixed"], "risk_refs": ["risk-doc@fixed"],
                 "inputs": {"sut": {"repository_url": "https://example.invalid/sut.git", "binary_sha256": "a" * 64},
                    "framework": {"repository_url": "https://example.invalid/framework.git", "commit_sha": "b" * 40,
                                  "local_changes": "untracked README; selected assets unchanged"},
                    "test_assets": [{"path": "existing/java-test", "sha256": "c" * 64}],
                    "environment": {"java": "21"}, "authorization_scope": "local isolated assertions"},
                 "cases": [{"key": "TC-NEG", "title": "Ambiguous response is expected", "requirement_ref": "requirement-doc@fixed",
                            "risk_ref": "risk-doc@fixed", "expected_result": "Ambiguous behavior asserted correctly",
                            "implementation_ref": "negative-case"}]}}


def write(receipt, key):
    return {"contributor_id": receipt["contributor_id"], "generation": receipt["generation"], "idempotency_key": key}


def execution(receipt, key="exec-1", *, outcome="PASS", step="PASS"):
    now = datetime.now(UTC).isoformat()
    return {**write(receipt, key), "command": ["bash", "existing/run.sh", "local", "scenarios"],
            "cwd": "/local/framework", "framework": "existing-java-node", "started_at": now,
            "finished_at": now, "exit_code": int(outcome == "FAIL"),
            "results": [{"case_key": "TC-NEG", "result": outcome}],
            "materials": [raw_material(parity(result=outcome, step=step, summary_passed=int(outcome == "PASS"))),
                          raw_material(b"", format="TEXT", name="stderr.log", kind="STDERR")]}


@pytest.fixture
async def context(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "native_intake_enabled", True)
    monkeypatch.setattr(settings, "connector_operator_key", "native-test-operator")
    monkeypatch.setattr(settings, "connector_operator_identity", "native-authenticated-operator")
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("NATIVE"), name="Native intake QA"))
        project_id, project_key = project.id, project.key
    monkeypatch.setattr(settings, "native_project_keys", [project_key])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        yield client, project_id, {"X-Hypertest-Operator-Key": "native-test-operator"}


async def create(context):
    client, project_id, headers = context
    response = await client.post("/api/v1/native-runs", json=proposal(project_id), headers=headers)
    assert response.status_code == 201, response.text
    receipt = response.json()
    return receipt, {**headers, "X-Hypertest-Native-Writer-Key": receipt["writer_token"]}


async def test_full_native_loop_handoff_capability_fence_and_legacy_preservation(context):
    c, _, operator = context
    async with AsyncSessionLocal() as db:
        old_counts = [await db.scalar(select(func.count()).select_from(m)) for m in [LegacyRun, Evidence]]
    receipt, headers = await create(context)
    root = "/api/v1/native-runs/" + receipt["run_id"]
    body = execution(receipt)
    accepted = await c.post(root + "/executions", json=body, headers=headers)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["checks"]["report_consistency"] == "CONSISTENT"
    verdict = await c.post(root + "/evaluate", json=write(receipt, "gate-1"), headers=headers)
    assert verdict.json()["decision"] == "UNKNOWN", verdict.text
    handoff_body = {**write(receipt, "handoff-1"), "successor_session_ref": "contribution-B",
                    "remaining_work": ["Obtain independent CI provenance"], "reason": "Explicit Operator continuation"}
    switched = await c.post(root + "/handoffs", json=handoff_body, headers=operator)
    assert switched.status_code == 201, switched.text
    successor = switched.json()
    # Reading the new generation and contributor does not grant its private capability.
    guessed = await c.post(root + "/evaluate", json=write(successor, "guess-new-writer"), headers=headers)
    assert guessed.status_code == 403
    stale = await c.post(root + "/executions", json=execution(receipt, "stale-submit"), headers=headers)
    assert stale.status_code == 409
    assert (await c.post(root + "/executions", json=body, headers=headers)).json() == accepted.json()
    replay_handoff = await c.post(root + "/handoffs", json=handoff_body, headers=operator)
    assert "writer_token" not in replay_handoff.json()
    view = (await c.get(root, headers=operator)).json()
    assert len(view["executions"]) == 1 and len(view["handoffs"]) == 1
    frozen = await c.get(root + "/handoffs/" + successor["handoff_id"] + "/state", headers=operator)
    assert frozen.status_code == 200 and frozen.json()["state"]["run"]["generation"] == 1
    assert "writer_token" not in json.dumps(view)
    material = view["materials"][0]
    readback = await c.get(root + "/materials/" + material["id"], headers=operator)
    assert hashlib.sha256(base64.b64decode(readback.json()["content_base64"])).hexdigest() == material["sha256"]
    async with AsyncSessionLocal() as db:
        assert old_counts == [await db.scalar(select(func.count()).select_from(m)) for m in [LegacyRun, Evidence]]
        assert await db.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_id == UUID(receipt["run_id"])))


async def test_unknown_blocks_handoff_and_key_loss_reconcile_is_operator_managed(context):
    c, _, operator = context
    receipt, headers = await create(context)
    root = "/api/v1/native-runs/" + receipt["run_id"]
    unknown = {**write(receipt, "unknown-original"), "external_operation_ref": "ci/job/123/attempt/1",
               "reason": "Response lost; original operation not yet read back"}
    assert (await c.post(root + "/uncertainties", json=unknown, headers=headers)).status_code == 201
    handoff = {**write(receipt, "handoff-after-query"), "successor_session_ref": "successor",
               "remaining_work": ["Review accepted results"], "reason": "Writer token lost"}
    assert (await c.post(root + "/handoffs", json=handoff, headers=operator)).status_code == 409
    assert (await c.post(root + "/executions", json=execution(receipt), headers=headers)).status_code == 409
    query = {**write(receipt, "reconcile-not-found"), "observed_operation_ref": unknown["external_operation_ref"],
             "resolution": "NOT_FOUND", "material": raw_material('{"job":123,"status":"NOT_FOUND"}', format="TEXT", kind="CONTEXT"),
             "reason": "Original source currently reports not found; still uncertain"}
    def attest():
        query["attestation"] = {"kind": "ORIGINAL_OPERATION_READBACK", "source_ref": "approved-ci-job-read-api",
            "operation_ref": query["observed_operation_ref"], "observed_at": datetime.now(UTC).isoformat(),
            "result": query["resolution"], "raw_material_sha256": query["material"]["sha256"],
            "operator_attests_original_readback": True}
    # Free text without explicit Operator original-source attestation is refused.
    assert (await c.post(root + "/uncertainties/unknown-original/reconcile", json=query, headers=operator)).status_code == 422
    attest()
    checked = await c.post(root + "/uncertainties/unknown-original/reconcile", json=query, headers=operator)
    assert checked.status_code == 200 and checked.json()["status"] == "UNKNOWN", checked.text
    assert (await c.post(root + "/handoffs", json=handoff, headers=operator)).status_code == 409
    query.update(idempotency_key="reconcile-confirmed", resolution="OBSERVED_FAILED",
                 material=raw_material('{"job":123,"attempt":1,"status":"FAILED"}', format="TEXT", kind="CONTEXT"))
    attest()
    checked = await c.post(root + "/uncertainties/unknown-original/reconcile", json=query, headers=operator)
    assert checked.status_code == 200 and checked.json()["status"] == "RESOLVED", checked.text
    assert (await c.post(root + "/handoffs", json=handoff, headers=operator)).status_code == 201


async def test_missing_auth_scope_disabled_and_input_conflict(context, monkeypatch):
    c, project_id, operator = context
    payload = proposal(project_id)
    assert (await c.post("/api/v1/native-runs", json=payload)).status_code == 401
    monkeypatch.setattr(get_settings(), "native_intake_enabled", False)
    assert (await c.post("/api/v1/native-runs", json=payload, headers=operator)).status_code == 503
    monkeypatch.setattr(get_settings(), "native_intake_enabled", True)
    monkeypatch.setattr(get_settings(), "native_project_keys", [])
    assert (await c.post("/api/v1/native-runs", json=payload, headers=operator)).status_code == 403
    async with AsyncSessionLocal() as db:
        assert not await db.scalar(select(NativeTestRun.id).where(NativeTestRun.project_id == project_id))


async def test_failures_and_tampered_material_remain_blocking_and_immutable(context):
    c, _, operator = context
    receipt, headers = await create(context)
    root = "/api/v1/native-runs/" + receipt["run_id"]
    failed = execution(receipt, "failed-original", outcome="FAIL", step="FAIL")
    response = await c.post(root + "/executions", json=failed, headers=headers)
    assert response.status_code == 201, response.text
    passed = execution(receipt, "explicit-rerun")
    passed["retry_of_execution_id"] = response.json()["execution_id"]
    assert (await c.post(root + "/executions", json=passed, headers=headers)).status_code == 201
    result = await c.post(root + "/evaluate", json=write(receipt, "gate-failure"), headers=headers)
    assert result.json()["decision"] == "BLOCKED"
    view = (await c.get(root, headers=operator)).json()
    target = view["materials"][0]
    path = _path(target["sha256"])
    path.chmod(0o600)
    path.write_bytes(b"changed")
    assert (await c.get(root + "/materials/" + target["id"], headers=operator)).status_code == 409
    changed = await c.post(root + "/evaluate", json=write(receipt, "gate-tamper"), headers=headers)
    assert "RAW_MATERIAL_MISSING_OR_CHANGED" in changed.json()["reasons"]
    async with AsyncSessionLocal() as db:
        for statement in ["UPDATE native_execution_records SET observation='{}' WHERE id=:id",
                          "DELETE FROM native_execution_records WHERE id=:id"]:
            with pytest.raises(DBAPIError, match="append-only"):
                async with db.begin_nested():
                    await db.execute(text(statement), {"id": UUID(response.json()["execution_id"])})


@pytest.mark.parametrize("content", [parity(step="FAIL"), parity(summary_passed=2),
    '{"type":"scenario","name":"negative-case","verdict":"PASS"}',
    parity() + '\n{"type":"scenario","name":"negative-case","verdict":"PASS"}'])
def test_report_contradictions_never_become_consistent(content):
    result = verify_reports([("CONSUMER_PARITY_JSONL", content.encode())], {"negative-case": "PASS"}, 0)
    assert result["report_consistency"] == "INVALID"


def test_negative_business_unknown_is_a_passing_framework_assertion():
    result = verify_reports([("CONSUMER_PARITY_JSONL", parity(business="UNKNOWN").encode())], {"negative-case": "PASS"}, 0)
    assert result["report_consistency"] == "CONSISTENT" and result["provenance"] == "UNVERIFIED"


def test_explicit_native_mismatches_or_cleanup_failure_cannot_hide_behind_pass():
    rows = [json.loads(line) for line in parity().splitlines()]
    rows[0]["mismatches"] = ["requestIssued: expected false, actual true"]
    content = "\n".join(json.dumps(r) for r in rows).encode()
    assert verify_reports([("CONSUMER_PARITY_JSONL", content)], {"negative-case": "PASS"}, 0)["report_consistency"] == "INVALID"
    rows[0].pop("mismatches")
    rows.insert(1, {"type": "scenario_error", "name": "negative-case", "message": "fault cleanup failed"})
    content = "\n".join(json.dumps(r) for r in rows).encode()
    assert verify_reports([("CONSUMER_PARITY_JSONL", content)], {"negative-case": "PASS"}, 0)["report_consistency"] == "INVALID"


def test_junit_aggregate_contradiction_and_xml_entity_are_invalid():
    xml = '<testsuites tests="1" failures="1" errors="0" skipped="0"><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="RealProductContract" name="case"/></testsuite></testsuites>'
    for content in [xml.encode(), ('<!DOCTYPE x [<!ENTITY e "expanded">]>' + xml).encode(), xml.encode("utf-16")]:
        result = verify_reports([("JUNIT_XML", content)], {"RealProductContract#case": "PASS"}, 0)
        assert result["report_consistency"] == "INVALID"


def test_manifest_and_all_text_members_are_bounded():
    from pydantic import ValidationError

    from hypertest.native_protocol import CreateNativeRun
    payload = proposal("00000000-0000-0000-0000-000000000001")
    payload["plan"]["inputs"]["environment"] = {"version": "x" * (1024 * 1024)}
    with pytest.raises(ValidationError, match="16000"):
        CreateNativeRun.model_validate(payload)


@pytest.mark.parametrize("key", ["ci/job/123", "..", "with space", "key?query=1", "percent%2Fslash"])
def test_every_accepted_idempotency_key_can_be_queried_in_one_url_segment(key):
    from pydantic import ValidationError

    from hypertest.native_protocol import CreateNativeRun, NativeWrite
    payload = proposal("00000000-0000-0000-0000-000000000001")
    payload["idempotency_key"] = key
    with pytest.raises(ValidationError):
        CreateNativeRun.model_validate(payload)
    with pytest.raises(ValidationError):
        NativeWrite.model_validate({"contributor_id": payload["project_id"], "generation": 1, "idempotency_key": key})


async def test_material_io_occurs_without_aggregate_lock_and_is_refenced(context, monkeypatch):
    from hypertest.application import native

    c, _, _ = context
    receipt, headers = await create(context)
    root = "/api/v1/native-runs/" + receipt["run_id"]
    actual_prepare = native.prepare_material
    prepared = []
    def instrument(payload):
        # No aggregate lock may be held by the async request during fsync.
        # PostgreSQL NOWAIT is exercised on an independent synchronous thread.
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        async def try_lock():
            from sqlalchemy.ext.asyncio import create_async_engine
            engine = create_async_engine(get_settings().database_url)
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT id FROM native_test_runs WHERE id=:id FOR UPDATE NOWAIT"), {"id": UUID(receipt["run_id"])})
            finally:
                await engine.dispose()
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(lambda: asyncio.run(try_lock())).result(timeout=5)
        prepared.append(payload.name)
        return actual_prepare(payload)
    monkeypatch.setattr(native, "prepare_material", instrument)
    response = await c.post(root + "/executions", json=execution(receipt), headers=headers)
    assert response.status_code == 201, response.text
    assert prepared == ["report.jsonl", "stderr.log"]
