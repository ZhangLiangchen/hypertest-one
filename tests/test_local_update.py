"""One-command updater release selection and mutation boundaries, with synthetic files."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_updater", ROOT / "scripts/update-local.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
TAG = "local-v0.1.1-rc.2"
COMMIT = "a" * 40


def record(tag=TAG, **changes):
    row = {"target_id": "linux-x86_64-py313", "python": "3.13", "release_tag": tag,
        "source_commit": COMMIT, "distribution_state": "CANDIDATE", "bootstrap_sha256": "b" * 64,
        "manifest_sha256": "c" * 64, "bundle_sha256": "d" * 64,
        "bundle_url": f"{updater.REPOSITORY}/releases/download/{tag}/hypertest-{tag}-linux-x86_64-py313.zip"}
    return {**row, **changes}


def catalog(**changes):
    return {"schema_version": "hypertest.local-install-catalog/v1", "updater_protocol": updater.PROTOCOL,
            "targets": [record()], **changes}


def release(tag=TAG, **changes):
    return {"tag_name": tag, "draft": False, "prerelease": "-" in tag,
        "assets": [{"name": "local-install-catalog.json", "browser_download_url":
            f"{updater.REPOSITORY}/releases/download/{tag}/local-install-catalog.json"}], **changes}


def args(tmp_path, **changes):
    values = dict(harness="codex", channel="candidate", check=False, replace_source=False,
        install_root=tmp_path / "installation", directory=None, client_config=None, host_config=None,
        enable_hooks=False, skills_directory=None, dsh_home=None, profile=None)
    return argparse.Namespace(**{**values, **changes})


def receipt(tmp_path, version="local-v0.1.0"):
    return {"profile": "hypertest.local-install/v1", "host": "codex", "configuration": "WRITTEN",
        "version": version, "python": str(tmp_path / "old/bin/python"),
        "client_config": str(tmp_path / "private/client.json"), "host_config": str(tmp_path / "codex.toml")}


def mock_metadata(monkeypatch, body=None):
    monkeypatch.setattr(updater, "latest_release", lambda channel: release())
    monkeypatch.setattr(updater, "release_catalog", lambda selected: body or catalog())


def test_channel_ignores_cloud_tags_drafts_and_orders_semver_not_publication_date(monkeypatch):
    releases = [release("local-v0.1.0", prerelease=False), release("local-v0.1.1-rc.2"),
        release("local-v0.1.1-rc.10"), release("local-v9.0.0", draft=True),
        release("cloud-v99.0.0", prerelease=False), release("local-v0.1.2-rc.1", prerelease=False)]
    monkeypatch.setattr(updater, "fetch", lambda *args: json.dumps(releases).encode())
    assert updater.latest_release("stable")["tag_name"] == "local-v0.1.0"
    assert updater.latest_release("candidate")["tag_name"] == "local-v0.1.2-rc.1"


@pytest.mark.parametrize("changes", [{"bundle_url": "https://evil.invalid/payload.zip"},
    {"bootstrap_sha256": "tampered"}, {"release_tag": "local-v0.1.0"},
    {"python": "3.12"}, {"source_commit": "main"}])
def test_catalog_rejects_foreign_or_inconsistent_target_identity_before_download(monkeypatch, changes):
    body = catalog(targets=[record(**changes)])
    monkeypatch.setattr(updater, "fetch", lambda *args: json.dumps(body).encode())
    with pytest.raises(updater.UpdateBlocked, match="INVALID_RELEASE_CATALOG"):
        updater.release_catalog(release())


def test_catalog_uses_exact_published_asset_not_latest_redirect(monkeypatch):
    monkeypatch.setattr(updater, "fetch", lambda *args: pytest.fail("must reject before network"))
    with pytest.raises(updater.UpdateBlocked, match="RELEASE_CATALOG_MISSING"):
        updater.release_catalog(release(assets=[{"name": "local-install-catalog.json", "browser_download_url":
            updater.REPOSITORY + "/releases/latest/download/local-install-catalog.json"}]))


def test_check_reports_release_and_missing_python_without_creating_installation(tmp_path, monkeypatch):
    mock_metadata(monkeypatch)
    def missing(*unused):
        raise updater.UpdateBlocked("PYTHON_REQUIRED: install exact CPython")
    monkeypatch.setattr(updater, "select_target", missing)
    result = updater.update(args(tmp_path, check=True))
    assert result["status"] == "NOT_INSTALLED" and result["release_tag"] == TAG
    assert result["prerequisite"].startswith("PYTHON_REQUIRED")
    assert list(tmp_path.iterdir()) == []


def test_legacy_stable_check_reports_new_entry_limitation_and_never_executes(tmp_path, monkeypatch):
    mock_metadata(monkeypatch, catalog(updater_protocol=None))
    monkeypatch.setattr(updater, "select_target", lambda *args: (record(), sys.executable))
    result = updater.update(args(tmp_path, check=True))
    assert result["unified_update_supported"] is False
    assert result["action"].startswith("NEW_UPDATER_RELEASE_REQUIRED")
    with pytest.raises(updater.UpdateBlocked, match="NEW_UPDATER_RELEASE_REQUIRED"):
        updater.update(args(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_newer_published_installation_cannot_downgrade_even_candidate(tmp_path, monkeypatch):
    mock_metadata(monkeypatch)
    monkeypatch.setattr(updater, "private_receipt", lambda *args: receipt(tmp_path, "local-v0.2.0"))
    monkeypatch.setattr(updater, "fetch", lambda *args: pytest.fail("must not download a downgrade"))
    with pytest.raises(updater.UpdateBlocked, match="DOWNGRADE_BLOCKED"):
        updater.update(args(tmp_path))
    assert not (tmp_path / "installation").exists()


def test_full_commit_source_replacement_requires_explicit_candidate_opt_in(tmp_path):
    old = receipt(tmp_path, "local-v0.1.0-source." + "f" * 40)
    with pytest.raises(updater.UpdateBlocked, match="SOURCE_REPLACEMENT_REQUIRED"):
        updater.installed_comparison(old, TAG, channel="candidate")
    assert updater.installed_comparison(old, TAG, channel="candidate", replace_source=True) == "SOURCE_REPLACEMENT"
    assert updater.installed_comparison(old, TAG, check=True) == "SOURCE_REPLACEMENT_REQUIRED"
    with pytest.raises(updater.UpdateBlocked, match="SOURCE_REPLACEMENT_REQUIRED"):
        updater.installed_comparison(old, TAG, channel="stable", replace_source=True)
    with pytest.raises(updater.UpdateBlocked, match="UNKNOWN_INSTALLED_VERSION"):
        updater.installed_comparison(receipt(tmp_path, "my-custom-version"), TAG)
    with pytest.raises(updater.UpdateBlocked, match="SOURCE_REPLACEMENT_NOT_APPLICABLE"):
        updater.installed_comparison(receipt(tmp_path), TAG, channel="candidate", replace_source=True)


def test_legacy_receipt_is_bounded_private_and_symlinks_are_rejected(tmp_path):
    path = tmp_path / "installed-codex.json"
    body = receipt(tmp_path)
    path.write_text(json.dumps(body))
    path.chmod(0o600)
    assert updater.private_receipt(tmp_path, "codex") == body
    path.chmod(0o644)
    with pytest.raises(updater.UpdateBlocked, match="PRIVATE_RECEIPT_REQUIRED"):
        updater.private_receipt(tmp_path, "codex")
    path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(body))
    outside.chmod(0o600)
    path.symlink_to(outside)
    with pytest.raises(OSError):
        updater.private_receipt(tmp_path, "codex")


def test_exact_target_selection_probes_actual_available_interpreter(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "local_platform", lambda: ("linux", "x86_64"))
    monkeypatch.setattr(updater.shutil, "which", lambda name: "/selected/python3.13" if name == "python3.13" else None)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        identity = ["cpython", "3.13" if command[0] == "/selected/python3.13" else "3.11", "linux", "x86_64"]
        return subprocess.CompletedProcess(command, 0, json.dumps(identity))
    monkeypatch.setattr(updater.subprocess, "run", run)
    selected, executable = updater.select_target(catalog(), receipt(tmp_path))
    assert selected["target_id"] == "linux-x86_64-py313" and executable == "/selected/python3.13"
    assert all(command[1:3] == ["-I", "-c"] for command in calls)


def test_no_exact_target_fails_without_probing_or_creating_files(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "local_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not probe foreign target"))
    with pytest.raises(updater.UpdateBlocked, match="NO_PUBLISHED_TARGET"):
        updater.select_target(catalog(), None)
    assert list(tmp_path.iterdir()) == []


def test_upgrade_uses_owned_receipt_and_new_install_requires_existing_authorization(tmp_path):
    old = receipt(tmp_path)
    command = updater.bootstrap_command(args(tmp_path), record(), "python3.13", Path("/verified/bootstrap.py"),
        tmp_path / "runtime", tmp_path / "legacy-receipt", old)
    assert "--directory" in command and str(tmp_path / "legacy-receipt") in command
    assert "--client-config" not in command and "--enable-hooks" not in command
    with pytest.raises(updater.UpdateBlocked, match="AUTHORIZED_CLIENT_CONFIG_REQUIRED"):
        updater.bootstrap_command(args(tmp_path), record(), "python3.13", Path("/verified/bootstrap.py"),
            tmp_path / "runtime", tmp_path / "legacy-receipt", None)
    assert not (tmp_path / "runtime").exists()


def test_deepseek_and_skill_options_remain_in_same_install_command(tmp_path):
    client = tmp_path / "client.json"
    client.write_text("{}")
    options = args(tmp_path, harness="deepseek-harness", client_config=client, host_config=tmp_path / "dsh.json",
        dsh_home=tmp_path / "dsh", profile="existing-profile", skills_directory=tmp_path / "skills")
    command = updater.bootstrap_command(options, record(), "python3.13", Path("/verified/bootstrap.py"),
        tmp_path / "runtime", tmp_path / "receipt", None)
    assert all(value in command for value in ["--dsh-home", "--profile", "existing-profile", "--skills-directory"])


def test_tampered_bootstrap_is_not_executed_and_leaves_no_installation(tmp_path, monkeypatch):
    mock_metadata(monkeypatch)
    monkeypatch.setattr(updater, "private_receipt", lambda *args: receipt(tmp_path))
    monkeypatch.setattr(updater, "select_target", lambda *args: (record(), sys.executable))
    monkeypatch.setattr(updater, "fetch", lambda *args: b"tampered executable")
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: pytest.fail("never execute tampered bootstrap"))
    with pytest.raises(updater.UpdateBlocked, match="BOOTSTRAP_DIGEST_MISMATCH"):
        updater.update(args(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_success_executes_only_verified_bootstrap_and_parses_final_result(tmp_path, monkeypatch):
    raw = b"# verified updater fixture"
    row = record(bootstrap_sha256=hashlib.sha256(raw).hexdigest())
    mock_metadata(monkeypatch, catalog(targets=[row]))
    monkeypatch.setattr(updater, "private_receipt", lambda *args: receipt(tmp_path))
    monkeypatch.setattr(updater, "select_target", lambda *args: (row, sys.executable))
    monkeypatch.setattr(updater, "fetch", lambda *args: raw)
    def run(command, **kwargs):
        assert Path(command[2]).read_bytes() == raw
        assert command[1] == "-I" and "--allow-candidate" in command
        return subprocess.CompletedProcess(command, 0, '{}\ninstall output\n{"operation":"UPGRADED","private_state":"PRESERVED"}\n')
    monkeypatch.setattr(updater.subprocess, "run", run)
    result = updater.update(args(tmp_path))
    assert result["status"] == "UPGRADED"
    assert result["installation"]["private_state"] == "PRESERVED"
