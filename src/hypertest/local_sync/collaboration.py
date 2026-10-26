"""Typed Local collaboration delivery, isolated from full sync and Cloud writes."""
from __future__ import annotations

from uuid import UUID

from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.errors import ClientError
from hypertest.sync_core import SyncError, canonical_json, digest, read_fixed_pages

PROFILE = "local-task-collaboration/v1alpha1"
COLLABORATION_TOOLS = {
    "hypertest_join_task": "JOIN",
    "hypertest_contribute_task": "CONTRIBUTE",
    "hypertest_publish_task": "PUBLISH",
}
GET_COLLABORATION_TOOL = "hypertest_get_task_collaboration"


def namespace(payload):
    # One root owns each stream; the server additionally fences keys across
    # all sources and operations within the actor/Project namespace.
    source = {key: payload[key] for key in ("provider", "session_id")}
    return ":".join(("task-collaboration", payload["project_id"], payload["task_id"],
                     digest(source), payload["operation"]))


def validate_receipt(receipt, key, *, payload):
    try:
        valid = (
            receipt["profile"] == PROFILE and receipt["status"] == "ACCEPTED"
            and receipt["idempotency_key"] == key
            and all(receipt[field] == payload[field] for field in (
                "operation", "project_id", "task_id", "provider", "session_id"))
            and type(receipt["version"]) is int and receipt["version"] > 0
            and ("expected_version" not in payload
                 or receipt["version"] == payload["expected_version"] + 1)
            and str(UUID(receipt["participant_id"])) == receipt["participant_id"]
            and receipt["actor_ref"].startswith("interactive:")
            and str(UUID(receipt["actor_ref"].split(":", 1)[1]))
                == receipt["actor_ref"].split(":", 1)[1]
            and type(receipt["primary_generation"]) is int
            and receipt["primary_generation"] >= 1
            and isinstance(receipt["contribution_refs"], list)
            and isinstance(receipt["request_digest"], str)
            and len(receipt["request_digest"]) == 64
            and all(character in "0123456789abcdef" for character in receipt["request_digest"])
            and ("expected_version" not in payload or receipt["request_digest"] == digest(payload))
        )
        if payload["operation"] == "PUBLISH" and "primary_generation" in payload:
            valid = valid and receipt["primary_generation"] == payload["primary_generation"]
        for ref in receipt["contribution_refs"]:
            valid = valid and (str(UUID(ref["contribution_id"])) == ref["contribution_id"]
                and type(ref["revision"]) is int and ref["revision"] > 0)
    except (KeyError, TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ApiError("INVALID_COLLABORATION_RECEIPT")


def validate_page(page, arguments):
    from hypertest.interactive_client.service import validate_task_page
    if page.get("profile") != PROFILE:
        raise ClientError("INVALID_COLLABORATION_PAGE")
    # Collaboration has per-contribution sources rather than a single source
    # field on its envelope. Reuse only the bounded fixed-page geometry.
    validate_task_page({**page, "source": None}, arguments)


class LocalCollaborationAdapter:
    def __init__(self, api):
        self.api = api

    @staticmethod
    def path(identity):
        return "interactive/tasks/" + identity["task_id"] + "/collaboration"

    async def submit(self, intent):
        payload = {key: value for key, value in intent.payload.items() if key != "task_id"}
        return await self.api.request("POST", self.path(intent.target), payload=payload)

    async def reconcile(self, intent):
        return await self.api.request("GET", self.path(intent.target) + "/receipts/by-key", params={
            **{field: intent.target[field] for field in ("project_id", "provider", "session_id")},
            "idempotency_key": intent.key})

    def validate_receipt(self, intent, receipt):
        # task_id is a route selector, not part of the server's body digest.
        wire = {key: value for key, value in intent.payload.items() if key != "task_id"}
        identity = {**wire, "task_id": intent.target["task_id"]}
        identity.pop("expected_version", None)
        validate_receipt(receipt, intent.key, payload=identity)
        if (receipt["version"] != intent.expected_version + 1
                or receipt["request_digest"] != digest(wire)):
            raise ApiError("INVALID_COLLABORATION_RECEIPT")

    async def baseline(self, identity, *, version=None):
        observed = {}

        async def fetch(arguments):
            page = await self.api.request("GET", self.path(identity), params={
                **{field: identity[field] for field in ("project_id", "provider", "session_id")},
                **arguments})
            observed["version"] = page.get("version")
            return page

        document = await read_fixed_pages(fetch, lambda page, args: validate_page(
            page, {**args, "task_id": identity["task_id"]}), version=version)
        try:
            task, collaboration = document["task"], document["collaboration"]
            valid = (document["profile"] == PROFILE and task["id"] == identity["task_id"]
                and task["project_id"] == identity["project_id"]
                and type(task["version"]) is int and task["version"] > 0
                and task["version"] == observed["version"]
                and (version is None or task["version"] == version)
                and collaboration["enabled"] is True
                and isinstance(collaboration["participants"], list)
                and isinstance(collaboration["contributions"], list)
                and isinstance(collaboration["publications"], list)
                and isinstance(document["operation_history"], list))
        except (KeyError, TypeError):
            valid = False
        if not valid:
            raise ClientError("INVALID_COLLABORATION_DOCUMENT")
        return document

    async def readback(self, intent, receipt):
        document = await self.baseline(intent.target, version=receipt["version"])
        collaboration = document["collaboration"]
        participant = next((item for item in collaboration["participants"]
                            if item.get("id") == receipt["participant_id"]), None)
        if (participant is None
                or any(participant.get(field) != intent.target[field]
                       for field in ("provider", "session_id"))
                or participant.get("actor_ref") != receipt["actor_ref"]
                or participant.get("status") != "ACTIVE"):
            raise SyncError("COLLABORATION_PARTICIPANT_READBACK_MISMATCH")
        wire = {key: value for key, value in intent.payload.items() if key != "task_id"}
        operation = next((item for item in document["operation_history"]
            if item.get("response", {}).get("idempotency_key") == intent.key
            and item.get("response", {}).get("operation") == wire["operation"]), None)
        if (operation is None or canonical_json(operation.get("request_payload")) != canonical_json(wire)
                or canonical_json(operation.get("response")) != canonical_json(receipt)):
            raise SyncError("COLLABORATION_OPERATION_READBACK_MISMATCH")
        if wire["operation"] == "CONTRIBUTE":
            if len(receipt["contribution_refs"]) != len(wire["contributions"]):
                raise SyncError("COLLABORATION_CONTRIBUTION_READBACK_MISMATCH")
            for submitted, ref in zip(wire["contributions"], receipt["contribution_refs"], strict=True):
                accepted = next((item for item in collaboration["contributions"]
                    if item.get("id") == ref["contribution_id"] and item.get("revision") == ref["revision"]), None)
                if (accepted is None or accepted.get("participant_id") != receipt["participant_id"]
                        or any(canonical_json(accepted.get(field)) != canonical_json(submitted[field])
                               for field in ("kind", "stable_key", "content"))
                        or ref["revision"] != submitted["expected_revision"] + 1):
                    raise SyncError("COLLABORATION_CONTRIBUTION_READBACK_MISMATCH")
        if wire["operation"] == "PUBLISH":
            publication = next((item for item in collaboration["publications"]
                if item.get("participant_id") == receipt["participant_id"]
                and item.get("task_version") == receipt["version"]), None)
            if (collaboration["primary_participant_id"] != receipt["participant_id"]
                    or collaboration["primary_generation"] != wire["primary_generation"]
                    or participant.get("role") != "PRIMARY"
                    or publication is None
                    or publication.get("primary_generation") != wire["primary_generation"]
                    or canonical_json(publication.get("summary")) != canonical_json(wire["summary"])
                    or any(document["task"].get(field) != wire["summary"][field]
                           for field in ("title", "objective", "status", "plan_markdown", "reported_result"))):
                raise SyncError("COLLABORATION_PUBLICATION_READBACK_MISMATCH")
        return document
