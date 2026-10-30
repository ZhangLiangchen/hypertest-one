"""Only frozen, scanned file bytes cross the Worker-to-Agent boundary."""
import hashlib
from uuid import uuid4

import pytest
from fastapi import HTTPException

from hypertest.api.cloud_schemas import TaskInputs
from hypertest.application.cloud_tasks import _reject_secrets
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.source_export import PROFILE, export_sources, validate_export


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
