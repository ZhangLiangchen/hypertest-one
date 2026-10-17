"""Pin advertised refs without creating snapshots, workspaces, or Agent sessions."""
import pytest
from httpx import ASGITransport, AsyncClient

from hypertest.application import workspaces
from hypertest.application.services import ConflictError
from hypertest.main import app
from hypertest.runner.backends import ProcessResult, run_process

COMMIT = "a" * 40
TAG_OBJECT = "b" * 40


def remote(monkeypatch, stdout=b"", exit_code=0, *, timed_out=False):
    calls = []

    async def process(command, **kwargs):
        calls.append(command)
        if command[1] == "check-ref-format":
            return await run_process(command, **kwargs)
        assert command[:4] == ["git", "ls-remote", "--exit-code", "--"]
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        return ProcessResult(stdout, b"private proxy diagnostic must not escape", exit_code, timed_out)

    monkeypatch.setattr(workspaces, "run_process", process)
    return calls


async def test_resolve_branch_returns_pinned_input_without_checkout(monkeypatch):
    calls = remote(monkeypatch, f"{COMMIT}\trefs/heads/main\n".encode())
    result = await workspaces.resolve_source(" https://github.com/example/project.git/ ", " main ")
    assert result == {"repository_url": "https://github.com/example/project.git", "commit_sha": COMMIT, "revision": "main"}
    assert len(calls) == 3
    assert all("fetch" not in command and "checkout" not in command for command in calls)


async def test_resolve_annotated_tag_uses_peeled_tip(monkeypatch):
    remote(monkeypatch, f"{TAG_OBJECT}\trefs/tags/v1\n{COMMIT}\trefs/tags/v1^{{}}\n".encode())
    assert (await workspaces.resolve_source("https://github.com/example/project", "refs/tags/v1"))["commit_sha"] == COMMIT


async def test_ambiguous_tag_and_branch_require_explicit_namespace(monkeypatch):
    remote(monkeypatch, f"{COMMIT}\trefs/heads/release\n{TAG_OBJECT}\trefs/tags/release\n".encode())
    with pytest.raises(ConflictError, match="ambiguous"):
        await workspaces.resolve_source("https://github.com/example/project", "release")


async def test_explicit_sha_is_normalized_without_network(monkeypatch):
    calls = remote(monkeypatch)
    result = await workspaces.resolve_source("https://github.com/example/project", COMMIT.upper())
    assert result["commit_sha"] == COMMIT
    assert calls == []


@pytest.mark.parametrize("url", [
    "file:///tmp/repo", "/tmp/checkout", "ssh://git@github.com/example/repo", "https://gitlab.com/a/b",
    "https://github.com.example.org/a/b", "https://token@github.com/a/b", "https://github.com:443/a/b",
    "https://github.com/a/b?token=private", "https://github.com/a/b#main",
])
async def test_source_resolution_rejects_other_transports_before_git(monkeypatch, url):
    calls = remote(monkeypatch)
    with pytest.raises(ValueError):
        await workspaces.resolve_source(url, "main")
    assert calls == []


@pytest.mark.parametrize("revision", ["", "../main", "--upload-pack=evil", "main~1", "refs/notes/main", "main lock"])
async def test_invalid_ref_never_contacts_remote(monkeypatch, revision):
    calls = remote(monkeypatch)
    with pytest.raises(ValueError):
        await workspaces.resolve_source("https://github.com/example/project", revision)
    assert not any(command[1] == "ls-remote" for command in calls)


@pytest.mark.parametrize("exit_code,timed_out", [(2, False), (0, True)])
async def test_missing_ref_and_network_timeout_have_actionable_redacted_error(monkeypatch, exit_code, timed_out):
    remote(monkeypatch, exit_code=exit_code, timed_out=timed_out)
    with pytest.raises(ConflictError, match="configured Git access") as error:
        await workspaces.resolve_source("https://github.com/example/project", "main")
    assert "private" not in str(error.value)


async def test_readonly_resolution_api_returns_full_pin_and_validates_transport(monkeypatch):
    remote(monkeypatch, f"{COMMIT}\trefs/heads/main\n".encode())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        response = await client.post("/api/v1/sources/resolve", json={"repository_url": "https://github.com/example/project", "revision": "main"})
        assert response.status_code == 200
        assert response.json()["commit_sha"] == COMMIT
        rejected = await client.post("/api/v1/sources/resolve", json={"repository_url": "/tmp/operator-checkout", "revision": "main"})
        assert rejected.status_code == 422


@pytest.mark.parametrize("origin", [
    "https://git:fake-resolution-token@github.com\uff0fexample/repo",
    "https://github.com:fake-resolution-token/example/repo",
    "https://@github.com/example/repo",
    "https://:@github.com/example/repo",
])
async def test_resolution_api_redacts_malformed_authority_and_port_before_git(monkeypatch, origin):
    calls = remote(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        rejected = await client.post("/api/v1/sources/resolve", json={
            "repository_url": origin, "revision": "main",
        })
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == (
        "automatic checkout supports credential-free HTTPS github.com owner/repository URLs; use an existing workspace for other hosts"
    )
    assert "fake-resolution-token" not in rejected.text
    assert origin not in rejected.text
    assert calls == []
