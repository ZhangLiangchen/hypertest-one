from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_directory, private_read


class ClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_url: str
    state_dir: Path
    integration_token_file: Path
    device_token_file: Path | None = None
    node_id: str | None = None
    ca_file: Path | None = None
    allow_insecure_loopback: bool = False
    host_adapter: dict = Field(default_factory=lambda: {"kind": "unsupported"})
    workspaces: dict[str, dict[str, str]] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    # Opt-in client orchestration only. No server field, grant or execution
    # permission changes; old private profiles retain their transport contract.
    local_sync: dict = Field(default_factory=dict)

    @field_validator("local_sync")
    @classmethod
    def local_settings(cls, value):
        allowed = {"enabled", "hooks_enabled", "host", "harness_version", "project_id",
                   "manifest_file", "allowed_roots", "event_bridge", "artifact_source"}
        if not value.keys() <= allowed:
            raise ValueError("unknown local synchronization setting")
        for field in ("enabled", "hooks_enabled"):
            if field in value and type(value[field]) is not bool:
                raise ValueError("local synchronization activation must be explicit boolean")
        if value.get("host") not in {None, "codex", "claude-code", "deepseek-harness"}:
            raise ValueError("unsupported local host")
        if "allowed_roots" in value and (not isinstance(value["allowed_roots"], list)
                or any(not isinstance(root, str) or not Path(root).is_absolute()
                       for root in value["allowed_roots"])):
            raise ValueError("absolute artifact roots required")
        if "artifact_source" in value:
            from hypertest.local_sync.sources import ArtifactSource
            ArtifactSource.model_validate(value["artifact_source"])
            if value.get("manifest_file"):
                raise ValueError("select artifact source or explicit manifest")
        return value

    def prepare(self, *, validate_credentials: bool = True) -> None:
        url = urlsplit(self.api_url)
        if (url.username is not None or url.password is not None or url.query or url.fragment
                or not url.hostname):
            raise ClientError("HTTPS_PLATFORM_URL_REQUIRED")
        if url.scheme != "https" and not (self.allow_insecure_loopback and url.scheme == "http"
                                          and url.hostname in {"127.0.0.1", "::1", "localhost"}):
            raise ClientError("HTTPS_PLATFORM_URL_REQUIRED")
        self.api_url = self.api_url.rstrip("/")
        self.state_dir = private_directory(self.state_dir)
        if validate_credentials:
            private_read(self.integration_token_file, max_bytes=4096)
            if self.device_token_file:
                private_read(self.device_token_file, max_bytes=4096)

    @property
    def socket_path(self) -> Path:
        return self.state_dir / "interactive.sock"

    @property
    def local_token_file(self) -> Path:
        return self.state_dir / "ipc.token"

    @classmethod
    def load(cls, path: Path, *, validate_credentials: bool = True) -> ClientConfig:
        try:
            config = cls.model_validate(json.loads(private_read(path)))
            config.prepare(validate_credentials=validate_credentials)
            return config
        except (ValueError, TypeError) as exc:
            raise ClientError("INVALID_PRIVATE_CONFIG") from exc
