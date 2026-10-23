"""Frozen public HTTPS read catalog. No network, credentials or task mutation."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import CloudBlocked

HTTPS_ACCESS_PROFILE = "HTTPS_CONTROLLED_API_V1"
HTTPS_PROTOCOL = "hypertest-https-controlled-api/v1"
HTTPS_RESPONSE = "hypertest-https-response/v1"
HTTPS_SOCKET = "/run/hypertest-https.sock"
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
SHA256 = re.compile(r"[a-f0-9]{64}")
_RESOURCE_FIELDS = {"key", "method", "path", "timeout_seconds", "response_limit_bytes"}


def blocked(code="HTTPS_CONTRACT_INVALID"):
    return CloudBlocked(code, "HTTPS input is outside the frozen public read capability")


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise blocked()
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise blocked()
    return value


def public_address(value) -> str:
    try:
        address = ipaddress.ip_address(value)
    except (TypeError, ValueError):
        raise blocked("HTTPS_ADDRESS_REFUSED") from None
    if (not isinstance(value, str) or str(address) != value or "%" in value
            or not address.is_global or address.is_multicast or address.is_reserved
            or address.is_loopback or address.is_link_local or address.is_unspecified
            or (address.version == 6 and (address.ipv4_mapped is not None
                or address.sixtofour is not None or address.teredo is not None))):
        raise blocked("HTTPS_ADDRESS_REFUSED")
    return value


def canonical_host(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 253 or not value.isascii():
        raise blocked("HTTPS_HOST_INVALID")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if (value != value.lower() or value.endswith(".") or "." not in value
                or value.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".onion"))
                or any(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                       for label in value.split("."))):
            raise blocked("HTTPS_HOST_INVALID") from None
        return value
    return public_address(value)


def canonical_target(host, port) -> str:
    canonical_host(host)
    integer(port, 1, 65535)
    hostname = f"[{host}]" if ":" in host else host
    return f"https://{hostname}:{port}"


def canonical_path(value) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048 or not value.startswith("/")
            or not value.isascii() or re.fullmatch(r"/[A-Za-z0-9/._~-]*", value) is None
            or "//" in value or any(part in {".", ".."} for part in value.split("/"))):
        raise blocked("HTTPS_PATH_INVALID")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise blocked("HTTPS_PATH_INVALID")
    return value


@dataclass(frozen=True)
class HttpResource:
    key: str
    method: str
    path: str
    timeout_seconds: int
    response_limit_bytes: int

    def document(self):
        return dict(vars(self))

    @classmethod
    def parse(cls, value):
        data = exact(value, _RESOURCE_FIELDS)
        if not isinstance(data["key"], str) or KEY.fullmatch(data["key"]) is None:
            raise blocked("HTTPS_RESOURCE_INVALID")
        if data["method"] not in {"GET", "HEAD"}:
            raise blocked("HTTPS_METHOD_UNSUPPORTED")
        canonical_path(data["path"])
        integer(data["timeout_seconds"], 1, 15)
        integer(data["response_limit_bytes"], 1, 262144)
        return cls(**data)


@dataclass(frozen=True)
class HttpProfile:
    host: str
    port: int
    allowed_addresses: tuple[str, ...]
    resources: tuple[HttpResource, ...]
    max_operations: int
    catalog_sha256: str

    @property
    def target(self):
        return canonical_target(self.host, self.port)

    def resource(self, key):
        for resource in self.resources:
            if resource.key == key:
                return resource
        raise blocked("HTTPS_RESOURCE_UNAVAILABLE")

    def catalog_document(self):
        return {"profile": HTTPS_ACCESS_PROFILE, "target": self.target,
            "allowed_addresses": list(self.allowed_addresses),
            "resources": [resource.document() for resource in self.resources],
            "max_operations": self.max_operations}


def validate_profile(environment):
    if not isinstance(environment, dict) or environment.get("connection") != "HTTPS":
        raise blocked("HTTPS_PROFILE_UNAVAILABLE")
    if environment.get("cloud_access_policy") == "LOCAL_ONLY":
        raise blocked("LOCAL_MODE_REQUIRED")
    if environment.get("cloud_access_policy") not in {None, "WEB_ONLY"}:
        raise blocked("CLOUD_ACCESS_POLICY_INVALID")
    # application_private_key is not a Bearer token. This first profile exposes
    # public resources only and must never materialize an environment credential.
    if environment.get("credential_version_id") is not None:
        raise blocked("HTTPS_CREDENTIAL_PROFILE_UNSUPPORTED")
    access = exact(environment.get("https_access"), {"profile", "catalog_sha256",
        "allowed_addresses", "resources", "max_operations"})
    if access["profile"] != HTTPS_ACCESS_PROFILE:
        raise blocked("HTTPS_PROFILE_UNAVAILABLE")
    host, port = environment.get("host"), environment.get("port")
    canonical_target(host, port)
    addresses = access["allowed_addresses"]
    if not isinstance(addresses, list) or not 1 <= len(addresses) <= 8:
        raise blocked("HTTPS_ADDRESS_REFUSED")
    pinned = tuple(public_address(address) for address in addresses)
    if len(set(pinned)) != len(pinned):
        raise blocked("HTTPS_ADDRESS_REFUSED")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if pinned != (host,):
            raise blocked("HTTPS_ADDRESS_REFUSED")
    values = access["resources"]
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise blocked("HTTPS_RESOURCE_INVALID")
    resources = tuple(HttpResource.parse(value) for value in values)
    if len({resource.key for resource in resources}) != len(resources):
        raise blocked("HTTPS_RESOURCE_INVALID")
    checksum = access["catalog_sha256"]
    if not isinstance(checksum, str) or SHA256.fullmatch(checksum) is None:
        raise blocked("HTTPS_CATALOG_DIGEST_MISMATCH")
    profile = HttpProfile(host, port, pinned, resources, integer(access["max_operations"], 1, 32), checksum)
    if digest(profile.catalog_document()) != checksum:
        raise blocked("HTTPS_CATALOG_DIGEST_MISMATCH")
    return profile
