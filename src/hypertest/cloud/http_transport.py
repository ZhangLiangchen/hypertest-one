"""One bounded host-only HTTPS request to a pinned public address.

The namespace never gets DNS/TCP access. No redirects, proxy environment,
connection retry, cookies from earlier calls or user-supplied headers are used.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from .http_profile import HttpProfile, HttpResource, blocked, public_address


@dataclass(frozen=True)
class HttpExchange:
    status: int
    body: bytes


async def resolve_public(host, port):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        answers = await asyncio.get_running_loop().getaddrinfo(host, port,
            type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        if not 1 <= len(answers) <= 64:
            raise blocked("HTTPS_DNS_REFUSED") from None
        values = {public_address(answer[4][0]) for answer in answers}
    else:
        values = {public_address(host)}
    if not values:
        raise blocked("HTTPS_DNS_REFUSED")
    return sorted(values)


class HttpsTransport:
    def __init__(self, *, resolver=None, transport=None, tls_context=None):
        # Dependency injection is a host-side test seam; none of these values is
        # accepted from the namespace, resource catalog or model handoff.
        self.resolver = resolver or resolve_public
        self.transport = transport
        self.tls = tls_context or ssl.create_default_context()
        if self.tls.verify_mode != ssl.CERT_REQUIRED or not self.tls.check_hostname:
            raise blocked("HTTPS_TLS_REQUIRED")

    async def send(self, profile: HttpProfile, resource: HttpResource, *, timeout: float,
                   before_send: Callable[[], Awaitable[None]]) -> HttpExchange:
        if (type(timeout) not in {int, float} or not 0 < timeout <= resource.timeout_seconds
                or resource != profile.resource(resource.key)):
            raise blocked("HTTPS_TIMEOUT_INVALID")
        # The complete resolution/admission/connect/read sequence has one finite
        # deadline. DNS is checked once, and the selected literal is used for TCP.
        async with asyncio.timeout(timeout):
            try:
                addresses = await self.resolver(profile.host, profile.port)
                if (not isinstance(addresses, (tuple, list)) or not addresses
                        or len(addresses) > 8 or any(public_address(address) not in profile.allowed_addresses
                                                  for address in addresses)):
                    raise blocked("HTTPS_DNS_REFUSED")
                address = sorted(set(addresses))[0]
                await before_send()  # Recheck current lease/authorization after DNS.
                pinned_host = f"[{address}]" if ":" in address else address
                authority = f"[{profile.host}]" if ":" in profile.host else profile.host
                host_header = f"{authority}:{profile.port}"
                # httpcore 1.0.9 uses sni_hostname for both TLS SNI and certificate
                # hostname checking. TCP uses the literal URL host; Host retains
                # the authorized origin. There is no second target DNS lookup.
                request = httpx.Request(resource.method,
                    f"https://{pinned_host}:{profile.port}{resource.path}",
                    headers={"Host": host_header, "Accept": "application/json, text/plain, */*",
                             "Accept-Encoding": "identity"},
                    extensions={"sni_hostname": profile.host,
                                "timeout": {key: timeout for key in ("connect", "read", "write", "pool")}})
                transport = self.transport or httpx.AsyncHTTPTransport(verify=self.tls, retries=0,
                    http1=True, http2=False, trust_env=False,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
                async with httpx.AsyncClient(transport=transport, trust_env=False,
                        follow_redirects=False, timeout=timeout) as client:
                    response = await client.send(request, stream=True, follow_redirects=False)
                    try:
                        if sum(len(key) + len(value) for key, value in response.headers.raw) > 16384:
                            raise blocked("HTTPS_OUTPUT_LIMIT")
                        if not 200 <= response.status_code <= 599:
                            raise blocked("HTTPS_STATUS_UNSUPPORTED")
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise blocked("HTTPS_ENCODING_UNSUPPORTED")
                        content_length = response.headers.get("content-length")
                        if (resource.method != "HEAD" and content_length is not None
                                and (not content_length.isdecimal()
                                    or int(content_length) > resource.response_limit_bytes)):
                            raise blocked("HTTPS_OUTPUT_LIMIT")
                        chunks, total = [], 0
                        async for chunk in response.aiter_raw():
                            total += len(chunk)
                            if total > resource.response_limit_bytes or (resource.method == "HEAD" and chunk):
                                raise blocked("HTTPS_OUTPUT_LIMIT")
                            chunks.append(chunk)
                        return HttpExchange(response.status_code, b"".join(chunks))
                    finally:
                        await response.aclose()
            except (OSError, ValueError, httpx.HTTPError):
                # HTTP exceptions often contain secret-bearing server text or
                # redirected URLs. Only a fixed code leaves this transport.
                raise blocked("HTTPS_TRANSPORT_UNKNOWN") from None
