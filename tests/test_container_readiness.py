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
