"""Local acceptance configuration validation; never contacts or writes GitLab."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parents[1] / "scripts" / "adr015_live_cycle.py"
spec = importlib.util.spec_from_file_location("adr015_live_driver", DRIVER)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def approved_config():
    return {"base_url": "https://gitlab.example.invalid", "project_id": 1,
        "assignee": "approved-developer", "assignee_id": 1, "integration_id": "approved-acceptance"}


def save_config(tmp_path, config, *, mode=0o600):
    path = tmp_path / "gitlab-acceptance.json"
    path.write_text(json.dumps(config))
    path.chmod(mode)
    return path


def test_local_target_requires_private_file_and_contains_no_credential_fields(tmp_path):
    path = save_config(tmp_path, approved_config())
    assert driver.load_gitlab_config(path) == approved_config()
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private 0600"):
        driver.load_gitlab_config(path)
    path.chmod(0o600)
    link = tmp_path / "alias.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="private 0600"):
        driver.load_gitlab_config(link)


@pytest.mark.parametrize("changes", [
    {"base_url": "http://gitlab.example.invalid"}, {"base_url": "https://user:FAKE_SECRET@example.invalid"},
    {"base_url": 42}, {"assignee": "name\ninjected instruction"}, {"project_id": True},
    {"token": "FAKE_SECRET"}, {"arbitrary_endpoint": "/admin"},
])
def test_target_configuration_cannot_include_secrets_or_expand_scope(tmp_path, changes):
    path = save_config(tmp_path, {**approved_config(), **changes})
    with pytest.raises(ValueError) as raised:
        driver.load_gitlab_config(path)
    assert "FAKE_SECRET" not in str(raised.value)


def test_cli_requires_explicit_local_target_before_starting_any_services(tmp_path):
    state = tmp_path / "must-not-be-created"
    result = subprocess.run([sys.executable, str(DRIVER), "--state-dir", str(state),
        "--database-url", "postgresql+asyncpg://example.invalid/disposable", "--broken", "--gitlab-test-issue"],
        capture_output=True, text=True, check=False)
    assert result.returncode == 2 and "--gitlab-config" in result.stderr
    assert not state.exists()
    help_result = subprocess.run([sys.executable, str(DRIVER), "--help"], capture_output=True, text=True, check=False)
    assert help_result.returncode == 0 and "--gitlab-config" in help_result.stdout


def test_public_acceptance_evidence_retains_fixture_proof_without_private_target_metadata():
    evidence_path = DRIVER.parents[1] / "docs" / "evidence" / "adr015-20261019.json"
    evidence = json.loads(evidence_path.read_text())
    assert evidence["public_evidence_redacted"] is True
    assert evidence["private_source"]["status"] == "ACCEPTED"
    assert not {"origin", "commit_sha", "root_tree", "bundle_sha256", "project_id", "node_id"} & evidence["private_source"].keys()
    assert all(evidence[name]["reports"][0]["content_sha256"] for name in ("positive", "negative"))
    assert all(evidence[name]["executions"][0]["source_commit"] for name in ("positive", "negative"))
    assert not {"iid", "project_id", "web_url", "assignees"} & evidence["gitlab_independent_read"].keys()
    assert evidence["gitlab_independent_read"]["matching_issue_count"] == 1
