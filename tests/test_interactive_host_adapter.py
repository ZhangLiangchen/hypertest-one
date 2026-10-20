"""Local identity fails closed; immutable source is checked beyond Git status."""
import json
import os
import subprocess
from uuid import uuid4

import pytest

from hypertest.interactive_client import host_adapter as host


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


@pytest.fixture
def observed_host(tmp_path, monkeypatch):
    native, run_id, node, transfer = [str(uuid4()) for _ in range(4)]
    home = tmp_path / "codex"
    logs = home / "sessions"
    logs.mkdir(parents=True)
    (logs / f"rollout-{native}.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {
        "id": native, "originator": "Codex Desktop", "cli_version": "test", "cwd": str(tmp_path)}}) + "\n")
    binary = tmp_path / "codex-executable"
    binary.touch()
    monkeypatch.setenv("CODEX_THREAD_ID", native)
    monkeypatch.setenv("CODEX_SESSION_ID", native)
    monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
    monkeypatch.setenv("CODEX_CLI_PATH", str(binary))
    # Simulated ps observations exercise policy; live E2E uses actual host ps.
    def process(pid):
        if pid == 91001:
            return 1, "host-birth", str(binary)
        if pid == 91002:
            return 91001, "stdio-birth", "/usr/bin/python3"
        return 91001, "daemon-birth", "/usr/bin/python3"
    monkeypatch.setattr(host, "_process", process)
    workspace = tmp_path / "sut"
    workspace.mkdir()
    git(workspace, "init", "-q")
    git(workspace, "config", "user.email", "test@example.invalid")
    git(workspace, "config", "user.name", "Host test")
    git(workspace, "remote", "add", "origin", "https://example.invalid/test/sut")
    (workspace / "app.py").write_text("answer = 42\n")
    git(workspace, "add", "app.py")
    git(workspace, "commit", "-qm", "fixture")
    config = {"host_adapter": {"kind": "codex-desktop-stdio", "codex_home": str(home)},
              "workspaces": {run_id: {"path": str(workspace), "workspace_id": str(uuid4()),
                  "commit_sha": git(workspace, "rev-parse", "HEAD"),
                  "origin": "https://example.invalid/test/sut", "source_bundle_transfer_id": transfer}}}
    return config, run_id, node, transfer, workspace


@pytest.mark.asyncio
async def test_real_identity_is_immutable_and_source_tamper_cannot_hide_in_git_index(observed_host):
    config, run_id, node, transfer, workspace = observed_host
    adapter = host.make_host_adapter(config)
    await adapter.assert_peer(91002)
    with pytest.raises(host.HostAdapterError, match="HOST_STDIO_PEER_CHANGED"):
        await adapter.assert_peer(91003)
    proof = await adapter.attest(project_id=str(uuid4()), run_id=run_id, node_id=node,
                                 source_transfer_id=transfer, workspace=workspace)
    assert proof["native_session_id"] == os.environ["CODEX_THREAD_ID"]
    with pytest.raises(host.HostAdapterError, match="HOST_ATTACHMENT_IDENTITY_MISMATCH"):
        await adapter.assert_live({**proof, "native_session_id": str(uuid4())})
    git(workspace, "update-index", "--assume-unchanged", "app.py")
    (workspace / "app.py").write_text("answer = 0\n")
    assert git(workspace, "status", "--porcelain") == ""
    with pytest.raises(host.HostAdapterError, match="HOST_PINNED_SOURCE_MISMATCH"):
        await adapter.assert_live(proof)


@pytest.mark.asyncio
async def test_model_session_or_unrelated_process_cannot_bind(observed_host, monkeypatch):
    config, run_id, node, transfer, workspace = observed_host
    adapter = host.make_host_adapter(config)
    monkeypatch.setattr(host, "_process", lambda pid: (1, "other-birth", "/bin/sh"))
    with pytest.raises(host.HostAdapterError, match="HOST_STDIO_PEER_REJECTED"):
        await adapter.assert_peer(91002)
    monkeypatch.setenv("CODEX_SESSION_ID", str(uuid4()))
    unsupported = host.make_host_adapter(config)
    assert unsupported.capabilities()["interactive_execution"] is False
    with pytest.raises(host.HostAdapterError):
        await unsupported.attest(project_id=str(uuid4()), run_id=run_id, node_id=node,
                                  source_transfer_id=transfer, workspace=workspace)
