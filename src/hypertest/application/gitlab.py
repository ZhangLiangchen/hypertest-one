"""Controlled, journal-first GitLab requests. Unknown outcomes never repeat POST."""
from __future__ import annotations

import asyncio
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from hypertest.application.services import ConflictError, canonical_json_sha256
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.domain.enums import EvidenceStatus, ExecutionPurpose, FindingStatus, TrustLevel
from hypertest.domain.harness import GitLabIssueOperation
from hypertest.domain.models import Evidence, Finding, FindingEvidence, TestExecution, utcnow
from hypertest.runner.artifacts import read_evidence_content


class ProjectPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    base_url: str
    project_id: int = Field(gt=0)
    assignees: dict[str, int]
    allow_create: bool = False
    token_file: str


class GitLabPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    version: str
    projects: dict[str, ProjectPolicy]


@dataclass(frozen=True)
class HTTPResult:
    status: int
    data: Any


class Transport(Protocol):
    async def request(self, method: str, url: str, token: str,
                      payload: dict[str, Any] | None = None) -> HTTPResult: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the configured token to a redirected destination.
        return None


class GitLabTransport:
    async def request(self, method: str, url: str, token: str,
                      payload: dict[str, Any] | None = None) -> HTTPResult:
        def perform() -> HTTPResult:
            request = urllib.request.Request(
                url, data=json.dumps(payload).encode() if payload is not None else None,
                method=method, headers={"PRIVATE-TOKEN": token, "Accept": "application/json",
                                        "Content-Type": "application/json"},
            )
            try:
                response = urllib.request.build_opener(_NoRedirect()).open(request, timeout=20)
            except urllib.error.HTTPError as exc:
                # Error bodies may contain reflected secrets; do not retain them.
                exc.close()
                return HTTPResult(exc.code, None)
            with response:
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise ValueError("GitLab response exceeds limit")
                return HTTPResult(response.status, json.loads(data))
        return await asyncio.to_thread(perform)


def _policy(project_id: UUID) -> ProjectPolicy | None:
    filename = get_settings().gitlab_policy_file
    if not filename:
        return None
    try:
        path = Path(filename)
        if not path.is_absolute() or path.is_symlink() or path.stat().st_size > 100_000:
            raise ValueError
        policy = GitLabPolicy.model_validate_json(path.read_bytes())
        if policy.version != "hypertest.gitlab-policy/v1":
            raise ValueError
        project = policy.projects.get(str(project_id))
        if project is None:
            return None
        target = urllib.parse.urlsplit(project.base_url)
        if (target.scheme != "https" or not target.hostname or target.username or target.password
                or target.query or target.fragment or ".." in target.path.split("/")
                or any(character.isspace() for character in project.base_url)
                or not Path(project.token_file).is_absolute()
                or any(type(value) is not int or value < 1 for value in project.assignees.values())):
            raise ValueError
        return project
    except (OSError, ValueError, ValidationError) as exc:
        raise ConflictError("GitLab operator policy is invalid or unavailable") from exc


def _token(policy: ProjectPolicy) -> str:
    try:
        path = Path(policy.token_file)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192 or path.stat().st_mode & 0o007:
            raise ValueError
        value = path.read_text().strip()
        if not value or any(character.isspace() for character in value):
            raise ValueError
        return value
    except (OSError, ValueError) as exc:
        raise ConflictError("GitLab credential file is unavailable or unsafe") from exc


def _view(operation: GitLabIssueOperation) -> dict[str, Any]:
    return {"operation_id": str(operation.id), "status": operation.status,
            "finding_id": str(operation.finding_id), "issue_iid": operation.issue_iid,
            "issue_url": operation.issue_url}


def _marker(operation_id: UUID) -> str:
    return "HTISSUE-" + operation_id.hex


def _safe_body(text: str) -> str:
    # GitLab descriptions support quick actions and mentions. Neither is an
    # authorized way for an Agent to change policy-selected assignees or notify others.
    text = html.escape(text, quote=False).replace("@", "&#64;")
    return re.sub(r"(?m)^(\s*)/", r"\1&#47;", text)


def _issue_reference(data: Any, policy: ProjectPolicy, marker: str,
                     assignee_id: int | None = None) -> tuple[int, str] | None:
    if (not isinstance(data, dict) or type(data.get("iid")) is not int or data["iid"] < 1
            or data.get("project_id") != policy.project_id or not isinstance(data.get("description"), str)
            or marker not in data["description"] or not isinstance(data.get("web_url"), str)
            or len(data["web_url"]) > 2048):
        return None
    if assignee_id is not None:
        assigned = data.get("assignees")
        if (not isinstance(assigned, list) or len(assigned) != 1
                or not isinstance(assigned[0], dict) or assigned[0].get("id") != assignee_id):
            return None
    target = urllib.parse.urlsplit(policy.base_url)
    try:
        url = urllib.parse.urlsplit(data["web_url"])
        if (url.scheme != "https" or url.netloc != target.netloc or url.username or url.password
                or url.query or url.fragment or not url.path.startswith(target.path.rstrip("/") + "/")
                or not url.path.endswith(f"/issues/{data['iid']}")
                or any(character.isspace() for character in data["web_url"])):
            return None
    except ValueError:
        return None
    return data["iid"], data["web_url"]


async def _record_outcome(tools, operation_id: UUID, status: str,
                          reference: tuple[int, str] | None = None) -> dict[str, Any]:
    await tools.owned()
    operation = await tools.db.get(GitLabIssueOperation, operation_id)
    if operation is None or operation.binding_id != tools.binding_id:
        raise ConflictError("GitLab operation does not belong to this binding")
    if operation.status == "SUCCEEDED":
        return _view(operation)
    operation.status, operation.updated_at = status, utcnow()
    if reference:
        operation.issue_iid, operation.issue_url = reference
        finding = await tools.db.get(Finding, operation.finding_id)
        # The integration reference is not a confirmation, resolution, or Gate decision.
        if finding.external_issue_ref not in {None, reference[1]}:
            raise ConflictError("finding already references a different external issue")
        finding.external_issue_ref = reference[1]
        finding.row_version += 1
    await tools.audit("gitlab.issue_" + status.lower(), operation.id,
                      {"status": status, "finding_id": str(operation.finding_id),
                       "issue_iid": operation.issue_iid})
    await tools.db.commit()
    return _view(operation)


async def request_issue(tools, args, *, transport: Transport | None = None) -> dict[str, Any]:
    binding, _, _, _, run, source = await tools.state()
    finding = await tools.db.get(Finding, args.finding_id)
    if (finding is None or finding.test_run_id != run.id or finding.project_id != run.project_id
            or finding.status in {FindingStatus.INVALID, FindingStatus.CLOSED, FindingStatus.RESOLVED}):
        raise ConflictError("issue requires an accepted active finding from this Run")
    digest = canonical_json_sha256(args.model_dump(mode="json", exclude={"idempotency_key"}))
    existing = await tools.db.scalar(select(GitLabIssueOperation).where(
        GitLabIssueOperation.binding_id == binding.id, GitLabIssueOperation.finding_id == finding.id))
    if existing:
        if existing.input_sha256 != digest:
            raise ConflictError("finding issue is already bound to different input")
        await tools.db.commit()
        # PENDING includes lost acknowledgement; no second POST even if no match is found.
        return await reconcile_issue(tools, existing.id, transport=transport)
    policy = _policy(run.project_id)
    if policy is None or not policy.allow_create:
        return {"status": "DECISION_REQUIRED", "reason": "GitLab issue creation is not authorized by operator policy"}
    if args.assignee not in policy.assignees:
        return {"status": "DECISION_REQUIRED", "reason": "assignee is not configured for this project"}
    if finding.external_issue_ref:
        raise ConflictError("finding already has an external issue reference")
    evidence = list(await tools.db.scalars(select(Evidence).join(
        FindingEvidence, FindingEvidence.evidence_id == Evidence.id).join(
        TestExecution, TestExecution.id == Evidence.execution_id).where(
        FindingEvidence.finding_id == finding.id, Evidence.test_run_id == run.id,
        Evidence.status == EvidenceStatus.VERIFIED, Evidence.trust_level == TrustLevel.RUNNER,
        TestExecution.test_run_id == run.id, TestExecution.purpose == ExecutionPurpose.OFFICIAL,
        TestExecution.source_commit == source.commit_sha)))
    if not evidence:
        raise ConflictError("issue requires verified Runner evidence from this Run")
    for item in evidence:
        read_evidence_content(item)  # Validate stored bytes/hash before publishing references.
    token = _token(policy)
    operation_id = uuid7()
    description = (
        _safe_body(args.description) + "\n\nHyperTest references\n"
        + f"Run: {run.id}\nCommit: {source.commit_sha}\nFinding: {finding.key}\n"
        + "\n".join(f"Evidence: {item.key} SHA256 {item.sha256}" for item in evidence)
        + f"\nCorrelation: {_marker(operation_id)}\n"
    )
    draft = {"title": _safe_body(args.title), "description": description,
             "assignee_ids": [policy.assignees[args.assignee]]}
    authorization = {"policy_sha256": canonical_json_sha256(policy.model_dump()),
                     "base_url": policy.base_url.rstrip("/"), "project_id": policy.project_id,
                     "assignee": args.assignee, "assignee_id": policy.assignees[args.assignee],
                     "allow_create": True}
    operation = GitLabIssueOperation(id=operation_id, binding_id=binding.id, test_run_id=run.id,
        finding_id=finding.id, durable_job_id=tools.job_id, input_sha256=digest,
        draft=draft, authorization=authorization, status="PENDING")
    tools.db.add(operation)
    await tools.audit("gitlab.issue_requested", operation.id, {"finding_id": str(finding.id),
        "policy_sha256": authorization["policy_sha256"], "status": "PENDING"})
    await tools.db.commit()
    # Never hold aggregate/claim locks across external HTTP. Re-fence immediately
    # before sending and once more before any response enters the database.
    await tools.owned()
    await tools.db.commit()
    try:
        response = await (transport or GitLabTransport()).request(
            "POST", f"{authorization['base_url']}/api/v4/projects/{policy.project_id}/issues", token, draft)
        reference = _issue_reference(response.data, policy, _marker(operation_id), authorization["assignee_id"])
        if response.status == 201 and reference:
            return await _record_outcome(tools, operation_id, "SUCCEEDED", reference)
        # Only a definite client rejection excludes creation; server errors,
        # redirects and malformed success payloads remain outcome-unknown.
        status = "REJECTED" if response.status in {400, 401, 403, 404, 405, 422} else "UNKNOWN"
    except (OSError, ValueError, TimeoutError):
        status = "UNKNOWN"
    return await _record_outcome(tools, operation_id, status)


async def reconcile_issue(tools, operation_id: UUID, *, transport: Transport | None = None) -> dict[str, Any]:
    _, _, _, _, run, _ = await tools.state()
    operation = await tools.db.get(GitLabIssueOperation, operation_id)
    if operation is None or operation.binding_id != tools.binding_id or operation.test_run_id != run.id:
        raise ConflictError("GitLab operation does not belong to this Run")
    if operation.status in {"SUCCEEDED", "REJECTED"}:
        return _view(operation)
    policy = _policy(run.project_id)
    if (policy is None or policy.base_url.rstrip("/") != operation.authorization["base_url"]
            or policy.project_id != operation.authorization["project_id"]):
        return {**_view(operation), "reconciliation": "OPERATOR_POLICY_REQUIRED"}
    token = _token(policy)
    marker = _marker(operation.id)
    url = (f"{policy.base_url.rstrip('/')}/api/v4/projects/{policy.project_id}/issues?"
           + urllib.parse.urlencode({"search": marker, "in": "description", "scope": "all", "per_page": 100}))
    await tools.db.commit()
    try:
        response = await (transport or GitLabTransport()).request("GET", url, token)
        matches = []
        if response.status == 200 and isinstance(response.data, list):
            matches = [reference for item in response.data if (reference := _issue_reference(item, policy, marker, operation.authorization["assignee_id"]))]
        if len(matches) == 1:
            return await _record_outcome(tools, operation_id, "SUCCEEDED", matches[0])
    except (OSError, ValueError, TimeoutError):
        pass
    return await _record_outcome(tools, operation_id, "UNKNOWN")
