"""Local ledger and credential boundaries; injected HTTP is not live GitLab QA."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from hypertest.application.gitlab import HTTPResult
from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import uuid7
from hypertest.connector.issues import LocalGitLabProject, LocalIssueAdapter, _GlabTransport


def delegation(default_node_id, **changes):
    op = uuid7()
    marker = "HTISSUE-" + op.hex
    result = {"operation_id": str(op), "project_id": str(uuid7()), "node_id": default_node_id,
        "test_run_id": str(uuid7()), "binding_id": str(uuid7()), "binding_epoch": 1,
        "durable_job_id": str(uuid7()), "finding_id": str(uuid7()), "integration_id": "work",
        "base_url": "https://gitlab.example.test", "gitlab_project_id": 42, "assignee_id": 7,
        "input_sha256": "1" * 64, "authorization_sha256": "2" * 64,
        "draft": {"title": "Runner found defect", "description": "controlled draft\nCorrelation: " + marker,
                  "assignee_ids": [7]}, "correlation": marker, **changes}
    result["delegation_sha256"] = canonical_json_sha256(result)
    result["expires_at"] = (datetime.now(UTC) + timedelta(seconds=20)).isoformat()
    return result


class HTTP:
    def __init__(self, mode="success"):
        self.calls, self.issue, self.mode = [], None, mode

    async def request(self, method, url, token, payload=None):
        assert token == "LOCAL-SECRET-NEVER-RELAY"
        self.calls.append((method, url))
        if method == "POST":
            self.issue = {"iid": 9, "project_id": 42, "description": payload["description"],
                "web_url": "https://gitlab.example.test/work/repo/-/issues/9", "assignees": [{"id": 7}]}
            if self.mode == "timeout":
                raise TimeoutError("untrusted text LOCAL-SECRET-NEVER-RELAY")
            if self.mode == "wrong_assignee":
                return HTTPResult(201, {**self.issue, "assignees": [{"id": 8}]})
            return HTTPResult(201, self.issue)
        return HTTPResult(200, ([self.issue] * (2 if self.mode == "duplicates" else 1)) if self.issue else [])


def adapter(tmp_path, monkeypatch, *, mode="success", node_id=None):
    node = node_id or str(uuid7())
    monkeypatch.setenv("GITLAB_TOKEN", "LOCAL-SECRET-NEVER-RELAY")
    http = HTTP(mode)
    integration = LocalGitLabProject(base_url="https://gitlab.example.test", gitlab_project_id=42,
        assignee_ids=[7], credential_kind="environment")
    return LocalIssueAdapter(tmp_path / "private" / "issues.sqlite", {"work": integration},
        node_id=node, transport=http), http, node


async def test_create_uses_local_authorization_once_and_receipt_contains_no_credentials(tmp_path, monkeypatch):
    local, http, node = adapter(tmp_path, monkeypatch)
    payload = delegation(node)
    first = await local.create(payload, {"create_once": True, "node_id": node})
    assert first["status"] == "SUCCEEDED" and first["issue"]["iid"] == 9
    assert "LOCAL-SECRET" not in json.dumps(first) and "token" not in json.dumps(payload)
    assert await local.create(payload, {"create_once": True}) == first
    assert await local.query(payload, {}) == first
    assert [c[0] for c in http.calls] == ["POST"]
    assert local.ledger_path.stat().st_mode & 0o077 == 0


async def test_timeout_ack_loss_and_restart_only_query_original_operation(tmp_path, monkeypatch):
    local, http, node = adapter(tmp_path, monkeypatch, mode="timeout")
    payload = delegation(node)
    assert (await local.create(payload, {"create_once": True}))["status"] == "UNKNOWN"
    restarted = LocalIssueAdapter(local.ledger_path, local.integrations, node_id=node, transport=http)
    assert (await restarted.create(payload, {"create_once": True}))["status"] == "UNKNOWN"
    assert (await restarted.query(payload, {}))["status"] == "SUCCEEDED"
    assert [c[0] for c in http.calls] == ["POST", "GET"]


async def test_missing_ledger_is_reconciled_and_cannot_mint_new_create_claim(tmp_path, monkeypatch):
    local, http, node = adapter(tmp_path, monkeypatch)
    payload = delegation(node)
    assert (await local.create(payload, {"create_once": True}))["status"] == "SUCCEEDED"
    local.ledger_path.unlink()
    replacement = LocalIssueAdapter(local.ledger_path, local.integrations, node_id=node, transport=http)
    assert (await replacement.create(payload, {"create_once": False}))["status"] == "UNKNOWN"
    assert (await replacement.query(payload, {}))["status"] == "SUCCEEDED"
    assert (await replacement.create(payload, {"create_once": True}))["status"] == "SUCCEEDED"
    assert [c[0] for c in http.calls] == ["POST", "GET"]


async def test_query_before_create_fails_closed_even_if_result_not_found(tmp_path, monkeypatch):
    local, http, node = adapter(tmp_path, monkeypatch)
    payload = delegation(node)
    assert (await local.query(payload, {}))["status"] == "UNKNOWN"
    assert (await local.create(payload, {"create_once": True}))["status"] == "UNKNOWN"
    assert [c[0] for c in http.calls] == ["GET"]


async def test_conflicting_input_cannot_reuse_operation_id(tmp_path, monkeypatch):
    local, http, node = adapter(tmp_path, monkeypatch)
    payload = delegation(node)
    await local.create(payload, {"create_once": True})
    changed = {**payload, "input_sha256": "3" * 64}
    changed["delegation_sha256"] = canonical_json_sha256({k: v for k, v in changed.items() if k not in {"delegation_sha256", "expires_at"}})
    with pytest.raises(ValueError, match="different input"):
        await local.create(changed, {"create_once": True})
    assert len(http.calls) == 1


@pytest.mark.parametrize("changes", [
    {"base_url": "https://evil.example"}, {"gitlab_project_id": 99}, {"assignee_id": 8},
    {"node_id": "other-node"}, {"integration_id": "unapproved"},
])
async def test_local_scope_cannot_be_expanded_by_delegation(tmp_path, monkeypatch, changes):
    local, http, node = adapter(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="scope"):
        await local.create(delegation(node, **changes), {"create_once": True})
    assert not http.calls


async def test_expired_delegation_and_forged_digest_do_not_write(tmp_path, monkeypatch):
    local, http, node = adapter(tmp_path, monkeypatch)
    payload = delegation(node)
    with pytest.raises(ValueError, match="deadline"):
        await local.create({**payload, "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}, {"create_once": True})
    with pytest.raises(ValueError, match="scope"):
        await local.create({**payload, "delegation_sha256": "0" * 64}, {"create_once": True})
    assert not http.calls


async def test_wrong_assignee_and_ambiguous_correlation_are_unknown(tmp_path, monkeypatch):
    local, http, node = adapter(tmp_path, monkeypatch, mode="wrong_assignee")
    payload = delegation(node)
    assert (await local.create(payload, {"create_once": True}))["status"] == "UNKNOWN"
    http.mode = "duplicates"
    assert (await local.query(payload, {}))["status"] == "UNKNOWN"
    assert [c[0] for c in http.calls] == ["POST", "GET"]


async def test_glab_json_stdin_sets_explicit_content_type_without_token_arguments(monkeypatch):
    commands, written = [], []
    class Stdin:
        def write(self, content): written.append(content)
        async def drain(self): pass
        def close(self): pass
    class Stdout:
        contents = [b'{"iid":9}', b'']
        async def read(self, _size): return self.contents.pop(0)
    class Process:
        returncode, stdin, stdout = 0, Stdin(), Stdout()
        async def wait(self): return 0
    async def spawn(*args, **kwargs):
        commands.append(args)
        return Process()
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    response = await _GlabTransport().request("POST", "https://gitlab.example.test/api/v4/projects/42/issues", "", {"title": "approved"})
    assert response.status == 201 and response.data == {"iid": 9}
    assert commands == [("glab", "api", "--hostname", "gitlab.example.test", "--method", "POST",
        "projects/42/issues", "--input", "-", "-H", "Content-Type: application/json")]
    assert json.loads(written[0]) == {"title": "approved"}
