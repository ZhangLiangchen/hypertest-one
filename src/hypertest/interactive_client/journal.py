"""Durable local intent ledger. An uncertain POST can only be queried."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_read


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Journal:
    def __init__(self, path: Path):
        if not path.exists():
            try:
                private_create(path, b"")
            except FileExistsError:
                pass
        private_read(path, max_bytes=64_000_000)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("CREATE TABLE IF NOT EXISTS intents (kind TEXT NOT NULL, key TEXT NOT NULL, "
                        "digest TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, result TEXT, "
                        "PRIMARY KEY(kind,key))")
        os.chmod(path, 0o600)

    def intent(self, kind: str, key: str, payload: dict, *, identity: dict | None = None) -> dict:
        digest = hashlib.sha256(canonical(identity or payload).encode()).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.get(kind, key)
            if old:
                if old["digest"] != digest:
                    raise ClientError("IDEMPOTENCY_CONFLICT")
                if old["state"] == "PENDING":
                    # A fresh host observation may change while immutable
                    # attachment identity stays fixed; persist it before SENT.
                    self.db.execute("UPDATE intents SET payload=? WHERE kind=? AND key=?",
                                    (canonical(payload), kind, key))
            else:
                self.db.execute("INSERT INTO intents VALUES (?,?,?,?,?,NULL)",
                                (kind, key, digest, canonical(payload), "PENDING"))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(kind, key)

    def get(self, kind: str, key: str) -> dict | None:
        row = self.db.execute("SELECT digest,payload,state,result FROM intents WHERE kind=? AND key=?",
                              (kind, key)).fetchone()
        if row is None:
            return None
        return {"digest": row[0], "payload": json.loads(row[1]), "state": row[2],
                "result": json.loads(row[3]) if row[3] else None}

    def mark(self, kind: str, key: str, state: str, result: dict | None = None) -> None:
        self.db.execute("UPDATE intents SET state=?,result=? WHERE kind=? AND key=?",
                        (state, canonical(result) if result is not None else None, kind, key))

    def close(self) -> None:
        self.db.close()
