"""The production driver validates locally without making business requests."""
import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adr015_online_cycle", ROOT / "scripts/adr015_online_cycle.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_dry_run_cannot_contact_platform_create_state_or_expose_operator_key(tmp_path, monkeypatch, capsys):
    key = tmp_path / "operator.key"
    key.write_text("test-secret-not-for-output")
    key.chmod(0o600)
    state = tmp_path / "new-state"
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    def forbidden(*args, **kwargs):
        pytest.fail("--dry-run must never contact the platform")

    monkeypatch.setattr(driver.API, "request", forbidden)
    monkeypatch.setattr(driver.shutil, "which", lambda _: "/fixture/codex")
    assert driver.main(["--api-url", "https://operator-ingress.example.invalid/api/v1",
        "--operator-key-file", str(key), "--commit-sha", commit, "--state-dir", str(state),
        "--connector-state-dir", "/private/tmp/ht15-test-" + uuid4().hex, "--dry-run"]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["acceptance_status"] == "LOCAL_VALIDATION_PASSED_NO_NETWORK"
    assert "operator-ingress" not in output and key.read_text() not in output
    assert result["commit_sha"] == commit and result["prd_sha256"]
    assert not state.exists()


def test_long_default_socket_path_is_rejected_before_platform_access(tmp_path, monkeypatch, capsys):
    key = tmp_path / "operator.key"
    key.write_text("private-key-not-for-output")
    key.chmod(0o600)
    state = tmp_path / ("evidence-directory-" + "x" * 90)

    def forbidden(*args, **kwargs):
        pytest.fail("socket preflight must run before any platform request")

    monkeypatch.setattr(driver.API, "request", forbidden)
    assert driver.main(["--api-url", "https://example.invalid/api/v1", "--operator-key-file", str(key),
        "--commit-sha", "a" * 40, "--state-dir", str(state)]) == 1
    assert "CONNECTOR_SOCKET_PATH_TOO_LONG_USE_CONNECTOR_STATE_DIR" in capsys.readouterr().err
    assert not state.exists()


def test_explicit_runtime_directory_must_not_reuse_existing_or_symlink_path(tmp_path):
    state = tmp_path / "new-evidence"
    with pytest.raises(driver.AcceptanceError, match="NEW_AND_CANONICAL"):
        driver.connector_state_path(state, tmp_path)
    symlink = tmp_path / "dangling"
    symlink.symlink_to(tmp_path / "absent")
    with pytest.raises(driver.AcceptanceError, match="NEW_AND_CANONICAL"):
        driver.connector_state_path(state, symlink)


@pytest.mark.parametrize("value", ["http://example.invalid/api/v1", "https://user:secret@example.invalid/api/v1",
    "https://example.invalid/api/v1?token=secret", "https://example.invalid/api/v1#fragment",
    "https://example.invalid/api/v1/../api/v1", "https://example.invalid/api/v1\n"])
def test_api_argument_cannot_weaken_tls_or_embed_credentials(value):
    with pytest.raises(argparse.ArgumentTypeError):
        driver.https_api(value)


def test_operator_key_requires_owned_regular_0600_file(tmp_path):
    key = tmp_path / "key"
    key.write_bytes(b"private-value")
    key.chmod(0o644)
    with pytest.raises(driver.AcceptanceError, match="0600"):
        driver.private_file(key)
    key.chmod(0o600)
    assert driver.private_file(key) == b"private-value"
    alias = tmp_path / "symlink"
    alias.symlink_to(key)
    with pytest.raises(OSError):
        driver.private_file(alias)


def test_device_environment_preserves_native_auth_without_platform_secrets(monkeypatch):
    monkeypatch.setenv("HYPERTEST_CONNECTOR_OPERATOR_KEY", "secret-admin")
    monkeypatch.setenv("HYPERTEST_DATABASE_URL", "secret-db")
    monkeypatch.setenv("DATABASE_URL", "secret-db")
    monkeypatch.setenv("PGPASSWORD", "secret-password")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/private/authorized-git-agent.sock")
    result = driver.connector_environment(ROOT)
    assert result["SSH_AUTH_SOCK"] == "/private/authorized-git-agent.sock"
    assert not any(key.startswith("HYPERTEST_") for key in result)
    assert "PGPASSWORD" not in result and "DATABASE_URL" not in result


def test_collector_requires_runner_evidence_exact_node_and_verified_final_report():
    content = b"Accepted report from the real Runner facts\n"
    responses = {"harness": {"selection": {"mode": "LOCAL_CONNECTOR", "node_id": "node"},
        "binding": {"id": "binding", "status": "CLOSED", "binding_epoch": 1}, "issues": [],
        "reports": [{"id": "report", "content_sha256": driver.sha256(content), "verdict_key": "verdict", "verdict_decision": "RELEASE_READY"}]},
        "executions": [{"id": "execution", "runner_backend": "docker", "status": "COMPLETED", "outcome": "PASS", "source_commit": "a" * 40}],
        "evidence": [{"id": "evidence", "status": "VERIFIED", "trust_level": "RUNNER", "execution_id": "execution"}],
        "verdicts": [{"key": "verdict", "scope": "TEST_RUN", "status": "FINAL", "decision": "RELEASE_READY"}],
        "content": content}

    class FakeAPI:
        def request(self, path, **kwargs):
            return responses[path.rsplit("/", 1)[-1]]

    summary = {"run_id": "run", "node_id": "node", "job_status": "SUCCEEDED", "commit_sha": "a" * 40}
    driver.collect(FakeAPI(), summary)
    assert summary["report_content_verified"]
    responses["content"] = b"Changed report bytes"
    with pytest.raises(driver.AcceptanceError, match="HASH_MISMATCH"):
        driver.collect(FakeAPI(), summary)
    responses["content"] = content
    responses["evidence"][0]["trust_level"] = "AGENT_REPORTED"
    with pytest.raises(driver.AcceptanceError, match="VERIFIED_RUNNER_EVIDENCE_MISSING"):
        driver.collect(FakeAPI(), summary)
