"""Immutable, non-secret native-session identity and legacy rejection."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from hypertest.cloud import native_resume_identity as identity
from hypertest.cloud.errors import CloudBlocked

_REAL_RUNTIME_IDENTITY = identity._runtime_identity


@pytest.fixture
def original(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "attempt"
    root.mkdir(mode=0o700)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    commits = []
    for name in ("sut", "framework"):
        repo = workspace / name
        repo.mkdir()
        env = {**os.environ, "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
               "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
        subprocess.run(["git", "-C", str(repo), "init", "-q"], env=env, check=True)
        (repo / "source.txt").write_text(name)
        subprocess.run(["git", "-C", str(repo), "add", "source.txt"], env=env, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], env=env, check=True)
        commits.append(subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip())
    home = tmp_path.resolve() / "dsh"
    profile = home / "profiles" / "sdk"
    profile.mkdir(parents=True)
    (profile / "package.json").write_text(json.dumps({"name": "dsh-profile-sdk", "private": True,
        "dependencies": {}, "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-sdk-app"]}}}))
    (profile / "cordis.patch.yml").write_text("[]\n")
    (home / ".credentials.yaml").write_text("NEVER_READ_OR_STORE_THIS_TEST_SECRET")
    monkeypatch.setattr(identity, "_runtime_identity", lambda: {
        "sdk_version": "fixture-1", "runtime_sha256": "a" * 64,
        "driver_sha256": "b" * 64, "cordis_adapter_sha256": "c" * 64})
    values = {"project_id": "018f0000-0000-7000-8000-000000000001",
              "task_id": "018f0000-0000-7000-8000-000000000002",
              "attempt_id": "018f0000-0000-7000-8000-000000000003",
              "session_id": "cloud-018f0000-0000-7000-8000-000000000003",
              "worker_id": "native-fixture", "original_generation": 1,
              "input_digest": "d" * 64, "prompt_sha256": "e" * 64, "title_sha256": "f" * 64,
              "workspace": workspace, "dsh_home": home,
              "sut_commit": commits[0], "framework_commit": commits[1],
              "selection": {"provider": "deepseek-official", "model": "deepseek-flash", "reasoning_effort": "max"},
              "environment": {"PATH": "/usr/bin:/bin", "DSH_PERMISSION_MODE": "workspace-write",
                              "DEEPSEEK_API_KEY": "SECRET_NOT_IN_IDENTITY"}}
    return root, values


def test_original_snapshot_is_anchored_non_secret_and_create_once(original):
    root, values = original
    anchor = identity.record_initial_identity(root, **values)
    raw = (root / identity.FILENAME).read_text()
    record = json.loads(raw)
    assert record["profile"] == identity.PROFILE
    assert record["session_id"] == values["session_id"]
    assert record["title_sha256"] == values["title_sha256"]
    assert record["source"] == {"sut": values["sut_commit"], "framework": values["framework_commit"]}
    assert "NEVER_READ_OR_STORE_THIS_TEST_SECRET" not in raw
    assert "SECRET_NOT_IN_IDENTITY" not in raw
    assert str(values["workspace"]) not in raw and str(values["dsh_home"]) not in raw
    assert identity.verify_original_identity(root, expected_identity_digest=anchor, **values) == record
    assert (root / identity.FILENAME).stat().st_mode & 0o777 == 0o600
    # Authentication rotation is outside the scoped profile fingerprint.
    (values["dsh_home"] / ".credentials.yaml").write_text("rotated")
    values["environment"]["DEEPSEEK_API_KEY"] = "rotated-token"
    assert identity.verify_original_identity(root, expected_identity_digest=anchor, **values) == record
    with pytest.raises(CloudBlocked):
        identity.record_initial_identity(root, **values)
    assert (root / identity.FILENAME).read_text() == raw


@pytest.mark.parametrize("change", ["missing", "wrong_anchor", "bad_record", "bad_session", "input", "title", "profile", "source", "runtime", "workspace", "unsafe_mode", "selection", "permission", "generation"])
def test_recovery_rejects_missing_tampered_or_drifted_original(original, monkeypatch, change):
    root, values = original
    anchor = identity.record_initial_identity(root, **values)
    path = root / identity.FILENAME
    if change == "missing":
        path.unlink()
    elif change == "wrong_anchor":
        anchor = "f" * 64
    elif change == "bad_record":
        path.write_text("{}")
    elif change == "bad_session":
        values["session_id"] = "cloud-different"
    elif change == "input":
        values["input_digest"] = "f" * 64
    elif change == "title":
        values["title_sha256"] = "0" * 64
    elif change == "profile":
        (values["dsh_home"] / "profiles/sdk/cordis.patch.yml").write_text("- changed\n")
    elif change == "source":
        values["sut_commit"] = "0" * 40
    elif change == "runtime":
        monkeypatch.setattr(identity, "_runtime_identity", lambda: {"sdk_version": "other"})
    elif change == "workspace":
        values["workspace"].rename(root / "original-workspace")
        values["workspace"].mkdir()
    elif change == "unsafe_mode":
        path.chmod(0o644)
    elif change == "selection":
        values["selection"]["reasoning_effort"] = "low"
    elif change == "permission":
        values["environment"]["DSH_PERMISSION_MODE"] = "danger-full-access"
    elif change == "generation":
        values["original_generation"] = 2
    with pytest.raises(CloudBlocked) as error:
        identity.verify_original_identity(root, expected_identity_digest=anchor, **values)
    assert error.value.code == "NATIVE_SESSION_IDENTITY_UNAVAILABLE"
    if change == "missing":
        assert not path.exists(), "recovery must not create historical identity"


def test_recovery_refuses_unanchored_legacy_record(original):
    root, values = original
    with pytest.raises(CloudBlocked):
        identity.verify_original_identity(root, expected_identity_digest="", **values)
    assert not (root / identity.FILENAME).exists()


def test_sdk_source_drift_is_rejected_even_when_package_version_is_unchanged(original, tmp_path, monkeypatch):
    root, values = original
    package = tmp_path.resolve() / "sdk-package"
    package.mkdir()
    for name in identity._SDK_SOURCE_FILES:
        (package / name).write_text("ORIGINAL = True\n")
    runtime = tmp_path.resolve() / "runtime"
    runtime.write_bytes(b"fixed runtime")
    monkeypatch.setitem(sys.modules, "deepseek_harness_runtime",
                        SimpleNamespace(resolve_bundled_launch_args=lambda: (str(runtime),)))
    monkeypatch.setattr(identity, "version", lambda name: "0.2.2a2")
    monkeypatch.setattr(identity, "_sdk_package_root", lambda: package)
    monkeypatch.setattr(identity, "_runtime_identity", _REAL_RUNTIME_IDENTITY)
    anchor = identity.record_initial_identity(root, **values)
    saved = json.loads((root / identity.FILENAME).read_text())
    assert saved["runtime"]["sdk_version"] == "0.2.2a2"
    assert len(saved["runtime"]["sdk_package_sha256"]) == 64
    (package / "client.py").write_text("ORIGINAL = False\n")
    with pytest.raises(CloudBlocked):
        identity.verify_original_identity(root, expected_identity_digest=anchor, **values)


def test_unreviewed_sdk_package_file_is_not_read(tmp_path, monkeypatch):
    package = tmp_path.resolve() / "sdk-package"
    package.mkdir()
    for name in identity._SDK_SOURCE_FILES:
        (package / name).write_text("# reviewed source\n")
    secret = package / "configuration.json"
    secret.write_text("HIDDEN_TOKEN_MUST_NOT_BE_READ")
    read = identity._stable_file

    def checked_read(path):
        assert path != secret, "unreviewed SDK package file must not be read"
        return read(path)

    monkeypatch.setattr(identity, "_stable_file", checked_read)
    with pytest.raises(ValueError, match="unreviewed SDK package"):
        identity._sdk_package_digest(package)


def test_escaping_profile_symlink_and_credential_file_are_refused(original, tmp_path):
    root, values = original
    profile = values["dsh_home"] / "profiles/sdk"
    (profile / "escape").symlink_to(tmp_path.resolve())
    with pytest.raises(CloudBlocked):
        identity.record_initial_identity(root, **values)
    (profile / "escape").unlink()
    (profile / ".npmrc").write_text("should-never-be-read")
    with pytest.raises(CloudBlocked):
        identity.record_initial_identity(root, **values)
    assert not (root / identity.FILENAME).exists()


def test_unknown_profile_file_is_not_opened_or_hashed(original, monkeypatch):
    root, values = original
    secret = b"HIDDEN_TOKEN_MUST_NOT_BE_READ"
    path = values["dsh_home"] / "profiles/sdk" / "appearance.json"
    path.write_bytes(secret)
    reader = identity._read_small_profile_file
    hasher = identity._sha

    def checked_read(candidate):
        assert candidate != path, "unreviewed profile file must not be read"
        return reader(candidate)

    def checked_sha(value):
        assert secret not in value, "unreviewed profile content must not be hashed"
        return hasher(value)

    monkeypatch.setattr(identity, "_read_small_profile_file", checked_read)
    monkeypatch.setattr(identity, "_sha", checked_sha)
    with pytest.raises(CloudBlocked):
        identity.record_initial_identity(root, **values)
    assert not (root / identity.FILENAME).exists()


@pytest.mark.parametrize("target", ["package", "patch"])
def test_hidden_token_in_reviewed_config_is_rejected_before_hashing(original, monkeypatch, target):
    root, values = original
    profile = values["dsh_home"] / "profiles/sdk"
    secret = "TOKEN_HIDDEN_IN_CONFIG"
    if target == "package":
        package = json.loads((profile / "package.json").read_text())
        package["telemetry"] = {"access_token": secret}
        (profile / "package.json").write_text(json.dumps(package))
    else:
        (profile / "cordis.patch.yml").write_text(
            "- id: agent-default-model\n  config:\n    provider: deepseek-official\n"
            "    model: deepseek-flash\n    access_token: " + secret + "\n")
    hasher = identity._sha

    def checked_sha(value):
        assert secret.encode() not in value, "unknown config must not be hashed"
        return hasher(value)

    monkeypatch.setattr(identity, "_sha", checked_sha)
    with pytest.raises(CloudBlocked):
        identity.record_initial_identity(root, **values)
    assert not (root / identity.FILENAME).exists()
