"""Host-only, short SSH admission tickets. Never reuse model/wrapping keys."""

from __future__ import annotations

import base64
import time

from .ssh_profile import blocked, canonical_bytes, digest, exact, integer, public_key

TICKET_PROFILE = "hypertest-ssh-ticket/v1"
TICKET_FIELDS = {"profile", "verb", "operation_id", "attempt_id", "generation", "target", "request_digest", "issued_at", "expires_at", "hard_deadline"}
TICKET_TTL_SECONDS = 60


def _serialization():
    try:
        from cryptography.hazmat.primitives import serialization
        return serialization
    except ImportError:
        raise blocked("SSH_CRYPTO_UNAVAILABLE") from None


def load_signing_key(raw: bytes):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        serialization = _serialization()
        key = (serialization.load_ssh_private_key(raw, password=None)
               if raw.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----")
               else serialization.load_pem_private_key(raw, password=None))
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError
        return key
    except (ImportError, ValueError, TypeError):
        raise blocked("SSH_SIGNING_KEY_INVALID") from None


def signer_public_key(raw: bytes) -> str:
    serialization = _serialization()
    return load_signing_key(raw).public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()


def sign_ticket(raw_key: bytes, request: dict, *, verb: str, generation: int,
                expires_at: int, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now
    claims = {"profile": TICKET_PROFILE, "verb": verb, "operation_id": request["operation_id"],
        "attempt_id": request["attempt_id"], "generation": generation, "target": request["target"],
        "request_digest": digest(request), "issued_at": now, "expires_at": expires_at,
        "hard_deadline": request["hard_deadline"]}
    _claims(claims, request, now)
    signature = load_signing_key(raw_key).sign(b"hypertest-ssh-admission\0" + canonical_bytes(claims))
    return {"claims": claims, "signature": base64.b64encode(signature).decode()}


def _claims(value: object, request: dict, now: int) -> dict:
    claims = exact(value, TICKET_FIELDS)
    if (claims["profile"] != TICKET_PROFILE or not isinstance(claims["verb"], str)
            or claims["verb"] not in {"START", "QUERY", "STOP"}
            or any(claims[k] != request[k] for k in ["operation_id", "attempt_id", "target", "hard_deadline"])
            or claims["request_digest"] != digest(request)):
        raise blocked("SSH_TICKET_INVALID")
    integer(claims["generation"], request["generation"], 2**53 - 1)
    for key in ["issued_at", "expires_at", "hard_deadline"]:
        integer(claims[key], 1, 2**53 - 1)
    if (claims["expires_at"] <= now or claims["issued_at"] > now + 2
            or not 0 < claims["expires_at"] - claims["issued_at"] <= TICKET_TTL_SECONDS
            or (claims["verb"] == "START" and (claims["hard_deadline"] <= now
                or claims["expires_at"] > claims["hard_deadline"]))):
        raise blocked("SSH_TICKET_EXPIRED")
    return claims


def verify_ticket(ticket: object, request: dict, authority_public_key: str, *, now: int | None = None) -> dict:
    envelope = exact(ticket, {"claims", "signature"})
    now = int(time.time()) if now is None else now
    claims = _claims(envelope["claims"], request, now)
    try:
        serialization = _serialization()
        key = serialization.load_ssh_public_key(public_key(authority_public_key).encode())
        signature = base64.b64decode(envelope["signature"], validate=True)
        key.verify(signature, b"hypertest-ssh-admission\0" + canonical_bytes(claims))
    except Exception:
        raise blocked("SSH_TICKET_SIGNATURE_INVALID") from None
    return claims
