from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

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
