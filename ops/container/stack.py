#!/usr/bin/env python3
"""Validate a single-host production bundle; never mutate live host policy."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IMAGE_KEYS = [f"HYPERTEST_{name}_IMAGE" for name in ("API", "WORKER", "WEB", "POSTGRES", "NGINX")]
PATH_KEYS = [
    "HYPERTEST_PLATFORM_ENV_FILE", "HYPERTEST_POSTGRES_ENV_FILE", "HYPERTEST_ARTIFACT_ROOT",
    "HYPERTEST_WORKSPACE_ROOT", "HYPERTEST_BRIDGE_SOCKET_DIR", "HYPERTEST_BRIDGE_EXECUTION_KEY_FILE",
    "HYPERTEST_BRIDGE_MANAGEMENT_KEY_FILE", "HYPERTEST_NGINX_CONFIG",
]
FIXED_IMAGE = re.compile(r"(?:sha256:[a-f0-9]{64}|[^\s@]+@sha256:[a-f0-9]{64})\Z")


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError("configuration requires unique KEY=value lines")
        # This file deliberately excludes credentials and shell/Compose interpolation.
        if any(char in value for char in "\r\n\x00$`\"'"):
            raise ValueError(f"{key}: interpolation/quoting is not supported")
        values[key] = value
    return values


def validate(values: dict[str, str], *, live: bool) -> None:
    for key in IMAGE_KEYS:
        if not FIXED_IMAGE.fullmatch(values.get(key, "")):
            raise ValueError(f"{key} must be a local image ID or registry digest; tags are refused")
        if live:
            subprocess.run(["docker", "image", "inspect", values[key]], check=True, stdout=subprocess.DEVNULL)
    for key in PATH_KEYS:
        raw = values.get(key, "")
        path = Path(raw)
        if not raw or not path.is_absolute() or raw != str(path) or ".." in path.parts:
            raise ValueError(f"{key} must be a normalized absolute path")
        if live and not path.exists():
            raise ValueError(f"{key} does not exist; refusing implicit directory creation")
    roots = [Path(values[key]) for key in ("HYPERTEST_ARTIFACT_ROOT", "HYPERTEST_WORKSPACE_ROOT")]
    if any(root == Path("/") for root in roots) or roots[0] == roots[1] or any(
        root in other.parents for root, other in (roots, roots[::-1])
    ):
        raise ValueError("Artifact and workspace roots must be distinct non-nested directories")
    for key in ("HYPERTEST_UID", "HYPERTEST_GID", "HYPERTEST_DOCKER_GID", "HYPERTEST_BRIDGE_GID"):
        if not values.get(key, "").isdigit() or int(values[key]) < 1:
            raise ValueError(f"{key} requires a non-root numeric service identity")
    for key in ("HYPERTEST_POSTGRES_VOLUME", "HYPERTEST_STACK_NAME", "HYPERTEST_BRIDGE_HOST_ID"):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", values.get(key, "")):
            raise ValueError(f"invalid {key}")
    for key in ("HYPERTEST_POSTGRES_PORT", "HYPERTEST_API_PORT", "HYPERTEST_WEB_PORT", "HYPERTEST_INGRESS_PORT"):
        if not values.get(key, "").isdigit() or not 1024 <= int(values[key]) <= 65535:
            raise ValueError(f"invalid unprivileged port: {key}")
    if len({values[key] for key in ("HYPERTEST_POSTGRES_PORT", "HYPERTEST_API_PORT", "HYPERTEST_WEB_PORT", "HYPERTEST_INGRESS_PORT")}) != 4:
        raise ValueError("host ports must be distinct")
    if values.get("HYPERTEST_PUBLIC_INGRESS", "enabled") not in ("enabled", "disabled"):
        raise ValueError("HYPERTEST_PUBLIC_INGRESS must be enabled or disabled")
    address = ipaddress.ip_address(values.get("HYPERTEST_PUBLIC_IP", ""))
    if address.version != 4 or address.is_unspecified or address.is_multicast or address.is_loopback:
        raise ValueError("public listener requires the host's specific IPv4 address")
    try:
        peer = ipaddress.ip_network(values.get("HYPERTEST_VPN_CIDR", ""), strict=True)
    except ValueError:
        raise ValueError("the authorized VPN allowlist requires one explicit IPv4 /32") from None
    if (peer.version != 4 or peer.prefixlen != 32 or str(peer) != values["HYPERTEST_VPN_CIDR"]
            or peer.network_address.is_unspecified or peer.network_address.is_multicast
            or peer.network_address.is_loopback or peer.network_address.is_link_local
            or str(peer.network_address) == "255.255.255.255"):
        raise ValueError("the authorized VPN allowlist requires one explicit IPv4 /32")
    if live:
        subprocess.run(["docker", "volume", "inspect", values["HYPERTEST_POSTGRES_VOLUME"]], check=True, stdout=subprocess.DEVNULL)
        platform = read_env(Path(values["HYPERTEST_PLATFORM_ENV_FILE"]))
        for key in ("HYPERTEST_WORKSPACE_ROOT", "HYPERTEST_ARTIFACT_ROOT"):
            if platform.get(key) != values[key]:
                raise ValueError(f"platform env and bind mount disagree on {key}")
        if platform.get("HYPERTEST_EXECUTION_MODE") != "queued":
            raise ValueError("production API requires queued execution")
        if platform.get("HYPERTEST_HARNESS_MODE") != "bridge":
            raise ValueError("production platform requires the host Bridge")
        for key in ("HYPERTEST_BRIDGE_EXECUTION_KEY_FILE", "HYPERTEST_BRIDGE_MANAGEMENT_KEY_FILE"):
            path = Path(values[key])
            if path.stat().st_mode & 0o007:
                raise ValueError(f"{key} must not be world-accessible")
        first = Path(values["HYPERTEST_BRIDGE_EXECUTION_KEY_FILE"]).read_bytes()
        second = Path(values["HYPERTEST_BRIDGE_MANAGEMENT_KEY_FILE"]).read_bytes()
        if min(len(first), len(second)) < 32 or first == second:
            raise ValueError("Bridge execution and management keys must be distinct and at least 32 bytes")


def compose_command(env_file: Path, *args: str) -> list[str]:
    command = ["docker", "compose", "--env-file", str(env_file), "-f", str(REPO / "compose.production.yml")]
    # One source of truth also for guarded startup/readiness/backup. Never let an
    # operator's deployment overlay disappear during a subsequent systemd start.
    if env_file.exists() and read_env(env_file).get("HYPERTEST_GITLAB_POLICY_DIR"):
        command.extend(["-f", str(REPO / "ops/container/compose.gitlab.yml")])
    return [*command, *args]


def render_nginx(values: dict[str, str]) -> str:
    ip = values["HYPERTEST_PUBLIC_IP"]
    ingress = values["HYPERTEST_INGRESS_PORT"]
    api = values["HYPERTEST_API_PORT"]
    web = values["HYPERTEST_WEB_PORT"]
    common = f"""
        client_max_body_size 10m;
        add_header X-Frame-Options DENY always;
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy same-origin always;
        location /api/v1/ {{
            proxy_pass http://127.0.0.1:{api};
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Forwarded "";
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }}
        location / {{
            proxy_pass http://127.0.0.1:{web};
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Forwarded "";
            proxy_read_timeout 300s;
        }}
"""
    public_server = f"""
    server {{
        listen {ip}:{ingress} default_server;
        server_name {ip};
        allow {values['HYPERTEST_VPN_CIDR']};
        deny all;
        if ($host != "{ip}") {{ return 444; }}
        if ($reject_origin) {{ return 403; }}
{common}
    }}
""" if values.get("HYPERTEST_PUBLIC_INGRESS", "enabled") == "enabled" else ""
    # Host/container health probes must not create a second user-facing Web/API
    # ingress. Full loopback ingress is reserved for explicitly isolated staging.
    loopback_locations = common if not public_server else f"""
        location = /api/v1/health {{
            limit_except GET HEAD {{ deny all; }}
            proxy_pass http://127.0.0.1:{api};
            proxy_method GET;
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header Forwarded "";
            proxy_read_timeout 5s;
        }}
        location / {{ return 403; }}
"""
    return f"""# Generated by ops/container/stack.py; do not trust forwarded client addresses.
worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {{ worker_connections 1024; }}
http {{
    include /etc/nginx/mime.types;
    client_body_temp_path /tmp/client;
    proxy_temp_path /tmp/proxy;
    fastcgi_temp_path /tmp/fastcgi;
    uwsgi_temp_path /tmp/uwsgi;
    scgi_temp_path /tmp/scgi;
    log_format peer '$remote_addr [$time_iso8601] "$request_method $uri" $status';
    access_log /dev/stdout peer;
    map $request_method $unsafe {{ default 1; GET 0; HEAD 0; OPTIONS 0; }}
    map $http_origin $foreign {{ default 1; "" 0; "http://{ip}:{ingress}" 0; }}
    map "$unsafe:$foreign" $reject_origin {{ default 0; "1:1" 1; }}
    server {{
        listen 127.0.0.1:{ingress};
        server_name localhost 127.0.0.1;
        allow 127.0.0.1;
        deny all;
{loopback_locations}
    }}
{public_server}
}}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="non-secret absolute compose.env")
    parser.add_argument("action", choices=("validate", "render-nginx", "config", "status"))
    parser.add_argument("--offline", action="store_true", help="schema validation only; no runtime/readiness claim")
    args = parser.parse_args()
    values = read_env(args.env)
    validate(values, live=not args.offline and args.action != "render-nginx")
    if args.action == "render-nginx":
        path = Path(values["HYPERTEST_NGINX_CONFIG"])
        # No automatic parent creation or overwrite of an existing accepted configuration.
        with path.open("x") as target:
            target.write(render_nginx(values))
        os.chmod(path, 0o644)
        print(f"created {path}")
    elif args.action in ("config", "status"):
        command = ("config", "--quiet") if args.action == "config" else ("ps", "--format", "json")
        subprocess.run(compose_command(args.env, *command), check=True)
    else:
        print(json.dumps({"valid": True, "live_resources_checked": not args.offline}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"container configuration rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
