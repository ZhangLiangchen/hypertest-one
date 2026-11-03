"""Native session anchors use the same frozen, original-key reporter semantics."""
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.api.cloud_schemas import PROFILE
from hypertest.cloud.broker import BrokerFailure
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.manifests import MANIFEST_PROFILE, load_handoff
from hypertest.cloud.reporter import CloudTaskReporter
from hypertest.sync_core import digest


class Broker:
    def __init__(self, *, lose_response=False, missing_receipt=False, corrupt_receipt=False):
        self.project_id, self.task_id, self.attempt_id = (str(uuid4()) for _ in range(3))
        self.version = 7
        self.identity = SimpleNamespace(worker_id="fixture-worker", generation=1)
        self.lose_response, self.missing_receipt, self.corrupt_receipt = lose_response, missing_receipt, corrupt_receipt
        self.posts, self.queries, self.pages, self.validations = [], [], [], []
        self.accepted = self.document = None

    async def validate_payload(self, payload):
        self.validations.append(payload)

    async def submit(self, payload):
        self.posts.append(payload)
        version = payload["expected_version"] + 1
        anchor = {key: payload[key] for key in ("identity_profile", "snapshot_sha256", "input_digest", "session_id")}
        anchor.update(worker_id=self.identity.worker_id, generation=self.identity.generation)
        checkpoint = {"native_session_anchor": anchor}
        self.document = {"task": {"id": self.task_id, "project_id": self.project_id, "version": version},
                         "attempts": [{"id": self.attempt_id, "checkpoint": checkpoint}]}
        self.accepted = {"status": "ACCEPTED", "profile": PROFILE, "project_id": self.project_id,
            "task_id": self.task_id, "attempt_id": self.attempt_id, "operation_key": payload["operation_key"],
            "operation": payload["operation"], "version": version, "checkpoint": checkpoint,
            "native_session_anchor": anchor}
        if self.lose_response:
            raise RuntimeError("synthetic response lost after acceptance")
        return self._receipt()

    def _receipt(self):
        if not self.corrupt_receipt:
            return self.accepted
        return {**self.accepted, "native_session_anchor": {**self.accepted["native_session_anchor"],
                                                            "snapshot_sha256": "b" * 64}}

    async def receipt(self, key):
        self.queries.append(key)
        if self.missing_receipt:
            raise BrokerFailure(404, "original receipt not observed")
        assert key == self.accepted["operation_key"]
        return self._receipt()

    async def page(self, *, version, offset, limit):
        self.pages.append(version)
        content = json.dumps(self.document)
        chunk = content[offset:offset + limit]
        return {"task_id": self.task_id, "version": version, "offset": offset, "content": chunk,
                "total_characters": len(content), "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "next_offset": offset + len(chunk), "complete": offset + len(chunk) == len(content)}


def _arguments(broker):
    return {"snapshot_sha256": "a" * 64, "input_digest": "d" * 64,
            "session_id": "cloud-" + broker.attempt_id}


def test_agent_cannot_publish_a_native_session_anchor(tmp_path):
    ready = tmp_path / ".hypertest-cloud" / "ready"
    ready.mkdir(parents=True)
    (ready / "anchor.json").write_text(json.dumps({"profile": MANIFEST_PROFILE, "task_id": "task",
        "attempt_id": "attempt", "key": "anchor", "operation": "ANCHOR_NATIVE_SESSION", "payload": {}}))
    with pytest.raises(CloudBlocked) as error:
        load_handoff(tmp_path, ".hypertest-cloud/ready/anchor.json", task_id="task", attempt_id="attempt")
    assert error.value.code == "HANDOFF_OPERATION_UNSUPPORTED"


@pytest.mark.asyncio
async def test_anchor_lost_response_recovers_only_original_key_and_fixed_version(tmp_path):
    broker = Broker(lose_response=True)
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=tmp_path / "workspace")
    try:
        first = await reporter.submit_native_session_anchor(**_arguments(broker))
        assert first.state == "UNKNOWN" and len(broker.posts) == 1 and reporter.version == 7
        original_key = broker.posts[0]["operation_key"]
        agent_key = "c:" + digest([broker.attempt_id, "native-session-anchor-v1"])
        assert original_key != agent_key and reporter.journal.get(reporter.namespace, agent_key) is None
        assert reporter.pending() == [original_key]
        second = await reporter.submit_native_session_anchor(**_arguments(broker))
        assert second.synced and len(broker.posts) == 1 and broker.queries == [original_key]
        assert reporter.version == 8 and broker.pages == [8] and not reporter.pending()
        assert second.document["attempts"][0]["checkpoint"]["native_session_anchor"]["snapshot_sha256"] == "a" * 64
        with pytest.raises(CloudBlocked, match="immutable"):
            await reporter.submit_native_session_anchor(**{**_arguments(broker), "snapshot_sha256": "b" * 64})
        assert len(broker.posts) == 1
    finally:
        reporter.close()


@pytest.mark.asyncio
async def test_anchor_missing_original_receipt_is_unknown_not_replayed(tmp_path):
    broker = Broker(lose_response=True, missing_receipt=True)
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=tmp_path / "workspace")
    try:
        assert (await reporter.submit_native_session_anchor(**_arguments(broker))).state == "UNKNOWN"
        assert (await reporter.submit_native_session_anchor(**_arguments(broker))).state == "UNKNOWN"
        assert len(broker.posts) == 1 and broker.queries == [broker.posts[0]["operation_key"]]
        assert reporter.version == 7 and len(reporter.pending()) == 1
    finally:
        reporter.close()


@pytest.mark.asyncio
async def test_anchor_receipt_identity_mismatch_cannot_be_used(tmp_path):
    broker = Broker(corrupt_receipt=True)
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=tmp_path / "workspace")
    try:
        result = await reporter.submit_native_session_anchor(**_arguments(broker))
        assert not result.synced and reporter.version == 7
        assert len(broker.posts) == 1 and len(reporter.pending()) == 1
    finally:
        reporter.close()
