"""Local binding uses the same durable delivery core, never a fake sync receipt."""
from uuid import UUID

from hypertest.interactive_client.api_client import ApiError
from hypertest.local_sync.adapter import LocalSyncAdapter
from hypertest.sync_core import SyncError


def validate_binding_receipt(receipt, key, *, payload=None):
    payload = payload or {}
    try:
        valid = (receipt["status"] == "ACCEPTED" and receipt["operation"] == "BIND"
            and receipt["profile"] == "codex-session-task-sync/v1alpha1"
            and receipt["idempotency_key"] == key and receipt["binding_state"] == "BOUND"
            and receipt.get("source") is None and receipt["actor_ref"].startswith("interactive:")
            and type(receipt["version"]) is int and receipt["version"] > 1
            and str(UUID(receipt["task_id"])) == receipt["task_id"]
            and str(UUID(receipt["project_id"])) == receipt["project_id"]
            and str(UUID(receipt["actor_ref"].split(":", 1)[1])) == receipt["actor_ref"].split(":", 1)[1]
            and all(receipt.get(field) == payload[field]
                    for field in ("task_id", "project_id", "provider", "session_id") if field in payload)
            and isinstance(receipt["provider"], str) and bool(receipt["provider"])
            and isinstance(receipt["session_id"], str) and bool(receipt["session_id"])
            and ("expected_version" not in payload or receipt["version"] == payload["expected_version"] + 1))
    except (ValueError, KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ApiError("INVALID_BINDING_RECEIPT")


class LocalBindingAdapter:
    def __init__(self, api):
        self.api = api
        self.reader = LocalSyncAdapter(api)

    async def submit(self, intent):
        return await self.api.request("POST", "interactive/tasks/bind", payload=intent.payload)

    async def reconcile(self, intent):
        return await self.api.request("GET", "interactive/tasks/bindings/by-key", params={
            "project_id": intent.target["project_id"], "idempotency_key": intent.key})

    def validate_receipt(self, intent, receipt):
        validate_binding_receipt(receipt, intent.key, payload=intent.payload)

    async def readback(self, intent, receipt):
        document = await self.reader.baseline(intent.target, version=receipt["version"],
                                              allow_unsynced=True)
        task = document["task"]
        if (task.get("binding_state") != "BOUND" or task.get("binding_required") is not True
                or task.get("owner_actor_ref") != receipt["actor_ref"]
                or not task.get("bound_at") or task.get("source") is not None
                or task.get("last_synced_at") is not None):
            raise SyncError("BINDING_READBACK_REJECTED")
        return document
