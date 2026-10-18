#!/usr/bin/env python3
"""Verify local topology and capabilities without starting a testing Run.

Capability requests use the real Worker operational queue. External VPN allow/
deny probes and application-data preservation are separate acceptance evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from network_guard import guard
from stack import compose_command, read_env, validate
from start import verify_daemon


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(label)


def check(env: Path, bridge_service: str) -> dict:
    values = read_env(env)
    validate(values, live=True)
    verify_daemon()
    network = guard(values)
    require(bool(re.fullmatch(r"hypertest-[a-zA-Z0-9_.-]{1,100}", bridge_service)), "invalid Bridge unit")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks, identities = [], {}
    for role in ("api", "worker", "web", "postgres", "nginx"):
        containers = output(compose_command(env, "ps", "-q", role)).splitlines()
        require(bool(containers) and (role == "worker" or len(containers) == 1), f"unexpected {role} container count")
        identities[role] = []
        for container in containers:
            def inspect(field: str, container_id: str = container):
                return json.loads(output(["docker", "inspect", "--format", "{{json " + field + "}}", container_id]))

            state = inspect(".State")
            require(state["Running"] and state.get("Health", {}).get("Status") == "healthy", f"{role} is not healthy")
            identities[role].append(inspect(".Image"))
            require(inspect(".HostConfig.RestartPolicy")["Name"] == "no", f"{role} bypasses guarded startup")
            mounts = inspect(".Mounts")
            if role != "postgres":
                require(inspect(".Config.User").split(":")[0] not in {"", "0", "root"}, f"{role} is root")
                require(inspect(".HostConfig.ReadonlyRootfs"), f"{role} root filesystem is writable")
                require("ALL" in inspect(".HostConfig.CapDrop"), f"{role} did not drop all capabilities")
            if role in {"api", "web", "postgres"}:
                ports = inspect(".HostConfig.PortBindings")
                require(bool(ports) and all(item["HostIp"] == "127.0.0.1" for entries in ports.values() for item in entries), f"{role} published beyond loopback")
            if role == "nginx":
                require(inspect(".HostConfig.NetworkMode") == "host" and not inspect(".HostConfig.PortBindings"), "nginx unexpectedly uses Docker port publishing")
            if role in {"api", "web"}:
                paths = " ".join(item["Source"] + " " + item["Destination"] for item in mounts)
                require(not any(token in paths for token in ("docker.sock", ".codex", ".claude", "bridge-execution", "bridge-management", "hypertest-gitlab")), f"{role} has a privileged mount")
                require(values["HYPERTEST_BRIDGE_SOCKET_DIR"] not in paths, f"{role} has Bridge socket access")
            if role in {"api", "worker"}:
                forbidden = ("docker", "codex", "claude") if role == "api" else ("codex", "claude")
                probe = f"import json,shutil; print(json.dumps({{x:shutil.which(x) for x in {forbidden!r}}}))"
                require(not any(json.loads(output(["docker", "exec", container, "python", "-c", probe])).values()), f"{role} contains a forbidden CLI")
            if role == "postgres":
                volumes = [mount["Name"] for mount in mounts if mount["Type"] == "volume"]
                require(volumes == [values["HYPERTEST_POSTGRES_VOLUME"]], "PostgreSQL volume identity mismatch")
        checks.append(f"{role}: {len(containers)} healthy; identity, runtime permissions and mounts checked")
    for role in ("API", "WEB", "INGRESS"):
        suffix = "/api/v1/health" if role == "API" else "/"
        with opener.open(f"http://127.0.0.1:{values['HYPERTEST_' + role + '_PORT']}{suffix}", timeout=10) as response:
            require(response.status == 200, f"{role} HTTP failed")
    ingress = f"http://127.0.0.1:{values['HYPERTEST_INGRESS_PORT']}"
    with opener.open(ingress + "/api/v1/capabilities", timeout=30) as response:
        capability = json.load(response)
    require(capability.get("harness_bridge") == "READY", "Worker did not confirm Bridge capability")
    require("docker" in capability.get("runner_backends", []), "Worker did not confirm Docker Runner")
    require(capability.get("worker", {}).get("available") is True, "Worker heartbeat unavailable")
    require(output(["systemctl", "is-active", bridge_service]) == "active", "Bridge service inactive")
    checks.extend(["loopback API/Web/nginx: HTTP 200", "Worker confirmed Bridge and Docker", "Bridge systemd: active"])
    return {"ready": True, "checks": checks, "images": identities, "network": network,
            "external_vpn_boundary_verified": False, "existing_application_data_verified": False,
            "real_testing_cycle_verified": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--bridge-service", default="hypertest-harness-bridge")
    args = parser.parse_args()
    print(json.dumps(check(args.env, args.bridge_service), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"readiness failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
