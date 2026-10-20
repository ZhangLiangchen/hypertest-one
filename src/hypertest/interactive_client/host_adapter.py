"""Current Codex desktop identity, observed outside model-controlled arguments.

The platform trusts an explicitly authorized local adapter, not an attestation
of a hostile computer. This adapter never starts a Provider or reads chat text.
Only a real Codex-descended stdio peer can use its execution attachment.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from hypertest.interactive_client.host_types import HostAdapterError

ADAPTER_ID = "codex-desktop-stdio/v1"


def _process(pid: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "ppid=,lstart=,comm=", "-p", str(pid)],
            capture_output=True, text=True, timeout=3, check=True,
            env={**os.environ, "LC_ALL": "C"},
        ).stdout.strip().split(None, 6)
        if len(result) != 7:
            raise ValueError
        return int(result[0]), " ".join(result[1:6]), result[6]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HostAdapterError("HOST_PROCESS_UNAVAILABLE") from exc


def _owned(path: Path, *, directory: bool = False) -> Path:
    try:
        if path.is_symlink() or path.absolute() != path.resolve(strict=True):
            raise ValueError
        info = path.stat()
        if (info.st_uid != os.getuid() or info.st_mode & 0o022
                or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
            raise ValueError
        return path
    except (OSError, ValueError) as exc:
        raise HostAdapterError("HOST_OWNED_RESOURCE_REQUIRED") from exc


def _git(path: Path, *arguments: str) -> str:
    # No network, shell, filters or hooks. Do not inherit model-supplied Git overrides.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               GIT_NO_REPLACE_OBJECTS="1")
    try:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
             "-C", str(path), *arguments],
            env=env, capture_output=True, text=True, check=True, timeout=15,
        )
        if len(result.stdout) > 100_000:
            raise ValueError
        return result.stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HostAdapterError("HOST_PINNED_SOURCE_UNAVAILABLE") from exc


def _verify_source(path: Path, item: dict) -> None:
    if (_git(path, "rev-parse", "HEAD") != item["commit_sha"]
            or _git(path, "config", "--local", "--get", "remote.origin.url") != item["origin"]
            or Path(_git(path, "rev-parse", "--show-toplevel")).resolve() != path):
        raise HostAdapterError("HOST_PINNED_SOURCE_MISMATCH")
    # Compare bytes to immutable Git blobs, including files hidden from ordinary
    # git status by assume-unchanged / skip-worktree index flags.
    algorithm = _git(path, "rev-parse", "--show-object-format")
    if algorithm not in {"sha1", "sha256"}:
        raise HostAdapterError("HOST_PINNED_SOURCE_MISMATCH")
    entries = _git(path, "ls-tree", "-rz", "--full-tree", "HEAD").rstrip("\0").split("\0")
    if not entries or len(entries) > 25000:
        raise HostAdapterError("HOST_PINNED_SOURCE_MISMATCH")
    total = 0
    for entry in entries:
        try:
            header, name = entry.split("\t", 1)
            mode, kind, oid = header.split()
            if mode not in {"100644", "100755"} or kind != "blob" or not name:
                raise ValueError
            file = _owned(path / name)
            if not file.is_relative_to(path) or file.stat().st_size > 24 * 1024 * 1024:
                raise ValueError
            raw = file.read_bytes()
            total += len(raw)
            if total > 32 * 1024 * 1024:
                raise ValueError
            actual = hashlib.new(algorithm, f"blob {len(raw)}\0".encode() + raw).hexdigest()
            if actual != oid or bool(file.stat().st_mode & 0o111) != (mode == "100755"):
                raise ValueError
        except (OSError, ValueError) as exc:
            raise HostAdapterError("HOST_PINNED_SOURCE_MISMATCH") from exc


class UnsupportedHostAdapter:
    def __init__(self, code: str = "HOST_ADAPTER_UNSUPPORTED"):
        self.code = code

    def capabilities(self) -> dict:
        return {"adapter_id": ADAPTER_ID, "interactive_execution": False, "reason": self.code}

    async def attest(self, **_kwargs) -> dict:
        raise HostAdapterError(self.code)

    async def assert_live(self, _attestation: dict) -> None:
        raise HostAdapterError(self.code)

    async def assert_peer(self, _pid: int) -> None:
        raise HostAdapterError(self.code)


class CodexDesktopHostAdapter:
    def __init__(self, config: dict):
        options = config.get("host_adapter", {})
        thread = os.environ.get("CODEX_THREAD_ID", "")
        if (not thread or os.environ.get("CODEX_SESSION_ID") != thread
                or os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE") != "Codex Desktop"):
            raise HostAdapterError("HOST_CURRENT_NATIVE_SESSION_REQUIRED")
        try:
            self.native_session_id = str(UUID(thread))
        except ValueError as exc:
            raise HostAdapterError("HOST_CURRENT_NATIVE_SESSION_REQUIRED") from exc
        self.home = _owned(Path(options.get("codex_home", Path.home() / ".codex")).absolute(), directory=True)
        matches = list((self.home / "sessions").rglob("*" + self.native_session_id + "*.jsonl"))
        if len(matches) != 1:
            raise HostAdapterError("HOST_NATIVE_METADATA_REQUIRED")
        self.metadata = _owned(matches[0])
        self._metadata_identity()
        expected = os.environ.get("CODEX_CLI_PATH")
        if not expected:
            raise HostAdapterError("HOST_CODEX_PROCESS_REQUIRED")
        executable = Path(expected).resolve(strict=True)
        pid = os.getpid()
        self.codex_pid = None
        for _ in range(24):
            parent, birth, command = _process(pid)
            if Path(command).resolve() == executable:
                self.codex_pid, self.codex_birth, self.codex_executable = pid, birth, executable
                break
            if parent <= 1 or parent == pid:
                break
            pid = parent
        if self.codex_pid is None:
            raise HostAdapterError("HOST_CODEX_PROCESS_REQUIRED")
        self.workspaces = config.get("workspaces", options.get("workspaces", {}))
        self._peer: tuple[int, str] | None = None
        self._attachments: dict[str, tuple[Path, dict]] = {}

    def _metadata_identity(self) -> None:
        try:
            _owned(self.metadata)
            descriptor = os.open(self.metadata, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source:
                first = source.readline(64 * 1024 + 1)
            if len(first) > 64 * 1024:
                raise ValueError
            record = json.loads(first)
            payload = record.get("payload", {})
            if (record.get("type") != "session_meta" or payload.get("id") != self.native_session_id
                    or payload.get("originator") != "Codex Desktop" or not payload.get("cli_version")
                    or not Path(payload.get("cwd", "")).is_absolute()):
                raise ValueError
        except (OSError, ValueError, TypeError) as exc:
            raise HostAdapterError("HOST_NATIVE_METADATA_MISMATCH") from exc

    def capabilities(self) -> dict:
        return {"adapter_id": ADAPTER_ID, "interactive_execution": True,
                "provider": "codex", "requires_live_stdio_peer": True}

    async def assert_peer(self, pid: int) -> None:
        await asyncio.to_thread(self._assert_peer, pid)

    def _assert_peer(self, pid: int) -> None:
        if not isinstance(pid, int) or pid <= 1:
            raise HostAdapterError("HOST_STDIO_PEER_REQUIRED")
        original, original_birth = pid, _process(pid)[1]
        if self._peer is not None and self._peer != (original, original_birth):
            # Desktop app-servers may host many chats: shared ancestry alone
            # cannot let a different stdio process adopt this native attachment.
            # A replacement needs an explicit daemon restart in the original
            # native launch context, followed by normal reconciliation.
            raise HostAdapterError("HOST_STDIO_PEER_CHANGED")
        for _ in range(24):
            parent, birth, command = _process(pid)
            if pid == self.codex_pid:
                if birth != self.codex_birth or Path(command).resolve() != self.codex_executable:
                    break
                self._peer = original, original_birth
                return
            if parent <= 1 or parent == pid:
                break
            pid = parent
        raise HostAdapterError("HOST_STDIO_PEER_REJECTED")

    async def assert_live(self, attestation: dict) -> None:
        await asyncio.to_thread(self._assert_live, attestation)

    def _assert_live(self, attestation: dict) -> None:
        self._metadata_identity()
        if self._peer is None or _process(self._peer[0])[1] != self._peer[1]:
            raise HostAdapterError("HOST_STDIO_PEER_REQUIRED")
        self._assert_peer(self._peer[0])
        if (attestation.get("adapter_id") != ADAPTER_ID
                or attestation.get("native_session_id") != self.native_session_id):
            raise HostAdapterError("HOST_ATTACHMENT_IDENTITY_MISMATCH")
        local = self._attachments.get(attestation.get("attachment_id"))
        if local is None:
            raise HostAdapterError("HOST_ATTACHMENT_IDENTITY_MISMATCH")
        _verify_source(*local)

    async def attest(self, *, project_id: str, run_id: str, node_id: str,
                     source_transfer_id: str, workspace: Path) -> dict:
        return await asyncio.to_thread(self._attest, project_id, run_id, node_id, source_transfer_id, workspace)

    def _attest(self, project_id: str, run_id: str, node_id: str,
                source_transfer_id: str, workspace: Path) -> dict:
        item = self.workspaces.get(run_id)
        if not isinstance(item, dict) or item.get("source_bundle_transfer_id") != source_transfer_id:
            raise HostAdapterError("HOST_APPROVED_WORKSPACE_REQUIRED")
        path = _owned(workspace.absolute(), directory=True)
        if str(path) != str(Path(item.get("path", "")).absolute()):
            raise HostAdapterError("HOST_APPROVED_WORKSPACE_REQUIRED")
        if not item.get("commit_sha") or not item.get("origin") or not item.get("workspace_id"):
            raise HostAdapterError("HOST_PINNED_SOURCE_IDENTITY_REQUIRED")
        _verify_source(path, item)
        proof = {"schema_version": "hypertest.host-attestation/v1alpha1", "adapter_id": ADAPTER_ID,
                 "provider": "codex", "harness": "codex", "native_session_id": self.native_session_id,
                 "node_id": str(UUID(node_id)), "workspace_id": item["workspace_id"],
                 "source_bundle_transfer_id": str(UUID(source_transfer_id)),
                 "attachment_id": str(uuid5(NAMESPACE_URL,
                     f"hypertest:{project_id}:{run_id}:{self.native_session_id}:{item['workspace_id']}")),
                 "observed_at": datetime.now(UTC).isoformat(), "lifecycle": "ACTIVE"}
        self._attachments[proof["attachment_id"]] = path, dict(item)
        self._assert_live(proof)
        return proof


def make_host_adapter(config: dict):
    if config.get("host_adapter", {}).get("kind") != "codex-desktop-stdio":
        return UnsupportedHostAdapter()
    try:
        return CodexDesktopHostAdapter(config)
    except (HostAdapterError, OSError) as exc:
        return UnsupportedHostAdapter(exc.code if isinstance(exc, HostAdapterError) else "HOST_RESOURCE_UNAVAILABLE")
