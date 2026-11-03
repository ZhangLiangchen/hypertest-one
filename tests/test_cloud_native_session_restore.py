import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from hypertest.cloud import native_session_restore as restore
from hypertest.cloud.errors import CloudBlocked


def _profile(home):
    root = home / "profiles" / "sdk"
    root.mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({
        "name": "dsh-profile-sdk", "private": True, "dependencies": {},
        "dsh": {"profile": {"bundles": list(restore._BASE)}},
    }))
    (root / "cordis.patch.yml").write_text("[]\n")


def _overlay(directory, *, title):
    (directory / "hypertest-cordis-root.mjs").write_text(restore._HOOK)
    path = directory / "overlay.yml"
    path.write_text("- id: example\n")
    return path


def test_inspection_overlay_disables_execution_and_redirects_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(restore, "prepare_cordis_overlay", _overlay)
    path = restore._prepare_inspection_overlay(tmp_path)
    rows = yaml.safe_load(path.read_text())
    disabled = {r["id"] for r in rows if r.get("disabled") is True}
    assert set(restore._DISABLED_FOR_INSPECTION) <= disabled
    creds = next(r["config"] for r in rows if r["id"] == "credentials")
    assert Path(creds["path"]).parent == tmp_path
    assert Path(creds["path"]).read_text() == "{}\n"
    assert Path(creds["path"]).stat().st_mode & 0o777 == 0o600
    assert creds["watch"] is False
    hook = (tmp_path / "hypertest-cordis-root.mjs").read_text()
    assert hook.index("return; // retain the original persisted preset") < hook.index('await ctx.agentPresets.select')
    assert hook.index("return; // retain the original persisted preset") < hook.index('ctx.sessionTitle.rename')


def test_unknown_profile_or_dotenv_never_starts_sdk(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _profile(home)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    identity = {"workspace": workspace, "dsh_home": home, "session_id": "cloud-synthetic",
                "selection": {"provider": "deepseek-official", "model": "deepseek-flash"}}
    monkeypatch.setattr(restore, "verify_original_identity", lambda *a, **kw: {})
    monkeypatch.setattr(restore, "read_native_selection", lambda **kw: pytest.fail("SDK must not start"))
    (home / ".env").write_text("DO_NOT_READ=1\n")
    with pytest.raises(CloudBlocked):
        restore._inspect_in_child(attempt_root=tmp_path, expected_identity_digest="test", identity=identity)
    (home / ".env").unlink()
    (home / "profiles/sdk/unreviewed-plugin.mjs").write_text("// not trusted\n")
    with pytest.raises(CloudBlocked):
        restore._inspect_in_child(attempt_root=tmp_path, expected_identity_digest="test", identity=identity)


def test_original_anchor_is_checked_before_any_sdk_work(tmp_path, monkeypatch):
    def rejected(*args, **kwargs):
        raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "No original receipt")
    monkeypatch.setattr(restore, "verify_original_identity", rejected)
    monkeypatch.setattr(restore, "_check_inspection_profile", lambda *a: pytest.fail("unanchored session touched"))
    with pytest.raises(CloudBlocked) as error:
        restore._inspect_in_child(attempt_root=tmp_path, expected_identity_digest="x", identity={})
    assert error.value.code == "NATIVE_SESSION_IDENTITY_UNAVAILABLE"


def test_same_original_session_restores_without_prompt_and_rejects_escape(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _profile(home)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    child_dir = workspace / "child"
    child_dir.mkdir()
    identity = {"workspace": workspace, "dsh_home": home, "session_id": "cloud-synthetic",
                "selection": {"provider": "deepseek-official", "model": "deepseek-flash"}}
    calls = []
    sdk = ModuleType("deepseek_harness")

    class Config:
        def __init__(self, **values): self.values = values

    class Client:
        cwd = child_dir
        def __init__(self, config): self.env = config.values["env"]
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def initialize(self, **values):
            calls.append(("initialize", values))
            Path(self.env["DSH_SDK_CORDIS_HANDSHAKE"]).write_text(json.dumps({
                "phase": "registered", "nonce": self.env["DSH_SDK_CORDIS_NONCE"],
                "root": self.env["DSH_SDK_CORDIS_ROOT"]}))
            return SimpleNamespace(serverInfo=SimpleNamespace(name="deepseek-harness-sdk-runtime", version="0.0.1"))
        def resume_session(self, session_id): calls.append(("resume", session_id))
        def get_working_directory(self, session_id): return str(self.cwd)
        def session_prompt(self, *args, **kwargs): pytest.fail("original prompt must never be sent")

    sdk.HarnessConfig, sdk.HarnessClient = Config, Client
    monkeypatch.setitem(sys.modules, "deepseek_harness", sdk)
    monkeypatch.setattr(restore, "verify_original_identity", lambda *a, **kw: {})
    monkeypatch.setattr(restore, "read_native_selection", lambda **kw: identity["selection"])
    monkeypatch.setattr(restore, "prepare_cordis_overlay", _overlay)
    result = restore._inspect_in_child(attempt_root=tmp_path, expected_identity_digest="test", identity=identity)
    assert result == {"session_id": "cloud-synthetic", "restored": True, "prompt_sent": False,
                      "continuation_started": False}
    assert [call[0] for call in calls] == ["initialize", "resume"]
    Client.cwd = tmp_path
    with pytest.raises(CloudBlocked):
        restore._inspect_in_child(attempt_root=tmp_path, expected_identity_digest="test", identity=identity)


def test_child_ipc_strips_secrets_and_process_environment(tmp_path, monkeypatch):
    class FakeProcess:
        returncode = 0
        pid = 123
        def __init__(self, command, **kwargs):
            assert kwargs["env"]["PATH"] == "/usr/bin:/bin"
            assert not ({"WORKER_TOKEN", "DEEPSEEK_API_KEY", "SSH_AUTH_SOCK", "GITLAB_TOKEN"} & kwargs["env"].keys())
        def communicate(self, payload=None, timeout=None):
            data = json.loads(payload)
            assert data["identity"]["environment"] == {"PATH": "/usr/bin:/bin"}
            result = {"session_id": "cloud-synthetic", "restored": True, "prompt_sent": False,
                      "continuation_started": False}
            return json.dumps(result).encode(), b""

    monkeypatch.setattr(restore.subprocess, "Popen", FakeProcess)
    for key in ("WORKER_TOKEN", "DEEPSEEK_API_KEY", "SSH_AUTH_SOCK", "GITLAB_TOKEN"):
        monkeypatch.setenv(key, "must-not-leak")
    identity = {"workspace": tmp_path, "dsh_home": tmp_path, "session_id": "cloud-synthetic",
                "environment": {"PATH": "/usr/bin:/bin", "DEEPSEEK_API_KEY": "must-not-leak"},
                "project_id": "p", "task_id": "t", "attempt_id": "a", "input_digest": "b" * 64,
                "prompt_sha256": "c" * 64, "title_sha256": "f" * 64,
                "sut_commit": "d" * 40, "framework_commit": "e" * 40,
                "selection": {"provider": "deepseek-official", "model": "deepseek-flash"},
                "worker_id": "synthetic", "original_generation": 1}
    assert restore.inspect_original_session(attempt_root=tmp_path, expected_identity_digest="a" * 64,
                                            identity=identity)["restored"]
