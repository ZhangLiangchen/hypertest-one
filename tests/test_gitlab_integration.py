"""PostgreSQL integration journal with injected HTTP; no real Issue writes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from test_run_bindings import bound_run as _bound_run

from hypertest.application.gitlab import (
    HTTPResult,
    _issue_reference,
    _NoRedirect,
    _policy,
    _safe_body,
    reconcile_issue,
    request_issue,
)
from hypertest.application.harness_tools import HarnessTools, IssueInput
from hypertest.application.services import ConflictError, canonical_json_sha256
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    FindingClassification,
    FindingSeverity,
    FindingStatus,
    TrustLevel,
)
from hypertest.domain.harness import GitLabIssueOperation, RunHarnessState, RunToolCall
from hypertest.domain.models import Evidence, Finding, FindingEvidence, SourceSnapshot
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.runner.artifacts import store_content

bound_run = _bound_run


@pytest.fixture
async def issue_context(bound_run, tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        run = await session.get(CanonicalRun, bound_run["run_id"])
        finding = Finding(id=uuid7(), key=public_key("FIND"), project_id=run.project_id,
            test_run_id=run.id, fingerprint=uuid7().hex * 2, classification=FindingClassification.PRODUCT_DEFECT,
            severity=FindingSeverity.MAJOR, title="Accepted defect", description="Runner showed wrong result",
            status=FindingStatus.NEW, reported_by_type="AGENT")
        source = await session.get(SourceSnapshot, run.source_snapshot_id)
        execution = CanonicalExecution(id=uuid7(), key=public_key("EX"), test_run_id=run.id,
            idempotency_key=public_key("EXEC"), purpose=ExecutionPurpose.OFFICIAL,
            runner_backend="pytest-docker", environment_id="fixture", environment_fingerprint="1" * 64,
            source_commit=source.commit_sha, execution_spec_sha256="2" * 64, spec={},
            status=ExecutionStatus.COMPLETED, outcome=ExecutionOutcome.FAIL, exit_code=1)
        session.add(execution)
        await session.flush()
        content = b"controlled test evidence"
        digest, uri = store_content(content)
        evidence = Evidence(id=uuid7(), key=public_key("EV"), test_run_id=run.id, execution_id=execution.id,
            evidence_type=EvidenceType.STDOUT, trust_level=TrustLevel.RUNNER, artifact_uri=uri,
            sha256=digest, size_bytes=len(content), collector="fixture-runner", source="fixture-runner",
            status=EvidenceStatus.VERIFIED)
        session.add_all([finding, evidence])
        await session.flush()
        session.add(FindingEvidence(finding_id=finding.id, evidence_id=evidence.id))
        await session.commit()
        result = {**bound_run, "project_id": run.project_id, "finding_id": finding.id, "evidence_id": evidence.id}
    token = tmp_path / "gitlab.secret"
    token.write_text("unit-test-token-never-log")
    token.chmod(0o600)
    policy = {"version": "hypertest.gitlab-policy/v1", "projects": {str(result["project_id"]): {
        "base_url": "https://gitlab.example.test", "project_id": 42,
        "assignees": {"responsible-developer": 7}, "allow_create": True, "token_file": str(token),
    }}}
    policy_path = tmp_path / "gitlab-policy.json"
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setattr(get_settings(), "gitlab_policy_file", str(policy_path))
    result.update(policy=policy, policy_path=policy_path, token_path=token)
    return result


def arguments(context, **changes):
    return IssueInput(finding_id=context["finding_id"], title=changes.pop("title", "Wrong response"),
                      description="Expected 3; Runner observed 1.\n/assign @unrelated-user",
                      assignee=changes.pop("assignee", "responsible-developer"),
                      idempotency_key=changes.pop("idempotency_key", "issue-create"), **changes)


def tools(session, context):
    return HarnessTools(session, context["binding_id"], 1, context["job_id"], context["token"])


class FakeTransport:
    def __init__(self, *, create="success", matches=None, db=None):
        self.create = create
        self.matches = matches or []
        self.calls = []
        self.db = db
        self.created = None

    async def request(self, method, url, token, payload=None):
        assert token == "unit-test-token-never-log"
        if self.db:
            assert not self.db.in_transaction(), "HTTP must not hold database locks"
        self.calls.append((method, url, payload))
        if method == "GET":
            return HTTPResult(200, self.matches)
        self.created = {"iid": 55, "project_id": 42, "description": payload["description"], "assignees": [{"id": 7}],
                        "web_url": "https://gitlab.example.test/team/project/-/issues/55"}
        if self.create == "timeout":
            raise TimeoutError("simulated untrusted token-bearing failure text")
        if self.create == "redirect":
            return HTTPResult(302, None)
        if self.create == "invalid":
            return HTTPResult(201, {**self.created, "project_id": 99})
        return HTTPResult(201, self.created)


async def test_authorized_issue_is_journaled_deduplicated_and_linked_without_confirming_finding(issue_context):
    context = issue_context
    async with AsyncSessionLocal() as session:
        harness = tools(session, context)
        transport = FakeTransport(db=session)
        result = await request_issue(harness, arguments(context), transport=transport)
        assert result["status"] == "SUCCEEDED" and result["issue_iid"] == 55
        repeated = await request_issue(harness, arguments(context, idempotency_key="repeat-input"), transport=transport)
        assert repeated == result and len(transport.calls) == 1
        operation = await session.get(GitLabIssueOperation, result["operation_id"])
        text = json.dumps({"draft": operation.draft, "authorization": operation.authorization})
        assert "unit-test-token" not in text and str(context["token_path"]) not in text
        assert "HTISSUE-" in operation.draft["description"]
        assert "Evidence:" in operation.draft["description"] and "Commit:" in operation.draft["description"]
        assert "\n/assign" not in operation.draft["description"]
        assert "@unrelated-user" not in operation.draft["description"]
        assert operation.draft["assignee_ids"] == [7]
        finding = await session.get(Finding, context["finding_id"])
        assert finding.external_issue_ref == result["issue_url"]
        assert finding.status is FindingStatus.NEW
        with pytest.raises(ConflictError, match="different input"):
            await request_issue(harness, arguments(context, title="Different draft"), transport=transport)


async def record_started_issue_tool(session, context, args):
    session.add(RunHarnessState(binding_id=context["binding_id"], first_job_id=context["job_id"],
        source_workspace=".", max_steps=12, timeout_seconds=300))
    call = RunToolCall(id=uuid7(), binding_id=context["binding_id"], durable_job_id=context["job_id"],
        binding_epoch=1, tool_name="request_gitlab_issue", idempotency_key=args.idempotency_key,
        input_sha256=canonical_json_sha256({"tool": "request_gitlab_issue", "arguments": args.model_dump(mode="json")}),
        status="STARTED")
    session.add(call)
    await session.commit()
    return call


async def test_started_issue_tool_reconciles_by_original_operation_without_post(issue_context, monkeypatch):
    context = issue_context
    async with AsyncSessionLocal() as session:
        harness, args = tools(session, context), arguments(context)
        call = await record_started_issue_tool(session, context, args)
        transport = FakeTransport(create="timeout", db=session)
        pending = await request_issue(harness, args, transport=transport)
        assert pending["status"] == "UNKNOWN"
        transport.matches = [transport.created]
        monkeypatch.setattr("hypertest.application.gitlab.GitLabTransport", lambda: transport)
        result = await harness.dispatch("request_gitlab_issue", args.model_dump(mode="json"))
        assert result["status"] == "SUCCEEDED" and result["operation_id"] == pending["operation_id"]
        assert [item[0] for item in transport.calls] == ["POST", "GET"]
        await session.refresh(call)
        assert call.status == "SUCCEEDED"
        page = await harness.dispatch("get_state", {"resource": "operations"})
        data = json.loads(page["content"])
        operation = data["gitlab_operations"][0]
        assert operation["operation_id"] == result["operation_id"]
        assert operation["finding_id"] == str(context["finding_id"])
        assert operation["issue_url"] == result["issue_url"]
        assert "unit-test-token" not in json.dumps(page) and "token_file" not in json.dumps(page)
        assert not data["unresolved_tool_calls"]


async def test_started_issue_tool_without_operation_stays_unknown_without_external_request(issue_context, monkeypatch):
    async with AsyncSessionLocal() as session:
        harness, args = tools(session, issue_context), arguments(issue_context)
        call = await record_started_issue_tool(session, issue_context, args)
        transport = FakeTransport()
        monkeypatch.setattr("hypertest.application.gitlab.GitLabTransport", lambda: transport)
        with pytest.raises(ConflictError, match="OUTCOME_UNKNOWN"):
            await harness.dispatch("request_gitlab_issue", args.model_dump(mode="json"))
        await session.refresh(call)
        assert call.status == "UNKNOWN" and not transport.calls
        data = json.loads((await harness.dispatch("get_state", {"resource": "operations"}))["content"])
        assert data["gitlab_operations"] == []
        assert data["unresolved_tool_calls"][0]["id"] == str(call.id)


async def test_started_issue_tool_cannot_reconcile_different_recorded_draft(issue_context, monkeypatch):
    async with AsyncSessionLocal() as session:
        harness = tools(session, issue_context)
        original = arguments(issue_context)
        changed = arguments(issue_context, title="Changed input")
        await record_started_issue_tool(session, issue_context, changed)
        transport = FakeTransport(create="timeout")
        await request_issue(harness, original, transport=transport)
        monkeypatch.setattr("hypertest.application.gitlab.GitLabTransport", lambda: transport)
        with pytest.raises(ConflictError, match="different input"):
            await harness.dispatch("request_gitlab_issue", changed.model_dump(mode="json"))
        assert [item[0] for item in transport.calls] == ["POST"]


async def test_timeout_is_reconciled_and_never_reposted_even_when_not_found(issue_context):
    context = issue_context
    async with AsyncSessionLocal() as session:
        harness = tools(session, context)
        transport = FakeTransport(create="timeout", db=session)
        original = await request_issue(harness, arguments(context), transport=transport)
        assert original["status"] == "UNKNOWN"
        still_unknown = await request_issue(harness, arguments(context), transport=transport)
        assert still_unknown["status"] == "UNKNOWN"
        assert [call[0] for call in transport.calls] == ["POST", "GET"]
        transport.matches = [transport.created]
        reconciled = await reconcile_issue(harness, original["operation_id"], transport=transport)
        assert reconciled["status"] == "SUCCEEDED" and reconciled["issue_iid"] == 55
        assert [call[0] for call in transport.calls] == ["POST", "GET", "GET"]
        assert "search=HTISSUE-" in transport.calls[-1][1]


@pytest.mark.parametrize("mode", ["redirect", "invalid"])
async def test_redirect_or_malformed_success_remains_unknown(issue_context, mode):
    async with AsyncSessionLocal() as session:
        result = await request_issue(tools(session, issue_context), arguments(issue_context),
                                     transport=FakeTransport(create=mode))
        assert result["status"] == "UNKNOWN" and result["issue_url"] is None


async def test_no_policy_or_unmapped_assignee_requires_operator_decision_without_http(issue_context, monkeypatch):
    context = issue_context
    async with AsyncSessionLocal() as session:
        transport = FakeTransport()
        result = await request_issue(tools(session, context), arguments(context, assignee="someone-else"), transport=transport)
        assert result["status"] == "DECISION_REQUIRED"
        monkeypatch.setattr(get_settings(), "gitlab_policy_file", None)
        result = await request_issue(tools(session, context), arguments(context), transport=transport)
        assert result["status"] == "DECISION_REQUIRED" and not transport.calls
        assert not await session.scalar(select(GitLabIssueOperation).where(GitLabIssueOperation.binding_id == context["binding_id"]))


async def test_cross_run_finding_and_untrusted_evidence_are_rejected(issue_context):
    context = issue_context
    async with AsyncSessionLocal() as session:
        harness = tools(session, context)
        transport = FakeTransport()
        with pytest.raises(ConflictError, match="accepted active finding"):
            invalid = arguments(context).model_copy(update={"finding_id": uuid7()})
            await request_issue(harness, invalid, transport=transport)
        evidence = await session.get(Evidence, context["evidence_id"])
        evidence.status = EvidenceStatus.REJECTED
        await session.commit()
        with pytest.raises(ConflictError, match="verified Runner evidence"):
            await request_issue(harness, arguments(context), transport=transport)
        assert not transport.calls


async def test_policy_cannot_change_destination_during_unknown_outcome(issue_context):
    context = issue_context
    async with AsyncSessionLocal() as session:
        harness = tools(session, context)
        transport = FakeTransport(create="timeout")
        result = await request_issue(harness, arguments(context), transport=transport)
        context["policy"]["projects"][str(context["project_id"])]["base_url"] = "https://other.example.test"
        context["policy_path"].write_text(json.dumps(context["policy"]))
        reconciled = await reconcile_issue(harness, result["operation_id"], transport=transport)
        assert reconciled["reconciliation"] == "OPERATOR_POLICY_REQUIRED"
        assert len(transport.calls) == 1


def test_http_redirects_are_not_followed_and_payload_cannot_run_quick_actions():
    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test") is None
    assert _safe_body("hello\n/assign @other\n  /close") == "hello\n&#47;assign &#64;other\n  &#47;close"


@pytest.mark.parametrize("url", ["http://gitlab.example.test", "https://token:secret@gitlab.example.test", "https://gitlab.example.test?token=secret"])
def test_invalid_operator_target_is_rejected_without_secret_details(tmp_path, monkeypatch, url):
    project_id = uuid7()
    path = Path(tmp_path) / "policy.json"
    path.write_text(json.dumps({"version": "hypertest.gitlab-policy/v1", "projects": {str(project_id): {
        "base_url": url, "project_id": 42, "assignees": {"owner": 7}, "allow_create": True,
        "token_file": str(tmp_path / "token"),
    }}}))
    monkeypatch.setattr(get_settings(), "gitlab_policy_file", str(path))
    with pytest.raises(ConflictError, match="invalid or unavailable") as raised:
        _policy(project_id)
    assert "secret" not in str(raised.value)


def test_issue_reference_rejects_credentialed_cross_origin_and_wrong_project():
    from hypertest.application.gitlab import ProjectPolicy
    policy = ProjectPolicy(base_url="https://gitlab.example.test", project_id=42, assignees={"owner": 7}, token_file="/secret")
    valid = {"iid": 5, "project_id": 42, "description": "marker", "web_url": "https://gitlab.example.test/a/b/-/issues/5"}
    assert _issue_reference(valid, policy, "marker")
    assert not _issue_reference({**valid, "project_id": 43}, policy, "marker")
    assert not _issue_reference({**valid, "web_url": "https://other.test/a/b/-/issues/5"}, policy, "marker")
    assert not _issue_reference({**valid, "web_url": "https://secret@gitlab.example.test/a/b/-/issues/5"}, policy, "marker")
