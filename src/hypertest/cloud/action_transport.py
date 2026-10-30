"""Host-only single authenticated HTTPS send for a frozen action.

This is not an Agent API and does not grant a send. The private broker must
persist the original SENT receipt and pass a fresh authority recheck. The
caller must verify the project signature using the pinned trusted adapter.
"""
from __future__ import annotations

import asyncio
import hashlib
import ssl
from urllib.parse import urlsplit

import httpx

from .action_body import validate_prepared_body
from .action_profile import validate_action_profile
from .action_resolver import resolve_action_public
from .errors import CloudBlocked
from .http_profile import public_address
from .http_transport import HttpExchange


def _blocked(code="CONTROLLED_ACTION_TRANSPORT_INVALID"):
    return CloudBlocked(code, "Controlled action transport failed closed")


class ActionTransport:
    def __init__(self, *, resolver=None, transport=None, tls_context=None):
        self.resolver = resolver or resolve_action_public
        self.transport = transport
        self.tls = tls_context or ssl.create_default_context()
        if self.tls.verify_mode != ssl.CERT_REQUIRED or not self.tls.check_hostname:
            raise _blocked()

    async def send(self, *, profile, action_key, client_ref, unique_ref, body, sent_body_sha256,
                   api_key, timeout, verify_signature, before_send):
        profile = validate_action_profile(profile)
        actions = [item for item in profile["actions"] if item["action_key"] == action_key]
        if (len(actions) != 1 or not isinstance(api_key, bytes) or not 1 <= len(api_key) <= 4096
                or any(byte < 33 or byte > 126 for byte in api_key)
                or type(timeout) not in (int, float) or not 0 < timeout <= 15):
            raise _blocked()
        action = actions[0]
        verified = validate_prepared_body(profile, action_key=action_key, client_ref=client_ref,
                                          unique_ref=unique_ref, body=body)
        if (not isinstance(sent_body_sha256, str) or verified["body_sha256"] != sent_body_sha256
                or hashlib.sha256(body).hexdigest() != sent_body_sha256):
            raise _blocked()
        # This callback is supplied by the trusted, fixed project adapter, not
        # by the Agent; a mere signature-shaped string grants no send right.
        if await verify_signature(action, body) is not True:
            raise _blocked("CONTROLLED_ACTION_SIGNATURE_INVALID")
        target = urlsplit(profile["target"])
        async with asyncio.timeout(timeout):
            try:
                addresses = await self.resolver(target.hostname, target.port)
                if (not isinstance(addresses, (tuple, list)) or not addresses or len(addresses) > 8
                        or any(public_address(address) not in profile["allowed_addresses"] for address in addresses)):
                    raise _blocked("CONTROLLED_ACTION_DNS_REFUSED")
                address = sorted(set(addresses))[0]
                await before_send(sent_body_sha256)
                host = f"[{address}]" if ":" in address else address
                authority = f"[{target.hostname}]" if ":" in target.hostname else target.hostname
                request = httpx.Request("POST", f"https://{host}:{target.port}{action['path']}",
                    headers={"Host": f"{authority}:{target.port}", "Content-Type": "application/json",
                             "Accept": "application/json", "Accept-Encoding": "identity",
                             "X-Api-Key": api_key.decode("ascii")}, content=body,
                    extensions={"sni_hostname": target.hostname,
                                "timeout": {key: timeout for key in ("connect", "read", "write", "pool")}})
                transport = self.transport or httpx.AsyncHTTPTransport(verify=self.tls, retries=0,
                    http1=True, http2=False, trust_env=False,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
                async with httpx.AsyncClient(transport=transport, trust_env=False,
                        follow_redirects=False, timeout=timeout) as client:
                    response = await client.send(request, stream=True, follow_redirects=False)
                    try:
                        if (not 200 <= response.status_code <= 599
                                or sum(len(key) + len(value) for key, value in response.headers.raw) > 16384
                                or response.headers.get("content-encoding", "identity").lower() != "identity"):
                            raise _blocked("CONTROLLED_ACTION_OUTPUT_INVALID")
                        length = response.headers.get("content-length")
                        if length is not None and (not length.isdecimal() or int(length) > 262144):
                            raise _blocked("CONTROLLED_ACTION_OUTPUT_INVALID")
                        chunks, total = [], 0
                        async for chunk in response.aiter_raw():
                            total += len(chunk)
                            if total > 262144:
                                raise _blocked("CONTROLLED_ACTION_OUTPUT_INVALID")
                            chunks.append(chunk)
                        return HttpExchange(response.status_code, b"".join(chunks))
                    finally:
                        await response.aclose()
            except (OSError, ValueError, httpx.HTTPError):
                # Exception strings can contain authentication headers and URLs.
                raise _blocked("CONTROLLED_ACTION_TRANSPORT_UNKNOWN") from None
