"""Host-only, read-only Cloud Codex OAuth snapshot and Responses capability.

No login/refresh operation exists here. The original cloud login is never
mounted, copied to the child HOME, or returned in a public observation.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CloudBlocked
from .model_broker import ModelBroker
from .private_file import read_private_file

CODEX_SOURCE_COMMIT = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"


@dataclass(frozen=True)
class CodexOAuthIdentity:
    access_token: str = field(repr=False)
    account_id: str = field(repr=False)
    expires_at: int


def read_cloud_codex_identity(path: str | Path, *, required_seconds: int = 60,
                             now: float | None = None) -> CodexOAuthIdentity:
    """Read only an operator-selected existing cloud credential file.

    JWT expiry is a conservative local freshness check, not signature or
    account verification; only the actual upstream request proves acceptance.
    Refresh tokens, id tokens, login history and native settings are unused.
    """
    try:
        try:
            raw = read_private_file(path, max_bytes=256 * 1024)
        except CloudBlocked:
            raise ValueError("private-file-required") from None
        document = json.loads(raw)
        tokens = document.get("tokens")
        if not isinstance(tokens, dict) or document.get("auth_mode") not in {None, "chatgpt"}:
            raise ValueError("oauth-required")
        token, account = tokens.get("access_token"), tokens.get("account_id")
        if (not isinstance(token, str) or not 1 <= len(token) <= 65536
                or not re.fullmatch(r"[A-Za-z0-9._~-]+", token)
                or not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", account)):
            raise ValueError("oauth-snapshot-invalid")
        pieces = token.split(".")
        if len(pieces) != 3:
            raise ValueError("expiry-unavailable")
        claims = json.loads(base64.urlsafe_b64decode(pieces[1] + "=" * (-len(pieces[1]) % 4)))
        expires = claims.get("exp")
        if type(expires) is not int:
            raise ValueError("expiry-unavailable")
        if expires <= (time.time() if now is None else now) + required_seconds:
            raise CloudBlocked("CODEX_OAUTH_EXPIRED", "Cloud Codex OAuth must remain valid for the entire bounded attempt; explicit cloud reauthentication is required")
        return CodexOAuthIdentity(token, account, expires)
    except CloudBlocked:
        raise
    except Exception:
        raise CloudBlocked("CODEX_OAUTH_UNAVAILABLE", "Configure a private existing cloud Codex OAuth file; no login is imported or refreshed automatically") from None


def _local_tools(tools: object, depth: int = 0) -> bool:
    if not isinstance(tools, list) or len(tools) > 512 or depth > 4:
        return False
    for tool in tools:
        if not isinstance(tool, dict):
            return False
        kind = tool.get("type")
        if kind == "namespace":
            if not _local_tools(tool.get("tools"), depth + 1):
                return False
        elif kind == "tool_search":
            if tool.get("execution") != "client":
                return False
        elif kind not in {"function", "custom", "local_shell"}:
            return False
    return True


class CodexOAuthBroker(ModelBroker):
    """Only one pinned Codex model's streaming Responses, no hosted tools.

    OAuth is accounted in frozen REQUEST_CREDITS. Codex's native request has no
    max_output_tokens field; this adapter makes no token-price/USD claim.
    """
    def __init__(self, socket_path: Path, *, identity: CodexOAuthIdentity,
                 model: str, max_requests: int, deadline: float | None = None):
        super().__init__(socket_path, base_url="https://chatgpt.com", api_key=identity.access_token.encode(),
                         model=model, max_requests=max_requests, deadline=deadline)
        self._identity = identity

    def prepare_request(self, path: str, payload: dict) -> urllib.request.Request:
        if path not in {"/responses", "/v1/responses"}:
            raise ValueError("operation")
        if self._identity.expires_at <= time.time():
            raise ValueError("oauth-expired")
        if (not isinstance(payload, dict) or payload.get("model") != self.model
                or payload.get("stream") is not True or payload.get("store") is not False
                or payload.get("background") not in {None, False}
                or payload.get("previous_response_id") is not None
                or not _local_tools(payload.get("tools", []))):
            raise ValueError("outside-native-responses-capability")
        # Images / audio / files with URLs can cause provider-side retrieval.
        # This profile accepts source text and native local-tool exchange only.
        def no_remote_content(value, depth=0):
            if depth > 40:
                return False
            if isinstance(value, dict):
                if value.get("type") in {"input_image", "input_audio", "input_file", "input_video"}:
                    return False
                return all(no_remote_content(item, depth + 1) for item in value.values())
            if isinstance(value, list):
                return all(no_remote_content(item, depth + 1) for item in value)
            return True
        if not no_remote_content(payload.get("input")):
            raise ValueError("remote-content-forbidden")
        return urllib.request.Request(CODEX_RESPONSES_URL,
            data=json.dumps(payload).encode(), method="POST", headers={
                "Content-Type": "application/json", "Accept": "text/event-stream",
                "Authorization": "Bearer " + self._identity.access_token,
                "ChatGPT-Account-ID": self._identity.account_id,
                "User-Agent": "hypertest-cloud-codex/0.153.4", "originator": "codex_cli_rs"})

    def __exit__(self, *args):
        super().__exit__(*args)
        # Retain no usable bearer in the stopped broker object.
        self._identity = CodexOAuthIdentity("", "", 0)
