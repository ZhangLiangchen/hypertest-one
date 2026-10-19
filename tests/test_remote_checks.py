"""Exercise the real remote shell dispatch without SSH, containers or a database."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ("hypertest-api", "hypertest-worker", "hypertest-web", "nginx")
CONTAINER = ("hypertest-container-stack", "hypertest-harness-bridge")


@pytest.fixture
def remote_check(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands.jsonl"
    marker = tmp_path / "deployment-mode"
    operations = tmp_path / "ops-current"
    # Only redirect the remote marker path; run the checked-in shell unchanged.
    stub = "#!" + sys.executable + "\n" + '''
import json, os, pathlib, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CHECK_LOG"], "a") as target:
    target.write(json.dumps([name, *args]) + "\\n")
if name == "ssh":
    expected = ["-T", "-o", "BatchMode=yes", "-o", "PreferredAuthentications=publickey",
                "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15", "-o",
                "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", "hypertest-one", "bash -se"]
    assert args == expected
    script = sys.stdin.read().replace("/etc/hypertest/deployment-mode", os.environ["CHECK_MARKER"])
    script = script.replace("/opt/hypertest/ops-current", os.environ["CHECK_OPERATIONS"])
    raise SystemExit(subprocess.run(["bash", "-se"], input=script, text=True).returncode)
if name == "systemctl":
    assert args[0] == "is-active"
    state = json.loads(os.environ["CHECK_UNITS"])[args[-1]]
    if "--quiet" not in args:
        print(state)
    raise SystemExit(0 if state == "active" else 3)
if name == "docker":
    assert args[1] == "hypertest-postgres"
    print("true healthy" if args[0] == "inspect" else "1")
elif name == "python3":
    if args == ["-"]:
        assert "get_json" in sys.stdin.read()
    else:
        prefix = os.environ["CHECK_OPERATIONS"] if pathlib.Path(os.environ["CHECK_OPERATIONS"]).exists() else "/opt/hypertest/container-current"
        assert args == [prefix + "/ops/container/readiness.py",
                        "--env", "/etc/hypertest/container/compose.env"]
        raise SystemExit(int(os.environ.get("CHECK_READINESS_EXIT", "0")))
elif name == "readlink":
    assert args[0] == "-f"
    print(args[1])
elif name == "date":
    assert args == ["-Is"]
    print("2026-10-19T00:00:00+00:00")
'''
    for name in ("ssh", "systemctl", "docker", "python3", "readlink", "date"):
        path = commands / name
        path.write_text(stub)
        path.chmod(0o755)

    def run(mode, *, unit_states=None, readiness_exit=0, operations_state="absent"):
        if mode is not None:
            marker.write_text(mode + "\n")
        if operations_state == "ready":
            readiness = operations / "ops/container/readiness.py"
            readiness.parent.mkdir(parents=True)
            readiness.write_text("# protected release fixture\n")
        elif operations_state == "incomplete":
            operations.mkdir()
        elif operations_state == "dangling":
            operations.symlink_to(tmp_path / "missing-operations")
        container = mode == "container-v1"
        states = {unit: "inactive" if container else "active" for unit in LEGACY}
        states.update({unit: "active" for unit in CONTAINER})
        states.update(unit_states or {})
        result = subprocess.run(
            ["bash", str(ROOT / "ops/check-remote.sh")], capture_output=True, text=True,
            env={**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                 "CHECK_LOG": str(log), "CHECK_MARKER": str(marker),
                 "CHECK_OPERATIONS": str(operations),
                 "CHECK_UNITS": json.dumps(states), "CHECK_READINESS_EXIT": str(readiness_exit)},
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls

    return run


@pytest.mark.parametrize("mode", [None, "legacy"])
def test_remote_check_preserves_legacy_mode(remote_check, mode):
    result, calls = remote_check(mode)
    assert result.returncode == 0, result.stderr
    assert [call for call in calls if call[0] == "docker"]
    assert ["python3", "-"] in calls
    assert not any("readiness.py" in " ".join(call) for call in calls)


def test_remote_check_uses_container_readiness_and_preserves_ssh_policy(remote_check):
    result, calls = remote_check("container-v1")
    assert result.returncode == 0, result.stderr
    assert ["python3", "/opt/hypertest/container-current/ops/container/readiness.py",
            "--env", "/etc/hypertest/container/compose.env"] in calls
    assert not any(call[0] == "docker" or call == ["python3", "-"] for call in calls)


def test_remote_check_prefers_the_explicit_operations_release(remote_check):
    result, calls = remote_check("container-v1", operations_state="ready")
    assert result.returncode == 0, result.stderr
    python_calls = [call for call in calls if call[0] == "python3"]
    assert len(python_calls) == 1 and "/ops-current/ops/container/readiness.py" in python_calls[0][1]
    assert not any("container-current/ops/container/readiness.py" in " ".join(call) for call in calls)


@pytest.mark.parametrize("state", ["incomplete", "dangling"])
def test_remote_check_never_falls_back_from_a_broken_operations_release(remote_check, state):
    result, calls = remote_check("container-v1", operations_state=state)
    assert result.returncode != 0
    assert "operations release is incomplete" in result.stderr
    assert not any(call[0] in {"python3", "docker", "systemctl"} for call in calls)


@pytest.mark.parametrize("unit", [*CONTAINER, *LEGACY])
def test_remote_container_unit_failure_cannot_fall_back_to_legacy(remote_check, unit):
    state = "inactive" if unit in CONTAINER else "active"
    result, calls = remote_check("container-v1", unit_states={unit: state})
    assert result.returncode != 0
    assert not any(call[0] in {"docker", "python3"} for call in calls)


def test_remote_container_readiness_failure_cannot_fall_back_to_legacy(remote_check):
    result, calls = remote_check("container-v1", readiness_exit=17)
    assert result.returncode == 17
    assert not any(call[0] == "docker" or call == ["python3", "-"] for call in calls)
    assert "health checks passed" not in result.stdout


@pytest.mark.parametrize("mode", ["", "container-v2"])
def test_remote_check_unknown_marker_fails_closed(remote_check, mode):
    result, calls = remote_check(mode)
    assert result.returncode != 0
    assert "Unknown HyperTest deployment mode" in result.stderr
    assert not any(call[0] in {"systemctl", "docker", "python3"} for call in calls)
