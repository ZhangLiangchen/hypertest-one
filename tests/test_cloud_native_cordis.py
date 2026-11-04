import hashlib
import sys
from types import SimpleNamespace

import pytest
import yaml

from hypertest.cloud import native_cordis
from hypertest.cloud.errors import CloudBlocked


@pytest.mark.parametrize("with_transport", [False, True])
def test_overlay_uses_pinned_official_preset_and_empty_environment(tmp_path, monkeypatch, with_transport):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"pinned runtime")
    monkeypatch.setattr(native_cordis, "_RUNTIME_SHA256", hashlib.sha256(runtime.read_bytes()).hexdigest())
    monkeypatch.setitem(sys.modules, "deepseek_harness_runtime", SimpleNamespace(resolve_bundled_launch_args=lambda: (str(runtime),)))
    observed = {}

    def dump(command, **kwargs):
        observed.update(command=command, **kwargs)
        return SimpleNamespace(stdout=b"- id: preset-cordis\n  name: '@deepseek-ai/dsh-agent-preset'\n  config:\n    id: cordis\n    expression: !!js 'process.platform === \"win32\"'\n")

    monkeypatch.setattr(native_cordis.subprocess, "run", dump)
    monkeypatch.setenv("CLOUD_TEST_SECRET", "not-for-child")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    workspace = tmp_path.resolve() / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / ".hypertest-cloud").mkdir(mode=0o700)
    policy = {"mode": native_cordis._Expression("process.env.DSH_PERMISSION_MODE ?? 'workspace-write'"),
              "workspaceRoot": native_cordis._Expression("process.cwd()"),
              "additionalWritableRoots": ["/previously-authorized"]}
    kwargs = {"workspace": workspace, "sandbox_policy": policy} if with_transport else {}
    result = native_cordis.prepare_cordis_overlay(private, title="任务标题", **kwargs)
    data = yaml.load(result.read_bytes(), Loader=native_cordis._Loader)
    inserted = data[-1]["insert"]
    preset = next(item for item in inserted if item["id"] == "preset-cordis")
    assert isinstance(preset["config"]["expression"], native_cordis._Expression)
    assert next(item for item in inserted if item["id"] == "hypertest-cordis-root")["name"] == str(private / "hypertest-cordis-root.mjs")
    assert next(item for item in inserted if item["id"] == "hypertest-cordis-root")["config"] == {"title": "任务标题"}
    assert "CLOUD_TEST_SECRET" not in observed["env"]
    assert "--dump-default-config" in observed["command"]
    assert observed["env"]["HOME"] == observed["env"]["DSH_HOME"]
    assert result.stat().st_mode & 0o777 == 0o600
    assert (private / "hypertest-cordis-root.mjs").stat().st_mode & 0o777 == 0o600
    policies = [row for row in data if row.get("id") == "sandbox-policy"]
    if with_transport:
        assert len(policies) == 1
        expected = {**policy, "additionalWritableRoots": ["/previously-authorized", str(workspace / ".hypertest-cloud")]}
        assert policies[0] == {"id": "sandbox-policy", "name": "@deepseek-ai/dsh-sandbox-policy", "config": expected}
        assert isinstance(policies[0]["config"]["mode"], native_cordis._Expression)
        assert isinstance(policies[0]["config"]["workspaceRoot"], native_cordis._Expression)
        assert policy["additionalWritableRoots"] == ["/previously-authorized"]
    else:
        assert policies == []


@pytest.mark.parametrize("unsafe", ["missing", "file", "symlink", "ancestor_symlink", "not_private", "wrong_owner", "relative"])
def test_transport_grant_rejects_unsafe_directory(tmp_path, monkeypatch, unsafe):
    workspace = tmp_path.resolve() / "workspace"
    workspace.mkdir(mode=0o700)
    transport = workspace / ".hypertest-cloud"
    if unsafe == "file":
        transport.write_text("not a directory")
    elif unsafe == "symlink":
        transport.symlink_to(tmp_path, target_is_directory=True)
    elif unsafe != "missing":
        transport.mkdir(mode=0o700)
    if unsafe == "ancestor_symlink":
        link = tmp_path / "linked-parent"
        link.symlink_to(tmp_path, target_is_directory=True)
        workspace = link / "workspace"
    if unsafe == "not_private":
        workspace.chmod(0o755)
    if unsafe == "wrong_owner":
        monkeypatch.setattr(native_cordis.os, "getuid", lambda: transport.stat().st_uid + 1)
    if unsafe == "relative":
        workspace = workspace.relative_to(workspace.anchor)
    with pytest.raises((ValueError, OSError)):
        native_cordis._transport_policy(workspace, {"mode": "workspace-write"})


def test_transport_grant_tightens_owned_legacy_directory_without_changing_contents(tmp_path):
    workspace = tmp_path.resolve()
    transport = workspace / ".hypertest-cloud"
    transport.mkdir(mode=0o755)
    transport.chmod(0o755)
    receipt = transport / "accepted.json"
    receipt.write_bytes(b'{"status":"ACCEPTED"}')
    before = (receipt.read_bytes(), receipt.stat().st_mode)
    policy = native_cordis._transport_policy(workspace, {"mode": "workspace-write"})
    assert transport.stat().st_mode & 0o777 == 0o700
    assert (receipt.read_bytes(), receipt.stat().st_mode) == before
    assert policy["additionalWritableRoots"] == [str(transport)]
    assert native_cordis._transport_policy(workspace, policy) == policy


def test_transport_grant_preserves_read_only_and_deduplicates_existing_grant(tmp_path):
    workspace = tmp_path.resolve()
    transport = workspace / ".hypertest-cloud"
    transport.mkdir(mode=0o700)
    policy = {"mode": "read-only", "additionalWritableRoots": [str(transport)]}
    assert native_cordis._transport_policy(workspace, policy) == policy


def test_overlay_rejects_runtime_drift_before_running_it(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"unapproved version")
    monkeypatch.setitem(sys.modules, "deepseek_harness_runtime", SimpleNamespace(resolve_bundled_launch_args=lambda: (str(runtime),)))
    monkeypatch.setattr(native_cordis.subprocess, "run", lambda *args, **kwargs: pytest.fail("unapproved runtime launched"))
    with pytest.raises(CloudBlocked) as error:
        native_cordis.prepare_cordis_overlay(tmp_path, title="任务标题")
    assert error.value.code == "HARNESS_CORDIS_UNAVAILABLE"
    assert not (tmp_path / "hypertest-cordis-overlay.yml").exists()


def test_overlay_rejects_missing_official_preset(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"pinned")
    monkeypatch.setattr(native_cordis, "_RUNTIME_SHA256", hashlib.sha256(runtime.read_bytes()).hexdigest())
    monkeypatch.setitem(sys.modules, "deepseek_harness_runtime", SimpleNamespace(resolve_bundled_launch_args=lambda: (str(runtime),)))
    monkeypatch.setattr(native_cordis.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"[]"))
    with pytest.raises(CloudBlocked) as error:
        native_cordis.prepare_cordis_overlay(tmp_path, title="任务标题")
    assert error.value.code == "HARNESS_CORDIS_UNAVAILABLE"
