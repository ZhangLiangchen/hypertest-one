"""Private client installer conserves host configuration and pending state."""
import hashlib
import json
import tomllib
from pathlib import Path
from uuid import uuid4

import pytest

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create
from hypertest.local_sync import installer
from hypertest.local_sync.manifest import artifact_read


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "probe_native_version", lambda host, executable=None: {
        "harness_version": "0.144.6" if host == "codex" else "2.1.218",
        "executable": "/verified/native-cli", "probe": "NATIVE_VERSION_COMMAND"})
    token = tmp_path / "integration-token"
    private_create(token, b"private-existing-token")
    client = tmp_path / "client.json"
    private_create(client, json.dumps({"api_url": "https://platform.invalid/api/v1",
        "state_dir": str(tmp_path / "state"), "integration_token_file": str(token)}).encode())
    host = tmp_path / "host.toml"
    host.write_text('# Existing user comment\nmodel = "existing"\n[mcp_servers.other]\ncommand = "other-server"\n')
    return {"directory": tmp_path / "installation", "host": "codex", "host_config": host,
            "client_config": client, "version": "local-v0.1.0", "python": Path("/explicit/python")}


def test_install_reinstall_upgrade_rollback_uninstall_preserve_user_entries_and_private_journal(installation):
    args = installation
    first = installer.install(**args)
    assert first["native_acceptance"] == "NOT_OBSERVED" and first["automatic_trigger"] == "DISABLED"
    installer.install(**args)
    state = json.loads(args["client_config"].read_text())["state_dir"]
    journal = Path(state) / "client.sqlite3"
    journal.write_bytes(b"unchanged pending ledger")
    journal.chmod(0o600)
    installer.install(**{**args, "version": "local-v0.2.0", "python": Path("/next/python")})
    # A user edit made after installation survives fragment-only rollback.
    with args["host_config"].open("a") as stream:
        stream.write('\n[unrelated]\nflag = true\n')
    result = installer.rollback(directory=args["directory"], host="codex")
    assert result["version"] == "local-v0.1.0"
    document = tomllib.loads(args["host_config"].read_text())
    assert document["mcp_servers"]["hypertest_local"]["command"] == "/explicit/python"
    assert document["mcp_servers"]["other"]["command"] == "other-server"
    assert document["unrelated"]["flag"]
    result = installer.uninstall(directory=args["directory"], host="codex")
    assert result["private_state"] == "PRESERVED"
    document = tomllib.loads(args["host_config"].read_text())
    assert "hypertest_local" not in document["mcp_servers"]
    assert document["unrelated"]["flag"] and journal.read_bytes() == b"unchanged pending ledger"
    installer.uninstall(directory=args["directory"], host="codex")
    installer.install(**args)


def test_one_host_cannot_overwrite_another_hosts_shared_private_configuration(installation):
    installer.install(**installation)
    original = installation["client_config"].read_bytes()
    with pytest.raises(ClientError, match="SEPARATE_HOST_CLIENT_CONFIGURATION_REQUIRED"):
        installer.install(**{**installation, "host": "claude-code",
                             "host_config": installation["directory"].parent / "claude.json"})
    assert installation["client_config"].read_bytes() == original


def test_owned_source_upgrade_preserves_hooks_policy_credentials_and_pending_files(installation):
    args = installation
    selected_config = json.loads(args["client_config"].read_text())
    selected_config["local_sync"] = {"project_id": str(uuid4())}
    args["client_config"].write_text(json.dumps(selected_config))
    workspace = args["directory"].parent / "approved-workspace"
    workspace.mkdir()
    hook_config = args["directory"].parent / "hooks.json"
    hook_config.write_text('{"hooks":{},"userSetting":"preserved"}')
    installer.install(**args, enable_hooks=True, hook_config=hook_config,
                      workspace=workspace, harness_version="0.144.6")
    original = json.loads(args["client_config"].read_text())
    state = Path(original["state_dir"])
    journal = state / "client.sqlite3"
    private_create(journal, b"frozen UNKNOWN request bytes")
    pending = state / "source-request.json"
    private_create(pending, b"complete original approved snapshot")
    result = installer.upgrade_owned(directory=args["directory"], host="codex",
        version="local-v0.1.0-source." + "a" * 40, python=Path("/private/candidate/python"))
    assert result["version"] == "local-v0.1.0-source." + "a" * 40
    assert result["reload_required"] is True
    current = json.loads(args["client_config"].read_text())
    assert current == original and current["local_sync"]["hooks_enabled"] is True
    assert journal.read_bytes() == b"frozen UNKNOWN request bytes"
    assert pending.read_bytes() == b"complete original approved snapshot"
    assert json.loads(hook_config.read_text())["userSetting"] == "preserved"
    host = tomllib.loads(args["host_config"].read_text())
    assert host["mcp_servers"]["hypertest_local"]["command"] == "/private/candidate/python"
    assert host["mcp_servers"]["other"]["command"] == "other-server"


@pytest.mark.parametrize("host", ["codex", "claude-code", "deepseek-harness"])
def test_each_host_uninstall_removes_only_its_owned_configuration(installation, host):
    args = {**installation, "host": host}
    if host == "claude-code":
        args["host_config"].write_text(json.dumps({"mcpServers": {"existing": {"command": "other"}},
                                                   "userSetting": True}))
    elif host == "deepseek-harness":
        home = args["directory"].parent / "dsh-home"
        profile = home / "profiles" / "selected"
        profile.mkdir(parents=True)
        (profile / "package.json").write_text('{"dsh":{"profile":{"bundles":[]}}}')
        args["host_config"] = profile / "cordis.patch.yml"
        args["host_config"].write_text('# Keep existing patch\n- insert:\n    - {"id":"other","name":"existing-plugin"}\n')
        args.update(dsh_home=home, profile="selected")
    original = args["host_config"].read_text()
    installer.install(**args)
    installer.uninstall(directory=args["directory"], host=host)
    actual = args["host_config"].read_text()
    if host == "claude-code":
        assert json.loads(actual) == json.loads(original)
    else:
        assert actual == original


def test_doctor_missing_state_directory_is_strictly_read_only(installation):
    installer.install(**installation)
    config = json.loads(installation["client_config"].read_text())
    Path(config["state_dir"]).rmdir()
    result = installer.doctor(directory=installation["directory"], host="codex")
    assert result["pending_state"] == "ABSENT"
    assert not Path(config["state_dir"]).exists()
    assert result["mcp"] == "RELOAD_AND_NATIVE_PROBE_REQUIRED"


def test_doctor_separates_written_receipt_from_observed_old_runtime(installation, monkeypatch):
    from hypertest.interactive_client import __main__ as entry
    installer.install(**installation)
    before = installation["client_config"].read_bytes()
    async def old_runtime(config):
        return {"state": "READY", "runtime": {"release_version": "local-v0.0.9"}}
    monkeypatch.setattr(entry, "observe_runtime", old_runtime)
    result = installer.doctor(directory=installation["directory"], host="codex")
    assert result["receipt_version"] == "local-v0.1.0"
    assert result["running_version"] == "local-v0.0.9"
    assert result["native_acceptance"] == "NOT_OBSERVED"
    assert installation["client_config"].read_bytes() == before


def test_doctor_blocks_overlong_darwin_socket_without_changing_state(installation, monkeypatch):
    installer.install(**installation)
    config = json.loads(installation["client_config"].read_text())
    state = installation["directory"].parent / ("native-state-" + "a" * 100)
    config["state_dir"] = str(state)
    installation["client_config"].write_text(json.dumps(config))
    before = installation["client_config"].read_bytes()
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    result = installer.doctor(directory=installation["directory"], host="codex")
    assert result["mcp"] == "BLOCKED" and result["mcp_code"] == "AF_UNIX_PATH_TOO_LONG"
    assert result["socket_path_bytes_including_nul"] > 104
    assert not state.exists() and installation["client_config"].read_bytes() == before


@pytest.mark.parametrize("value", ["false", "true", 1])
def test_string_or_numeric_config_flags_cannot_enable_automatic_sync(installation, value):
    from pydantic import ValidationError

    from hypertest.interactive_client.config import ClientConfig
    body = json.loads(installation["client_config"].read_text())
    body["local_sync"] = {"enabled": value}
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(body)


def test_uninstall_failure_rolls_back_all_owned_files_and_can_be_retried(installation, monkeypatch):
    installer.install(**installation)
    before_host = installation["host_config"].read_bytes()
    before_client = installation["client_config"].read_bytes()
    original = installer.atomic_write
    injected = False

    def fail_second(path, data):
        nonlocal injected
        if path == installation["client_config"] and not injected:
            injected = True
            raise OSError("injected disk failure")
        return original(path, data)

    monkeypatch.setattr(installer, "atomic_write", fail_second)
    with pytest.raises(OSError):
        installer.uninstall(directory=installation["directory"], host="codex")
    assert installation["host_config"].read_bytes() == before_host
    assert installation["client_config"].read_bytes() == before_client
    installer.uninstall(directory=installation["directory"], host="codex")


def test_interrupted_transaction_recovers_only_known_bytes_and_preserves_user_edits(installation):
    directory = installation["directory"]
    directory.mkdir(mode=0o700)
    transaction = directory / "backups" / "interrupted"
    transaction.mkdir(parents=True, mode=0o700)
    transaction.parent.chmod(0o700)
    target = installation["host_config"]
    before, after = target.read_bytes(), b'new_owned = true\n'
    private_create(transaction / "0.before", before)
    private_create(transaction / "transaction.json", json.dumps({"changes": [{"path": str(target),
        "existed": True, "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest()}]}).encode())
    target.write_bytes(after + b'user_edit = true\n')
    with pytest.raises(ClientError, match="INSTALL_RECOVERY_CONFLICT"):
        installer.recover_install(directory=directory)
    assert b"user_edit" in target.read_bytes()
    target.write_bytes(after)
    result = installer.recover_install(directory=directory)
    assert result["configuration"] == "RECOVERED" and target.read_bytes() == before


def test_manifest_file_open_rejects_parent_escape_symlink_and_transcript(installation):
    root = installation["directory"]
    root.mkdir(mode=0o700)
    outside = root.parent / "outside.md"
    outside.write_text("outside")
    with pytest.raises(ClientError, match="ARTIFACT_SOURCE_REJECTED"):
        artifact_read(root / ".." / "outside.md", [root])
    (root / "linked").symlink_to(root.parent, target_is_directory=True)
    with pytest.raises(ClientError, match="APPROVED_ARTIFACT_FILE_REJECTED"):
        artifact_read(root / "linked" / "outside.md", [root])
    with pytest.raises(ClientError, match="ONLY_APPROVED_MARKDOWN"):
        artifact_read(root / "rollout.jsonl", [root])
    (root / "transcript.md").write_text("must not be uploaded")
    with pytest.raises(ClientError, match="ARTIFACT_SOURCE_REJECTED"):
        artifact_read(root / "transcript.md", [root])
    valid = root / "analysis.md"
    valid.write_text("Approved testing analysis")
    assert artifact_read(valid, [root]) == b"Approved testing analysis"


def test_explicit_workspace_installs_automatic_source_without_manifest_or_session_id(installation):
    args = installation
    workspace = args["directory"].parent / "workspace"
    workspace.mkdir()
    client = json.loads(args["client_config"].read_text())
    client["local_sync"] = {"project_id": "00000000-0000-4000-8000-000000000001"}
    args["client_config"].write_text(json.dumps(client))
    hooks = workspace / "hooks.json"
    result = installer.install(**args, workspace=workspace, enable_hooks=True,
                               hook_config=hooks, harness_version="0.144.6")
    selected = json.loads(args["client_config"].read_text())["local_sync"]
    assert selected["artifact_source"]["workspace"] == str(workspace)
    assert selected["artifact_source"]["initial"]["status"] == "DRAFT"
    assert selected["artifact_source"]["initial"]["reported_result"] == "NOT_RUN"
    assert "manifest_file" not in selected and "session_id" not in json.dumps(selected)
    assert result["automatic_trigger"] == "CONFIGURED_UNACCEPTED"
    assert set(json.loads(hooks.read_text())["hooks"]) == {
        "SessionStart", "PostToolUse", "Stop", "SubagentStop"}
    installer.uninstall(directory=args["directory"], host="codex")
    assert not json.loads(args["client_config"].read_text())["local_sync"]["hooks_enabled"]
    assert json.loads(args["client_config"].read_text())["local_sync"]["artifact_source"] == selected["artifact_source"]


def test_automatic_hook_configuration_without_source_is_explicitly_blocked(installation):
    with pytest.raises(ClientError, match="EXPLICIT_HOOK_SOURCE_CONFIGURATION_REQUIRED"):
        installer.install(**installation, hook_config=installation["directory"].parent / "hooks.json",
                          enable_hooks=True, harness_version="0.144.6")
    assert not installation["directory"].exists()


def test_native_version_declaration_must_match_real_probe_before_hook_install(installation):
    with pytest.raises(ClientError, match="LOCAL_DECLARED_HOST_VERSION_MISMATCH"):
        installer.install(**installation, hook_config=installation["directory"].parent / "hooks.json",
                          enable_hooks=True, harness_version="0.100.0")
    assert not installation["directory"].exists()


def test_deepseek_declared_version_must_match_verified_bridge_package(installation, monkeypatch):
    from hypertest.local_sync import deepseek_bridge

    workspace = installation["directory"].parent / "workspace"
    workspace.mkdir()
    home = installation["directory"].parent / "dsh-home"
    profile = home / "profiles" / "selected"
    profile.mkdir(parents=True)
    (profile / "package.json").write_text('{"dsh":{"profile":{"bundles":["official-base"]}}}')
    monkeypatch.setattr(deepseek_bridge, "root_bridge_descriptor", lambda **kwargs: {
        "id": "hypertest-local-hook-bridge", "name": "/verified/root-bridge.mjs",
        "config": {"harnessVersion": "0.1.5-rc.1"}})
    args = {**installation, "host": "deepseek-harness", "host_config": profile / "cordis.patch.yml"}
    with pytest.raises(ClientError, match="LOCAL_DECLARED_HOST_VERSION_MISMATCH"):
        installer.install(**args, dsh_home=home, profile="selected", workspace=workspace,
                          enable_hooks=True, harness_version="0.1.4", event_bridge="native-root")
    assert not installation["directory"].exists()


def test_approved_artifact_strategy_is_private_and_preserves_explicit_business_fields(installation):
    workspace = installation["directory"].parent / "workspace"
    workspace.mkdir()
    strategy = installation["directory"].parent / "strategy.json"
    private_create(strategy, json.dumps({"workspace": str(workspace),
        "initial": {"title": "Explicit title", "objective": "Explicit objective", "status": "BLOCKED",
                    "plan_markdown": "", "reported_result": "FAIL"},
        "artifacts": [{"kind": "TEST_PLAN", "path": "analysis.md"}]}).encode())
    installer.install(**installation, artifact_source=strategy)
    selected = json.loads(installation["client_config"].read_text())["local_sync"]["artifact_source"]
    assert selected["initial"]["status"] == "BLOCKED" and selected["initial"]["reported_result"] == "FAIL"
    strategy.chmod(0o644)
    with pytest.raises(ClientError, match="PRIVATE_FILE_REQUIRED"):
        installer.install(**installation, artifact_source=strategy)
