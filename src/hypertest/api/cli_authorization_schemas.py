"""Strict, non-secret pairing payloads. Proofs travel only in protected headers."""
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairingCreate(Strict):
    request_id: UUID
    idempotency_key: Key
    client_instance_id: UUID
    client_name: str = Field(min_length=1, max_length=80)
    server_url: str = Field(max_length=512)
    credential_hash: Digest
    verifier_challenge: Digest
    project_id: UUID | None = None

    @field_validator("server_url")
    @classmethod
    def origin_only(cls, value):
        parsed = urlsplit(value)
        if (any(character.isspace() for character in value) or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("server_url must be an HTTPS origin")
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("server_url has an invalid port") from None
        return value.rstrip("/")


class PairingApprove(Strict):
    idempotency_key: Key
    # Accepted only to recover the exact receipt of a pre-retirement approval.
    # New approvals must omit the field, including an explicit null.
    actor_identity_id: UUID | None = Field(default=None, deprecated=True)
    project_ids: list[UUID] = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=2, max_length=2)
    expires_in_days: int = Field(default=30, ge=1, le=90)
    short_code: str = Field(min_length=8, max_length=12)

    @field_validator("project_ids")
    @classmethod
    def unique_projects(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate projects")
        return sorted(value, key=str)

    @field_validator("scopes")
    @classmethod
    def archive_scopes(cls, value):
        if set(value) != {"archive:read", "archive:write"}:
            raise ValueError("CLI pairing requires exactly archive:read and archive:write")
        return sorted(value)


class PairingRedeem(Strict):
    idempotency_key: Key
    approval_digest: Digest


class GrantRevoke(Strict):
    idempotency_key: Key
