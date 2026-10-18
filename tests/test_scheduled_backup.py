"""Maintenance sequencing and error recovery, without live services or PostgreSQL."""
from __future__ import annotations

import fcntl
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("postgres", "api", "worker", "web", "nginx")


@pytest.fixture
def scheduled(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "ops/container"))
    spec = importlib.util.spec_from_file_location("hypertest_scheduled_backup", ROOT / "ops/container/scheduled_backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events = []
    flags = {"busy": False, "backup_error": False, "readiness_error": False, "bridge_stop_error": False,
             "api_start_error": False, "api_health_error": False}
    state = {"hypertest-container-stack": "active", "hypertest-harness-bridge": "active"}
    dependencies = {"Requires": "docker.service", "BindsTo": "docker.service", "PartOf": "",
                    "Wants": "hypertest-harness-bridge.service"}

    def inspect(command, **kwargs):
        if "--property=ActiveState" in command:
            return state[command[2]]
        return "\n".join(f"{key}={value}" for key, value in dependencies.items())

    def command(args, **kwargs):
        events.append(tuple(args))
        if args[:2] == ["systemctl", "stop"]:
            if flags["bridge_stop_error"]:
                raise subprocess.CalledProcessError(1, args)
            state[args[2]] = "inactive"
        elif args[:2] == ["systemctl", "start"]:
            state[args[2]] = "active"
        return subprocess.CompletedProcess(args, 0)

    def compose(env, *args, **kwargs):
        events.append(("compose", *args))
        if args == ("start", "api") and flags["api_start_error"]:
            raise subprocess.CalledProcessError(1, ["compose", *args])

    def start(env, roles):
        events.append(("guarded-start", *roles))

    def check(env, bridge_service):
        events.append(("readiness",))
        if flags["readiness_error"] and events.count(("readiness",)) > 1:
            raise ValueError("restored readiness failed")

    def wait_healthy(*args):
        events.append(("api-healthy",))
        if flags["api_health_error"]:
            raise ValueError("API health failed")

    def backup(env, values, target, bridge_state, bridge_service):
        assert state[bridge_service] == "inactive"
        events.append(("backup",))
        target.mkdir()
        (target / "database.dump").write_bytes(b"preserved-partial-or-complete")
        if flags["backup_error"]:
            raise OSError("dump failed")
        (target / "COMPLETE").write_text("manifest-digest")

    module.subprocess = SimpleNamespace(check_output=inspect, run=command)
    module.backup = SimpleNamespace(compose=compose, backup=backup)
    module.start = SimpleNamespace(ROLES=ROLES, start=start, verify_daemon=lambda: "same-daemon",
                                  wait_healthy=wait_healthy)
    module.readiness = SimpleNamespace(check=check)
    module.read_env = lambda env: {}
    module.validate = lambda *args, **kwargs: None
    module.guard = lambda values: {"protected": True}
    module.compose_command = lambda env, *args: ["compose", *args]
    module.active_requests = lambda env: flags["busy"]
    bridge_state = tmp_path / "bridge-state"
    bridge_state.mkdir()
    args = (tmp_path / "compose.env", tmp_path / "backups", bridge_state,
            "hypertest-container-stack", "hypertest-harness-bridge")
    return module, events, flags, state, dependencies, args


def test_scheduled_backup_busy_only_restores_api_without_interrupting_worker(scheduled):
    module, events, flags, _, _, args = scheduled
    flags["busy"] = True
    result = module.snapshot(*args)
    assert result["status"] == "skipped" and result["backup_created"] is False
    assert events == [("readiness",), ("compose", "stop", "api"),
                      ("compose", "start", "api"), ("api-healthy",)]
    assert not args[1].exists()


@pytest.mark.parametrize("failure", ["api_start_error", "api_health_error"])
def test_busy_backup_api_restore_failure_keeps_worker_postgres_and_bridge(scheduled, failure):
    module, events, flags, state, _, args = scheduled
    flags.update(busy=True, **{failure: True})
    with pytest.raises((subprocess.CalledProcessError, ValueError)):
        module.snapshot(*args)
    assert events[-1] == ("compose", "stop", "api", "nginx")
    assert ("compose", "stop", *ROLES) not in events
    assert not any(event[0] in {"guarded-start", "systemctl", "backup"} for event in events)
    assert state["hypertest-harness-bridge"] == "active"
    assert not args[1].exists()


@pytest.mark.parametrize("failure", ["guard-removed", "guard-inspection-failed", "daemon-changed"])
def test_busy_backup_unsafe_or_unknown_ingress_stops_all_roles(scheduled, failure):
    module, events, flags, _, _, args = scheduled
    flags["busy"] = True
    if failure == "daemon-changed":
        module.start.verify_daemon = lambda: "new-daemon" if ("compose", "stop", "api") in events else "same-daemon"
    elif failure == "guard-removed":
        module.guard = lambda values: {"protected": False}
    else:
        def unavailable(values):
            raise OSError("cannot verify guard")
        module.guard = unavailable
    with pytest.raises((ValueError, OSError)):
        module.snapshot(*args)
    assert events[-1] == ("compose", "stop", *ROLES)
    assert ("compose", "start", "api") not in events
    assert not args[1].exists()


def test_scheduled_backup_stops_provider_then_uses_guard_for_db_and_restore(scheduled):
    module, events, _, _, _, args = scheduled
    result = module.snapshot(*args)
    assert result["status"] == "complete"
    assert (Path(result["backup"]) / "COMPLETE").exists()
    assert events == [
        ("readiness",), ("compose", "stop", "api"), ("compose", "stop", *ROLES),
        ("systemctl", "stop", "hypertest-harness-bridge"), ("guarded-start", "postgres"),
        ("backup",), ("systemctl", "start", "hypertest-harness-bridge"),
        ("guarded-start", *ROLES), ("readiness",),
    ]


def test_scheduled_backup_failure_preserves_partial_files_and_restores_services(scheduled):
    module, events, flags, state, _, args = scheduled
    flags["backup_error"] = True
    with pytest.raises(OSError, match="dump failed"):
        module.snapshot(*args)
    assert list(args[1].glob("*/database.dump"))
    assert not list(args[1].glob("*/COMPLETE"))
    assert state[args[4]] == "active"
    assert events[-2:] == [("guarded-start", *ROLES), ("readiness",)]


def test_scheduled_backup_restore_failure_stops_listeners_and_never_reports_success(scheduled):
    module, events, flags, _, _, args = scheduled
    flags["readiness_error"] = True
    with pytest.raises(ValueError, match="restored readiness failed"):
        module.snapshot(*args)
    assert list(args[1].glob("*/COMPLETE"))
    assert events[-1] == ("compose", "stop", *ROLES)


def test_scheduled_backup_bridge_stop_failure_cannot_copy_live_state(scheduled):
    module, events, flags, _, _, args = scheduled
    flags["bridge_stop_error"] = True
    with pytest.raises(subprocess.CalledProcessError):
        module.snapshot(*args)
    assert ("backup",) not in events
    assert events[-2:] == [("guarded-start", *ROLES), ("readiness",)]


@pytest.mark.parametrize("dependency", ["Requires", "BindsTo", "PartOf"])
def test_scheduled_backup_rejects_bridge_stop_propagation_before_touching_services(scheduled, dependency):
    module, events, _, _, dependencies, args = scheduled
    dependencies[dependency] += " hypertest-harness-bridge.service"
    with pytest.raises(ValueError, match="stop propagation"):
        module.snapshot(*args)
    assert events == []


def test_scheduled_backup_lock_contention_does_not_touch_services(scheduled, monkeypatch, capsys, tmp_path):
    module, events, _, _, _, args = scheduled
    lock_path = tmp_path / "maintenance.lock"
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "umask", lambda value: 0)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["scheduled_backup", "--env", str(args[0]), "--lock-file", str(lock_path)])
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        module.main()
    assert '"reason": "maintenance lock held"' in capsys.readouterr().out
    assert events == []


def test_container_unit_requires_docker_and_checks_bridge_without_stop_propagation():
    unit = (ROOT / "ops/container/hypertest-container-stack.service").read_text()
    assert "Requires=docker.service\n" in unit
    assert "Wants=hypertest-harness-bridge.service\n" in unit
    assert "After=docker.service hypertest-harness-bridge.service network-online.target\n" in unit
    assert "BindsTo=docker.service\n" in unit
    assert "ExecStartPre=/usr/bin/systemctl is-active --quiet hypertest-harness-bridge.service\n" in unit
