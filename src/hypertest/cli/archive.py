"""Archive adapter over TaskSyncCore; uncertain requests are only reconciled."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from hypertest.cli import PREFIX, PROFILE
from hypertest.cli.manifest import MAX_BYTES, load_manifest
from hypertest.cli.state import CLIError, State, identifier
from hypertest.cli.transport import HTTP
from hypertest.sync_core import FrozenIntent, TaskSyncCore, canonical_json

NAMESPACE = "local-artifact-archive"
METADATA = {"id", "revision", "submission_id", "accepted_at", "uploader_actor_ref"}
TARGET_KEYS = ("project_id", "task_id", "target_kind", "subtask_id")


def read_snapshot(http, path: str, target: dict, *, version: int | None = None,
                  submission_id: str | None = None) -> dict:
    offset, total, chunks = 0, None, []
    while True:
        page = http.call("GET", path, query={"project_id": target["project_id"],
                         "archive_version": version, "offset": offset, "limit": 24000})
        if (page.get("profile") != PROFILE or any(page.get(k) != target[k] for k in TARGET_KEYS)
                or (submission_id and page.get("submission_id") != submission_id)
                or type(page.get("archive_version")) is not int or page["archive_version"] < 1
                or (version is not None and page["archive_version"] != version)
                or type(page.get("offset")) is not int or page["offset"] != offset
                or not isinstance(page.get("content"), str)
                or len(page["content"]) > 24000 or type(page.get("complete")) is not bool
                or type(page.get("total_chars")) is not int
                or not 0 <= page["total_chars"] <= 16 * 1024 * 1024):
            raise CLIError("READBACK_ENVELOPE_MISMATCH", 4)
        if total is not None and total != page["total_chars"]:
            raise CLIError("READBACK_IDENTITY_CHANGED", 4)
        total, version = page["total_chars"], page["archive_version"]
        end = offset + len(page["content"])
        if (end > total or (page["complete"] and (end != total or page.get("next_offset") is not None))
                or (not page["complete"] and (end <= offset or end >= total
                                              or page.get("next_offset") != end))):
            raise CLIError("READBACK_OFFSET_MISMATCH", 4)
        chunks.append(page["content"])
        if page["complete"]:
            break
        offset = end
    try:
        result = json.loads("".join(chunks))
    except (ValueError, TypeError) as exc:
        raise CLIError("READBACK_INVALID_JSON", 4) from exc
    if (not isinstance(result, dict) or result.get("profile") != PROFILE
            or result.get("archive_version") != version
            or any(result.get(k) != target[k] for k in TARGET_KEYS)
            or not isinstance(result.get("assets"), list)):
        raise CLIError("READBACK_DOCUMENT_MISMATCH", 4)
    return result


def asset_map(document: dict) -> dict:
    result = {}
    for asset in document["assets"]:
        if not isinstance(asset, dict):
            raise CLIError("READBACK_INVALID_ASSET", 4)
        key = (asset.get("kind"), asset.get("stable_key"))
        if key in result or not all(isinstance(v, str) for v in key):
            raise CLIError("READBACK_DUPLICATE_ASSET", 4)
        result[key] = asset
    return result


def business(asset: dict) -> dict:
    return {k: v for k, v in asset.items() if k not in METADATA}


class ArchiveAdapter:
    def __init__(self, http):
        self.http = http

    async def submit(self, intent: FrozenIntent) -> dict:
        return self.http.call("POST", f"{PREFIX}/tasks/{intent.target['task_id']}/submissions",
                              body=intent.payload)

    async def reconcile(self, intent: FrozenIntent) -> dict:
        return self.http.call("GET", f"{PREFIX}/submissions/by-key", query={
            "project_id": intent.target["project_id"], "idempotency_key": intent.key})

    def validate_receipt(self, intent: FrozenIntent, receipt: dict) -> None:
        outcome = receipt.get("outcome")
        if (receipt.get("profile") != PROFILE or outcome not in {"ACCEPTED", "UNCHANGED"}
                or any(receipt.get(k) != intent.target[k] for k in TARGET_KEYS)
                or receipt.get("uploader_actor_ref") != intent.target["actor_ref"]
                or receipt.get("idempotency_key") != intent.key
                or receipt.get("request_digest") != intent.request_digest
                or type(receipt.get("accepted_version")) is not int
                or receipt["accepted_version"] != intent.expected_version + (outcome == "ACCEPTED")):
            raise CLIError("RECEIPT_MISMATCH", 4)
        identifier(receipt.get("submission_id"))

    async def readback(self, intent: FrozenIntent, receipt: dict) -> dict:
        actual = read_snapshot(self.http, f"{PREFIX}/submissions/{receipt['submission_id']}",
                               intent.target, version=receipt["accepted_version"],
                               submission_id=receipt["submission_id"])
        baseline, submitted = asset_map(intent.target["baseline"]), asset_map(intent.payload)
        expected = {**baseline, **submitted}
        observed = asset_map(actual)
        if observed.keys() != expected.keys():
            raise CLIError("READBACK_ASSET_SET_MISMATCH", 4)
        changed = False
        for key, wanted in expected.items():
            old, got = baseline.get(key), observed[key]
            if business(got) != business(wanted):
                raise CLIError("READBACK_CONTENT_MISMATCH", 4)
            if old is not None and business(old) == business(wanted):
                if got != old:
                    raise CLIError("READBACK_REVISION_MISMATCH", 4)
            else:
                changed = True
                if (set(got) != set(wanted) | METADATA
                        or type(got.get("revision")) is not int
                        or got.get("revision") != (old["revision"] + 1 if old else 1)
                        or got.get("submission_id") != receipt["submission_id"]
                        or got.get("uploader_actor_ref") != intent.target["actor_ref"]
                        or not isinstance(got.get("accepted_at"), str)):
                    raise CLIError("READBACK_REVISION_MISMATCH", 4)
                identifier(got.get("id"))
        if intent.target["subtask_id"]:
            for key in ("status", "reported_result"):
                wanted = intent.payload.get("subtask_update", {}).get(key, intent.target["baseline"][key])
                if actual.get(key) != wanted:
                    raise CLIError("READBACK_SUBTASK_MISMATCH", 4)
                changed |= wanted != intent.target["baseline"][key]
        elif "status" in actual or "reported_result" in actual:
            raise CLIError("READBACK_ROOT_STATE_MISMATCH", 4)
        if changed != (receipt["outcome"] == "ACCEPTED"):
            raise CLIError("READBACK_OUTCOME_MISMATCH", 4)
        return actual


def outcome_result(intent: FrozenIntent, state: str, receipt: dict | None = None,
                   code: str | None = None) -> tuple[dict, int]:
    receipt = receipt or {}
    complete = state == "READBACK_COMPLETE"
    status = ("UNCHANGED" if receipt.get("outcome") == "UNCHANGED" else "ARCHIVED") if complete else (
        "REJECTED" if state == "REJECTED" else "UNKNOWN" if state in {"SENT", "UNKNOWN"} else "PENDING")
    result = {"status": status, "request_id": intent.key,
              **{k: intent.target[k] for k in TARGET_KEYS}, "readback_complete": complete,
              "task_url": intent.target["server"] + "/archives/" + intent.target["task_id"]
                          + "?projectId=" + intent.target["project_id"]}
    for key in ("submission_id", "accepted_version"):
        if key in receipt:
            result[key] = receipt[key]
    if code:
        result["code"] = code
    return result, 0 if complete else 3 if status == "REJECTED" else 4


def deliver(state: State, intent: FrozenIntent, *, http_factory=HTTP) -> tuple[dict, int]:
    profile = state.profile(intent.target["profile_name"], project_id=intent.target["project_id"])
    if profile["server"] != intent.target["server"] or profile["actor_ref"] != intent.target["actor_ref"]:
        raise CLIError("PROFILE_IDENTITY_CONFLICT", 5)
    http = http_factory(profile["server"], token=profile["grant"]["credential"])
    with state.ledger() as ledger:
        outcome = asyncio.run(TaskSyncCore(ledger, ArchiveAdapter(http)).deliver(intent))
    return outcome_result(intent, outcome.state, outcome.receipt, outcome.code)


def archive(state: State, *, profile_name: str | None, project_id: str, task_id: str,
            subtask_id: str | None, manifest: Path, request_id: str | None = None,
            dry_run: bool = False, http_factory=HTTP) -> tuple[dict, int]:
    request_id = identifier(request_id) if request_id else str(uuid.uuid4())
    target = {"project_id": identifier(project_id), "task_id": identifier(task_id),
              "subtask_id": identifier(subtask_id) if subtask_id else None,
              "target_kind": "SUBTASK" if subtask_id else "TASK"}
    with state.lock("archive-request:" + request_id):
        if (state.requests / (request_id + ".json")).exists():
            intent = state.snapshots.load(NAMESPACE, request_id)
            if any(intent.target[k] != target[k] for k in TARGET_KEYS) or (
                    profile_name and profile_name != intent.target["profile_name"]):
                raise CLIError("REQUEST_TARGET_MISMATCH")
            if dry_run:
                raise CLIError("EXISTING_REQUEST_REQUIRES_STATUS")
            return deliver(state, intent, http_factory=http_factory)
        body = load_manifest(manifest, project_id=project_id, task_id=task_id, subtask_id=subtask_id)
        profile = state.profile(profile_name, project_id=target["project_id"])
        with state.lock("archive-target:" + canonical_json([profile["server"], target])):
            http = http_factory(profile["server"], token=profile["grant"]["credential"])
            path = f"{PREFIX}/tasks/{task_id}"
            if subtask_id:
                path += f"/subtasks/{subtask_id}"
            baseline = read_snapshot(http, path + "/archive", target)
            body.update(idempotency_key=request_id, expected_archive_version=baseline["archive_version"])
            if len(canonical_json(body).encode()) > MAX_BYTES:
                raise CLIError("REQUEST_SIZE_EXCEEDED")
            if dry_run:
                return {"status": "PREVIEW", "request_id": request_id, **target,
                        "asset_count": len(body["assets"]), "readback_complete": False}, 0
            intent = FrozenIntent(NAMESPACE, request_id,
                                  {**target, "profile_name": profile["name"], "server": profile["server"],
                                   "actor_ref": profile["actor_ref"], "baseline": baseline},
                                  body, baseline["archive_version"])
            state.snapshots.save(intent)
            state.write(state.requests, request_id, {"request_id": request_id})
            return deliver(state, intent, http_factory=http_factory)


def status(state: State, request_id: str, *, remote: bool = False, http_factory=HTTP) -> tuple[dict, int]:
    request_id = identifier(request_id)
    with state.lock("archive-request:" + request_id):
        intent = state.snapshots.load(NAMESPACE, request_id)
        with state.ledger() as ledger:
            record = ledger.journal.get(NAMESPACE, request_id)
            if not record:
                # A crash before SENT is not a recovery mandate to upload.
                return outcome_result(intent, "PREPARED", code="REQUEST_NOT_SENT")
            if remote and record["state"] == "PENDING":
                return outcome_result(intent, "PREPARED", code="REQUEST_NOT_SENT")
        if remote:
            return deliver(state, intent, http_factory=http_factory)
        return outcome_result(intent, ledger.TO_CORE.get(record["state"], record["state"]),
                              record.get("result"))
