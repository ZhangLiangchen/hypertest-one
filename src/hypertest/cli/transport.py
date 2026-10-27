"""Bounded HTTPS JSON transport. No redirects, ambient auth, retries, or secret logs."""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from hypertest.cli.state import CLIError
from hypertest.sync_core import canonical_json


def server_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in {"", "/"}):
        raise CLIError("HTTPS_SERVER_ORIGIN_REQUIRED", 5)
    try:
        _ = parts.port
    except ValueError as exc:
        raise CLIError("HTTPS_SERVER_ORIGIN_REQUIRED", 5) from exc
    return f"https://{parts.netloc.lower()}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTP:
    def __init__(self, server: str, *, token: str | None = None, proof: str | None = None,
                 timeout: float = 20):
        self.server, self.token, self.proof = server_url(server), token, proof
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def call(self, method: str, path: str, *, query: dict | None = None,
             body: dict | None = None) -> dict:
        if (not path.startswith(("/api/v1/local-archive/", "/api/v1/cli-authorizations/"))
                or "?" in path or "#" in path or ".." in path):
            raise CLIError("API_ROUTE_REJECTED", 5)
        target = self.server + path
        if query:
            target += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.proof:
            headers["X-Hypertest-Pairing-Proof"] = self.proof
        request = urllib.request.Request(target, headers=headers, method=method,
                                         data=canonical_json(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            code = "HTTP_REJECTED"
            try:
                error = json.loads(exc.read(32768))
                detail = error.get("detail", error)
                candidate = detail.get("code") if isinstance(detail, dict) else detail
                if isinstance(candidate, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", candidate):
                    code = candidate
            except (ValueError, OSError):
                pass
            raise CLIError(code, 3 if 400 <= exc.code < 500 else 4, status=exc.code) from None
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise CLIError("TRANSPORT_UNCERTAIN", 4) from exc
        if len(data) > 4 * 1024 * 1024:
            raise CLIError("RESPONSE_LIMIT_EXCEEDED", 4)
        try:
            value = json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise CLIError("INVALID_SERVER_RESPONSE", 4) from exc
        if not isinstance(value, dict):
            raise CLIError("INVALID_SERVER_RESPONSE", 4)
        return value
