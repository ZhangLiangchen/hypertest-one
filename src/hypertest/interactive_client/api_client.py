"""Typed-API HTTP transport. Credentials remain inside the local daemon."""
from __future__ import annotations

import json
import re
import ssl

import httpx

from hypertest.interactive_client import MAX_MESSAGE, PROFILE
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_read


class ApiError(ClientError):
    def __init__(self, code: str, status: int = 0):
        self.status = status
        super().__init__(code)


class ApiClient:
    def __init__(self, config: ClientConfig, *, transport=None):
        self.config = config
        self._integration = private_read(config.integration_token_file, max_bytes=4096).decode().strip()
        self._device = (private_read(config.device_token_file, max_bytes=4096).decode().strip()
                        if config.device_token_file else None)
        context = ssl.create_default_context(cafile=str(config.ca_file) if config.ca_file else None)
        self.client = httpx.AsyncClient(base_url=config.api_url + "/", verify=context,
                                       timeout=config.timeout_seconds, follow_redirects=False,
                                       trust_env=False, transport=transport)

    async def request(self, method: str, path: str, *, payload=None, params=None,
                      device: bool = False, execution_token: str | None = None,
                      request_key: str | None = None) -> dict:
        if not path.startswith("interactive/") or ".." in path or ":" in path:
            raise ApiError("INVALID_API_ROUTE")
        headers = {"Authorization": "Bearer " + self._integration,
                   "X-Hypertest-Interactive-Profile": PROFILE}
        if device:
            if not self._device:
                raise ApiError("DEVICE_IDENTITY_REQUIRED")
            headers["X-Hypertest-Device-Token"] = self._device
        if execution_token:
            headers["X-Hypertest-Execution-Token"] = execution_token
        if request_key:
            headers["X-Hypertest-Request-Key"] = request_key
        try:
            async with self.client.stream(method, path, json=payload, params=params,
                                          headers=headers) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_MESSAGE:
                        raise ApiError("API_RESPONSE_TOO_LARGE")
                if not 200 <= response.status_code < 300:
                    code = "PLATFORM_REQUEST_REJECTED"
                    try:
                        detail = json.loads(raw).get("detail")
                        candidate = detail.get("code") if isinstance(detail, dict) else detail
                        if isinstance(candidate, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", candidate):
                            code = candidate
                    except (ValueError, TypeError, AttributeError):
                        pass
                    raise ApiError(code, response.status_code)
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ApiError("INVALID_PLATFORM_RESPONSE")
                return result
        except (httpx.HTTPError, TimeoutError) as exc:
            raise ApiError("PLATFORM_UNAVAILABLE") from exc
        except (ValueError, UnicodeError) as exc:
            raise ApiError("INVALID_PLATFORM_RESPONSE") from exc

    async def capabilities(self) -> dict:
        value = await self.request("GET", "interactive/capabilities")
        if value.get("profile") != PROFILE:
            raise ApiError("INTERACTIVE_PROFILE_UNSUPPORTED")
        return value

    async def close(self):
        await self.client.aclose()
