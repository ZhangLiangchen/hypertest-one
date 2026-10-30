"""One synthetic framework process through action, observation and reporting.

This is a dedicated-test-database regression, not an SDK, Docker or real-SUT
acceptance. The only provider transport is an in-memory synthetic handler.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from test_cloud_action_observer import _policy, _response
from test_cloud_tasks import (
    FRAMEWORK_SHA,
    claimed,
    configuration,
    inputs,
    post,
    read_all,
    worker_submit,
)

from hypertest.application import cloud_actions
from hypertest.application.cloud_actions import WorkerActionAuthority
from hypertest.cloud.action_broker import ActionBroker
from hypertest.cloud.action_observer import ActionObserver
from hypertest.cloud.action_signer import ActionCredentials, ActionSigner
from hypertest.cloud.broker import CloudBroker
from hypertest.cloud.http_transport import HttpExchange
from hypertest.cloud.reporter import CloudTaskReporter
from hypertest.cloud.worker import CloudWorker
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_actions import (
    CloudActionIdentity,
    CloudActionObservation,
    CloudActionSend,
)

pytest_plugins = ("test_cloud_tasks",)


@pytest.mark.asyncio
async def test_framework_process_action_observation_and_report_close_once(cloud_context, monkeypatch, tmp_path):
    """A real framework subprocess uses the broker; no real model/SUT/network."""
    monkeypatch.setattr(cloud_actions, "controlled_actions_enabled", lambda: True)
    target = "https://api.example.invalid:443"
    credential_versions = {}
    oauth = json.dumps({"username": "fixture-user", "password": "fixture-password", "client_id": "fixture-client",
                        "client_secret": "fixture-secret", "grant_type": "password"})
    for role, secret in (("api_key", "fixture-api-key"), ("signing_key", "fixture-signing-key"), ("observer_oauth", oauth)):
        response = await post(cloud_context, "STORE_CREDENTIAL", kind="APPLICATION_PRIVATE_KEY", label=role,
            purpose="controlled-action-" + role.replace("_", "-"), allowed_targets=[target],
            allowed_actions=["environment:read" if role == "observer_oauth" else "environment:write"], secret=secret)
        assert response.status_code == 200
        credential_versions[role] = response.json()["credential_version_id"]

    profile = _policy()
    action = profile["actions"][0]
    action["credential_version_ids"] = credential_versions
    action["framework_commit"] = FRAMEWORK_SHA
    observer_settings = action["observer"]
    observer_settings["preflight_observed_profile"] = "preflight-observation/v1"
    fixture_inputs = inputs(framework_entrypoints=["python -m unittest -v test_fixture"])
    fixture_inputs["authorization"].update(targets=fixture_inputs["authorization"]["targets"] + [target, "api.example.invalid"],
        network_targets=[target], permitted_actions=["git:read", "framework:execute", "environment:read", "environment:write"])
    fixture_inputs["controlled_actions"] = profile
    fixture_inputs["agent_source_export"] = {"profile": "cloud-agent-source-export/v1",
        "sut": [{"path": "main.py", "sha256": "a" * 64}],
        "framework": [{"path": "python/adapter.py", "sha256": "b" * 64},
                      {"path": "python/observer.py", "sha256": "c" * 64}]}
    environment = {"name": "Synthetic HTTPS", "connection": "HTTPS", "host": "api.example.invalid",
                   "port": 443, "cloud_access_policy": "WEB_ONLY"}
    receipt, claim, identity = await claimed(cloud_context, framework_sha=FRAMEWORK_SHA,
        config=configuration(environment=environment), task_inputs=fixture_inputs)
    receipt = await worker_submit(cloud_context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 300,
            "request_limits": [{"scope": "ROOT", "max_requests": 2, "cost_per_request_microunits": 1}]})
    claim["task"]["version"] = receipt["version"]
    broker = CloudBroker(AsyncSessionLocal, claim, identity.worker_id)
    authority = WorkerActionAuthority(AsyncSessionLocal, task_id=broker.task_id, attempt_id=broker.attempt_id,
                                      identity=identity)
    signer = object.__new__(ActionSigner)
    provider = {"posts": 0, "client_ref": None}

    async def prepare(_action, client_ref, unique_ref, *, identity_id):
        return json.dumps({**action["expected_body"], "clientOrderId": client_ref, "uniqueUserKey": unique_ref,
                           "sign": base64.b64encode(b"s" * 256).decode()}).encode()

    async def verify(_action, _body, *, identity_id):
        return True

    async def preflight_adapter(_action, _address, _balance):
        return {"profile": "preflight-observation/v1", "allowed": True, "available_atomic": "3000000",
                "address_membership": "OBSERVED", "aggregate_dex_withdraw_role": "OBSERVED",
                "coin_specific_role": "UNOBSERVED", "address_active": "UNOBSERVED", "lock_state": "UNOBSERVED",
                "concurrent_changes": "POSSIBLE"}

    async def observe_adapter(_action, client_ref, _first, _second):
        return {"profile": "observation/v1", "client_order_id": client_ref, "order_id": "42",
                "business_status": "Completed", "business_terminal": True,
                "details": [{"detail_id": "5", "transaction_type": "Uniswap", "status": "Success",
                    "tx_hash": "ab" * 32, "block_number": "20", "confirmations": 2, "required_confirmations": 1}],
                "chain_receipt": "UNOBSERVED", "actual_trx_received": "UNOBSERVED"}

    monkeypatch.setattr(signer, "prepare", prepare)
    monkeypatch.setattr(signer, "verify", verify)
    monkeypatch.setattr(signer, "preflight", preflight_adapter)
    monkeypatch.setattr(signer, "observe", observe_adapter)

    def reply(request):
        if request.url.path == "/oauth/token":
            return _response({"code": 200, "data": {"access_token": "fixture-bearer"}})
        if request.url.path == "/addresses/page":
            return _response({"code": 200, "data": {"records": [{"walletId": 42,
                "chain": "TRON_TEST", "address": "synthetic-address", "allOutRuleTypes": ["DEXWithdraw"]}]}})
        if request.url.path == "/addresses/balance/TRON_TEST/synthetic-address":
            return _response({"code": 200, "data": [{"chain": "TRON_TEST", "address": "synthetic-address",
                "code": "TRON_TESTUSDT", "available": 3000000}]})
        order = {"id": "42", "clientOrderId": provider["client_ref"], "status": "Completed", "walletId": 42,
                 "fromChain": "TRON_TEST", "toChain": "TRON_TEST", "fromCoinCode": "TRON_TESTUSDT",
                 "toCoinCode": "TRON_TESTTRX", "amount": 2000000, "fromAddress": "synthetic-address",
                 "transactionType": "Uniswap"}
        if request.url.path == "/orders/client/" + str(provider["client_ref"]):
            return _response({"code": 200, "data": order})
        if request.url.path == "/orders/42/with-details":
            return _response({"code": 200, "data": {**order, "details": [{"id": "5", "orderId": "42",
                "transactionType": "Uniswap", "status": "Success", "txHash": "ab" * 32, "blockNumber": "20",
                "confirmations": 2, "requiredConfirmations": 1}]}})
        pytest.fail("unexpected synthetic provider request")

    async def resolve(_host, _port):
        return ["8.8.8.8"]

    class SendOnce:
        async def send(self, *, body, before_send, sent_body_sha256, **_kwargs):
            await before_send(sent_body_sha256)
            provider["posts"] += 1
            provider["client_ref"] = json.loads(body)["clientOrderId"]
            return HttpExchange(200, b'{"code":200}')

    observer = ActionObserver(profile=profile, resolver=resolve, transport=httpx.MockTransport(reply))
    workspace = tmp_path / "workspace"
    framework = workspace / "framework"
    ready = workspace / ".hypertest-cloud" / "ready"
    framework.mkdir(parents=True)
    ready.mkdir(parents=True)
    script = '''import json, os, socket, unittest
def call(verb):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
        c.settimeout(10); c.connect(os.environ["FIXTURE_SOCKET"])
        c.sendall(json.dumps({"verb": verb, "action_key": "swap-2"}).encode()+b"\\n")
        with c.makefile("rb") as stream: return json.loads(stream.readline())
class Fixture(unittest.TestCase):
    def test_original_action(self):
        result = call("INVOKE")
        self.assertEqual(result["status"], "HTTP_OBSERVED", result)
        self.assertEqual(call("QUERY")["operation"]["state"], "SENT")
'''
    (framework / "test_fixture.py").write_text(script, encoding="utf-8")
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=workspace)
    worker = CloudWorker(None, None, identity.worker_id)
    accepted = {}

    async def publish(key, operation, payload):
        document = {"profile": "hypertest-cloud-handoff/v1alpha1", "task_id": broker.task_id,
                    "attempt_id": broker.attempt_id, "key": key, "operation": operation, "payload": payload}
        (ready / (key + ".json")).write_text(json.dumps(document), encoding="utf-8")
        terminal = await worker.collect(reporter, workspace, accepted, stopped=False)
        return terminal if terminal else json.loads((workspace / ".hypertest-cloud" / "receipts" / (key + ".json")).read_text())

    try:
        with tempfile.TemporaryDirectory(prefix="ht-e2e-", dir=str(Path("/tmp").resolve())) as socket_dir:
            socket_path = Path(socket_dir) / "action.sock"
            private = tmp_path / "action-private"
            private.mkdir(mode=0o700)
            async def check_preflight(item):
                return await observer.preflight(action=item, authority=authority, signer=signer)
            action_broker = ActionBroker(socket_path, task_id=broker.task_id, profile=profile, authority=authority,
                signer=signer, credentials=ActionCredentials(authority), private_root=private, deadline=int(time.time()) + 120,
                validate_output=broker.validate_payload, preflight=check_preflight, observer=observer, transport=SendOnce())
            await action_broker.start()
            started = datetime.now(UTC)
            process = await asyncio.create_subprocess_exec(sys.executable, "-m", "unittest", "-v", "test_fixture",
                cwd=framework, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "FIXTURE_SOCKET": str(socket_path)})
            output, _ = await asyncio.wait_for(process.communicate(), 30)
            finished = datetime.now(UTC)
            assert process.returncode == 0, output.decode(errors="replace")
            assert provider["posts"] == 1
            assert await action_broker.observe_before_close(deadline=time.monotonic() + 30)
            await action_broker.close()
            assert await action_broker.drained()
        (workspace / "framework-report.txt").write_bytes(output)
        upload = await publish("01-report-original", "UPLOAD_ARTIFACT", {"path": "framework-report.txt",
            "filename": "framework-report.txt", "media_type": "text/plain", "sha256": hashlib.sha256(output).hexdigest(),
            "byte_count": len(output)})
        tree_digest = hashlib.sha256(script.encode()).hexdigest()
        assets = await publish("02-stage-assets", "SUBMIT_ASSETS", {"assets": [
            {"kind": "ANALYSIS", "key": "analysis", "title": "Synthetic analysis", "markdown": "Fixture only"},
            {"kind": "DESIGN", "key": "design", "title": "Synthetic design", "markdown": "Invoke one action"},
            {"kind": "CASE", "key": "case", "title": "Synthetic case", "reported_result": "PASS",
             "details": {"steps": ["Run synthetic unittest"], "expected": "terminal", "actual": "terminal"}},
            {"kind": "IMPLEMENTATION", "key": "implementation", "title": "Synthetic framework", "markdown": "Fixture",
             "details": {"framework_sha": FRAMEWORK_SHA, "cwd": "framework", "dirty_files": [], "untracked_files": [],
                         "test_tree_digest": tree_digest}},
            {"kind": "REPORT", "key": "final", "title": "Synthetic report", "markdown": "Synthetic output",
             "artifact_id": upload["artifact_id"], "reported_result": "PASS"}]})
        case_id = next(item["id"] for item in assets["assets"] if item["kind"] == "CASE")
        final_id = next(item["id"] for item in assets["assets"] if item["kind"] == "REPORT")
        asset_ids = [item["id"] for item in assets["assets"]]
        await publish("03-framework-run", "SUBMIT_RUN", {"run_key": "fixture-run", "execution": {
            "source": "PROJECT_FRAMEWORK", "actual_sut_build": "UNKNOWN", "framework_sha": FRAMEWORK_SHA,
            "test_tree_digest": tree_digest, "environment_observation": {"source": "synthetic-local-fixture"},
            "entrypoint": "python -m unittest -v test_fixture", "cwd": "framework", "framework_version": "python-stdlib-unittest",
            "started_at": started.isoformat(), "finished_at": finished.isoformat(), "exit_code": process.returncode},
            "reported_result": "PASS", "report_artifact_ids": [upload["artifact_id"]],
            "cases": [{"case_revision_id": case_id, "actual": "terminal", "reported_result": "PASS"}]})
        handoff, handoff_digest = await publish("04-finish", "COMPLETE_ATTEMPT", {
            "final_report_revision": final_id, "reported_result": "PASS", "completion_manifest": {
                "required_asset_ids": asset_ids, "scope_and_gaps": "Synthetic transport only; no SDK, model or real SUT"}})
        result = await reporter.submit_handoff(handoff, handoff_digest, runtime_stopped=True,
                                               external_operations_reconciled=True)
        assert result.synced
        document = await read_all(cloud_context, broker.task_id, result.receipt["version"])
        assert document["task"]["status"] == "COMPLETED" and document["task"]["reported_result"] == "PASS"
        assert document["runs"][0]["execution"]["exit_code"] == 0
        assert await broker.artifact(upload["artifact_id"]) == output
        async with AsyncSessionLocal() as db:
            attempt_id = UUID(broker.attempt_id)
            assert await db.scalar(select(func.count()).select_from(CloudActionIdentity).where(CloudActionIdentity.attempt_id == attempt_id)) == 1
            assert await db.scalar(select(func.count()).select_from(CloudActionSend).where(CloudActionSend.attempt_id == attempt_id)) == 1
            rows = list(await db.scalars(select(CloudActionObservation.state).where(CloudActionObservation.attempt_id == attempt_id)))
            assert sorted(rows) == ["BUSINESS_TERMINAL", "HTTP_OBSERVED"]
    finally:
        reporter.close()
