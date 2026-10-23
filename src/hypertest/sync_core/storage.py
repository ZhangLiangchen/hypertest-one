"""Private approved snapshots and isolated compact ledgers, never transcripts."""
from __future__ import annotations

import json
import os
from pathlib import Path

from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.security import private_create, private_directory, private_read
from hypertest.sync_core import FrozenIntent, SyncError, canonical_json, digest


class SnapshotStore:
    def __init__(self, directory: Path, *, max_bytes: int = 3 * 1024 * 1024):
        self.directory = private_directory(directory)
        self.max_bytes = max_bytes

    def _path(self, namespace: str, key: str) -> Path:
        return self.directory / (digest([namespace, key]) + ".json")

    def save(self, intent: FrozenIntent) -> None:
        path = self._path(intent.namespace, intent.key)
        body = {"namespace": intent.namespace, "key": intent.key, "target": intent.target,
                "expected_version": intent.expected_version, "payload": intent.payload,
                "request_digest": intent.request_digest}
        encoded = canonical_json(body).encode()
        if len(encoded) > self.max_bytes:
            raise SyncError("FROZEN_REQUEST_SIZE_EXCEEDED")
        try:
            private_create(path, encoded)
            directory = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except FileExistsError:
            if private_read(path, max_bytes=self.max_bytes) != encoded:
                raise SyncError("FROZEN_REQUEST_CONFLICT") from None

    def load(self, namespace: str, key: str) -> FrozenIntent:
        body = json.loads(private_read(self._path(namespace, key), max_bytes=self.max_bytes))
        intent = FrozenIntent(body["namespace"], body["key"], body["target"], body["payload"],
                              body["expected_version"])
        if (namespace != intent.namespace or key != intent.key
                or body["request_digest"] != intent.request_digest):
            raise SyncError("FROZEN_REQUEST_CORRUPT")
        return intent


class JournalLedger:
    """Use the existing private-client journal rather than a parallel outbox.

    ACKED is retained as the old journal's transport name; READBACK_COMPLETE is a distinct
    additive client delivery state. No server state or wire field is introduced.
    """
    TO_CORE = {"PENDING": "PREPARED", "ACKED": "ACCEPTED", "LEGACY_ACCEPTED_READBACK": "ACCEPTED"}
    TO_JOURNAL = {"PREPARED": "PENDING", "ACCEPTED": "ACKED"}

    def __init__(self, journal: Journal):
        self.journal = journal

    def prepare(self, intent: FrozenIntent) -> dict:
        # identity=payload preserves old complete-request idempotency digests.
        compact = {**intent.target, "idempotency_key": intent.key,
                   "expected_version": intent.expected_version,
                   "snapshot_schema": "hypertest.sync-snapshot/v1"}
        record = self.journal.intent(intent.namespace, intent.key, compact, identity=intent.payload)
        return {"state": self.TO_CORE.get(record["state"], record["state"]),
                "receipt": record.get("result")}

    def mark(self, namespace: str, key: str, state: str, receipt=None) -> None:
        self.journal.mark(namespace, key, self.TO_JOURNAL.get(state, state), receipt)
