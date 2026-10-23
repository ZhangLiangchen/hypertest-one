"""Attempt-local model-only capability over a Unix socket.

The sandbox has no network interface except loopback. Its relay can POST only
the official DeepSeek Messages inference for the configured model. The real API key stays in this host
process, outside model tools, environment and filesystem mounts.
"""
from __future__ import annotations

import json
import math
import os
import socket
import socketserver
import ssl
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .errors import CloudBlocked

REFUSED_CATEGORIES = frozenset({"FRAMING", "JSON", "ENDPOINT", "MODEL", "TOKENS",
    "MESSAGE_SCHEMA", "UNAPPROVED_EXTENSION", "IDENTITY", "CLOSED", "REQUEST_LIMIT", "DEADLINE", "OTHER"})

_VALIDATION_CATEGORIES = {
    "operation": "ENDPOINT", "model": "MODEL", "tokens": "TOKENS",
    "oauth-expired": "IDENTITY", "outside-native-responses-capability": "MESSAGE_SCHEMA",
    "remote-content-forbidden": "MESSAGE_SCHEMA", "messages-extension-fields": "UNAPPROVED_EXTENSION",
    **{reason: "MESSAGE_SCHEMA" for reason in (
        "messages-fields", "messages-thinking", "messages-output-config", "messages-system",
        "messages-temperature", "messages-stop", "messages-tools", "messages-hosted-tool",
        "messages-history", "messages-content", "messages-block", "messages-nontext-result",
        "messages-remote-or-unsupported-content", "messages-role")},
}


class _RequestRefused(ValueError):
    """Internal fixed category; never retains a request field or native error."""
    def __init__(self, category: str):
        self.category = category if category in REFUSED_CATEGORIES else "OTHER"
        super().__init__("Model request refused")


def refusal_category(error: Exception) -> str:
    """Map known validator failures only; arbitrary exception text never escapes."""
    if isinstance(error, _RequestRefused):
        return error.category if error.category in REFUSED_CATEGORIES else "OTHER"
    if isinstance(error, json.JSONDecodeError):
        return "JSON"
    if isinstance(error, ValueError) and len(error.args) == 1 and type(error.args[0]) is str:
        return _VALIDATION_CATEGORIES.get(error.args[0], "OTHER")
    return "OTHER"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ModelBroker:
    def __init__(self, socket_path: Path, *, base_url: str, api_key: bytes,
                 model: str, max_requests: int = 100, max_tokens: int = 8192,
                 deadline: float | None = None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"", "/anthropic", "/anthropic/v1"}):
            raise CloudBlocked("MODEL_ENDPOINT_INVALID", "Model broker requires an explicit HTTPS API origin")
        if not api_key or b"\r" in api_key or b"\n" in api_key:
            raise CloudBlocked("MODEL_IDENTITY_UNAVAILABLE", "Model service identity is unavailable")
        self.path = socket_path
        self.base_url, self._key, self.model = base_url.rstrip("/"), api_key, model
        path = parsed.path.rstrip("/") or "/anthropic"
        self.messages_url = f"{parsed.scheme}://{parsed.netloc}{path}" + ("" if path.endswith("/v1") else "/v1") + "/messages"
        self.max_requests, self.max_tokens, self.requests = max_requests, max_tokens, 0
        self.lock = threading.Lock()
        self.deadline = deadline
        self.closed = False
        self.inflight = 0
        self.upstream_successes = 0
        self.upstream_completed = 0
        self.upstream_status_counts: dict[str, int] = {}
        self.transport_failure_counts: dict[str, int] = {}
        self.refused_scope_count = 0
        self.refused_category_counts: dict[str, int] = {}
        self._responses = set()
        self.server = None

    def prepare_request(self, path: str, payload: dict) -> urllib.request.Request:
        """Only model inference; subclasses must supply equally narrow contracts."""
        if path != "/v1/messages":
            raise ValueError("operation")
        if not isinstance(payload, dict) or payload.get("model") != self.model:
            raise ValueError("model")
        validate_messages(payload)
        requested = payload.get("max_tokens", self.max_tokens)
        if type(requested) is not int or not 0 < requested <= self.max_tokens:
            raise ValueError("tokens")
        payload["max_tokens"] = requested
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
            "x-api-key": self._key.decode(), "anthropic-version": "2023-06-01"}
        if any(block["type"] in {"tool_addition", "tool_removal"} for message in payload["messages"] for block in message["content"]):
            headers["anthropic-beta"] = "mid-conversation-tool-changes-2026-07-01"
        return urllib.request.Request(self.messages_url,
            data=json.dumps(payload).encode(), method="POST",
            headers=headers)

    def observation(self) -> dict:
        with self.lock:
            return {"closed": self.closed, "requests": self.requests,
                    "inflight": self.inflight, "drained": self.closed and self.inflight == 0,
                    "upstream_successes": self.upstream_successes,
                    "upstream_completed": self.upstream_completed,
                    "upstream_status_counts": dict(self.upstream_status_counts),
                    "transport_failure_counts": dict(self.transport_failure_counts),
                    "refused_scope_count": self.refused_scope_count,
                    "refused_category_counts": dict(self.refused_category_counts)}

    def __enter__(self):
        broker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                admitted = False
                response = None
                try:
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except (TypeError, ValueError):
                        raise _RequestRefused("FRAMING") from None
                    if not 0 < length <= 8 * 1024 * 1024:
                        raise _RequestRefused("FRAMING")
                    payload = json.loads(self.rfile.read(length))
                    request = broker.prepare_request(self.path, payload)
                    with broker.lock:
                        if broker.closed:
                            raise _RequestRefused("CLOSED")
                        if broker.requests >= broker.max_requests:
                            raise _RequestRefused("REQUEST_LIMIT")
                        if broker.deadline is not None and time.monotonic() >= broker.deadline:
                            raise _RequestRefused("DEADLINE")
                        broker.requests += 1
                        broker.inflight += 1
                        admitted = True
                    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
                    timeout = 60 if broker.deadline is None else min(60, max(0.1, broker.deadline - time.monotonic()))
                    with opener.open(request, timeout=timeout) as response:
                        with broker.lock:
                            broker._responses.add(response)
                            status = str(response.status) if type(response.status) is int and 100 <= response.status <= 599 else "OTHER"
                            broker.upstream_status_counts[status] = broker.upstream_status_counts.get(status, 0) + 1
                            if 200 <= response.status < 300:
                                broker.upstream_successes += 1
                        self.send_response(response.status)
                        self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        total = 0
                        while chunk := response.read(65536):
                            total += len(chunk)
                            if (total > 32 * 1024 * 1024 or broker.closed
                                    or (broker.deadline is not None and time.monotonic() >= broker.deadline)):
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        else:
                            with broker.lock:
                                if 200 <= response.status < 300:
                                    broker.upstream_completed += 1
                except Exception as error:
                    with broker.lock:
                        if not admitted:
                            broker.refused_scope_count += 1
                            category = refusal_category(error)
                            broker.refused_category_counts[category] = min(
                                1000000, broker.refused_category_counts.get(category, 0) + 1)
                        elif isinstance(error, urllib.error.HTTPError):
                            code = error.code
                            status = str(code) if type(code) is int and 100 <= code <= 599 else "OTHER"
                            broker.upstream_status_counts[status] = broker.upstream_status_counts.get(status, 0) + 1
                        else:
                            category = transport_category(error)
                            broker.transport_failure_counts[category] = broker.transport_failure_counts.get(category, 0) + 1
                    # Never relay upstream errors/headers that may contain credentials.
                    self.close_connection = True
                    try:
                        self.send_error(502, "Model request unavailable or outside capability limits")
                    except OSError:
                        pass
                finally:
                    with broker.lock:
                        if response is not None:
                            broker._responses.discard(response)
                        if admitted:
                            broker.inflight -= 1

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.server = Server(str(self.path), Handler)
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        with self.lock:
            self.closed = True
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
        # A daemon request thread is not evidence of stopped model work. Closing
        # its response is best effort; outstanding opens remain observable and
        # the Worker must retain the durable budget reservation in that case.
        with self.lock:
            responses = tuple(self._responses)
        for response in responses:
            try:
                # shutdown does not wait for another thread's buffered-read
                # lock, unlike HTTPResponse.close(). Unknown transports remain
                # inflight and cannot release a reservation.
                response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
        until = time.monotonic() + 2
        while self.observation()["inflight"] and time.monotonic() < until:
            time.sleep(0.01)
        self.path.unlink(missing_ok=True)
        self._key = b""


def transport_category(error: Exception) -> str:
    """Allowlisted observations only; never render provider exception text."""
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, socket.gaierror):
        return "DNS"
    if isinstance(cause, ssl.SSLError):
        return "TLS"
    if isinstance(cause, TimeoutError):
        return "TIMEOUT"
    if isinstance(cause, (ConnectionError, OSError)):
        return "CONNECT"
    return "OTHER"


def validate_messages(payload: dict) -> None:
    """Fixed Harness serialize.ts WireRequest: text and client-executed tools.

    No provider-side image/file retrieval, hosted search, dynamic endpoint or
    unknown extension is admitted. Arbitrary tool input/output remains data for
    the namespace's existing local tool executor, not a provider-hosted action.
    """
    allowed = {"model", "stream", "max_tokens", "messages", "system", "thinking", "output_config",
               "temperature", "stop_sequences", "tools"}
    if set(payload) - allowed:
        raise ValueError("messages-extension-fields")
    if payload.get("stream") is not True:
        raise ValueError("messages-fields")
    if payload.get("thinking") not in ({"type": "enabled"}, {"type": "disabled"}):
        raise ValueError("messages-thinking")
    if "output_config" in payload and payload["output_config"] not in (
            {"effort": "low"}, {"effort": "high"}, {"effort": "max"}):
        raise ValueError("messages-output-config")
    if "system" in payload and not isinstance(payload["system"], str):
        raise ValueError("messages-system")
    if "temperature" in payload and (type(payload["temperature"]) not in {int, float}
            or not math.isfinite(payload["temperature"]) or not 0 <= payload["temperature"] <= 2):
        raise ValueError("messages-temperature")
    if "stop_sequences" in payload and (not isinstance(payload["stop_sequences"], list)
            or len(payload["stop_sequences"]) > 32 or not all(isinstance(item, str) for item in payload["stop_sequences"])):
        raise ValueError("messages-stop")
    tools = payload.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 512:
        raise ValueError("messages-tools")
    for tool in tools:
        if (not isinstance(tool, dict) or set(tool) - {"name", "description", "input_schema", "defer_loading"}
                or not isinstance(tool.get("name"), str) or not tool["name"]
                or not isinstance(tool.get("description"), str) or not isinstance(tool.get("input_schema"), dict)
                or ("defer_loading" in tool and tool["defer_loading"] is not True)):
            raise ValueError("messages-hosted-tool")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 10000:
        raise ValueError("messages-history")

    def blocks(content, *, results=False):
        if not isinstance(content, list) or len(content) > 10000:
            raise ValueError("messages-content")
        for block in content:
            if not isinstance(block, dict):
                raise ValueError("messages-block")
            kind = block.get("type")
            if kind == "text" and set(block) == {"type", "text"} and isinstance(block["text"], str):
                continue
            if results:
                raise ValueError("messages-nontext-result")
            if (kind == "thinking" and set(block) <= {"type", "thinking", "signature"}
                    and isinstance(block.get("thinking"), str)
                    and ("signature" not in block or isinstance(block["signature"], str))):
                continue
            if (kind == "tool_use" and set(block) == {"type", "id", "name", "input"}
                    and isinstance(block["id"], str) and isinstance(block["name"], str)
                    and isinstance(block["input"], dict)):
                continue
            if (kind == "tool_result" and set(block) <= {"type", "tool_use_id", "content", "is_error"}
                    and isinstance(block.get("tool_use_id"), str)
                    and ("is_error" not in block or type(block["is_error"]) is bool)):
                blocks(block.get("content"), results=True)
                continue
            if (kind in {"tool_addition", "tool_removal"} and set(block) == {"type", "tool"}
                    and isinstance(block["tool"], dict) and set(block["tool"]) == {"type", "name"}
                    and block["tool"]["type"] == "tool_reference" and isinstance(block["tool"]["name"], str)):
                continue
            raise ValueError("messages-remote-or-unsupported-content")
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in {"user", "assistant", "system"}):
            raise ValueError("messages-role")
        blocks(message["content"])


def start_sandbox_relay(socket_path: str, *, port: int = 0):
    """Run inside the network namespace; broker enforces target/method/model."""
    import http.client
    import socket

    class UnixConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(90)
            self.sock.connect(socket_path)

    class Relay(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            connection = UnixConnection("model-broker")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8 * 1024 * 1024:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                connection.request("POST", self.path, body, {"Content-Type": "application/json"})
                response = connection.getresponse()
                self.send_response(response.status)
                self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
                self.send_header("Connection", "close")
                self.end_headers()
                while data := response.read(65536):
                    self.wfile.write(data)
                    self.wfile.flush()
            except Exception:
                self.close_connection = True
            finally:
                connection.close()

    server = ThreadingHTTPServer(("127.0.0.1", port), Relay)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
