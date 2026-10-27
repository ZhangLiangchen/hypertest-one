"""Optional Memory wiring preserves existing TCP policy and credential boundaries."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("memory_stack", ROOT / "ops/container/stack.py")
stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stack)


def configuration():
    values = stack.read_env(ROOT / "ops/container/compose.env.example")
    for index, key in enumerate(stack.IMAGE_KEYS):
        values[key] = "sha256:" + f"{index + 1:064x}"
    values.update(HYPERTEST_DOCKER_GID="998", HYPERTEST_BRIDGE_GID="997", HYPERTEST_GID="989",
        HYPERTEST_INGRESS_TLS="enabled", HYPERTEST_TLS_CERT_FILE="/cert/server.crt",
        HYPERTEST_TLS_KEY_FILE="/cert/server.key", HYPERTEST_CLOUD_API_ORIGIN="https://203.0.113.10:8080",
        HYPERTEST_CLOUD_WEB_SOCKET_DIR="/run/hypertest-cloud-web",
        HYPERTEST_CLOUD_API_CA_FILE="/private/issuer-ca.crt",
        HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE="/private/web-operator-key",
        HYPERTEST_MEMORY_GATEWAY="enabled", HYPERTEST_MEMORY_POWERCONTEXT_ORIGIN="https://memory.example.invalid:8443",
        HYPERTEST_MEMORY_POWERCONTEXT_TOKEN_FILE="/private/api-powercontext-token",
        HYPERTEST_MEMORY_WORKER_SOCKET_DIR="/run/hypertest-memory-worker")
    return values


def test_memory_only_needs_no_cloud_worker_or_wrapping_identity_and_adds_no_tcp():
    values = configuration()
    stack.validate(values, live=False)
    old = stack.render_nginx({**values, "HYPERTEST_MEMORY_GATEWAY": "disabled"})
    new = stack.render_nginx(values)
    # Public and loopback TCP listeners/allowlist are unchanged.
    assert new.split("# Private filesystem transport.")[0] == old.rsplit("}", 1)[0] + "\n    "
    assert new.count("listen ") == old.count("listen ") + 2
    web, worker = new.split("# Private Memory Worker transport.")
    assert "listen unix:/run/hypertest-cloud-web/api.sock ssl;" in web
    assert "location /api/v1/memory/" in web
    assert "location /api/v1/cloud/" not in web
    assert "listen unix:/run/hypertest-memory-worker/api.sock ssl;" in worker
    assert "location /api/v1/memory/" in worker
    assert "location /api/v1/cloud/" not in worker and "task-directory" not in worker
    assert "location / { return 404; }" in worker
    assert 'if ($http_host != "203.0.113.10:8080")' in worker
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in worker


def test_memory_disabled_preserves_existing_nginx_output_byte_for_byte():
    values = configuration()
    values.update(HYPERTEST_MEMORY_GATEWAY="disabled", HYPERTEST_CLOUD_API_WRAPPING_KEY_FILE="/private/api-wrapping-key",
        HYPERTEST_CLOUD_CREDENTIAL_KEY_ID="primary", HYPERTEST_CLOUD_WORKER_ENABLED="true")
    # Recorded from the previous committed renderer for this exact configuration.
    for cloud, expected in [("disabled", "52c736ffc419e8ccb8d55b68eabff323d90a22ab1538ae368a612eb7523bace2"),
                            ("enabled", "62f5a06480f21533b96ff998a6e68c59595ae8ccc6968806f3605f0f33522c87")]:
        values["HYPERTEST_CLOUD_WEB"] = cloud
        assert hashlib.sha256(stack.render_nginx(values).encode()).hexdigest() == expected


def test_archive_only_exposes_scoped_web_transport_without_cloud_or_memory(tmp_path):
    values = {**configuration(), "HYPERTEST_MEMORY_GATEWAY": "disabled", "HYPERTEST_ARCHIVE_WEB": "enabled"}
    stack.validate(values, live=False)
    rendered = stack.render_nginx(values)
    private = rendered.split("# Private filesystem transport.")[1]
    assert "location /api/v1/local-archive/" in private
    assert "location /api/v1/cli-authorizations/" in private
    assert "location /api/v1/cloud/" not in private
    assert "location /api/v1/memory/" not in private
    assert "location / { return 404; }" in private
    assert "listen unix:/run/hypertest-cloud-web/api.sock ssl;" in private
    env = tmp_path / "compose.env"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    command = stack.compose_command(env, "config")
    assert str(ROOT / "ops/container/compose.archive.yml") in command
    assert str(ROOT / "ops/container/compose.cloud.yml") not in command
    assert str(ROOT / "ops/container/compose.memory.yml") not in command


@pytest.mark.parametrize("key,value", [
    ("HYPERTEST_MEMORY_GATEWAY", "true"),
    ("HYPERTEST_MEMORY_POWERCONTEXT_ORIGIN", "http://memory.example.invalid:8443"),
    ("HYPERTEST_MEMORY_POWERCONTEXT_ORIGIN", "https://secret@memory.example.invalid"),
    ("HYPERTEST_MEMORY_POWERCONTEXT_ORIGIN", "https://memory.example.invalid/path"),
    ("HYPERTEST_MEMORY_POWERCONTEXT_ORIGIN", "https://memory.example.invalid?secret=value"),
    ("HYPERTEST_MEMORY_POWERCONTEXT_ORIGIN", "https://memory.example.invalid:"),
    ("HYPERTEST_MEMORY_POWERCONTEXT_ORIGIN", "https://memory example.invalid"),
    ("HYPERTEST_MEMORY_POWERCONTEXT_TOKEN_FILE", "/private/../wrong"),
    ("HYPERTEST_MEMORY_WORKER_SOCKET_DIR", "/run/hypertest-cloud-web"),
    ("HYPERTEST_MEMORY_WORKER_SOCKET_DIR", "/run/hypertest-cloud-web/worker"),
    ("HYPERTEST_CLOUD_API_ORIGIN", "http://api:8000"),
    ("HYPERTEST_INGRESS_TLS", "disabled"),
])
def test_memory_refuses_ambiguous_flags_paths_and_non_tls_origins(key, value):
    with pytest.raises(ValueError):
        stack.validate({**configuration(), key: value}, live=False)


def test_memory_validates_private_api_token_and_worker_directory_without_cloud_flags(monkeypatch):
    values = configuration()
    calls = []
    monkeypatch.setattr(stack, "validate_web_facade", lambda *args, **kwargs: calls.append("web-facade"))
    monkeypatch.setattr(stack, "_private_paths", lambda *args, **kwargs: None)
    monkeypatch.setattr(stack, "_private_file", lambda path, uid, gid, key: calls.append((str(path), uid, gid, key)))
    monkeypatch.setattr(stack, "_socket_directory", lambda path, gid, label: calls.append((str(path), gid, label)))
    stack.validate_memory_gateway(values, live=True)
    assert calls == ["web-facade", ("/private/api-powercontext-token", 999, 989, "HYPERTEST_MEMORY_POWERCONTEXT_TOKEN_FILE"),
        ("/run/hypertest-memory-worker", 988, "Memory Worker")]


def test_private_file_and_socket_metadata_enforce_owner_modes_and_no_extra_files():
    details = SimpleNamespace(st_mode=stat.S_IFREG | 0o400, st_uid=999, st_gid=989, st_nlink=1)
    path = SimpleNamespace(stat=lambda: details)
    stack._private_file(path, 999, 989, "memory token")
    details.st_mode = stat.S_IFREG | 0o444
    with pytest.raises(ValueError, match="private regular file"):
        stack._private_file(path, 999, 989, "memory token")
    details = SimpleNamespace(st_mode=stat.S_IFDIR | 0o710, st_uid=101, st_gid=988)
    directory = SimpleNamespace(stat=lambda: details, iterdir=lambda: [])
    stack._socket_directory(directory, 988, "Memory Worker")
    details.st_gid = 1000
    with pytest.raises(ValueError, match="clientgroup988"):
        stack._socket_directory(directory, 988, "Memory Worker")


def test_memory_overlay_is_independent_and_secret_mounts_reach_only_api(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose parser required")
    values = configuration()
    for key in ("HYPERTEST_PLATFORM_ENV_FILE", "HYPERTEST_POSTGRES_ENV_FILE"):
        path = tmp_path / key
        path.write_text("EXAMPLE=value\n")
        values[key] = str(path)
    env = tmp_path / "compose.env"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    command = stack.compose_command(env, "config", "--format", "json")
    assert str(ROOT / "ops/container/compose.memory.yml") in command
    assert str(ROOT / "ops/container/compose.cloud.yml") not in command
    parsed = json.loads(subprocess.run(command, text=True, capture_output=True, check=True).stdout)
    services = parsed["services"]
    assert services["api"]["environment"]["HYPERTEST_MEMORY_ENABLED"] == "true"
    assert services["web"]["environment"]["HYPERTEST_MEMORY_WEB_ENABLED"] == "true"
    assert "HYPERTEST_CLOUD_WEB_ENABLED" not in services["web"]["environment"]
    for role, service in services.items():
        targets = {mount["target"] for mount in service.get("volumes", [])}
        assert ("/run/hypertest-memory/powercontext-token" in targets) == (role == "api")
        assert ("/run/hypertest-memory-worker" in targets) == (role == "nginx")
    assert services["nginx"]["entrypoint"] == ["/bin/sh", "-c"]
    assert services["nginx"]["command"] == ["umask 000; exec nginx -g 'daemon off;'"]
    assert services["nginx"]["network_mode"] == "host" and "ports" not in services["nginx"]
    # Compose merges shared facade mounts by destination when both independent
    # overlays are selected; the upstream admin secret stays API-only.
    values.update(HYPERTEST_CLOUD_WEB="enabled", HYPERTEST_CLOUD_API_WRAPPING_KEY_FILE="/private/api-wrapping-key",
        HYPERTEST_CLOUD_CREDENTIAL_KEY_ID="primary", HYPERTEST_CLOUD_WORKER_ENABLED="true")
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    merged = json.loads(subprocess.run(stack.compose_command(env, "config", "--format", "json"),
        text=True, capture_output=True, check=True).stdout)["services"]
    assert merged["web"]["environment"]["HYPERTEST_CLOUD_WEB_ENABLED"] == "true"
    assert merged["web"]["environment"]["HYPERTEST_MEMORY_WEB_ENABLED"] == "true"
    for role, service in merged.items():
        mounts = service.get("volumes", [])
        targets = [mount["target"] for mount in mounts]
        assert len(targets) == len(set(targets))
        assert ("/run/hypertest-memory/powercontext-token" in targets) == (role == "api")
    values["HYPERTEST_MEMORY_GATEWAY"] = "disabled"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    assert str(ROOT / "ops/container/compose.memory.yml") not in stack.compose_command(env, "config")
