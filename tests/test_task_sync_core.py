"""Shared delivery contract with no domain/version/auth assumptions."""
from copy import deepcopy

import pytest

from hypertest.sync_core import FrozenIntent, SyncError, TaskSyncCore, merge_present


class Ledger:
    def __init__(self):
        self.rows = {}
        self.transitions = []

    def prepare(self, intent):
        identity = (intent.namespace, intent.key)
        prior = self.rows.get(identity)
        if prior and prior["digest"] != intent.request_digest:
            raise SyncError("IDEMPOTENCY_CONFLICT")
        return self.rows.setdefault(identity, {"state": "PREPARED", "receipt": None,
                                               "digest": intent.request_digest})

    def mark(self, namespace, key, state, receipt=None):
        self.transitions.append(state)
        self.rows[(namespace, key)].update(state=state, receipt=deepcopy(receipt))


class Adapter:
    def __init__(self):
        self.calls = []
        self.fail_submit = False
        self.fail_lookup = False
        self.fail_readback = False

    async def submit(self, intent):
        self.calls.append("POST")
        if self.fail_submit:
            raise SyncError("LOST_RESPONSE")
        return {"operation_key": intent.key, "accepted_revision": 37}

    async def reconcile(self, intent):
        self.calls.append("GET_RECEIPT")
        if self.fail_lookup:
            error = SyncError("NOT_FOUND")
            error.status = 404
            raise error
        return {"operation_key": intent.key, "accepted_revision": 37}

    def validate_receipt(self, intent, receipt):
        if receipt.get("operation_key") != intent.key:
            raise SyncError("BAD_RECEIPT")

    async def readback(self, intent, receipt):
        self.calls.append(("GET_REVISION", receipt["accepted_revision"]))
        if self.fail_readback:
            raise SyncError("MISSING_PAGE")
        return {"assets": ["exact original bytes"]}


def intent(namespace="cloud-attempt:independent"):
    return FrozenIntent(namespace, "original-key", {"attempt": "A", "generation": 7},
                        {"kind": "REPORT", "content": "failure"}, expected_version=2)


def test_frozen_intent_defensively_copies_every_mutable_view():
    body = {"content": ["original"]}
    frozen = FrozenIntent("local", "one", {"source": {"id": "real"}}, body, 0)
    body["content"][0] = "changed"
    leaked = frozen.payload
    leaked["content"].append("changed")
    assert frozen.payload == {"content": ["original"]}
    assert merge_present({"plan": "keep", "result": "FAIL"}, {"status": "BLOCKED"}) == {
        "plan": "keep", "result": "FAIL", "status": "BLOCKED"}
    with pytest.raises(SyncError, match="CLEAR_FIELD_UNSUPPORTED"):
        merge_present({"result": "FAIL"}, {}, clear_fields=["result"])


async def test_sent_and_not_found_are_get_only_and_isolated_per_namespace():
    ledger, adapter = Ledger(), Adapter()
    core = TaskSyncCore(ledger, adapter)
    adapter.fail_submit = True
    assert (await core.deliver(intent())).state == "UNKNOWN"
    adapter.fail_submit = False
    adapter.fail_lookup = True
    assert (await core.deliver(intent())).state == "UNKNOWN"
    assert (await core.deliver(intent())).state == "UNKNOWN"
    assert adapter.calls == ["POST", "GET_RECEIPT", "GET_RECEIPT"]
    adapter.fail_lookup = False
    assert (await core.deliver(intent("local-source:separate"))).synced
    assert adapter.calls[-2:] == ["POST", ("GET_REVISION", 37)]
    assert ledger.rows[(intent().namespace, "original-key")]["state"] == "UNKNOWN"


async def test_accepted_is_not_synced_and_readback_retries_without_post_or_latest():
    ledger, adapter = Ledger(), Adapter()
    core = TaskSyncCore(ledger, adapter)
    adapter.fail_readback = True
    first = await core.deliver(intent())
    assert first.state == "ACCEPTED" and not first.synced
    adapter.fail_readback = False
    second = await core.deliver(intent())
    assert second.state == "READBACK_COMPLETE" and second.synced
    assert adapter.calls == ["POST", ("GET_REVISION", 37), ("GET_REVISION", 37)]
    assert ledger.transitions == ["SENT", "ACCEPTED", "READBACK_COMPLETE"]
