"""Installation upgrades preserve patched releases and private archive state."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "scripts/install-cli-release.py"


def artifact(tmp_path: Path, version: str) -> Path:
    path = tmp_path / f"hypertest-cli-{version}.pyz"
    with zipfile.ZipFile(path, "w") as bundle:
        # Synthetic version-only fixture, never a release or an upload client.
        bundle.writestr("__main__.py", f"print('hypertest {version}')\n")
    return path


def install(tmp_path: Path, path: Path, version: str, *, sha256: str | None = None):
    return subprocess.run(
        [sys.executable, "-I", str(INSTALLER), "--artifact", str(path), "--version", version,
         "--sha256", sha256 or hashlib.sha256(path.read_bytes()).hexdigest(),
         "--bin-dir", str(tmp_path / "bin"), "--install-dir", str(tmp_path / "installed")],
        env={**os.environ, "HYPERTEST_CLI_HOME": str(tmp_path / "private-state")},
        capture_output=True, text=True,
    )


@pytest.fixture
def patched_install(tmp_path: Path):
    old_artifact = artifact(tmp_path, "0.1.0")
    result = install(tmp_path, old_artifact, "0.1.0")
    assert result.returncode == 0, result.stderr
    old_release = tmp_path / "installed/releases/0.1.0/hypertest.pyz"
    backup = old_release.with_name("hypertest.pyz.before-stable-key-fix-20261027")
    backup.write_bytes(old_release.read_bytes())
    # Match the reported local patch: the managed launcher is intact, the old
    # bundle's bytes differ from its historical installation receipt.
    with zipfile.ZipFile(old_release, "a") as bundle:
        bundle.writestr("local-stable-key-fix.txt", "temporary local fix\n")
    state = tmp_path / "private-state"
    preserved = [old_release, backup]
    for relative in ("profiles/hypertest-one.json", "receipts/accepted.json", "journal/pending.json"):
        path = state / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fixture": relative, "request_id": "original-request"}))
        preserved.append(path)
    return {path: path.read_bytes() for path in preserved}


def test_upgrade_preserves_patched_old_bundle_backup_and_private_state(tmp_path, patched_install):
    new_artifact = artifact(tmp_path, "0.1.1")
    result = install(tmp_path, new_artifact, "0.1.1")
    assert result.returncode == 0, result.stderr
    command = tmp_path / "bin/hypertest"
    assert subprocess.check_output([str(command), "--version"], text=True).strip() == "hypertest 0.1.1"
    installed = tmp_path / "installed/releases/0.1.1/hypertest.pyz"
    assert installed.read_bytes() == new_artifact.read_bytes()
    receipt = json.loads((tmp_path / "installed/installation.json").read_text())
    assert receipt["version"] == "0.1.1"
    assert receipt["release"] == str(installed)
    assert receipt["artifact_sha256"] == hashlib.sha256(new_artifact.read_bytes()).hexdigest()
    assert receipt["command_sha256"] == hashlib.sha256(command.read_bytes()).hexdigest()
    for path, original in patched_install.items():
        assert path.read_bytes() == original


@pytest.mark.parametrize("conflict", ["download_digest", "modified_target_version"])
def test_invalid_upgrade_preserves_launcher_receipt_and_history(tmp_path, patched_install, conflict):
    new_artifact = artifact(tmp_path, "0.1.1")
    command = tmp_path / "bin/hypertest"
    receipt = tmp_path / "installed/installation.json"
    preserved = {**patched_install, command: command.read_bytes(), receipt: receipt.read_bytes()}
    options = {}
    if conflict == "download_digest":
        options["sha256"] = "0" * 64
    else:
        target = tmp_path / "installed/releases/0.1.1/hypertest.pyz"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"pre-existing local modifications")
        preserved[target] = target.read_bytes()
    result = install(tmp_path, new_artifact, "0.1.1", **options)
    assert result.returncode == 2
    expected = "artifact SHA256 mismatch" if conflict == "download_digest" else "version already exists with different bytes"
    assert expected in result.stderr
    for path, original in preserved.items():
        assert path.read_bytes() == original
