"""Only frozen, scanned file bytes cross the Worker-to-Agent boundary."""
import hashlib
import subprocess
from uuid import uuid4

import pytest
from fastapi import HTTPException

from hypertest.api.cloud_schemas import TaskInputs
from hypertest.application.cloud_tasks import _reject_secrets
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.source_export import (
    PROFILE,
    derive_checkout_export,
    export_sources,
    validate_export,
)


def entry(path, content):
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest()}


def fixture(tmp_path):
    roots = {}
    for role in ("sut", "framework"):
        source = tmp_path / (role + "-private")
        target = tmp_path / (role + "-agent")
        source.mkdir(mode=0o700)
        target.mkdir(mode=0o700)
        (source / "src").mkdir()
        (source / "src" / "module.py").write_bytes(b"print('synthetic')\n")
        (source / ".git").mkdir()
        (source / ".git" / "private-object").write_text("private object store")
        (source / "secrets.yaml").write_text("synthetic secret")
        roots[role] = (source, target)
    policy = {"profile": PROFILE, **{role: [entry("src/module.py", b"print('synthetic')\n")]
                                  for role in ("sut", "framework")}}
    return roots, policy


def test_export_contract_is_frozen_and_absence_preserves_existing_input():
    value = {"sut_selector": {"kind": "SHA", "value": "a" * 40},
        "framework_selector": {"kind": "SHA", "value": "b" * 40},
        "prd_markdown": "synthetic", "prd_version": "v1", "objective": "test", "basic_flow": "test",
        "test_scope": "test", "framework_entrypoints": ["python -m pytest"],
        "authorization": {"targets": ["fixture"], "permitted_actions": ["git:read", "framework:execute"],
            "side_effect_limits": "none", "expires_at": "2030-01-01T00:00:00+00:00"},
        "budgets": {"total_seconds": 60, "total_cost_microunits": 1}}
    assert "agent_source_export" not in TaskInputs.model_validate(value).model_dump(mode="json")
    policy = {"profile": PROFILE, **{role: [entry("main.py", b"synthetic")]
                                  for role in ("sut", "framework")}}
    assert TaskInputs.model_validate({**value, "agent_source_export": policy}).model_dump(mode="json")["agent_source_export"] == policy


@pytest.mark.asyncio
async def test_only_selected_scanned_text_crosses_to_agent(tmp_path):
    roots, policy = fixture(tmp_path)
    seen = []
    async def validate(payload):
        seen.append(payload)
    await export_sources(policy=policy, sources={k: v[0] for k, v in roots.items()},
                         destinations={k: v[1] for k, v in roots.items()}, validate_payload=validate)
    assert len(seen) == 1
    for _, target in roots.values():
        assert (target / "src/module.py").read_bytes() == b"print('synthetic')\n"
        assert not (target / ".git").exists() and not (target / "secrets.yaml").exists()


@pytest.mark.asyncio
async def test_scan_failure_releases_no_files(tmp_path):
    roots, policy = fixture(tmp_path)
    async def reject(_payload):
        raise CloudBlocked("SECRET_REFUSED", "synthetic credential")
    with pytest.raises(CloudBlocked, match="synthetic credential"):
        await export_sources(policy=policy, sources={k: v[0] for k, v in roots.items()},
                             destinations={k: v[1] for k, v in roots.items()}, validate_payload=reject)
    assert all(not list(target.iterdir()) for _, target in roots.values())


@pytest.mark.asyncio
async def test_source_scanner_allows_documented_marker_but_rejects_pem_material():
    class Db:
        async def scalars(self, _query):
            return []
    example = {"source_export": [{"path": "signer.py", "content": 'Example: "-----BEGIN PRIVATE KEY-----"'}]}
    await _reject_secrets(Db(), uuid4(), example, source_text=True)
    with pytest.raises(HTTPException):
        await _reject_secrets(Db(), uuid4(), example)  # Other artifacts remain stricter.
    actual = {"source_export": [{"path": "signer.py", "content": "-----BEGIN PRIVATE KEY-----\n" + "A" * 64}]}
    with pytest.raises(HTTPException):
        await _reject_secrets(Db(), uuid4(), actual, source_text=True)


@pytest.mark.parametrize("path", ["../secret", "a/../b", ".git/config", "configs/secrets.yaml",
                                 "configs/keys/member.pem", "configs/test_API_Key.txt", "a//b"])
def test_rejects_unapproved_or_sensitive_paths(path):
    value = {"profile": PROFILE, "sut": [entry("main.py", b"x")], "framework": [entry(path, b"x")]}
    with pytest.raises(CloudBlocked):
        validate_export(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["symlink", "digest", "binary", "nonempty"])
async def test_rejects_unsafe_or_changed_file_before_release(tmp_path, failure):
    roots, policy = fixture(tmp_path)
    source, target = roots["framework"]
    file = source / "src/module.py"
    if failure == "symlink":
        file.unlink()
        file.symlink_to(source / "secrets.yaml")
    elif failure == "digest":
        file.write_text("changed")
    elif failure == "binary":
        file.write_bytes(b"\xff")
        policy["framework"] = [entry("src/module.py", b"\xff")]
    else:
        (target / "already-there").write_text("keep")
    async def reject_scan(_payload):
        pytest.fail("unsafe source must fail before scanning")
    with pytest.raises(CloudBlocked):
        await export_sources(policy=policy, sources={k: v[0] for k, v in roots.items()},
                             destinations={k: v[1] for k, v in roots.items()}, validate_payload=reject_scan)
    assert not (roots["sut"][1] / "src/module.py").exists()
    if failure == "nonempty":
        assert (target / "already-there").read_text() == "keep"


def git_checkout(path, files):
    """Create an isolated synthetic checkout; no model, network or SUT."""
    path.mkdir(mode=0o700)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    for name, value in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, tuple):
            target.symlink_to(value[0])
        else:
            target.write_bytes(value)
    subprocess.run(["git", "-C", str(path), "add", "--all"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "--quiet", "-m", "synthetic"], check=True)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


@pytest.mark.asyncio
async def test_derived_policy_copies_all_frozen_tracked_text_without_git_metadata(tmp_path):
    root = tmp_path.resolve()
    sources = {role: root / (role + "-source") for role in ("sut", "framework")}
    repositories = {role: {"commit_sha": git_checkout(path, {"main.py": b"print('synthetic')\n", "src/test.py": b"pass\n"})}
                    for role, path in sources.items()}
    (sources["sut"] / "untracked.txt").write_text("not in the frozen commit")
    destinations = {role: root / (role + "-destination") for role in sources}
    for destination in destinations.values():
        destination.mkdir(mode=0o700)
    policy = await derive_checkout_export(sources=sources, repositories=repositories)
    assert {entry["path"] for entry in policy["sut"]} == {"main.py", "src/test.py"}
    scanned = []
    async def validate(payload):
        scanned.extend(payload["source_export"])
    await export_sources(policy=policy, sources=sources, destinations=destinations, validate_payload=validate)
    assert len(scanned) == 4
    for target in destinations.values():
        assert (target / "src/test.py").read_bytes() == b"pass\n"
        assert not (target / ".git").exists()
        assert not (target / "untracked.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["sensitive", "symlink", "binary", "binary_nul", "lfs", "changed", "wrong_commit"])
async def test_derived_policy_rejects_unsafe_or_unfrozen_files_before_release(tmp_path, failure):
    root = tmp_path.resolve()
    files = {"main.py": b"synthetic\n"}
    if failure == "sensitive":
        files["secrets.yaml"] = b"refused\n"
    elif failure == "symlink":
        files["link.py"] = ("main.py",)
    elif failure == "binary":
        files["image.bin"] = b"\xff\x00"
    elif failure == "binary_nul":
        files["image.bin"] = b"otherwise valid utf8\x00"
    elif failure == "lfs":
        files["model.dat"] = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n"
    sources = {role: root / (role + "-source") for role in ("sut", "framework")}
    repositories = {role: {"commit_sha": git_checkout(path, files if role == "framework" else {"main.py": b"ok\n"})}
                    for role, path in sources.items()}
    if failure == "changed":
        (sources["framework"] / "main.py").write_text("changed")
    elif failure == "wrong_commit":
        repositories["framework"]["commit_sha"] = "0" * 40
    with pytest.raises(CloudBlocked):
        await derive_checkout_export(sources=sources, repositories=repositories)
