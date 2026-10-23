"""ADR-018 wire adapter. No Cloud identity, lease or execution capability."""
from __future__ import annotations

from hypertest.api.task_schemas import SessionTaskSync, TaskCase, TaskReport
from hypertest.interactive_client.api_client import ApiError
from hypertest.sync_core import FrozenIntent, SyncError, read_fixed_pages

SCALARS = ("title", "objective", "status", "plan_markdown", "reported_result")
CASE_FIELDS = tuple(TaskCase.model_fields)
REPORT_FIELDS = tuple(TaskReport.model_fields)


def task_document_payload(document: dict) -> dict:
    task = document["task"]
    return {**{field: task[field] for field in SCALARS},
            "cases": [{field: item[field] for field in CASE_FIELDS} for item in document["cases"]],
            "reports": [{field: item[field] for field in REPORT_FIELDS} for item in document["reports"]]}


class LocalSyncAdapter:
    def __init__(self, api, journal=None):
        self.api, self.journal = api, journal

    async def submit(self, intent: FrozenIntent) -> dict:
        return await self.api.request("POST", "interactive/tasks/sync", payload=intent.payload,
                                      device=False, execution_token=None, request_key=None)

    async def reconcile(self, intent: FrozenIntent) -> dict:
        return await self.api.request("GET", "interactive/tasks/syncs/by-key", params={
            "project_id": intent.target["project_id"], "idempotency_key": intent.key})

    def validate_receipt(self, intent: FrozenIntent, receipt: dict) -> None:
        from hypertest.interactive_client.service import validate_sync_receipt
        known = self.journal.get(intent.namespace, intent.key) if self.journal else None
        prior_task_id = intent.target.get("task_id") or ((known or {}).get("result") or {}).get("task_id")
        validate_sync_receipt(receipt, intent.key, intent.expected_version,
                              prior_task_id, intent.target)

    async def baseline(self, identity: dict, *, version=None, allow_unsynced=False) -> dict | None:
        from hypertest.interactive_client.service import validate_task_page
        source = {field: identity[field] for field in ("project_id", "provider", "session_id")}
        observed = {}

        async def fetch(arguments):
            task_id = identity.get("task_id")
            path = "interactive/tasks/" + task_id if task_id else "interactive/tasks/by-session"
            params = {"project_id": source["project_id"]} if task_id else source
            page = await self.api.request("GET", path, params={**params, **arguments})
            observed.update(task_id=page.get("task_id"), version=page.get("version"))
            return page

        try:
            document = await read_fixed_pages(fetch, validate_task_page, version=version)
        except ApiError as exc:
            if exc.status == 404 and version is None and not identity.get("task_id"):
                return None
            raise
        task = document.get("task", {})
        if (any(task.get(field) != value for field, value in source.items())
                or (task.get("source") != "AGENT_REPORTED" and not (
                    allow_unsynced and task.get("source") is None
                    and task.get("binding_state") == "BOUND"
                    and task.get("last_synced_at") is None))
                or (identity.get("task_id") is not None and task.get("id") != identity["task_id"])
                or task.get("id") != observed.get("task_id")
                or task.get("version") != observed.get("version")
                or type(task.get("version")) is not int
                or (version is not None and task["version"] != version)
                or not isinstance(document.get("cases"), list)
                or not isinstance(document.get("reports"), list)):
            raise SyncError("BASELINE_IDENTITY_REJECTED")
        return document

    async def readback(self, intent: FrozenIntent, receipt: dict) -> dict:
        document = await self.baseline(intent.target, version=receipt["version"])
        if document is None or document["task"].get("id") != receipt["task_id"]:
            raise SyncError("READBACK_TASK_ID_MISMATCH")
        expected = SessionTaskSync.model_validate(intent.payload).model_dump(mode="json")
        if any(document["task"].get(field) != expected[field] for field in SCALARS):
            raise SyncError("READBACK_TASK_CONTENT_MISMATCH")
        for group, fields in (("cases", CASE_FIELDS), ("reports", REPORT_FIELDS)):
            actual = {item["key"]: item for item in document[group]}
            for submitted in expected[group]:
                found = actual.get(submitted["key"])
                if found is None or any(found.get(field) != submitted[field] for field in fields):
                    raise SyncError("READBACK_ARTIFACT_CONTENT_MISMATCH")
        return document
