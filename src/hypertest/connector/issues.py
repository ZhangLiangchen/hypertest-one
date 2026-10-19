"""Local controlled GitLab adapter. Credentials never cross the Connector channel.

The daemon consumes an issue_create delivery once before handing it here. The
SQLite journal commits UNKNOWN before POST; duplicate delivery and query only
read/reconcile. A missing journal reached through query also stays UNKNOWN.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hypertest.application.gitlab import (
    GitLabTransport,
    HTTPResult,
    ProjectPolicy,
    Transport,
    _issue_reference,
)
from hypertest.application.services import canonical_json_sha256


class LocalGitLabProject(BaseModel):
    """Operator-owned local configuration, independent from model input."""
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    base_url: str
    gitlab_project_id: int = Field(gt=0)
    assignee_ids: list[int] = Field(min_length=1, max_length=100)
    credential_kind: Literal["glab", "token_file", "environment"] = "glab"
    token_file: str | None = None
    environment_name: Literal["GITLAB_TOKEN", "GLAB_TOKEN"] = "GITLAB_TOKEN"


class IssueDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    operation_id: str
    project_id: str
    node_id: str
    test_run_id: str
    binding_id: str
    binding_epoch: int = Field(gt=0)
    durable_job_id: str
    finding_id: str
    integration_id: str = Field(min_length=1, max_length=128)
    base_url: str
    gitlab_project_id: int = Field(gt=0)
    assignee_id: int = Field(gt=0)
    input_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    authorization_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    draft: dict[str, Any]
    correlation: str = Field(pattern="^HTISSUE-[a-f0-9]{32}$")
    delegation_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    expires_at: str


def _safe_project(config: LocalGitLabProject) -> None:
    url = urllib.parse.urlsplit(config.base_url)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or ".." in url.path.split("/")
            or any(c.isspace() for c in config.base_url)
            or any(type(i) is not int or i < 1 for i in config.assignee_ids)):
        raise ValueError("local GitLab scope is invalid")


class _GlabTransport:
    """Use glab's existing login without reading or returning its token."""
    async def request(self, method: str, url: str, token: str,
                      payload: dict[str, Any] | None = None) -> HTTPResult:
        target = urllib.parse.urlsplit(url)
        # glab api is used only for a validated fixed project endpoint. A glab
        # host with a path prefix needs token_file/environment configuration.
        if not target.path.startswith("/api/v4/projects/"):
            raise ValueError("glab requires an origin-root GitLab installation")
        endpoint = target.path.removeprefix("/api/v4/") + ("?" + target.query if target.query else "")
        command = ["glab", "api", "--hostname", target.netloc, "--method", method, endpoint]
        if payload is not None:
            command.extend(["--input", "-", "-H", "Content-Type: application/json"])
        process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            if payload is not None:
                process.stdin.write(json.dumps(payload).encode())
                await process.stdin.drain()
            process.stdin.close()
            async def read_bounded():
                chunks, size = [], 0
                while chunk := await process.stdout.read(65536):
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ValueError("GitLab response exceeds limit")
                    chunks.append(chunk)
                return b"".join(chunks)
            content = await asyncio.wait_for(read_bounded(), timeout=20)
            await asyncio.wait_for(process.wait(), timeout=20)
            # stderr can contain credentials or reflected untrusted data.
            return HTTPResult(0, None) if process.returncode else HTTPResult(201 if method == "POST" else 200, json.loads(content))
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


class LocalIssueAdapter:
    def __init__(self, ledger_path: Path, integrations: dict[str, LocalGitLabProject], *,
                 node_id: str, transport: Transport | None = None) -> None:
        self.node_id, self.integrations, self.transport = node_id, integrations, transport
        for config in integrations.values():
            _safe_project(config)
        self.ledger_path = Path(ledger_path)
        if not self.ledger_path.is_absolute() or self.ledger_path.is_symlink():
            raise ValueError("Issue ledger requires an absolute non-symlink path")
        self.ledger_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.ledger_path.parent.is_symlink():
            raise ValueError("Issue ledger directory cannot be a symlink")
        descriptor = os.open(self.ledger_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        self.ledger_path.chmod(0o600)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS issue_operations (operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL, status TEXT NOT NULL, issue TEXT)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.ledger_path, timeout=5)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _validate(self, payload: dict[str, Any], envelope: dict[str, Any]) -> tuple[IssueDelegation, LocalGitLabProject]:
        request = IssueDelegation.model_validate(payload)
        config = self.integrations.get(request.integration_id)
        try:
            deadline = datetime.fromisoformat(request.expires_at)
            now = datetime.now(UTC)
            if deadline.tzinfo is None or not now < deadline or (deadline - now).total_seconds() > 60:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Issue delegation deadline is invalid") from exc
        intent = request.model_dump(exclude={"delegation_sha256", "expires_at"})
        if (request.node_id != self.node_id or config is None
                or request.delegation_sha256 != canonical_json_sha256(intent)
                or request.base_url.rstrip("/") != config.base_url.rstrip("/")
                or request.gitlab_project_id != config.gitlab_project_id
                or request.assignee_id not in config.assignee_ids
                or request.correlation != "HTISSUE-" + request.operation_id.replace("-", "")
                or set(request.draft) != {"title", "description", "assignee_ids"}
                or not isinstance(request.draft["title"], str) or not 0 < len(request.draft["title"]) <= 255
                or not isinstance(request.draft["description"], str) or len(request.draft["description"]) > 48000
                or request.correlation not in request.draft["description"]
                or request.draft["assignee_ids"] != [request.assignee_id]):
            raise ValueError("Issue delegation does not match local integration scope")
        if envelope.get("node_id") not in {None, self.node_id}:
            raise ValueError("Issue delegation targets another node")
        return request, config

    def _transport(self, config: LocalGitLabProject) -> tuple[Transport, str]:
        if config.credential_kind == "glab":
            return self.transport or _GlabTransport(), ""
        if config.credential_kind == "environment":
            token = os.environ.get(config.environment_name, "")
        else:
            path = Path(config.token_file or "")
            if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                    or path.stat().st_mode & 0o077 or path.stat().st_size > 8192):
                raise ValueError("local GitLab credential is unavailable or unsafe")
            token = path.read_text().strip()
        if not token or len(token) > 8192 or any(c.isspace() for c in token):
            raise ValueError("local GitLab credential is unavailable or unsafe")
        return self.transport or GitLabTransport(), token

    def _receipt(self, request: IssueDelegation, status: str, issue: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"operation_id": request.operation_id, "delegation_sha256": request.delegation_sha256,
                "status": status, "issue": issue}

    def _read(self, request: IssueDelegation) -> tuple[str, dict[str, Any] | None] | None:
        with self._connect() as db:
            row = db.execute("SELECT digest,status,issue FROM issue_operations WHERE operation_id=?", (request.operation_id,)).fetchone()
        if row is None:
            return None
        if row[0] != request.delegation_sha256:
            raise ValueError("Issue operation is already bound to different input")
        return row[1], json.loads(row[2]) if row[2] else None

    def _save(self, request: IssueDelegation, status: str, issue: dict[str, Any] | None = None) -> None:
        with self._connect() as db:
            db.execute("UPDATE issue_operations SET status=?,issue=? WHERE operation_id=? AND digest=? AND status='UNKNOWN'",
                (status, json.dumps(issue) if issue else None, request.operation_id, request.delegation_sha256))

    async def create(self, payload: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
        request, config = self._validate(payload, envelope)
        existing = self._read(request)
        if existing is not None:
            return self._receipt(request, *existing)
        # SENT is persisted by the server before its single delivery. In
        # particular, query/reconnect cannot manufacture this first-write claim.
        if envelope.get("create_once") is not True:
            return self._receipt(request, "UNKNOWN")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute("INSERT OR IGNORE INTO issue_operations VALUES (?,?,'UNKNOWN',NULL)",
                (request.operation_id, request.delegation_sha256)).rowcount
        if not inserted:
            return self._receipt(request, *(self._read(request) or ("UNKNOWN", None)))
        try:
            transport, token = self._transport(config)
            remaining = (datetime.fromisoformat(request.expires_at) - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                return self._receipt(request, "UNKNOWN")
            response = await asyncio.wait_for(transport.request("POST", f"{request.base_url.rstrip('/')}/api/v4/projects/{request.gitlab_project_id}/issues", token, request.draft), timeout=remaining)
            policy = ProjectPolicy(base_url=config.base_url, project_id=config.gitlab_project_id,
                assignees={}, token_file="/local-only")
            reference = _issue_reference(response.data, policy, request.correlation, request.assignee_id)
            if response.status == 201 and reference:
                issue = self._issue(response.data)
                self._save(request, "SUCCEEDED", issue)
                return self._receipt(request, *(self._read(request) or ("UNKNOWN", None)))
            status = "REJECTED" if response.status in {400, 401, 403, 404, 405, 422} else "UNKNOWN"
            self._save(request, status)
            return self._receipt(request, *(self._read(request) or ("UNKNOWN", None)))
        except (OSError, ValueError, TimeoutError):
            return self._receipt(request, "UNKNOWN")

    @staticmethod
    def _issue(data: dict[str, Any]) -> dict[str, Any]:
        # Never relay arbitrary GitLab response fields (which can include user
        # profiles or reflected data). Only the fields needed for verification.
        return {**{key: data[key] for key in ("iid", "project_id", "description", "web_url")},
                "assignees": [{"id": item["id"]} for item in data["assignees"]]}

    async def probe(self) -> dict[str, Any]:
        """Read-only authentication diagnostics; never claims write permission."""
        result = {}
        for integration_id, config in self.integrations.items():
            available = False
            try:
                transport, token = self._transport(config)
                response = await asyncio.wait_for(transport.request("GET",
                    f"{config.base_url.rstrip('/')}/api/v4/projects/{config.gitlab_project_id}", token), timeout=20)
                available = (response.status == 200 and isinstance(response.data, dict)
                    and response.data.get("id") == config.gitlab_project_id
                    and response.data.get("issues_enabled") is True)
            except (OSError, ValueError, TimeoutError):
                pass
            result[integration_id] = {"authenticated_project_access": available, "create_permission_verified": False}
        return result

    async def query(self, payload: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
        request, config = self._validate(payload, envelope)
        existing = self._read(request)
        if existing is not None and existing[0] in {"SUCCEEDED", "REJECTED"}:
            return self._receipt(request, *existing)
        # Missing ledger may mean loss after a successful POST. Record UNKNOWN
        # and search; it can never authorize another POST.
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO issue_operations VALUES (?,?,'UNKNOWN',NULL)",
                (request.operation_id, request.delegation_sha256))
        try:
            transport, token = self._transport(config)
            url = (f"{request.base_url.rstrip('/')}/api/v4/projects/{request.gitlab_project_id}/issues?"
                + urllib.parse.urlencode({"search": request.correlation, "in": "description", "scope": "all", "per_page": 100}))
            remaining = (datetime.fromisoformat(request.expires_at) - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                return self._receipt(request, "UNKNOWN")
            response = await asyncio.wait_for(transport.request("GET", url, token), timeout=remaining)
            policy = ProjectPolicy(base_url=config.base_url, project_id=config.gitlab_project_id,
                assignees={}, token_file="/local-only")
            matches = [item for item in response.data if _issue_reference(item, policy, request.correlation, request.assignee_id)] if response.status == 200 and isinstance(response.data, list) else []
            if len(matches) == 1:
                issue = self._issue(matches[0])
                self._save(request, "SUCCEEDED", issue)
                return self._receipt(request, "SUCCEEDED", issue)
        except (OSError, ValueError, TimeoutError):
            pass
        return self._receipt(request, "UNKNOWN")

    def register(self, daemon) -> None:
        daemon.register_handler("issue_create", self.create)
        daemon.register_handler("issue_query", self.query)
