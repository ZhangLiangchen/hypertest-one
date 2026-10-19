"""Optional TLS upgrades the existing ingress without changing its network boundary."""
from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hypertest_tls_stack", ROOT / "ops/container/stack.py")
stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stack)


def configuration(tmp_path):
    values = stack.read_env(ROOT / "ops/container/compose.env.example")
    for index, key in enumerate(stack.IMAGE_KEYS):
        values[key] = "sha256:" + f"{index + 1:064x}"
    values.update(HYPERTEST_DOCKER_GID="998", HYPERTEST_BRIDGE_GID="997",
                  HYPERTEST_INGRESS_TLS="enabled",
                  HYPERTEST_TLS_CERT_FILE=str(tmp_path / "server.crt"),
                  HYPERTEST_TLS_KEY_FILE=str(tmp_path / "server.key"))
    return values


def test_disabled_tls_preserves_original_http_configuration(tmp_path):
    values = configuration(tmp_path)
    for setting in ({"HYPERTEST_INGRESS_TLS": "disabled"}, {}):
        original = {key: value for key, value in values.items() if key != "HYPERTEST_INGRESS_TLS"}
        original.update(setting)
        assert stack.render_nginx(original) == stack._render_nginx_http(original)
        stack.validate(original, live=False)
    with pytest.raises(ValueError, match="INGRESS_TLS"):
        stack.validate({**values, "HYPERTEST_INGRESS_TLS": "true"}, live=False)


def test_tls_upgrades_exact_listener_and_keeps_health_only_loopback(tmp_path):
    values = configuration(tmp_path)
    stack.validate(values, live=False)
    config = stack.render_nginx(values)
    assert config.count("listen ") == 2
    assert "listen 203.0.113.10:8080 ssl default_server;" in config
    assert "error_page 497 =308 https://203.0.113.10:8080$request_uri;" in config
    loopback, public = config.split("listen 203.0.113.10:8080 ssl default_server;")
    assert "listen 127.0.0.1:8080;" in loopback
    assert "location / { return 403; }" in loopback
    assert "location /api/v1/ {" not in loopback
    assert "limit_except GET HEAD { deny all; }" in loopback
    assert '"https://203.0.113.10:8080" 0;' in loopback
    assert '"http://203.0.113.10:8080"' not in config
    assert "allow 198.51.100.7/32;" in public
    assert 'if ($host != "203.0.113.10")' in public
    assert "location = /api/v1/harness-connectors/ws {" in public
    assert "proxy_set_header Upgrade $http_upgrade;" in public
    assert "proxy_set_header Connection $hypertest_connection_upgrade;" in public
    assert "location ^~ /api/v1/source-transfers/ {" in public
    assert "client_max_body_size 50m;" in public
    assert "client_body_timeout 150s;" in public
    assert "proxy_request_buffering off;" in public
    assert config.count("proxy_set_header X-Forwarded-For $remote_addr;") == 5
    assert "$proxy_add_x_forwarded_for" not in config and "real_ip_header" not in config
    assert "TLSv1.2 TLSv1.3" in config
    named = stack.render_nginx({**values, "HYPERTEST_TLS_SERVER_NAME": "hypertest.example.com"})
    assert "listen 203.0.113.10:8080 ssl" in named
    assert "https://hypertest.example.com:8080" in named


@pytest.mark.parametrize("field,bad", [
    ("HYPERTEST_PUBLIC_INGRESS", "disabled"),
    ("HYPERTEST_TLS_CERT_FILE", "relative.crt"),
    ("HYPERTEST_TLS_KEY_FILE", "/safe/../key"),
    ("HYPERTEST_TLS_SERVER_NAME", "other.example.com; listen 9000"),
    ("HYPERTEST_TLS_SERVER_NAME", "UPPER.example.com"),
    ("HYPERTEST_TLS_SERVER_NAME", "203.0.113.11"),
])
def test_tls_rejects_ambiguous_policy_before_launch(tmp_path, field, bad):
    with pytest.raises(ValueError):
        stack.validate({**configuration(tmp_path), field: bad}, live=False)


@pytest.mark.parametrize("peers", ["*", "127.0.0.1,10.0.0.0/24", "127.0.0.1, 10.0.0.1",
                                   "127.0.0.1,127.0.0.1", "127.0.0.1,10.0.0.1,10.0.0.2",
                                   "::1", "0.0.0.0", "127.0.0.1,224.0.0.1"])
def test_connector_proxy_trust_is_bounded_to_exact_observed_peers(peers):
    with pytest.raises(ValueError, match="FORWARDED_ALLOW_IPS"):
        stack.validate_connector_platform({"HYPERTEST_CONNECTOR_OPERATOR_KEY": "x" * 40,
                                           "FORWARDED_ALLOW_IPS": peers})


def test_connector_operator_secret_stays_in_platform_env():
    base = {"HYPERTEST_CONNECTOR_OPERATOR_KEY": "x" * 40, "FORWARDED_ALLOW_IPS": "127.0.0.1,192.0.2.9"}
    stack.validate_connector_platform(base)
    with pytest.raises(ValueError, match="Operator key"):
        stack.validate_connector_platform({**base, "HYPERTEST_CONNECTOR_OPERATOR_KEY": ""})
    with pytest.raises(ValueError, match="insecure"):
        stack.validate_connector_platform({**base, "HYPERTEST_CONNECTOR_ALLOW_INSECURE_LOOPBACK": "true"})


@pytest.mark.parametrize("gitlab", [False, True])
def test_tls_compose_mounts_leaf_only_into_nginx_and_preserves_server_bridge(tmp_path, gitlab):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose parser required")
    values = configuration(tmp_path)
    for key in ("HYPERTEST_PLATFORM_ENV_FILE", "HYPERTEST_POSTGRES_ENV_FILE"):
        path = tmp_path / key
        path.write_text("HYPERTEST_CONNECTOR_OPERATOR_KEY=test-only-key\n" if "PLATFORM" in key else "")
        values[key] = str(path)
    if gitlab:
        values["HYPERTEST_GITLAB_POLICY_DIR"] = str(tmp_path / "gitlab")
    env = tmp_path / "compose.env"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    parsed = json.loads(subprocess.check_output(stack.compose_command(env, "config", "--format", "json"), text=True))
    services = parsed["services"]
    for role, service in services.items():
        mounts = [mount for mount in service.get("volumes", []) if mount["target"].startswith("/run/hypertest-tls/")]
        assert len(mounts) == (2 if role == "nginx" else 0)
        assert all(mount["type"] == "bind" and mount["read_only"]
                   and not mount["bind"].get("create_host_path", False) for mount in mounts)
        if role in {"api", "worker", "migrate"}:
            assert service["environment"]["HYPERTEST_CONNECTOR_OPERATOR_KEY"] == "test-only-key"
        else:
            assert "HYPERTEST_CONNECTOR_OPERATOR_KEY" not in service.get("environment", {})
        assert service["restart"] == "no" and service["pull_policy"] == "never"
    assert services["api"].get("command") is None  # Uvicorn reads checked platform.env.
    assert services["worker"]["environment"]["HYPERTEST_HARNESS_MODE"] == "bridge"
    assert "bridge-execution" in repr(services["worker"]["volumes"])
    assert services["nginx"]["network_mode"] == "host" and "ports" not in services["nginx"]
    assert parsed["volumes"]["postgres_data"]["external"] is True
    for role in ("api", "web", "postgres"):
        assert all(item["host_ip"] == "127.0.0.1" for item in services[role]["ports"])


@pytest.fixture
def leaf(tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL required for throwaway test leaf")
    values = configuration(tmp_path)
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=203.0.113.10", "-addext", "subjectAltName=IP:203.0.113.10",
                    "-out", values["HYPERTEST_TLS_CERT_FILE"], "-keyout", values["HYPERTEST_TLS_KEY_FILE"]],
                   check=True, capture_output=True)
    return values


def test_tls_checks_leaf_key_match_and_nginx_key_permissions(leaf, monkeypatch):
    key = Path(leaf["HYPERTEST_TLS_KEY_FILE"])
    certificate = Path(leaf["HYPERTEST_TLS_CERT_FILE"])
    certificate.chmod(0o644)
    original = Path.stat
    details = SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=0, st_gid=101)
    monkeypatch.setattr(Path, "stat", lambda path, *a, **kw: details if path == key else original(path, *a, **kw))
    stack.validate_tls(leaf, live=True)
    details.st_mode = stat.S_IFREG | 0o644
    with pytest.raises(ValueError, match="world-accessible"):
        stack.validate_tls(leaf, live=True)
    details.st_mode = stat.S_IFREG | 0o640
    key.write_text("invalid throwaway key")
    with pytest.raises(OSError):
        stack.validate_tls(leaf, live=True)


def test_tls_generated_config_passes_real_nginx_parser_without_external_network(leaf, tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker required for real nginx parser")
    # Use an already-present fixed local image: never pull or publish a port.
    found = subprocess.run(["docker", "image", "inspect", "registry-1.docker.io/library/nginx:stable",
                            "--format", "{{.Id}}"], capture_output=True, text=True)
    if found.returncode:
        pytest.skip("fixed local nginx test image unavailable")
    config = tmp_path / "nginx.conf"
    config.write_text(stack.render_nginx(leaf))
    config.chmod(0o644)
    command = ["docker", "run", "--rm", "--network", "none", "--read-only", "--user", "101:101",
               "--sysctl", "net.ipv4.ip_nonlocal_bind=1",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,mode=1777",
               "--entrypoint", "nginx", "-v", f"{config}:/etc/nginx/nginx.conf:ro"]
    for field, name in (("HYPERTEST_TLS_CERT_FILE", "server.crt"), ("HYPERTEST_TLS_KEY_FILE", "server.key")):
        # This fixture contains a freshly generated disposable test key only.
        Path(leaf[field]).chmod(0o644)
        command += ["-v", f"{leaf[field]}:/run/hypertest-tls/{name}:ro"]
    result = subprocess.run([*command, found.stdout.strip(), "-t"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
