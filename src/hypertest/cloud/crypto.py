"""Authenticated credential encryption. The wrapping key stays outside PostgreSQL."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from .errors import CloudBlocked
from .private_file import read_private_file


class CredentialCipher:
    def __init__(self, master_key: bytes):
        if len(master_key) != 32:
            raise CloudBlocked("CREDENTIAL_KEY_INVALID", "Cloud wrapping key must be 32 bytes")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise CloudBlocked("CRYPTO_UNAVAILABLE", "Install the Cloud cryptography dependency") from exc
        self._cipher = AESGCM(master_key)
        self._fingerprint_key = hmac.digest(master_key, b"hypertest-cloud-credential-fingerprint/v1", "sha256")

    @classmethod
    def from_key_file(cls, path: str | Path) -> CredentialCipher:
        try:
            try:
                raw = read_private_file(path, max_bytes=128).strip()
            except CloudBlocked as error:
                code = "CREDENTIAL_KEY_PERMISSIONS" if error.code == "PRIVATE_FILE_UNSAFE" else "CREDENTIAL_KEY_UNAVAILABLE"
                raise CloudBlocked(code, "Cloud wrapping key is unavailable or outside its private file profile") from None
            key = base64.b64decode(raw, validate=True)
        except (OSError, ValueError) as exc:
            raise CloudBlocked("CREDENTIAL_KEY_UNAVAILABLE", "Cloud wrapping key is unavailable") from exc
        return cls(key)

    @staticmethod
    def _aad(context: dict[str, Any]) -> bytes:
        if not context:
            raise CloudBlocked("CREDENTIAL_CONTEXT_REQUIRED", "Credential encryption requires an ownership context")
        return json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def fingerprint(self, secret: str | bytes) -> str:
        content = secret.encode() if isinstance(secret, str) else secret
        return hmac.new(self._fingerprint_key, content, hashlib.sha256).hexdigest()

    def encrypt(self, secret: str | bytes, *, context: dict[str, Any]) -> dict[str, str]:
        content = secret.encode() if isinstance(secret, str) else secret
        if not content or len(content) > 65536:
            raise CloudBlocked("CREDENTIAL_SIZE", "Credential is empty or exceeds the private input limit")
        nonce = os.urandom(12)
        encrypted = self._cipher.encrypt(nonce, content, self._aad(context))
        return {"algorithm": "AES-256-GCM", "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(encrypted).decode()}

    def decrypt(self, envelope: dict[str, str], *, context: dict[str, Any]) -> bytes:
        try:
            if envelope["algorithm"] != "AES-256-GCM":
                raise ValueError("unsupported envelope")
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            content = base64.b64decode(envelope["ciphertext"], validate=True)
            return self._cipher.decrypt(nonce, content, self._aad(context))
        except Exception as exc:
            raise CloudBlocked("CREDENTIAL_DECRYPTION_FAILED", "Credential cannot be decrypted for this owner/version") from exc


def credential_fingerprint(cipher: CredentialCipher, secret: str | bytes) -> str:
    """Keyed idempotency identity; never store a brute-forceable raw secret hash."""
    return cipher.fingerprint(secret)
