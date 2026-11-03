import asyncio
import json
import subprocess
import sys

import pytest

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.native_sdk_adapter import NativeSdkAdapter, host_environment


def test_host_environment_excludes_platform_credentials():
    result = host_environment({"HOME": "/users/a", "PATH": "/bin", "SSH_AUTH_SOCK": "/tmp/sock",
                               "HYPERTEST_WORKER_TOKEN": "secret", "DATABASE_URL": "secret",
                               "DEEPSEEK_API_KEY": "native-model", "GH_TOKEN": "native-git"})
    assert {key: value for key, value in result.items() if key != "PYTHONPATH"} == {
        "HOME": "/users/a", "PATH": "/bin", "SSH_AUTH_SOCK": "/tmp/sock",
        "DEEPSEEK_API_KEY": "native-model", "GH_TOKEN": "native-git"}


def test_driver_imports_fixed_package_from_unrelated_workspace_without_model(tmp_path):
    import os

    env = host_environment({**os.environ, "PYTHONPATH": "/untrusted"})
    assert env["PYTHONPATH"] != "/untrusted"
    result = subprocess.run([sys.executable, "-P", "-m", "hypertest.cloud.native_sdk_driver"],
        input="{}", text=True, cwd=tmp_path, env=env, capture_output=True, timeout=10)
    assert result.returncode == 1
    assert '"code":"SDK_RUN_FAILED"' in result.stdout
    assert not result.stderr


@pytest.mark.asyncio
async def test_start_once_and_stop_reports_unproven_descendants(tmp_path, monkeypatch):
    class Input:
        def write(self, value):
            self.value = value
        async def drain(self):
            pass
        def close(self):
            pass
        def is_closing(self):
            return False
    class Process:
        pid = 1234
        returncode = None
        stdin = Input()
        async def wait(self):
            self.returncode = 0
    child = Process()
    seen = {}
    async def spawn(*args, **kwargs):
        seen.update(kwargs)
        return child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr("hypertest.cloud.native_sdk_adapter.os.killpg", lambda *_: None)
    adapter = NativeSdkAdapter(workspace=tmp_path, dsh_home=tmp_path)
    await adapter.start(session_id="cloud-test", prompt="test",
                        resume_identity={"attempt_root": str(tmp_path), "digest": "a" * 64, "original": {}})
    assert seen["start_new_session"] is True
    assert "HYPERTEST_WORKER_TOKEN" not in seen["env"]
    assert json.loads(child.stdin.value)["resume_identity"]["digest"] == "a" * 64
    with pytest.raises(CloudBlocked, match="cannot be started twice"):
        await adapter.start(session_id="cloud-test", prompt="test")
    result = await adapter.stop()
    assert result == {"direct_process_stopped": True, "all_local_processes_stopped": None,
                      "external_operations_reconciled": None}
