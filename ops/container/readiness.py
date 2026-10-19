#!/usr/bin/env python3
"""Verify local topology and capabilities without starting a testing Run.

Capability requests use the real Worker operational queue. Routine releases check
the configured ingress policy without repeating external connectivity acceptance.
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
from stack import compose_command, ingress_tls_enabled, read_env, render_nginx, validate
from start import verify_daemon


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(label)


def check_http(values: dict[str, str]) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for role in ("API", "WEB", "INGRESS"):
        suffix = "/" if role == "WEB" else "/api/v1/health"
        with opener.open(f"http://127.0.0.1:{values['HYPERTEST_' + role + '_PORT']}{suffix}", timeout=10) as response:
            require(response.status == 200, f"{role} HTTP failed")
            if role != "WEB":
                require(json.load(response).get("status") == "ok", f"{role} health response failed")
    # The production loopback nginx listener intentionally serves health only.
    api = f"http://127.0.0.1:{values['HYPERTEST_API_PORT']}"
    with opener.open(api + "/api/v1/capabilities", timeout=30) as response:
        capability = json.load(response)
    require(capability.get("harness_bridge") == "READY", "Worker did not confirm Bridge capability")
    require("docker" in capability.get("runner_backends", []), "Worker did not confirm Docker Runner")
    require(capability.get("worker", {}).get("available") is True, "Worker heartbeat unavailable")


def check_tls_runtime(role: str, values: dict[str, str], platform: dict[str, str], mounts: list[dict], inspect) -> None:
    credentials = {
        "/run/hypertest-tls/server.crt": Path(values["HYPERTEST_TLS_CERT_FILE"]).resolve(),
        "/run/hypertest-tls/server.key": Path(values["HYPERTEST_TLS_KEY_FILE"]).resolve(),
    }
    if role == "nginx":
        for destination, source in credentials.items():
            matching = [mount for mount in mounts if mount["Destination"] == destination]
            require(len(matching) == 1 and matching[0]["Type"] == "bind" and matching[0].get("RW") is False
                    and Path(matching[0]["Source"]).resolve() == source,
                    "nginx TLS leaf credentials are not mounted from the checked files read-only")
    else:
        for mount in mounts:
            source = Path(mount["Source"]).resolve()
            require(not mount["Destination"].startswith("/run/hypertest-tls")
                    and not any(source == path or source in path.parents for path in credentials.values()),
                    f"{role} has a TLS credential mount")
    environment = dict(item.split("=", 1) for item in inspect(".Config.Env") or [] if "=" in item)
    if role in {"api", "worker"}:
        require(environment.get("HYPERTEST_CONNECTOR_OPERATOR_KEY") == platform["HYPERTEST_CONNECTOR_OPERATOR_KEY"],
                f"{role} Operator key differs from protected platform env")
        require(environment.get("HYPERTEST_CONNECTOR_ALLOW_INSECURE_LOOPBACK", "false").lower() in {"false", "0"},
                f"{role} enables insecure Connector authorization")
    else:
        require(not environment.get("HYPERTEST_CONNECTOR_OPERATOR_KEY"), f"{role} unexpectedly has the Operator key")
    if role == "api":
        require(environment.get("FORWARDED_ALLOW_IPS", "127.0.0.1") == platform.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
                "API trusted proxy peers differ from protected platform env")
        command = inspect(".Config.Cmd") or []
        require(not any(item == "--no-proxy-headers" or item.startswith("--forwarded-allow-ips") for item in command),
                "API command overrides the checked Uvicorn proxy environment")


def check(env: Path, bridge_service: str) -> dict:
    values = read_env(env)
    validate(values, live=True)
    tls = ingress_tls_enabled(values)
    platform = read_env(Path(values["HYPERTEST_PLATFORM_ENV_FILE"])) if tls else {}
    require(Path(values["HYPERTEST_NGINX_CONFIG"]).read_text() == render_nginx(values),
            "nginx configuration differs from the protected ingress policy")
    verify_daemon()
    network = guard(values)
    require(bool(re.fullmatch(r"hypertest-[a-zA-Z0-9_.-]{1,100}", bridge_service)), "invalid Bridge unit")
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
            if tls:
                check_tls_runtime(role, values, platform, mounts, inspect)
            if role != "postgres":
                require(inspect(".Config.User").split(":")[0] not in {"", "0", "root"}, f"{role} is root")
                require(inspect(".HostConfig.ReadonlyRootfs"), f"{role} root filesystem is writable")
                require("ALL" in inspect(".HostConfig.CapDrop"), f"{role} did not drop all capabilities")
            if role in {"api", "web", "postgres"}:
                ports = inspect(".HostConfig.PortBindings")
                require(bool(ports) and all(item["HostIp"] == "127.0.0.1" for entries in ports.values() for item in entries), f"{role} published beyond loopback")
            if role == "nginx":
                require(inspect(".HostConfig.NetworkMode") == "host" and not inspect(".HostConfig.PortBindings"), "nginx unexpectedly uses Docker port publishing")
                configs = [mount for mount in mounts if mount["Destination"] == "/etc/nginx/nginx.conf"]
                require(len(configs) == 1 and configs[0]["Type"] == "bind" and configs[0].get("RW") is False
                        and Path(configs[0]["Source"]).resolve() == Path(values["HYPERTEST_NGINX_CONFIG"]).resolve(),
                        "nginx is not mounting the checked protected configuration read-only")
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
    check_http(values)
    require(output(["systemctl", "is-active", bridge_service]) == "active", "Bridge service inactive")
    checks.extend(["loopback API/Web and nginx health: HTTP 200", "protected nginx ingress policy matches",
                   "Worker confirmed Bridge and Docker", "Bridge systemd: active"])
    if tls:
        checks.append("TLS leaf credentials mounted only by nginx read-only; Operator and API proxy environments checked")
    return {"ready": True, "checks": checks, "images": identities, "network": network,
            "external_vpn_boundary_verified": False, "existing_application_data_verified": False,
            "real_testing_cycle_verified": False, "connector_tls_e2e_verified": False}


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
