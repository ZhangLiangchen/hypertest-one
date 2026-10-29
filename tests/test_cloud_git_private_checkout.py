"""The shared-volume checkout target must already be private and empty."""
from pathlib import Path

import pytest

from hypertest.cloud import git
from hypertest.cloud.errors import CloudBlocked


@pytest.mark.asyncio
async def test_private_empty_target_only_by_explicit_opt_in(tmp_path, monkeypatch):
    target = tmp_path / "sut"
    target.mkdir(mode=0o700)
    commit = "a" * 40
    calls = []

    async def fake_git(args, **_kwargs):
        calls.append(args)
        return ""

    async def fake_fetch(_self, _root, _url, ref, _env):
        return ref

    monkeypatch.setattr(git, "_git", fake_git)
    monkeypatch.setattr(git.GitResolver, "_fetch", fake_fetch)
    resolved = {"commit_sha": commit, "url": "https://example.invalid/sut.git"}
    with pytest.raises(CloudBlocked):
        await git.GitResolver().checkout(resolved, target)
    await git.GitResolver().checkout(resolved, target, private_empty=True)
    assert calls == [["init", str(target)], ["checkout", "--detach", commit]]


@pytest.mark.asyncio
async def test_private_target_rejects_nonempty_wrong_mode_missing_and_symlink(tmp_path, monkeypatch):
    async def unexpected(*_args, **_kwargs):
        pytest.fail("Git must not start before target validation")

    monkeypatch.setattr(git, "_git", unexpected)
    resolved = {"commit_sha": "a" * 40, "url": "https://example.invalid/sut.git"}
    target = tmp_path / "sut"
    target.mkdir(mode=0o700)
    marker = target / "existing"
    marker.write_text("do not overwrite")
    with pytest.raises(CloudBlocked):
        await git.GitResolver().checkout(resolved, target, private_empty=True)
    assert marker.read_text() == "do not overwrite"
    marker.unlink()
    target.chmod(0o755)
    with pytest.raises(CloudBlocked):
        await git.GitResolver().checkout(resolved, target, private_empty=True)
    target.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    for invalid in (link, tmp_path / "missing", Path(str(target) + "/../sut")):
        with pytest.raises(CloudBlocked):
            await git.GitResolver().checkout(resolved, invalid, private_empty=True)
