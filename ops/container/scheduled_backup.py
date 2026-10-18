#!/usr/bin/env python3
"""One-lock scheduled cold backup; active testing is skipped, never interrupted."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import backup
import readiness
import start
from network_guard import guard
from stack import compose_command, read_env, validate


def unit_state(unit: str) -> str:
    if not re.fullmatch(r"hypertest-[a-zA-Z0-9_.-]{1,100}", unit):
        raise ValueError("explicit hypertest- unit name required")
    return subprocess.check_output(["systemctl", "show", unit, "--property=ActiveState", "--value"], text=True).strip()


def require_managed_stack(stack_service: str, bridge_service: str) -> None:
    if unit_state(stack_service) != "active" or unit_state(bridge_service) != "active":
        raise ValueError("scheduled backup requires an already active stack and Bridge")
    raw = subprocess.check_output([
        "systemctl", "show", stack_service, "--property=Requires", "--property=BindsTo",
        "--property=PartOf", "--property=Wants",
    ], text=True)
    dependencies = dict(line.split("=", 1) for line in raw.splitlines())
    bridge_unit = bridge_service if bridge_service.endswith(".service") else bridge_service + ".service"
    if any(bridge_unit in dependencies.get(key, "").split() for key in ("Requires", "BindsTo", "PartOf")):
        raise ValueError("stack must Want Bridge without stop propagation; otherwise maintenance would relock itself")
    if bridge_unit not in dependencies.get("Wants", "").split():
        raise ValueError("stack must Want the selected Bridge")


def active_requests(env: Path) -> bool:
    query = (
        "SELECT (SELECT count(*) FROM durable_jobs WHERE status IN ('QUEUED','RUNNING','CANCEL_REQUESTED'))"
        "+(SELECT count(*) FROM runtime_control_requests WHERE status IN ('QUEUED','RUNNING'))"
    )
    result = backup.postgres(env, f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "{query}"',
                             stdout=subprocess.PIPE)
    return int(result.stdout.strip()) > 0


def snapshot(env: Path, output_root: Path, bridge_state: Path, stack_service: str, bridge_service: str) -> dict:
    """Caller owns the maintenance lock throughout, including restoration."""
    values = read_env(env)
    validate(values, live=True)
    require_managed_stack(stack_service, bridge_service)
    if not output_root.is_absolute() or not bridge_state.is_absolute() or not bridge_state.is_dir():
        raise ValueError("backup root and existing Bridge state require absolute paths")
    # This also checks actual image/mount/guard identities and Bridge capabilities.
    # No service is touched if the existing deployment is unhealthy.
    readiness.check(env, bridge_service)
    daemon = start.verify_daemon()
    api_stopped = False
    cold = False
    try:
        # Block new writes, then let a busy Worker continue without a restart.
        api_stopped = True
        backup.compose(env, "stop", "api")
        if active_requests(env):
            return {"status": "skipped", "reason": "active testing or control request", "backup_created": False}
        cold = True
        backup.compose(env, "stop", *start.ROLES)
        subprocess.run(["systemctl", "stop", bridge_service], check=True)
        if unit_state(bridge_service) != "inactive":
            raise ValueError("Bridge did not stop; refusing a partial cold backup")
        # Use in-process APIs: their CLIs and systemd ExecStart/Stop take this same lock.
        start.start(env, ("postgres",))
        output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = output_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup.backup(env, values, target, bridge_state, bridge_service)
        return {"status": "complete", "backup": str(target), "backup_created": True}
    finally:
        if cold:
            try:
                subprocess.run(["systemctl", "start", bridge_service], check=True)
                if unit_state(bridge_service) != "active":
                    raise ValueError("Bridge did not recover after the backup window")
                start.start(env, start.ROLES)
                readiness.check(env, bridge_service)
            except BaseException:
                # Never report success with a partially restored or unsafe listener.
                subprocess.run(compose_command(env, "stop", *start.ROLES), check=False)
                raise
        elif api_stopped:
            try:
                if start.verify_daemon() != daemon or not guard(values)["protected"]:
                    raise ValueError("Docker or ingress guard changed during the backup admission check")
                backup.compose(env, "start", "api")
                start.wait_healthy(env, values, ("api",), daemon)
            except BaseException:
                # API failure must not kill the busy Job that made us skip backup.
                # Only an unsafe/unknown network boundary requires a full stop.
                roles = ("api", "nginx")
                try:
                    if start.verify_daemon() != daemon or not guard(values)["protected"]:
                        roles = start.ROLES
                except Exception:
                    roles = start.ROLES
                subprocess.run(compose_command(env, "stop", *roles), check=False)
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("/var/backups/hypertest"))
    parser.add_argument("--bridge-state", type=Path, default=Path("/var/lib/hypertest-harness"))
    parser.add_argument("--stack-service", default="hypertest-container-stack")
    parser.add_argument("--bridge-service", default="hypertest-harness-bridge")
    parser.add_argument("--lock-file", type=Path, default=Path("/run/lock/hypertest-maintenance.lock"))
    args = parser.parse_args()
    if os.geteuid() != 0 or not args.lock_file.is_absolute():
        raise ValueError("scheduled backup requires root and an absolute maintenance lock")
    os.umask(0o077)

    def interrupted(signum, frame):
        raise InterruptedError(f"scheduled backup interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with args.lock_file.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "skipped", "reason": "maintenance lock held", "backup_created": False}))
            return
        result = snapshot(args.env, args.output_root, args.bridge_state, args.stack_service, args.bridge_service)
        print(json.dumps({**result, "services_restored": True}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"scheduled backup failed: {exc}; any partial backup was retained", file=sys.stderr)
        raise SystemExit(1) from None
