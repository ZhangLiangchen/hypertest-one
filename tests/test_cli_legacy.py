"""Owned-fragment removal without touching unrelated configuration."""
import json
import os

import pytest

from hypertest.cli import legacy
from hypertest.cli.state import CLIError
from hypertest.sync_core import canonical_json


def private(path, content):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else canonical_json(content).encode())
    path.chmod(0o600)
    return path


def installation(tmp_path, host):
    directory = tmp_path / "install"
    directory.mkdir(mode=0o700)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    token = private(tmp_path / "token", b"private-legacy-token")
    journal = private(state / "client.sqlite3", b"original-pending-journal")
    source = private(tmp_path / "report.md", b"# FAIL\noriginal source\n")
    client = private(tmp_path / "client.json", {"api_url": "https://archive.example/api/v1",
        "state_dir": str(state), "integration_token_file": str(token), "local_sync": {"enabled": True, "hooks_enabled": True}})
    group = {"hooks": [{"type": "command", "command": "/private/hypertest-local hook", "timeout": 15}]}
    other = {"hooks": [{"type": "command", "command": "unrelated-tool", "timeout": 15}]}
    hooks = private(tmp_path / "hooks.json", {"hooks": {"Stop": [group, other]}, "unrelated": "preserve"})
    if host == "claude-code":
        entry = {"command": "/private/python", "args": ["-m", "hypertest.interactive_client", "stdio"]}
        config = private(tmp_path / "host.json", {"mcpServers": {"hypertest-local": entry, "other": {"command": "other"}}, "permission": True})
        owned = {"entry": entry}
    else:
        body = ('[mcp_servers.hypertest_local]\ncommand = "/private/python"\n' if host == "codex"
            else '- insert:\n    - {"id":"hypertest-local-mcp"}\n    - {"id":"hypertest-local-hook-bridge"}\n')
        block = legacy.BEGIN + body + legacy.END
        config = private(tmp_path / "host.conf", ("# Unrelated comment\n" + block).encode())
        owned = {"block": block}
    receipt = private(directory / f"installed-{host}.json", {"profile": "hypertest.local-install/v1", "host": host,
        "configuration": "WRITTEN", "host_config": str(config), "hook_config": str(hooks),
        "client_config": str(client), "python": "/private/python", "owned": owned,
        "hooks_owned": {"groups": {"Stop": group}}, "version": "local-v0.1.1-rc.2"})
    return {"directory": directory, "state": state, "token": token, "journal": journal, "source": source,
        "client": client, "host": config, "hooks": hooks, "receipt": receipt, "other": other}


@pytest.mark.parametrize("host", ["codex", "claude-code", "deepseek-harness"])
async def test_retire_preserves_unowned_configuration_and_all_private_history(tmp_path, host):
    f = installation(tmp_path, host)
    before = {name: f[name].read_bytes() for name in ("token", "journal", "source")}
    result, code = legacy.retire(str(f["directory"]), host)
    assert code == 0 and result["status"] == "RETIRED" and result["runtime"] == "NOT_RUNNING"
    assert "hypertest-local" not in f["host"].read_text() and "hypertest_local" not in f["host"].read_text()
    if host == "claude-code":
        host_config = json.loads(f["host"].read_text())
        assert host_config["mcpServers"]["other"] == {"command": "other"} and host_config["permission"]
    else:
        assert f["host"].read_text() == "# Unrelated comment\n"
    assert json.loads(f["hooks"].read_text()) == {"hooks": {"Stop": [f["other"]]}, "unrelated": "preserve"}
    assert json.loads(f["client"].read_text())["local_sync"] == {"enabled": False, "hooks_enabled": False}
    assert {name: f[name].read_bytes() for name in before} == before
    assert len(list((f["directory"] / "legacy-retire").glob("*/committed.json"))) == 1
    assert legacy.retire(str(f["directory"]), host)[0]["status"] == "RETIRED"


@pytest.mark.parametrize("changed", ["host", "hooks"])
async def test_drift_rejects_before_runtime_stop_or_partial_configuration_write(tmp_path, monkeypatch, changed):
    f = installation(tmp_path, "codex")
    if changed == "host":
        f["host"].write_text(f["host"].read_text().replace('/private/python', '/user/custom/python'))
    else:
        f["hooks"].write_text(f["hooks"].read_text().replace('hypertest-local hook', 'user-modified-command'))
    before = {name: f[name].read_bytes() for name in ("host", "hooks", "client", "receipt")}
    monkeypatch.setattr(legacy, "_stop_owned", lambda *args: pytest.fail("drift must be rejected before stopping"))
    with pytest.raises(CLIError, match="PRESERVED"):
        legacy.retire(str(f["directory"]), "codex")
    assert {name: f[name].read_bytes() for name in before} == before


async def test_runtime_requires_authenticated_identity_and_never_signals_pid(tmp_path, monkeypatch):
    f = installation(tmp_path, "codex")
    calls = []

    def foreign(config, operation):
        calls.append(operation)
        return {"runtime": {"profile": "another-service", "python": "/private/python"}, "pid": os.getpid()}

    monkeypatch.setattr(legacy, "_rpc", foreign)
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("must not signal arbitrary process"))
    with pytest.raises(CLIError, match="IDENTITY_MISMATCH"):
        legacy.retire(str(f["directory"]), "codex")
    assert calls == ["runtime-info"]
    assert json.loads(f["receipt"].read_text())["configuration"] == "WRITTEN"


async def test_runtime_from_another_configuration_is_preserved(tmp_path, monkeypatch):
    f = installation(tmp_path, "codex")
    calls = []

    def different_configuration(config, operation):
        calls.append(operation)
        return {"runtime": {"profile": "hypertest.local-runtime/v1", "python": "/private/python",
            "runtime_sha256": "a" * 64, "configuration_sha256": "b" * 64}, "state": "READY"}

    monkeypatch.setattr(legacy, "_rpc", different_configuration)
    with pytest.raises(CLIError, match="IDENTITY_MISMATCH"):
        legacy.retire(str(f["directory"]), "codex")
    assert calls == ["runtime-info"]
    assert json.loads(f["receipt"].read_text())["configuration"] == "WRITTEN"


def test_cli_retains_cleanup_and_rejects_retired_session_reconcile():
    from hypertest.cli.__main__ import parser

    for command in ("retire", "cleanup"):
        args = parser().parse_args(["legacy", command, "--directory", "/tmp/owned", "--host", "codex"])
        assert args.action == command
    with pytest.raises(SystemExit):
        parser().parse_args(["legacy", "reconcile", "--config", "/tmp/client.json", "--request-id", "original"])
