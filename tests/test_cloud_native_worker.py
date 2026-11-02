from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from hypertest.cloud.broker import BrokerFailure
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.manifests import MANIFEST_PROFILE, Handoff
from hypertest.cloud.native_worker import WorkerAPI, complete_claim, prepare_claim
from hypertest.cloud.reporter import CloudTaskReporter


def test_claim_must_not_be_replayed_after_unconfirmed_send(tmp_path):
    pending = prepare_claim(tmp_path, "worker-test")
    with pytest.raises(CloudBlocked, match="Original claim"):
        prepare_claim(tmp_path, "worker-test")
    complete_claim(pending)
    assert prepare_claim(tmp_path, "worker-test").exists()


@pytest.mark.asyncio
async def test_http_rejection_is_distinct_from_unconfirmed_transport():
    client = WorkerAPI("https://example.invalid", b"a" * 32)
    await client.client.aclose()
    async def denied(request):
        return httpx.Response(409, json={"detail": "private response"})
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(denied), base_url="https://example.invalid/")
    with pytest.raises(BrokerFailure) as rejected:
        await client.request("submit", {})
    assert rejected.value.status == 409 and "private response" not in str(rejected.value)
    await client.client.aclose()
    async def lost(request):
        raise httpx.ReadTimeout("private transport content", request=request)
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(lost), base_url="https://example.invalid/")
    with pytest.raises(CloudBlocked) as unknown:
        await client.request("submit", {})
    assert unknown.value.code == "WORKER_API_UNCONFIRMED" and "private" not in str(unknown.value)
    await client.close()


@pytest.mark.asyncio
async def test_native_completion_does_not_claim_unknown_processes_or_external_scope(tmp_path):
    ids = [str(uuid4()) for _ in range(5)]
    class Broker:
        project_id, task_id, attempt_id = ids[:3]
        version = 1
        identity = SimpleNamespace(generation=1)
        async def validate_payload(self, payload):
            self.payload = payload
    broker = Broker()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=workspace)
    async def deliver(intent):
        return SimpleNamespace(synced=False, intent=intent)
    reporter.core.deliver = deliver
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id=broker.task_id, attempt_id=broker.attempt_id,
        key="finish", operation="COMPLETE_ATTEMPT", payload={"final_report_revision": ids[3],
        "reported_result": "UNKNOWN", "completion_manifest": {"required_asset_ids": [ids[4]],
        "scope_and_gaps": "Native host execution", "pending_operation_keys": []}})
    outcome = await reporter.submit_native_completion(handoff, "a" * 64, usage_seconds=4)
    payload = outcome.intent.payload
    assert payload["operation"] == "COMPLETE_NATIVE_ATTEMPT"
    assert payload["runtime_observation"] == "DIRECT_SDK_PROCESS_EXITED"
    assert payload["completion_manifest"]["all_local_processes_stopped"] is False
    assert payload["completion_manifest"]["external_operations_reconciled"] is False
    reporter.close()


@pytest.mark.asyncio
async def test_native_completion_persists_receipt_and_full_original_readback(tmp_path):
    import hashlib
    import json

    from hypertest.api.cloud_schemas import PROFILE

    ids = [str(uuid4()) for _ in range(5)]
    class Broker:
        project_id, task_id, attempt_id = ids[:3]
        version = 1
        identity = SimpleNamespace(generation=1)
        async def validate_payload(self, payload):
            pass
        async def submit(self, payload):
            checkpoint = {"final_report_revision": ids[3], "completion_manifest": payload["completion_manifest"],
                "native_completion_observation": {"runtime": "DIRECT_SDK_PROCESS_EXITED",
                    "other_local_processes": "UNKNOWN", "external_operations": "NOT_OBSERVED"}}
            self.document = {"task": {"id": self.task_id, "project_id": self.project_id, "version": 2,
                "status": "COMPLETED", "reported_result": "UNKNOWN"},
                "attempts": [{"id": self.attempt_id, "status": "COMPLETED", "reported_result": "UNKNOWN",
                              "checkpoint": checkpoint}], "assets": []}
            return {"status": "ACCEPTED", "profile": PROFILE, "project_id": self.project_id,
                "task_id": self.task_id, "attempt_id": self.attempt_id, "operation": payload["operation"],
                "operation_key": payload["operation_key"], "version": 2, "checkpoint": checkpoint}
        async def page(self, *, version, offset, limit):
            content = json.dumps(self.document)
            page = content[offset:offset + limit]
            return {"task_id": self.task_id, "version": version, "offset": offset, "content": page,
                "total_characters": len(content), "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "next_offset": offset + len(page), "complete": offset + len(page) == len(content)}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    broker = Broker()
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=workspace)
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id=broker.task_id, attempt_id=broker.attempt_id,
        key="finish", operation="COMPLETE_ATTEMPT", payload={"final_report_revision": ids[3],
        "reported_result": "UNKNOWN", "completion_manifest": {"required_asset_ids": [ids[4]],
        "scope_and_gaps": "Host process and remote operations unobserved", "pending_operation_keys": []}})
    result = await reporter.submit_native_completion(handoff, "a" * 64, usage_seconds=4)
    assert result.synced and reporter.version == 2 and not reporter.pending()
    reporter.close()


@pytest.mark.asyncio
async def test_resolution_rechecks_original_authority_before_each_git_access(tmp_path, monkeypatch):
    from hypertest.cloud.native_git import NativeGitResolver
    from hypertest.cloud.native_worker import resolve

    ids = [str(uuid4()) for _ in range(3)]
    operations = []
    class API:
        async def request(self, operation, body):
            operations.append((operation, body))
            return {"current": True}
    async def fake_resolve(self, url, selector, *, token=None):
        operations.append(("git", {"url": url, "token": token}))
        return {"url": url, "selector": selector, "commit_sha": "a" * 40}
    monkeypatch.setattr(NativeGitResolver, "resolve", fake_resolve)
    claim = {"resolution": {"id": ids[2]}, "task": {"id": ids[1], "project_id": ids[0],
        "inputs": {"sut_selector": {"kind": "BRANCH", "value": "main"},
                   "framework_selector": {"kind": "BRANCH", "value": "main"}}},
        "configuration": {"sut": {"url": "https://example.invalid/sut"},
                          "framework": {"url": "ssh://git@example.invalid/framework"}},
        "lease_token": "lease", "work_token": "work", "generation": 1}
    await resolve(API(), SimpleNamespace(worker_id="worker-test", lease_seconds=90), tmp_path, claim)
    assert [operation for operation, _ in operations] == ["resolution/assert", "git", "resolution/assert", "git", "resolution/accept"]
    assert all(body["token"] is None for operation, body in operations if operation == "git")
    assert (tmp_path / ("resolution-" + ids[2]) / "result.json").exists()


def test_native_prompt_describes_host_network_and_terminal_exit(tmp_path):
    import json

    from hypertest.cloud.native_worker import native_prompt

    task_id, attempt_id = str(uuid4()), str(uuid4())
    prompt = json.loads(native_prompt({"id": task_id, "frozen_manifest": {}}, {"id": attempt_id}, tmp_path))
    assert prompt["capabilities"]["remote_network"] == "HOST_USER_NETWORK_UNVERIFIED"
    assert prompt["capabilities"]["ssh"] == "HOST_USER_ACCESS_UNVERIFIED"
    assert prompt["capabilities"]["https_controlled_api"] == "HOST_USER_ACCESS_UNVERIFIED"
    assert any("end your turn immediately without waiting" in line for line in prompt["instructions"])
    assert all("SSH diagnostics are unavailable" not in line for line in prompt["instructions"])
    assert any(str(tmp_path / "framework") in line for line in prompt["instructions"])


@pytest.mark.parametrize("authorization", [
    {"targets": ["https://example.invalid/sut"], "permitted_actions": ["git:read", "framework:execute"],
     "network_targets": [], "side_effect_limits": "Runtime tools, network access and credentials are managed by the execution environment; preserve unknown external operations.",
     "expires_at": "2036-11-01T00:00:00Z"},
    {"targets": ["https://example.invalid/sut", "https://explicit.invalid"],
     "permitted_actions": ["git:read", "framework:execute", "environment:read"],
     "network_targets": ["https://explicit.invalid"], "side_effect_limits": "Read only and do not modify data.",
     "expires_at": "2036-11-01T00:00:00Z"},
])
def test_native_prompt_preserves_frozen_authorization_and_explains_preflight(tmp_path, authorization):
    import copy
    import json

    from hypertest.cloud.native_worker import native_prompt
    from hypertest.sync_core import digest

    manifest = {"inputs": {"authorization": authorization}, "configuration": {}}
    original = copy.deepcopy(manifest)
    before = digest(manifest)
    prompt = json.loads(native_prompt({"id": str(uuid4()), "frozen_manifest": manifest},
                                      {"id": str(uuid4())}, tmp_path))
    assert manifest == original and digest(manifest) == before
    assert prompt["frozen_manifest"] == original
    assert any("not an inventory of the host environment's capabilities" in line for line in prompt["instructions"])
    assert any("honor any explicit task authorization" in line for line in prompt["instructions"])
    assert any("Do not infer extra authorization" in line for line in prompt["instructions"])
