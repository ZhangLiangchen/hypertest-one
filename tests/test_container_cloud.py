"""Cloud's private HTTPS facade is additive to the existing ingress policy."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cloud_stack", ROOT / "ops/container/stack.py")
stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stack)


def configuration():
    values = stack.read_env(ROOT / "ops/container/compose.env.example")
    for index, key in enumerate(stack.IMAGE_KEYS):
        values[key] = "sha256:" + f"{index + 1:064x}"
    values.update(HYPERTEST_DOCKER_GID="998", HYPERTEST_BRIDGE_GID="997",
        HYPERTEST_INGRESS_TLS="enabled", HYPERTEST_CLOUD_WEB="enabled",
        HYPERTEST_TLS_CERT_FILE="/cert/server.crt", HYPERTEST_TLS_KEY_FILE="/cert/server.key",
        HYPERTEST_CLOUD_API_ORIGIN="https://203.0.113.10:8080",
        HYPERTEST_CLOUD_WEB_SOCKET_DIR="/run/hypertest-cloud-web",
        HYPERTEST_CLOUD_API_CA_FILE="/private/issuer-ca.crt",
        HYPERTEST_CLOUD_API_WRAPPING_KEY_FILE="/private/api-wrapping-key",
        HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE="/private/web-operator-key",
        HYPERTEST_CLOUD_CREDENTIAL_KEY_ID="primary", HYPERTEST_CLOUD_WORKER_ENABLED="true")
    return values


def test_cloud_facade_preserves_tcp_listeners_and_limits_private_routes():
    values = configuration()
    stack.validate(values, live=False)
    old = stack.render_nginx({**values, "HYPERTEST_CLOUD_WEB": "disabled"})
    new = stack.render_nginx(values)
    assert new.count("listen ") == old.count("listen ") + 1
    assert "listen unix:/run/hypertest-cloud-web/api.sock ssl;" in new
    assert "listen 203.0.113.10:8080 ssl default_server;" in new
    assert "allow 198.51.100.7/32;" in new
    private = new.split("# Private filesystem transport.", 1)[1]
    assert 'if ($http_host != "203.0.113.10:8080")' in private
    assert "location /api/v1/cloud/" in private
    assert '/api/v1/projects/[0-9a-f-]{36}/task-directory$' in private
    assert "location / { return 404; }" in private
    assert "location /api/v1/ {" not in private
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in private
    assert "real_ip_header" not in new and "$proxy_add_x_forwarded_for" not in new


@pytest.mark.parametrize("key,value", [
    ("HYPERTEST_CLOUD_API_ORIGIN", "http://api:8000"),
    ("HYPERTEST_CLOUD_API_ORIGIN", "https://203.0.113.10:9443"),
    ("HYPERTEST_CLOUD_API_ORIGIN", "https://other.invalid:8080"),
    ("HYPERTEST_CLOUD_API_CA_FILE", "/safe/../wrong"),
    ("HYPERTEST_CLOUD_WORKER_ENABLED", "yes"),
    ("HYPERTEST_INGRESS_TLS", "disabled"),
])
def test_cloud_refuses_origin_drift_and_ambiguous_configuration(key, value):
    with pytest.raises(ValueError):
        stack.validate({**configuration(), key: value}, live=False)


def test_overlay_is_opt_in_and_keeps_secrets_out_of_nginx_and_legacy_worker(tmp_path):
    values = configuration()
    env = tmp_path / "compose.env"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    assert str(ROOT / "ops/container/compose.cloud.yml") in stack.compose_command(env, "config")
    values["HYPERTEST_CLOUD_WEB"] = "disabled"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    assert str(ROOT / "ops/container/compose.cloud.yml") not in stack.compose_command(env, "config")
    overlay = (ROOT / "ops/container/compose.cloud.yml").read_text()
    assert "HYPERTEST_CLOUD_WEB_ENABLED" in overlay and "HYPERTEST_CLOUD_WEB_ORIGIN" in overlay
    assert "  worker:" not in overlay and "  postgres:" not in overlay
    assert "private_key" not in overlay and "  ports:" not in overlay
    nginx = overlay.split("  nginx:", 1)[1]
    assert "WRAPPING_KEY" not in nginx and "OPERATOR_KEY" not in nginx
    web = overlay.split("  web:", 1)[1].split("  nginx:", 1)[0]
    assert "server.key" not in web and "read_only: true" in web
