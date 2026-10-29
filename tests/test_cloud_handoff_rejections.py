"""Only pre-freeze malformed proposals get local feedback; no models or DB."""
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hypertest.api.cloud_schemas import PROFILE
from hypertest.cloud.broker import BrokerFailure
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.handoff_rejections import MAX_LOCAL_REJECTIONS, HandoffRejected, key_digest
from hypertest.cloud.manifests import MANIFEST_PROFILE, Handoff
from hypertest.cloud.reporter import CloudTaskReporter
from hypertest.cloud.worker import CloudWorker
from hypertest.sync_core import FrozenIntent, digest


class Broker:
    def __init__(self):
        self.project_id, self.task_id, self.attempt_id = (str(uuid4()) for _ in range(3))
        self.version = 1
        self.identity = SimpleNamespace(generation=1)
        self.posts, self.validations, self.checks = [], [], 0

    async def assert_current(self):
        self.checks += 1

    async def validate_payload(self, request):
        self.validations.append(request)

    async def submit(self, request):
        self.posts.append(request)
        version = request["expected_version"] + 1
        assets = [{**asset, "id": str(uuid4()), "revision": 1} for asset in request["assets"]]
        self.document = {"task": {"id": self.task_id, "project_id": self.project_id, "version": version},
            "attempts": [{"id": self.attempt_id, "checkpoint": {}}], "assets": assets}
        return {"status": "ACCEPTED", "profile": PROFILE,
            "project_id": self.project_id, "task_id": self.task_id, "attempt_id": self.attempt_id,
            "operation_key": request["operation_key"], "operation": request["operation"],
            "version": version, "checkpoint": {}, "assets": assets}

    async def page(self, *, version, offset, limit):
        content = json.dumps(self.document)
        chunk = content[offset:offset + limit]
        return {"task_id": self.task_id, "version": version, "offset": offset, "content": chunk,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "total_characters": len(content), "next_offset": offset + len(chunk), "complete": offset + len(chunk) == len(content)}


@pytest.fixture
def reporting(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    broker = Broker()
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=workspace)
    yield reporter, broker, workspace
    reporter.close()


def case(reporter, key="private-key-canary", *, valid=False):
    return Handoff(profile=MANIFEST_PROFILE, task_id=reporter.broker.task_id, attempt_id=reporter.broker.attempt_id,
        key=key, operation="SUBMIT_ASSETS", payload={"assets": [{"kind": "CASE", "key": "case-one", "title": "Case",
            "markdown": "private-source-canary", "details": {"steps": [], "expected": "match", **({"actual": "NOT_RUN"} if valid else {})}}]})


def publish(workspace, handoff, name):
    ready = workspace / ".hypertest-cloud" / "ready"
    ready.mkdir(parents=True, exist_ok=True)
    (ready / name).write_text(handoff.model_dump_json())


async def test_invalid_case_is_locally_rejected_without_journal_snapshot_or_platform_write(reporting):
    reporter, broker, workspace = reporting
    handoff = case(reporter)
    with pytest.raises(HandoffRejected) as rejected:
        await reporter.submit_handoff(handoff, digest(handoff.model_dump(mode="json")))
    document = rejected.value.observation
    assert document["status"] == "LOCAL_REJECTED" and document["platform_operation_submitted"] is False
    assert document["required_action"] == "PUBLISH_NEW_HANDOFF_KEY"
    assert document["errors"] == [{"type": "value_error", "loc": ["SUBMIT_ASSETS", "assets", 0]}]
    assert document["key_sha256"] == key_digest(handoff.key)
    assert broker.posts == broker.validations == [] and reporter.pending() == []
    assert reporter.journal.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    assert list(reporter.snapshots.directory.iterdir()) == []
    public = workspace / ".hypertest-cloud" / "rejections" / (key_digest(handoff.key) + ".json")
    assert json.loads(public.read_bytes()) == document and public.stat().st_mode & 0o077 == 0
    assert "private-" not in public.read_text() and not (workspace / ".hypertest-cloud" / "receipts").exists()


async def test_collect_skips_original_bad_key_and_accepts_only_new_revision_key(reporting):
    reporter, broker, workspace = reporting
    handoff = case(reporter)
    publish(workspace, handoff, "01-invalid.json")
    worker = CloudWorker(None, None, "fixture")
    accepted = {}
    assert await worker.collect(reporter, workspace, accepted, stopped=False) is None
    checks = broker.checks
    assert await worker.collect(reporter, workspace, accepted, stopped=False) is None
    assert broker.checks == checks and broker.posts == []
    publish(workspace, case(reporter, valid=True), "01-invalid.json")
    assert await worker.collect(reporter, workspace, accepted, stopped=False) is None
    assert broker.posts == []  # Editing the rejected key cannot turn it into a submission.
    revised = case(reporter, key="revision-two", valid=True)
    publish(workspace, revised, "02-revision.json")
    await worker.collect(reporter, workspace, accepted, stopped=False)
    assert len(broker.posts) == 1 and set(accepted) == {"revision-two"}
    assert reporter.pending() == [] and reporter.version == 2
    receipt = json.loads((workspace / ".hypertest-cloud/receipts/revision-two.json").read_bytes())
    assert receipt["status"] == "ACCEPTED" and receipt["version"] == 2


async def test_digest_mismatch_retries_fixed_readback_without_resubmission(reporting):
    reporter, broker, _ = reporting
    handoff = case(reporter, key="stable-key", valid=True)
    original_page = broker.page

    async def corrupt_page(**kwargs):
        page = await original_page(**kwargs)
        return {**page, "sha256": "0" * 64}

    broker.page = corrupt_page
    source_digest = digest(handoff.model_dump(mode="json"))
    first = await reporter.submit_handoff(handoff, source_digest)
    assert first.state == "ACCEPTED" and first.code == "CLOUD_READBACK_DIGEST_MISMATCH"
    assert len(broker.posts) == 1 and reporter.pending()
    broker.page = original_page
    second = await reporter.submit_handoff(handoff, source_digest)
    assert second.synced and len(broker.posts) == 1 and reporter.pending() == []


async def test_unknown_frozen_request_blocks_correction_without_transport_or_key_replacement(reporting):
    reporter, broker, _ = reporting
    original = FrozenIntent(reporter.namespace, "original-key", {"generation": 1}, {"frozen": "original"}, 1)
    reporter.snapshots.save(original)
    reporter.core.ledger.prepare(original)
    reporter.core.ledger.mark(original.namespace, original.key, "UNKNOWN")
    with pytest.raises(CloudBlocked) as error:
        await reporter.submit_handoff(case(reporter), digest({"fixture": "bad"}))
    assert error.value.code == "REPORT_STREAM_PENDING"
    assert reporter.journal.get(original.namespace, original.key)["state"] == "UNKNOWN"
    assert reporter.snapshots.load(original.namespace, original.key).payload == original.payload
    assert list(reporter.rejections.directory.iterdir()) == [] and broker.posts == broker.validations == []


async def test_secret_validation_failure_is_fatal_and_not_a_correctable_local_rejection(reporting):
    reporter, broker, _ = reporting

    async def reject_secret(_):
        raise CloudBlocked("SECRET_MATERIAL_FORBIDDEN", "fixed policy code")

    broker.validate_payload = reject_secret
    valid = case(reporter, valid=True)
    with pytest.raises(CloudBlocked) as error:
        await reporter.submit_handoff(valid, digest(valid.model_dump(mode="json")))
    assert error.value.code == "SECRET_MATERIAL_FORBIDDEN"
    assert list(reporter.rejections.directory.iterdir()) == [] and broker.posts == []
    assert reporter.pending() == [] and list(reporter.snapshots.directory.iterdir()) == []


async def test_platform_http_rejection_keeps_original_frozen_transport_and_no_local_feedback(reporting):
    reporter, broker, _ = reporting

    async def refuse(request):
        broker.posts.append(request)
        raise BrokerFailure(403, "CLOUD_OPERATION_REJECTED")

    broker.submit = refuse
    handoff = case(reporter, valid=True)
    result = await reporter.submit_handoff(handoff, digest(handoff.model_dump(mode="json")))
    assert result.state == "REJECTED" and not result.synced
    assert len(broker.posts) == 1 and list(reporter.rejections.directory.iterdir()) == []
    assert len(list(reporter.snapshots.directory.iterdir())) == 1
    key = "c:" + digest([broker.attempt_id, handoff.key])
    assert reporter.journal.get(reporter.namespace, key)["state"] == "REJECTED"


async def test_invalid_host_identity_is_not_reported_as_an_agent_correctable_proposal(reporting):
    reporter, broker, _ = reporting
    broker.project_id = "private-host-identity"
    handoff = case(reporter, valid=True)
    with pytest.raises(ValidationError):
        reporter.prevalidate_handoff(handoff, digest(handoff.model_dump(mode="json")))
    assert broker.posts == [] and list(reporter.rejections.directory.iterdir()) == []


async def test_agent_symlink_cannot_redirect_local_feedback_outside_the_workspace(reporting, tmp_path):
    reporter, broker, workspace = reporting
    root = workspace / ".hypertest-cloud"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "rejections").symlink_to(outside, target_is_directory=True)
    handoff = case(reporter)
    with pytest.raises(CloudBlocked) as error:
        reporter.prevalidate_handoff(handoff, digest(handoff.model_dump(mode="json")))
    assert error.value.code == "LOCAL_REJECTION_PATH_UNSAFE"
    assert list(outside.iterdir()) == [] and broker.posts == [] and reporter.pending() == []


async def test_malformed_terminal_is_prevalidated_before_collect_can_stop_the_runtime(reporting):
    reporter, broker, workspace = reporting
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id=broker.task_id, attempt_id=broker.attempt_id,
        key="bad-terminal", operation="COMPLETE_ATTEMPT", payload={})
    publish(workspace, handoff, "terminal.json")
    assert await CloudWorker(None, None, "fixture").collect(reporter, workspace, {}, stopped=False) is None
    assert reporter.rejected("bad-terminal") and broker.posts == [] and reporter.pending() == []


async def test_valid_terminal_preview_discards_inert_host_fields_and_requires_actual_stop_for_submit(reporting):
    reporter, broker, _ = reporting
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id=broker.task_id, attempt_id=broker.attempt_id,
        key="valid-terminal", operation="COMPLETE_ATTEMPT", payload={"final_report_revision": str(uuid4()),
            "reported_result": "NOT_RUN", "completion_manifest": {"required_asset_ids": [str(uuid4())],
                "no_tests_reason": "Fixture-only shape check", "scope_and_gaps": "No execution claimed"}})
    original = handoff.model_dump(mode="json")
    reporter.prevalidate_handoff(handoff, digest(original))
    assert handoff.model_dump(mode="json") == original
    assert list(reporter.snapshots.directory.iterdir()) == [] and list(reporter.rejections.directory.iterdir()) == []
    assert reporter.journal.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    with pytest.raises(CloudBlocked) as error:
        await reporter.submit_handoff(handoff, digest(original))
    assert error.value.code == "RUNTIME_STILL_ACTIVE" and broker.posts == broker.validations == []


async def test_local_feedback_bounds_error_count_and_drops_arbitrary_extra_field_names(reporting):
    reporter, _, _ = reporting
    handoff = case(reporter)
    asset = handoff.payload["assets"][0]
    asset["private-field-canary"] = "private-input-canary"
    handoff.payload["assets"] = [dict(asset) for _ in range(20)]
    with pytest.raises(HandoffRejected) as rejected:
        reporter.prevalidate_handoff(handoff, digest(handoff.model_dump(mode="json")))
    errors = rejected.value.observation["errors"]
    assert len(errors) == 8 and "private-" not in json.dumps(errors)
    assert any("OTHER" in item["loc"] for item in errors)


async def test_local_proposal_correction_count_is_finite(reporting):
    reporter, broker, _ = reporting
    for index in range(MAX_LOCAL_REJECTIONS):
        handoff = case(reporter, key=f"bad-{index}")
        with pytest.raises(HandoffRejected):
            reporter.prevalidate_handoff(handoff, digest(handoff.model_dump(mode="json")))
    handoff = case(reporter, key="one-too-many")
    with pytest.raises(CloudBlocked) as error:
        reporter.prevalidate_handoff(handoff, digest(handoff.model_dump(mode="json")))
    assert error.value.code == "LOCAL_REJECTION_LIMIT"
    assert len(list(reporter.rejections.directory.iterdir())) == MAX_LOCAL_REJECTIONS and broker.posts == []
