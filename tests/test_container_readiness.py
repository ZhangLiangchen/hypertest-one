"""Health-only ingress must remain usable without a loopback Web/API bypass."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def readiness_module(monkeypatch):
    # HTTP routing is independent of Docker; do not require a daemon for this check.
    monkeypatch.setitem(sys.modules, "stack", SimpleNamespace(
        compose_command=Mock(), read_env=Mock(), render_nginx=Mock(), validate=Mock(),
        ingress_tls_enabled=Mock(return_value=False),
    ))
    monkeypatch.setitem(sys.modules, "network_guard", SimpleNamespace(guard=Mock()))
    monkeypatch.setitem(sys.modules, "start", SimpleNamespace(verify_daemon=Mock()))
    spec = importlib.util.spec_from_file_location("hypertest_readiness", ROOT / "ops/container/readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("bad_health", [False, True])
def test_readiness_uses_direct_api_capabilities_and_health_only_ingress(monkeypatch, bad_health):
    module = readiness_module(monkeypatch)
    requests = []
    capability = {"harness_bridge": "READY", "runner_backends": ["docker"], "worker": {"available": True}}

    def open_url(url, timeout):
        requests.append((url, timeout))
        if url.endswith("/api/v1/capabilities"):
            assert url == "http://127.0.0.1:18000/api/v1/capabilities"
            payload = capability
        elif url.endswith("/api/v1/health"):
            payload = {"status": "unavailable" if bad_health else "ok"}
        else:
            # A full Web probe via production nginx loopback would be forbidden.
            assert url == "http://127.0.0.1:13000/"
            payload = {}
        response = io.StringIO(json.dumps(payload))
        response.status = 200
        return response

    opener = SimpleNamespace(open=open_url)
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args: opener)
    values = {"HYPERTEST_API_PORT": "18000", "HYPERTEST_WEB_PORT": "13000", "HYPERTEST_INGRESS_PORT": "18080"}
    if bad_health:
        with pytest.raises(ValueError, match="API health response failed"):
            module.check_http(values)
        assert len(requests) == 1
    else:
        module.check_http(values)
        assert requests == [
            ("http://127.0.0.1:18000/api/v1/health", 10),
            ("http://127.0.0.1:13000/", 10),
            ("http://127.0.0.1:18080/api/v1/health", 10),
            ("http://127.0.0.1:18000/api/v1/capabilities", 30),
        ]


def test_tls_readiness_requires_nginx_only_readonly_leaf_mounts(monkeypatch, tmp_path):
    module = readiness_module(monkeypatch)
    values = {"HYPERTEST_TLS_CERT_FILE": str(tmp_path / "server.crt"),
              "HYPERTEST_TLS_KEY_FILE": str(tmp_path / "server.key")}
    mounts = [{"Source": values[key], "Destination": "/run/hypertest-tls/" + name, "Type": "bind", "RW": False}
              for key, name in (("HYPERTEST_TLS_CERT_FILE", "server.crt"), ("HYPERTEST_TLS_KEY_FILE", "server.key"))]
    def inspect(field):
        return []

    module.check_tls_runtime("nginx", values, {}, mounts, inspect)
    mounts[1]["RW"] = True
    with pytest.raises(ValueError, match="read-only"):
        module.check_tls_runtime("nginx", values, {}, mounts, inspect)
    mounts[1]["RW"] = False
    for role in ("api", "worker", "web", "postgres"):
        with pytest.raises(ValueError, match="TLS credential mount"):
            module.check_tls_runtime(role, values, {}, mounts, inspect)
    with pytest.raises(ValueError, match="TLS credential mount"):
        module.check_tls_runtime("worker", values, {}, [{"Source": str(tmp_path), "Destination": "/leaked-directory"}], inspect)


@pytest.mark.parametrize("bad", ["secret", "peers", "command", "insecure"])
def test_tls_readiness_rejects_stale_or_overridden_api_auth_without_disclosing_secrets(monkeypatch, tmp_path, bad):
    module = readiness_module(monkeypatch)
    values = {"HYPERTEST_TLS_CERT_FILE": str(tmp_path / "server.crt"),
              "HYPERTEST_TLS_KEY_FILE": str(tmp_path / "server.key")}
    platform = {"HYPERTEST_CONNECTOR_OPERATOR_KEY": "PRIVATE-TEST-KEY",
                "FORWARDED_ALLOW_IPS": "127.0.0.1,192.0.2.9"}
    environment = dict(platform)
    command = ["uvicorn", "hypertest.main:app", "--host", "0.0.0.0", "--port", "8000"]
    def inspect(field):
        return [f"{key}={value}" for key, value in environment.items()] if field == ".Config.Env" else command

    module.check_tls_runtime("api", values, platform, [], inspect)
    if bad == "secret":
        environment["HYPERTEST_CONNECTOR_OPERATOR_KEY"] = "STALE-TEST-KEY"
    elif bad == "peers":
        environment["FORWARDED_ALLOW_IPS"] = "*"
    elif bad == "insecure":
        environment["HYPERTEST_CONNECTOR_ALLOW_INSECURE_LOOPBACK"] = "true"
    else:
        command.extend(["--forwarded-allow-ips", "*"])
    with pytest.raises(ValueError) as rejected:
        module.check_tls_runtime("api", values, platform, [], inspect)
    assert "PRIVATE-TEST-KEY" not in str(rejected.value) and "STALE-TEST-KEY" not in str(rejected.value)


def test_tls_readiness_rejects_operator_key_in_web_or_nginx(monkeypatch, tmp_path):
    module = readiness_module(monkeypatch)
    values = {"HYPERTEST_TLS_CERT_FILE": str(tmp_path / "server.crt"),
              "HYPERTEST_TLS_KEY_FILE": str(tmp_path / "server.key")}
    with pytest.raises(ValueError, match="unexpectedly has the Operator key"):
        module.check_tls_runtime("web", values, {}, [], lambda field: ["HYPERTEST_CONNECTOR_OPERATOR_KEY=test-only"])
