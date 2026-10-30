"""Fixed, public DNS-over-HTTPS resolver for controlled actions.

The resolver is trusted Worker infrastructure, never an Agent input.  It uses
one fixed public Cloudflare resolver address with its original TLS hostname and
does not grant the action permission to send.  Callers must still require all
returned addresses to belong to the separately frozen target pin set.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import ssl

import httpx

from .errors import CloudBlocked
from .http_profile import canonical_host, public_address

_PROVIDER_ADDRESS = "1.1.1.1"
_PROVIDER_HOST = "cloudflare-dns.com"
_PROVIDER_URL = "https://1.1.1.1:443/dns-query"
_MAX_RESPONSE = 32768
_MAX_ANSWERS = 32
_MAX_ADDRESSES = 8


def _blocked() -> CloudBlocked:
    return CloudBlocked("CONTROLLED_ACTION_DNS_REFUSED", "Controlled action DNS resolution failed closed")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _dns_name(value):
    if not isinstance(value, str) or not value or value.endswith(".."):
        raise ValueError
    name = value.removesuffix(".").lower()
    if canonical_host(name) != name:
        raise ValueError
    # A CNAME target and DNS owner must be names, never literal addresses.
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name
    raise ValueError


def parse_answer(raw: bytes, host: str, record_type: int) -> tuple[list[str], str]:
    """Accept only the asked name, a single reachable CNAME chain, and public IPs."""
    try:
        if (not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE
                or record_type not in (1, 28) or canonical_host(host) != host):
            raise ValueError
        document = json.loads(raw, object_pairs_hook=_unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (not isinstance(document, dict) or type(document.get("Status")) is not int
                or document["Status"] != 0 or document.get("TC", False) is not False):
            raise ValueError
        questions = document.get("Question")
        if (not isinstance(questions, list) or len(questions) != 1 or not isinstance(questions[0], dict)
                or _dns_name(questions[0].get("name")) != host
                or type(questions[0].get("type")) is not int or questions[0]["type"] != record_type):
            raise ValueError
        answers = document.get("Answer", [])
        if not isinstance(answers, list) or len(answers) > _MAX_ANSWERS:
            raise ValueError
        aliases, records = {}, {}
        for item in answers:
            if not isinstance(item, dict) or type(item.get("type")) is not int:
                raise ValueError
            owner = _dns_name(item.get("name"))
            typ, data = item["type"], item.get("data")
            if typ == 5:
                target = _dns_name(data)
                if owner in aliases and aliases[owner] != target:
                    raise ValueError
                aliases[owner] = target
            elif typ == record_type:
                address = public_address(data)
                if ipaddress.ip_address(address).version != (4 if record_type == 1 else 6):
                    raise ValueError
                records.setdefault(owner, set()).add(address)
            else:
                raise ValueError
        reached = set()
        current = host
        while current in aliases:
            if current in reached or current in records or len(reached) >= 16:
                raise ValueError
            reached.add(current)
            current = aliases[current]
        reached.add(current)
        if set(aliases) - reached or set(records) - {current}:
            raise ValueError
        addresses = sorted(records.get(current, set()))
        if len(addresses) > _MAX_ADDRESSES:
            raise ValueError
        return addresses, current
    except (CloudBlocked, ValueError, TypeError, UnicodeError, KeyError, RecursionError):
        raise _blocked() from None


async def resolve_action_public(host: str, port: int) -> list[str]:
    """Resolve a fixed action host with the fixed resolver, never from Agent input."""
    try:
        if type(port) is not int or not 1 <= port <= 65535 or canonical_host(host) != host:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return [public_address(str(address))]
        # The endpoint, literal TCP address, SNI and Host are constant. The
        # global target IP pin check remains the responsibility of each caller.
        public_address(_PROVIDER_ADDRESS)
        tls = ssl.create_default_context()
        if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
            raise ValueError
        transport = httpx.AsyncHTTPTransport(verify=tls, retries=0, trust_env=False, http1=True, http2=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
        results = []
        async with asyncio.timeout(10):
            async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=5) as client:
                for number, label in ((1, "A"), (28, "AAAA")):
                    request = httpx.Request("GET", _PROVIDER_URL, params={"name": host, "type": label},
                        headers={"Host": _PROVIDER_HOST + ":443", "Accept": "application/dns-json",
                                 "Accept-Encoding": "identity"}, extensions={"sni_hostname": _PROVIDER_HOST,
                                 "timeout": {key: 5 for key in ("connect", "read", "write", "pool")}})
                    response = await client.send(request, stream=True, follow_redirects=False)
                    try:
                        if (response.status_code != 200
                                or sum(len(k) + len(v) for k, v in response.headers.raw) > 16384
                                or response.headers.get("content-encoding", "identity").lower() != "identity"
                                or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/dns-json"):
                            raise ValueError
                        length = response.headers.get("content-length")
                        if length is not None and (not length.isdecimal() or int(length) > _MAX_RESPONSE):
                            raise ValueError
                        chunks, size = [], 0
                        async for chunk in response.aiter_raw():
                            size += len(chunk)
                            if size > _MAX_RESPONSE:
                                raise ValueError
                            chunks.append(chunk)
                        results.append(parse_answer(b"".join(chunks), host, number))
                    finally:
                        await response.aclose()
        (ipv4, owner4), (ipv6, owner6) = results
        if ipv4 and ipv6 and owner4 != owner6:
            raise ValueError
        addresses = sorted(set(ipv4 + ipv6))
        if not addresses or len(addresses) > _MAX_ADDRESSES:
            raise ValueError
        return addresses
    except CloudBlocked:
        raise
    except (OSError, ValueError, TypeError, httpx.HTTPError, TimeoutError):
        raise _blocked() from None
