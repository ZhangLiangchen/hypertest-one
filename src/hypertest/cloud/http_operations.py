"""Exact HTTPS operation identity and host-only immutable response originals."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_directory, private_read

from .http_profile import (
    HTTPS_PROTOCOL,
    HTTPS_RESPONSE,
    SHA256,
    HttpProfile,
    blocked,
    canonical_bytes,
    digest,
    exact,
    integer,
)

RESPONSE_LIMIT = 262144
WIRE_LIMIT = 384 * 1024
REASONS = frozenset({"RESPONSE_OBSERVED", "REDIRECT_REFUSED", "OUTPUT_LIMIT", "TRANSPORT_UNKNOWN",
                     "AUTHORITY_LOST", "OUTPUT_REJECTED"})
_REQUEST_FIELDS = {"profile", "operation_id", "task_id", "attempt_id", "generation", "target",
                   "catalog_sha256", "resource", "hard_deadline"}
_RESPONSE_FIELDS = {"profile", "operation_id", "request_digest", "state", "http_status", "body_base64",
                    "body_sha256", "byte_count", "reason", "observed_at"}


def uuid_text(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise blocked() from None


def request_document(*, operation_id, task_id, attempt_id, generation, target, catalog_sha256,
                     resource, hard_deadline):
    return {"profile": HTTPS_PROTOCOL, "operation_id": operation_id, "task_id": task_id,
        "attempt_id": attempt_id, "generation": generation, "target": target,
        "catalog_sha256": catalog_sha256, "resource": resource, "hard_deadline": hard_deadline}


def validate_request(value, profile: HttpProfile):
    value = exact(value, _REQUEST_FIELDS)
    if (value["profile"] != HTTPS_PROTOCOL or value["target"] != profile.target
            or value["catalog_sha256"] != profile.catalog_sha256):
        raise blocked("HTTPS_ORIGINAL_TARGET_CHANGED")
    for name in ("operation_id", "task_id", "attempt_id"):
        uuid_text(value[name])
    integer(value["generation"], 1, 2 ** 63 - 1)
    integer(value["hard_deadline"], 1, 2 ** 63 - 1)
    resource = value["resource"]
    if not isinstance(resource, dict) or resource != profile.resource(resource.get("key")).document():
        raise blocked("HTTPS_RESOURCE_INVALID")
    return value


def response_document(request, *, state="UNKNOWN", http_status=None, body=b"",
                      reason="TRANSPORT_UNKNOWN", observed_at=None):
    value = {"profile": HTTPS_RESPONSE, "operation_id": request["operation_id"],
        "request_digest": digest(request), "state": state, "http_status": http_status,
        "body_base64": base64.b64encode(body).decode(), "body_sha256": hashlib.sha256(body).hexdigest(),
        "byte_count": len(body), "reason": reason,
        "observed_at": int(time.time()) if observed_at is None else observed_at}
    return project_response(value, request)


def project_response(value, request):
    value = exact(value, _RESPONSE_FIELDS)
    if (value["profile"] != HTTPS_RESPONSE or value["operation_id"] != request["operation_id"]
            or value["request_digest"] != digest(request) or value["state"] not in {"UNKNOWN", "OBSERVED"}
            or value["reason"] not in REASONS):
        raise blocked("HTTPS_RESPONSE_INVALID")
    integer(value["observed_at"], 1, 2 ** 63 - 1)
    integer(value["byte_count"], 0, request["resource"]["response_limit_bytes"])
    if not isinstance(value["body_sha256"], str) or SHA256.fullmatch(value["body_sha256"]) is None:
        raise blocked("HTTPS_RESPONSE_INVALID")
    try:
        body = base64.b64decode(value["body_base64"], validate=True)
    except (ValueError, TypeError):
        raise blocked("HTTPS_RESPONSE_INVALID") from None
    if (len(body) != value["byte_count"] or hashlib.sha256(body).hexdigest() != value["body_sha256"]
            or base64.b64encode(body).decode() != value["body_base64"]):
        raise blocked("HTTPS_RESPONSE_INVALID")
    if value["state"] == "OBSERVED":
        integer(value["http_status"], 200, 599)
        expected = "REDIRECT_REFUSED" if 300 <= value["http_status"] <= 399 else "RESPONSE_OBSERVED"
        if value["reason"] != expected or (request["resource"]["method"] == "HEAD" and body):
            raise blocked("HTTPS_RESPONSE_INVALID")
    elif (value["http_status"] is not None or body or value["reason"] in {"RESPONSE_OBSERVED", "REDIRECT_REFUSED"}):
        raise blocked("HTTPS_RESPONSE_INVALID")
    return dict(value)


class HttpOriginals:
    """Approved response bytes only; the canonical SENT/UNKNOWN ledger is in DB.

    Files are not placed in the Agent workspace and contain no authority tokens.
    Reads require the exact original operation ID and request digest. A missing
    original is never replaced by repeating the external request.
    """
    def __init__(self, root: Path):
        try:
            self.root = private_directory(root)
        except ClientError:
            raise blocked("HTTPS_PRIVATE_ORIGINAL_UNAVAILABLE") from None

    def _path(self, operation_id):
        return self.root / (uuid_text(operation_id) + ".json")

    def save(self, request, response):
        value = project_response(response, request)
        if value["state"] != "OBSERVED":
            raise blocked("HTTPS_PRIVATE_ORIGINAL_INVALID")
        path = self._path(request["operation_id"])
        raw = canonical_bytes({"request_digest": digest(request), "response": value})
        try:
            private_create(path, raw)
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except FileExistsError:
            if private_read(path, max_bytes=WIRE_LIMIT) != raw:
                raise blocked("HTTPS_PRIVATE_ORIGINAL_CONFLICT") from None
        except (OSError, ClientError):
            raise blocked("HTTPS_PRIVATE_ORIGINAL_UNAVAILABLE") from None

    def get(self, request):
        try:
            value = json.loads(private_read(self._path(request["operation_id"]), max_bytes=WIRE_LIMIT))
        except (OSError, ClientError, ValueError):
            raise blocked("HTTPS_PRIVATE_ORIGINAL_UNAVAILABLE") from None
        if value.get("request_digest") != digest(request):
            raise blocked("HTTPS_PRIVATE_ORIGINAL_CONFLICT")
        return project_response(value.get("response"), request)
