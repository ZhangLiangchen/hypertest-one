"""Refused requests produce fixed metadata, never request or exception text."""
import http.client
import json
import socket
import time

import pytest

from hypertest.cloud.model_broker import REFUSED_CATEGORIES, ModelBroker, refusal_category


def messages(**changes):
    return {"model": "fixture", "stream": True, "max_tokens": 512,
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Synthetic requirement"}]}],
        **changes}


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("model-broker", timeout=3)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


@pytest.mark.parametrize("category,path,payload,headers", [
    # Invalid framing is refused from the headers before any body is read. Send
    # headers only so a separate body write cannot race the server's close.
    ("FRAMING", "/v1/messages", None, {"Content-Length": "private-invalid-length"}),
    ("JSON", "/v1/messages", b"{private-invalid-json", {}),
    ("ENDPOINT", "/private-unadmitted-path", messages(), {}),
    ("MODEL", "/v1/messages", messages(model="private-unadmitted-model"), {}),
    ("TOKENS", "/v1/messages", messages(max_tokens=513), {}),
    ("MESSAGE_SCHEMA", "/v1/messages", messages(stream=False), {}),
    ("MESSAGE_SCHEMA", "/v1/messages", messages(messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://private.invalid/image"}}]}]), {}),
    ("UNAPPROVED_EXTENSION", "/v1/messages", messages(dsh_session_log={"events": ["private-session-original"]}), {}),
])
def test_refusal_categories_observe_real_uds_admission_without_upstream_or_body_leaks(
        tmp_path, monkeypatch, category, path, payload, headers):
    upstream = []

    def unexpected_upstream(*args):
        upstream.append(True)
        raise AssertionError("Refused input must never reach an upstream opener")

    monkeypatch.setattr("hypertest.cloud.model_broker.urllib.request.build_opener", unexpected_upstream)
    broker = ModelBroker(tmp_path / "model.sock", base_url="https://api.deepseek.com/anthropic",
        api_key=b"private-host-identity", model="fixture", max_tokens=512)
    body = json.dumps(payload).encode() if isinstance(payload, dict) else payload
    with broker:
        connection = UnixConnection(broker.path)
        try:
            connection.request("POST", path, body, {"Content-Type": "application/json", **headers})
            response = connection.getresponse()
            assert response.status == 502
            public_response = response.read().decode()
        finally:
            connection.close()
    observed = broker.observation()
    assert observed["requests"] == 0 and observed["inflight"] == 0 and observed["drained"] is True
    assert observed["refused_scope_count"] == 1
    assert observed["refused_category_counts"] == {category: 1}
    assert set(observed["refused_category_counts"]) <= REFUSED_CATEGORIES
    assert "private-" not in json.dumps(observed) + public_response
    assert upstream == []
    observed["refused_category_counts"]["private-injected-field"] = 100
    assert broker.observation()["refused_category_counts"] == {category: 1}


@pytest.mark.parametrize("category", ["CLOSED", "REQUEST_LIMIT", "DEADLINE"])
def test_local_lifecycle_and_budget_refusals_remain_separate_from_transport_failures(tmp_path, category):
    broker = ModelBroker(tmp_path / "model.sock", base_url="https://api.deepseek.com/anthropic",
        api_key=b"private-host-identity", model="fixture", max_tokens=512, max_requests=1)
    with broker:
        with broker.lock:
            if category == "CLOSED":
                broker.closed = True
            elif category == "REQUEST_LIMIT":
                broker.requests = 1  # Synthetic already-admitted request slot.
            else:
                broker.deadline = time.monotonic() - 1
        connection = UnixConnection(broker.path)
        try:
            connection.request("POST", "/v1/messages", json.dumps(messages()))
            response = connection.getresponse()
            assert response.status == 502
            response.read()
        finally:
            connection.close()
    observed = broker.observation()
    assert observed["refused_category_counts"] == {category: 1}
    assert observed["requests"] == (1 if category == "REQUEST_LIMIT" else 0)
    assert observed["transport_failure_counts"] == {} and observed["upstream_status_counts"] == {}


@pytest.mark.parametrize("error,expected", [
    (ValueError("operation"), "ENDPOINT"),
    (ValueError("oauth-expired"), "IDENTITY"),
    (ValueError("outside-native-responses-capability"), "MESSAGE_SCHEMA"),
    (ValueError("private arbitrary exception contains an API key"), "OTHER"),
    (RuntimeError("private arbitrary native exception"), "OTHER"),
    (ValueError({"private": "unexpected non-string payload"}), "OTHER"),
])
def test_only_known_failure_labels_become_public_categories(error, expected):
    assert refusal_category(error) == expected
    assert refusal_category(error) in REFUSED_CATEGORIES
