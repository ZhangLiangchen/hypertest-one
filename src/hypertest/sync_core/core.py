"""Reliable delivery without domain identities, credentials or lifecycle assumptions.

The adapter owns authority, wire shape, receipt versions and readback. A durable
ledger owns delivery state; approved request snapshots are stored separately.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol


class SyncError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def merge_present(base: dict, changes: dict, *, clear_fields=(), clear_values=None) -> dict:
    """Only caller-declared fields change. CLEAR must have a domain-defined value."""
    cleared = set(clear_fields)
    if cleared & changes.keys():
        raise SyncError("CLEAR_AND_SET_CONFLICT")
    allowed = clear_values or {}
    if not cleared <= allowed.keys():
        raise SyncError("CLEAR_FIELD_UNSUPPORTED")
    result = copy.deepcopy(base)
    result.update(copy.deepcopy(changes))
    result.update({field: copy.deepcopy(allowed[field]) for field in cleared})
    return result


@dataclass(frozen=True, init=False)
class FrozenIntent:
    namespace: str
    key: str
    expected_version: int
    _target_json: str
    _payload_json: str
    request_digest: str

    def __init__(self, namespace: str, key: str, target: dict, payload: dict,
                 expected_version: int):
        if not namespace or not key or type(expected_version) is not int or expected_version < 0:
            raise SyncError("INVALID_FROZEN_INTENT")
        target_json, payload_json = canonical_json(target), canonical_json(payload)
        for name, value in {"namespace": namespace, "key": key,
                            "expected_version": expected_version,
                            "_target_json": target_json, "_payload_json": payload_json,
                            "request_digest": digest(payload)}.items():
            object.__setattr__(self, name, value)

    @property
    def target(self) -> dict:
        return json.loads(self._target_json)

    @property
    def payload(self) -> dict:
        return json.loads(self._payload_json)

    def compact(self) -> dict:
        return {"target": self.target, "request_digest": self.request_digest,
                "expected_version": self.expected_version}


class Ledger(Protocol):
    def prepare(self, intent: FrozenIntent) -> dict: ...
    def mark(self, namespace: str, key: str, state: str, receipt: dict | None = None) -> None: ...


class SyncAdapter(Protocol):
    async def submit(self, intent: FrozenIntent) -> dict: ...
    async def reconcile(self, intent: FrozenIntent) -> dict: ...
    def validate_receipt(self, intent: FrozenIntent, receipt: dict) -> None: ...
    async def readback(self, intent: FrozenIntent, receipt: dict) -> dict: ...


@dataclass(frozen=True)
class SyncOutcome:
    state: str
    receipt: dict | None = None
    document: dict | None = None
    code: str | None = None

    @property
    def synced(self) -> bool:
        return self.state == "READBACK_COMPLETE"


class TaskSyncCore:
    """Caller serializes a target stream; no global lock or lease is implied.

    CancelledError/BaseException deliberately propagate after SENT persists. A
    restart therefore reconciles, including crashes immediately before network I/O.
    """
    def __init__(self, ledger: Ledger, adapter: SyncAdapter):
        self.ledger, self.adapter = ledger, adapter

    async def deliver(self, intent: FrozenIntent) -> SyncOutcome:
        record = self.ledger.prepare(intent)
        state, receipt = record["state"], record.get("receipt")
        prior_receipt = receipt
        if state == "READBACK_COMPLETE":
            return SyncOutcome(state, receipt)
        if state == "REJECTED":
            return SyncOutcome(state, receipt, code="PREVIOUSLY_REJECTED")
        if state not in {"PREPARED", "SENT", "UNKNOWN", "ACCEPTED"}:
            raise SyncError("INVALID_DELIVERY_STATE")
        if state != "ACCEPTED":
            fresh = state == "PREPARED"
            if fresh:
                self.ledger.mark(intent.namespace, intent.key, "SENT")
            try:
                receipt = (await self.adapter.submit(intent) if fresh
                           else await self.adapter.reconcile(intent))
                self.adapter.validate_receipt(intent, receipt)
            except Exception as exc:
                # Only an explicit first-send HTTP rejection is definitive.
                # GET 404 never establishes that a preceding POST did not run.
                status = getattr(exc, "status", 0)
                rejected = fresh and 400 <= status < 500 and status != 408
                state = "REJECTED" if rejected else "UNKNOWN"
                self.ledger.mark(intent.namespace, intent.key, state,
                                 {"code": getattr(exc, "code", "SYNC_TRANSPORT_FAILED")} if rejected else prior_receipt)
                return SyncOutcome(state, code=getattr(exc, "code", "SYNC_TRANSPORT_FAILED"))
            self.ledger.mark(intent.namespace, intent.key, "ACCEPTED", receipt)
        try:
            # Read the exact receipt's accepted revision, never 'latest'.
            self.adapter.validate_receipt(intent, receipt)
            document = await self.adapter.readback(intent, receipt)
        except Exception as exc:
            return SyncOutcome("ACCEPTED", receipt, code=getattr(exc, "code", "READBACK_INCOMPLETE"))
        self.ledger.mark(intent.namespace, intent.key, "READBACK_COMPLETE", receipt)
        return SyncOutcome("READBACK_COMPLETE", receipt, document)


async def read_fixed_pages(fetch, validate, *, version: int | None = None,
                           max_chars: int = 16 * 1024 * 1024) -> dict:
    """Reassemble JSON with contiguous offsets, fixed identity and fixed version."""
    chunks, offset, identity, total = [], 0, None, None
    while True:
        arguments = {"offset": offset, "limit": 24000}
        if version is not None:
            arguments["version"] = version
        page = await fetch(arguments)
        validate(page, arguments)
        observed = (page["task_id"], page["version"], page["total_chars"])
        if identity is not None and identity != observed:
            raise SyncError("READBACK_IDENTITY_CHANGED")
        identity, version, total = observed, page["version"], page["total_chars"]
        if total > max_chars:
            raise SyncError("READBACK_SIZE_EXCEEDED")
        chunks.append(page["content"])
        if page["complete"]:
            break
        offset = page["next_offset"]
    content = "".join(chunks)
    if len(content) != total:
        raise SyncError("READBACK_INCOMPLETE")
    try:
        result = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise SyncError("READBACK_INVALID_JSON") from exc
    if not isinstance(result, dict):
        raise SyncError("READBACK_INVALID_JSON")
    return result
