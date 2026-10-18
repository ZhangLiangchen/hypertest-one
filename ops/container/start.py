#!/usr/bin/env python3
"""Start only this stack after installing its ingress guard; never migrate data.

Restart policies must be `no` and daemon live restore must be disabled. This
prevents Docker from reopening published ports before host firewall preparation
after a daemon/host restart. The paired systemd unit is the boot entry point.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path

from network_guard import guard
from stack import compose_command, read_env, validate

ROLES = ("postgres", "api", "worker", "web", "nginx")


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def verify_daemon() -> str:
    info = json.loads(output(["docker", "info", "--format", "{{json .}}"]))
    if info.get("LiveRestoreEnabled") is not False:
        raise ValueError("live-restore must be disabled: containers cannot survive loss of the ingress guard")
    identity = output(["systemctl", "show", "docker", "--property=MainPID", "--property=ExecMainStartTimestampMonotonic"])
    if "MainPID=0" in identity or "MainPID=" not in identity:
        raise ValueError("Docker must be supervised by the host docker systemd unit")
    return identity


def verify_restart_policy(env: Path, values: dict[str, str]) -> None:
    config = json.loads(output(compose_command(env, "--profile", "maintenance", "config", "--format", "json")))
    if any(service.get("restart", "no") != "no" for service in config["services"].values()):
        raise ValueError("every service requires restart=no; automatic Docker restart bypasses the ingress guard")
    containers = output(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + values["HYPERTEST_STACK_NAME"]]).splitlines()
    for container in containers:
        policy = json.loads(output(["docker", "inspect", "--format", "{{json .HostConfig.RestartPolicy}}", container]))
        if policy["Name"] != "no":
            raise ValueError("existing stack container has unsafe restart policy; stop it and explicitly set restart=no before rollout")


def wait_healthy(env: Path, values: dict[str, str], roles: tuple[str, ...], daemon: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if verify_daemon() != daemon or not guard(values)["protected"]:
            raise ValueError("Docker or ingress guard changed while waiting for readiness")
        ready = True
        for role in roles:
            containers = output(compose_command(env, "ps", "--all", "-q", role)).splitlines()
            if not containers:
                raise ValueError(f"{role} container was not created")
            for container in containers:
                state = json.loads(output(["docker", "inspect", "--format", "{{json .State}}", container]))
                if not state["Running"] or state.get("Health", {}).get("Status") == "unhealthy":
                    raise ValueError(f"{role} exited or became unhealthy during guarded startup")
                ready = ready and state.get("Health", {}).get("Status") == "healthy"
        if ready:
            return
        time.sleep(1)
    raise ValueError("container readiness timed out; stack remains stopped")


def start(env: Path, roles: tuple[str, ...]) -> dict:
    values = read_env(env)
    validate(values, live=False)
    # Stop our own stack first. No published port may be live during guard repair.
    subprocess.run(compose_command(env, "stop", *ROLES), check=True)
    try:
        validate(values, live=True)
        daemon = verify_daemon()
        verify_restart_policy(env, values)
        subprocess.run(compose_command(env, "create", "--no-build", "--pull", "never", *roles), check=True)
        verify_restart_policy(env, values)
        protection = guard(values, "install")
        if not protection["protected"] or verify_daemon() != daemon:
            raise ValueError("Docker changed while preparing ingress; refusing startup")
        # start never recreates a network or starts an implicit migration.
        subprocess.run(compose_command(env, "start", *roles), check=True)
        wait_healthy(env, values, roles, daemon)
        if verify_daemon() != daemon or not guard(values)["protected"]:
            raise ValueError("Docker or ingress guard changed during startup")
        return {"started": list(roles), "restart_policy": "no", "live_restore": False,
                "guard_installed_before_start": True, "network": protection,
                "reboot_test_performed": False}
    except (ValueError, OSError, subprocess.CalledProcessError):
        subprocess.run(compose_command(env, "stop", *ROLES), check=False)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True, help="same host maintenance lock used by backup/migration")
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--postgres-only", action="store_true", help="prepare a database for the separate one-shot migration")
    args = parser.parse_args()
    if not args.lock.is_absolute():
        raise ValueError("maintenance lock must be absolute")
    with args.lock.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "start":
            print(json.dumps(start(args.env, ("postgres",) if args.postgres_only else ROLES), indent=2))
        else:
            subprocess.run(compose_command(args.env, "stop", *ROLES), check=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"guarded startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
