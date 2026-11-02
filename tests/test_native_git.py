from pathlib import Path

import pytest

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.native_git import NativeGitResolver, _environment, repository_url


@pytest.mark.parametrize("value", [
    "https://example.test/group/repo.git",
    "ssh://git@example.test/group/repo.git",
    "git@example.test:group/repo.git",
])
def test_accepts_host_git_addresses(value):
    assert repository_url(value) == value


@pytest.mark.parametrize("value", [
    "https://user:secret@example.test/repo.git",
    "https://user@example.test/repo.git",
    "ssh://git:secret@example.test/repo.git",
    "https://example.test/repo.git?token=secret",
    "file:///tmp/repo",
    "file:/etc/passwd",
    "file:local-repo",
    "ext::malicious-helper",
    "example.test:group/repo.git",
    "--upload-pack=evil",
    "git@example.test:repo with spaces",
])
def test_rejects_embedded_credentials_and_unsafe_addresses(value):
    with pytest.raises(CloudBlocked):
        repository_url(value)


def test_environment_excludes_platform_credentials_and_disables_prompts(monkeypatch):
    monkeypatch.setenv("HYPERTEST_CLOUD_WORKER_TOKEN", "secret")
    monkeypatch.setenv("DATABASE_URL", "private")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/example-agent")
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN", "GLAB_TOKEN", "GH_CONFIG_DIR", "GLAB_CONFIG_DIR"):
        monkeypatch.setenv(name, "example")
    result = _environment()
    assert "HYPERTEST_CLOUD_WORKER_TOKEN" not in result
    assert "DATABASE_URL" not in result
    assert all(result[name] == "example" for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN", "GLAB_TOKEN", "GH_CONFIG_DIR", "GLAB_CONFIG_DIR"))
    assert result["SSH_AUTH_SOCK"] == "/tmp/example-agent"
    assert result["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in result["GIT_SSH_COMMAND"]


@pytest.mark.asyncio
async def test_host_git_rejects_platform_token_before_git(monkeypatch):
    async def no_git(*args, **kwargs):
        pytest.fail("must reject before invoking git")

    monkeypatch.setattr("hypertest.cloud.native_git._git", no_git)
    with pytest.raises(CloudBlocked) as error:
        await NativeGitResolver().resolve("https://example.test/repo", {"kind": "SHA", "value": "a" * 40}, token=b"secret")
    assert error.value.code == "GIT_PLATFORM_TOKEN_UNSUPPORTED"


@pytest.mark.asyncio
async def test_fixed_sha_resolve_and_checkout_without_retry(monkeypatch, tmp_path):
    sha = "a" * 40
    calls = []

    async def fake_git(args, **kwargs):
        calls.append(args)
        if args[0] == "rev-parse":
            return sha
        return ""

    monkeypatch.setattr("hypertest.cloud.native_git._git", fake_git)
    resolver = NativeGitResolver()
    resolved = await resolver.resolve("git@example.test:group/repo.git", {"kind": "SHA", "value": sha})
    await resolver.checkout(resolved, tmp_path / "checkout")
    assert resolved["commit_sha"] == sha
    assert sum(args[0] == "fetch" for args in calls) == 2
    assert [args for args in calls if args[0] == "checkout"] == [["checkout", "--detach", sha]]


@pytest.mark.asyncio
async def test_rejects_mismatched_fetched_sha_without_checkout_or_retry(monkeypatch, tmp_path):
    calls = []

    async def fake_git(args, **kwargs):
        calls.append(args)
        return "b" * 40 if args[0] == "rev-parse" else ""

    monkeypatch.setattr("hypertest.cloud.native_git._git", fake_git)
    with pytest.raises(CloudBlocked) as error:
        await NativeGitResolver().checkout({"url": "https://example.test/repo", "commit_sha": "a" * 40}, tmp_path / "checkout")
    assert error.value.code == "CHECKOUT_SHA_MISMATCH"
    assert sum(args[0] == "fetch" for args in calls) == 1
    assert all(args[0] != "checkout" for args in calls)


@pytest.mark.asyncio
async def test_mr_merge_rejects_unmatched_parents(monkeypatch):
    head, base, merge = "a" * 40, "b" * 40, "c" * 40
    resolver = NativeGitResolver()
    seen = []

    async def fetch(root: Path, url: str, ref: str):
        seen.append(ref)
        return {"refs/merge-requests/9/head": head, "refs/heads/main": base,
                "refs/merge-requests/9/merge": merge}[ref]

    async def fake_git(args, **kwargs):
        return f"{merge} {head} {'d' * 40}" if args[0] == "rev-list" else ""

    monkeypatch.setattr(resolver, "_fetch", fetch)
    monkeypatch.setattr("hypertest.cloud.native_git._git", fake_git)
    with pytest.raises(CloudBlocked) as error:
        await resolver.resolve("https://example.test/repo", {"kind": "MR", "number": 9,
            "base_ref": "refs/heads/main", "checkout_strategy": "MERGE"})
    assert error.value.code == "MR_MERGE_PROVENANCE"
    assert len(seen) == 3
