"""User-private profiles, pairing records, and durable archive snapshots."""
from __future__ import annotations

import fcntl
import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.security import private_create, private_directory, private_read
from hypertest.sync_core import canonical_json, digest
from hypertest.sync_core.storage import JournalLedger, SnapshotStore


class CLIError(ValueError):
    def __init__(self, code: str, exit_code: int = 2, *, status: int = 0):
        self.code, self.exit_code, self.status = code, exit_code, status
        super().__init__(code)


def identifier(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CLIError("INVALID_UUID") from exc


def profile_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise CLIError("INVALID_PROFILE_NAME")
    return value


def atomic_private(path: Path, value: dict) -> None:
    temporary = path.parent / ("." + uuid.uuid4().hex + ".tmp")
    private_create(temporary, canonical_json(value).encode())
    try:
        if path.is_symlink():
            raise CLIError("PRIVATE_FILE_REQUIRED", 5)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


class State:
    def __init__(self, directory: Path | None = None):
        self.directory = private_directory(directory or Path(os.environ.get(
            "HYPERTEST_CLI_HOME", str(Path.home() / ".hypertest-cli"))))
        self.profiles = private_directory(self.directory / "profiles")
        self.pairings = private_directory(self.directory / "pairings")
        self.requests = private_directory(self.directory / "requests")
        self.locks = private_directory(self.directory / "locks")
        self.snapshots = SnapshotStore(self.directory / "snapshots", max_bytes=32 * 1024 * 1024)

    @contextmanager
    def lock(self, identity: str):
        path = self.locks / (digest(identity) + ".lock")
        try:
            private_create(path, b"")
        except FileExistsError:
            private_read(path)
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            # A second caller must not queue behind a potentially long network wait.
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CLIError("OPERATION_ALREADY_RUNNING", 4) from exc
            yield
        finally:
            os.close(descriptor)

    @contextmanager
    def ledger(self):
        journal = Journal(self.directory / "archive-journal.sqlite3")
        try:
            yield JournalLedger(journal)
        finally:
            journal.close()

    def read(self, folder: Path, key: str) -> dict:
        path = folder / (key + ".json")
        if not path.exists():
            raise CLIError("LOCAL_RECORD_NOT_FOUND", 5)
        try:
            value = json.loads(private_read(path, max_bytes=5 * 1024 * 1024))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CLIError("LOCAL_RECORD_INVALID", 5) from exc
        if not isinstance(value, dict):
            raise CLIError("LOCAL_RECORD_INVALID", 5)
        return value

    def write(self, folder: Path, key: str, value: dict) -> None:
        atomic_private(folder / (key + ".json"), value)

    def profile(self, name: str | None, *, project_id: str | None = None) -> dict:
        names = sorted(p.stem for p in self.profiles.glob("*.json"))
        if name is None:
            if len(names) != 1:
                raise CLIError("EXPLICIT_PROFILE_REQUIRED" if names else "CLI_BINDING_REQUIRED", 5)
            name = names[0]
        value = self.read(self.profiles, profile_name(name))
        if not value.get("active", True):
            raise CLIError("PROFILE_LOGGED_OUT", 5)
        grants = value.get("grants", [])
        if project_id:
            grants = [g for g in grants if (g.get("all_projects") is True or project_id in g.get("project_ids", []))
                      and {"archive:read", "archive:write"} <= set(g.get("scopes", []))]
        if not grants:
            raise CLIError("PROJECT_NOT_AUTHORIZED" if project_id else "CLI_BINDING_REQUIRED", 5)
        # Newest approved grant first, never switch uploader or server.
        result = {**value, "name": name, "grant": grants[-1]}
        return result

    def save_profile(self, name: str, server: str, client_id: str, actor_ref: str,
                     grant: dict | list[dict]) -> None:
        name = profile_name(name)
        with self.lock("profiles"):
            path = self.profiles / (name + ".json")
            value = self.read(self.profiles, name) if path.exists() else {
                "server": server, "client_id": client_id, "actor_ref": actor_ref, "grants": []}
            if any(value.get(k) != v for k, v in {
                    "server": server, "client_id": client_id, "actor_ref": actor_ref}.items()):
                raise CLIError("PROFILE_IDENTITY_CONFLICT", 5)
            additions = grant if isinstance(grant, list) else [grant]
            for item in additions:
                old = next((g for g in value["grants"] if g["grant_id"] == item["grant_id"]), None)
                if old is not None and old != item:
                    raise CLIError("GRANT_IDENTITY_CONFLICT", 5)
                if old is None:
                    value["grants"].append(item)
            value["active"] = True
            self.write(self.profiles, name, value)

    def safe_profiles(self, name: str | None = None) -> list[dict]:
        names = [profile_name(name)] if name else sorted(p.stem for p in self.profiles.glob("*.json"))
        result = []
        for key in names:
            value = self.read(self.profiles, key)
            result.append({"name": key, **{k: value[k] for k in ("server", "client_id", "actor_ref")},
                           "active": value.get("active", True), "grants": [
                               {k: g.get(k) for k in ("grant_id", "project_ids", "all_projects", "scopes", "expires_at")}
                               for g in value.get("grants", [])]})
        return result
