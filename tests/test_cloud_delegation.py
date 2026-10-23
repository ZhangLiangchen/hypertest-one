"""Native integration contracts, using inert payloads and synthetic cloud OAuth."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import io
import json
import socket
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud.delegate_broker import (
    CODEX_RESPONSES_URL,
    CodexOAuthBroker,
    CodexOAuthIdentity,
    read_cloud_codex_identity,
)
from hypertest.cloud.delegation import (
    BUNDLE_VERSION,
    CODEX_VERSION,
    HARNESS_SOURCE,
    NATIVE_READY,
    NPM_PINS,
    OBSERVATION_PROFILE,
    PAYLOAD_PROFILE,
    DelegationChannel,
    DelegationObservations,
    native_profile,
    request_limits,
    validate_lock,
    verify_payload,
    write_native_configuration,
)
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.manifests import Handoff, task_prompt
from hypertest.cloud.model_broker import ModelBroker, start_sandbox_relay
from hypertest.cloud.reporter import CloudTaskReporter
from hypertest.cloud.worker import CloudWorker
from hypertest.config import Settings
from hypertest.sync_core import digest


def identity_file(tmp_path, *, expires=10000, mode=0o400):
    claims = base64.urlsafe_b64encode(json.dumps({"exp": expires}).encode()).decode().rstrip("=")
    path = tmp_path / "cloud-auth.json"
    path.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {
        "access_token": "header." + claims + ".synthetic-signature", "account_id": "cloud-account",
        "refresh_token": "unused-refresh-canary", "id_token": "unused-id-canary"}}))
    path.chmod(mode)
    return path


def test_cloud_oauth_is_read_only_private_and_does_not_expose_identity(tmp_path):
    path = identity_file(tmp_path)
    original = path.read_bytes()
    identity = read_cloud_codex_identity(path, now=100, required_seconds=200)
    assert identity.expires_at == 10000
    assert "cloud-account" not in repr(identity)
    assert identity.access_token not in repr(identity)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
    with pytest.raises(CloudBlocked) as error:
        read_cloud_codex_identity(path, now=9900, required_seconds=200)
    assert error.value.code == "CODEX_OAUTH_EXPIRED"


def test_oauth_never_follows_links_or_uses_ambient_or_refresh_login(tmp_path):
    path = identity_file(tmp_path, mode=0o644)
    with pytest.raises(CloudBlocked) as error:
        read_cloud_codex_identity(path, now=100)
    assert error.value.code == "CODEX_OAUTH_UNAVAILABLE"
    path.chmod(0o600)
    link = tmp_path / "linked-auth.json"
    link.symlink_to(path)
    with pytest.raises(CloudBlocked):
        read_cloud_codex_identity(link, now=100)
    path.write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "synthetic-unused-key"}))
    with pytest.raises(CloudBlocked):
        read_cloud_codex_identity(path, now=100)


def oauth_broker(tmp_path):
    return CodexOAuthBroker(tmp_path / "codex.sock",
        identity=CodexOAuthIdentity("synthetic-access", "cloud-account", int(time.time()) + 3600),
        model="gpt-5.4", max_requests=2)


def responses(**changes):
    return {"model": "gpt-5.4", "input": [{"role": "user", "content": [{"type": "input_text", "text": "fixture"}]}],
        "stream": True, "store": False, "tools": [{"type": "function", "name": "read_file"}], **changes}


def root_messages(**changes):
    """Fixed official llm-deepseek serialize.ts/WireRequest, not OpenAI chat."""
    return {"model": "fixture", "stream": True, "max_tokens": 1024,
        "thinking": {"type": "enabled"}, "output_config": {"effort": "high"},
        "system": "Synthetic task instructions",
        "tools": [{"name": "read_file", "description": "Read approved workspace source",
                   "input_schema": {"type": "object", "properties": {}}}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Synthetic requirement"}]},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "Synthetic protocol replay", "signature": "fixture-signature"},
                {"type": "tool_use", "id": "tool-1", "name": "read_file", "input": {"path": "framework/fixture.txt"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": [{"type": "text", "text": "Synthetic workspace output"}]}]},
            {"role": "system", "content": [{"type": "tool_addition", "tool": {"type": "tool_reference", "name": "read_file"}}]},
        ], **changes}


def test_root_official_messages_shape_and_required_headers(tmp_path):
    broker = ModelBroker(tmp_path / "model.sock", base_url="https://api.deepseek.com/anthropic",
        api_key=b"synthetic-host-only-key", model="fixture")
    request = broker.prepare_request("/v1/messages", root_messages())
    assert request.full_url == "https://api.deepseek.com/anthropic/v1/messages"
    assert request.get_header("X-api-key") == "synthetic-host-only-key"
    assert request.get_header("Anthropic-version") == "2023-06-01"
    assert request.get_header("Anthropic-beta") == "mid-conversation-tool-changes-2026-07-01"
    assert request.get_header("Authorization") is None
    assert json.loads(request.data) == root_messages()


@pytest.mark.parametrize("payload", [
    root_messages(web_search_options={"search_context_size": "high"}),
    root_messages(files=["https://private.invalid/file"]),
    root_messages(tools=[{"type": "web_search", "name": "search"}]),
    root_messages(messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "url", "url": "https://private.invalid"}}]}]),
    root_messages(messages=[{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": [{"type": "file", "url": "https://private.invalid"}]}]}]),
    root_messages(messages=[{"role": "user", "content": [{"type": "input_audio", "data": "fixture"}]}]),
])
def test_root_official_messages_refuses_provider_side_remote_actions(tmp_path, payload):
    broker = ModelBroker(tmp_path / "model.sock", base_url="https://api.deepseek.com/anthropic",
        api_key=b"synthetic-host-only-key", model="fixture")
    with pytest.raises(ValueError):
        broker.prepare_request("/v1/messages", payload)
    with pytest.raises(ValueError):
        broker.prepare_request("/chat/completions", root_messages())
    assert broker.requests == 0


def test_native_oauth_broker_is_fixed_responses_inference_not_a_host_cli(tmp_path):
    broker = oauth_broker(tmp_path)
    request = broker.prepare_request("/v1/responses", responses())
    assert request.full_url == CODEX_RESPONSES_URL
    assert request.headers["Authorization"] == "Bearer synthetic-access"
    assert request.get_header("Chatgpt-account-id") == "cloud-account"
    assert json.loads(request.data)["model"] == "gpt-5.4"
    assert "synthetic-access" not in json.dumps(broker.observation())
    assert "cloud-account" not in json.dumps(broker.observation())
    broker.__exit__()
    assert broker._identity.access_token == ""


@pytest.mark.parametrize("path,payload", [
    ("https://example.invalid/responses", responses()),
    ("/responses?target=other", responses()),
    ("/v1/models", responses()),
    ("/responses", responses(model="different-model")),
    ("/responses", responses(store=True)),
    ("/responses", responses(stream=False)),
    ("/responses", responses(background=True)),
    ("/responses", responses(previous_response_id="another-attempt-response")),
    ("/responses", responses(tools=[{"type": "web_search"}])),
    ("/responses", responses(tools=[{"type": "namespace", "name": "hidden", "tools": [{"type": "mcp"}]}])),
    ("/responses", responses(tools=[{"type": "tool_search", "execution": "server"}])),
    ("/responses", responses(input=[{"type": "input_image", "image_url": "https://private.invalid"}])),
])
def test_native_broker_rejects_other_actions_before_any_upstream_request(tmp_path, path, payload):
    broker = oauth_broker(tmp_path)
    with pytest.raises(ValueError):
        broker.prepare_request(path, payload)
    assert broker.requests == 0


def test_one_budget_is_shared_across_root_and_native_model_scopes():
    settings = SimpleNamespace(cloud_model_max_requests=100, cloud_model_request_cost_microunits=2,
        cloud_codex_max_requests=20, cloud_codex_request_credits=3)
    limits = request_limits(settings, remaining=31, allow_codex=True)
    assert {item["scope"] for item in limits} == {"ROOT", "CODEX"}
    assert sum(item["max_requests"] * item["cost_per_request_microunits"] for item in limits) <= 31
    assert all(type(item["max_requests"]) is int and item["max_requests"] > 0 for item in limits)
    assert request_limits(settings, remaining=31, allow_codex=False) == [
        {"scope": "ROOT", "max_requests": 15, "cost_per_request_microunits": 2}]
    with pytest.raises(CloudBlocked):
        request_limits(settings, remaining=3, allow_codex=True)


def event(state="RUNNING", *, run_id=None, native_ref=None, reason=None):
    return {"profile": OBSERVATION_PROFILE, "run_id": run_id or str(uuid4()),
        "native_ref": native_ref or str(uuid4()), "provider": "codex", "state": state, "stop_reason": reason}


def test_native_lifecycle_requires_paired_external_terminal_and_no_raw_output():
    observations = DelegationObservations()
    start = event()
    with pytest.raises(CloudBlocked):
        observations.accept({**start, "state": "TERMINAL", "stop_reason": "completed"})
    observations.accept(start)
    assert not observations.all_terminal
    with pytest.raises(CloudBlocked):
        observations.terminal(start["native_ref"])
    with pytest.raises(CloudBlocked):
        observations.accept({**start, "lastAssistantMessage": "unapproved-output-canary"})
    terminal = {**start, "state": "TERMINAL", "stop_reason": "error"}
    observations.accept(terminal)
    assert observations.all_terminal and observations.terminal(start["native_ref"]) == terminal
    with pytest.raises(CloudBlocked):
        observations.accept(terminal)


def test_native_configuration_uses_official_bundle_and_clean_cloud_only_home(tmp_path):
    model = Settings.model_fields["cloud_codex_model"].default
    assert model == "gpt-5.6-sol"
    assert Settings.model_fields["cloud_enabled"].default is False
    assert Settings.model_fields["cloud_codex_enabled"].default is False
    assert Settings.model_fields["codex_model"].default is None
    patch = write_native_configuration(tmp_path, model=model, codex_base_url="http://127.0.0.1:12345")
    document = json.loads(patch.read_text())
    rows = document[1]["insert"]
    assert document[0] == {"id": "subprocess", "disabled": True}
    assert rows[0]["name"].endswith("/native_subprocess.mjs")
    assert rows[1]["name"].endswith("node_modules/@deepseek-ai/dsh-subagent-codex/lib/index.js")
    assert rows[1]["config"]["model"] == model
    assert rows[1]["config"]["permissionMode"] == "never"
    assert rows[2]["config"] == {"provider": "codex", "toolName": "subagent_codex", "maxDepth": "provider-managed"}
    config = (tmp_path / "codex/config.toml").read_text()
    assert f'model = "{model}"' in config
    assert 'requires_openai_auth = false' in config and 'supports_websockets = false' in config
    assert 'web_search = "disabled"' in config
    assert not (tmp_path / "codex/auth.json").exists()
    assert "claude" not in json.dumps(document).lower()
    with pytest.raises(CloudBlocked):
        native_profile(model="gpt-5.4", codex_base_url="https://model.invalid")


def locked_packages():
    return {"lockfileVersion": 3, "packages": {"": {"name": "fixture"}, **{
        "node_modules/" + name: {"version": pin["version"], "integrity": pin["integrity"],
            "resolved": "https://registry.npmjs.org/" + name + "/-/fixed.tgz"}
        for name, pin in NPM_PINS.items()}}}


def inert_payload(tmp_path):
    root = tmp_path / "payload"
    root.mkdir()
    files = {
        "bin/node": b"inert-never-executed-node-fixture",
        "package-lock.json": json.dumps(locked_packages()).encode(),
        "node_modules/@deepseek-ai/dsh-subagent-codex/package.json": json.dumps({"name": "@deepseek-ai/dsh-subagent-codex", "version": BUNDLE_VERSION}).encode(),
        "node_modules/@deepseek-ai/dsh-subagent-codex/lib/index.js": b"inert-never-executed-plugin",
        "node_modules/@openai/codex/package.json": json.dumps({"name": "@openai/codex", "version": CODEX_VERSION}).encode(),
        "node_modules/@openai/codex/bin/codex.js": b"inert-never-executed-wrapper",
    }
    for relative, raw in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o755 if relative == "bin/node" else 0o644)
    document = {"profile": PAYLOAD_PROFILE, "source_commit": HARNESS_SOURCE,
        "bundle_version": BUNDLE_VERSION, "codex_version": CODEX_VERSION,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}}
    raw = json.dumps(document).encode()
    (root / "manifest.json").write_bytes(raw)
    return root, hashlib.sha256(raw).hexdigest()


def test_payload_requires_operator_trust_anchor_and_complete_frozen_files(tmp_path):
    root, sha = inert_payload(tmp_path)
    observed = verify_payload(root, sha)
    assert observed["integrity_verified"] is True
    assert observed["native_delegation_observed"] is False
    with pytest.raises(CloudBlocked):
        verify_payload(root, "")
    (root / "node_modules/@openai/codex/bin/codex.js").write_bytes(b"changed-canary")
    with pytest.raises(CloudBlocked):
        verify_payload(root, sha)


def test_registry_lock_cannot_float_or_substitute_custom_bundle_sources():
    lock = locked_packages()
    validate_lock(lock)
    lock["packages"]["node_modules/@openai/codex"]["resolved"] = "https://evil.invalid/codex.tgz"
    with pytest.raises(CloudBlocked):
        validate_lock(lock)


def test_prompt_advertises_exact_opt_in_profile_and_complete_typed_contract():
    task = {"id": str(uuid4()), "frozen_manifest": {"fixture": "no-secrets"}}
    attempt = {"id": str(uuid4())}
    disabled = json.loads(task_prompt(task, attempt))
    enabled = json.loads(task_prompt(task, attempt, allow_delegation=True))
    assert disabled["capabilities"]["codex"] is False
    assert enabled["capabilities"]["codex"] is True
    assert enabled["capabilities"]["claude_code"] == "PLACEHOLDER"
    variants = enabled["handoff_contract"]["schema"]["oneOf"]
    native = next(item for item in variants if item["properties"]["operation"]["const"] == "SUBMIT_DELEGATION")
    assert native["properties"]["payload"]["properties"]["provider"]["enum"] == ["codex"]
    assert "status" not in native["properties"]["payload"]["properties"]
    guidance = "\n".join(enabled["instructions"])
    assert "description, a complete self-contained prompt, and explicit cwd=/workspace/framework" in guidance
    assert "absolute /workspace/sut paths for read-only source" in guidance
    assert "child must not publish ready handoffs or call platform APIs" in guidance
    assert "Read and check the child's original contribution" in guidance
    assert "at most two assets including a REPORT; wait for its accepted receipt before the next batch" in guidance
    assert "Keep the frozen PRD objectives and required outputs" in guidance
    assert "explicit cwd=/workspace/framework" not in "\n".join(disabled["instructions"])
    assert enabled["frozen_manifest"] == disabled["frozen_manifest"] == task["frozen_manifest"]


async def test_worker_bounded_projection_never_uses_subagent_finished_as_external_terminal():
    start = event()
    frames = [json.dumps({"activity": "subagent.finished"}).encode() + b"\n",
              json.dumps({"delegation": start}).encode() + b"\n", b""]
    class Stream:
        async def readline(self):
            return frames.pop(0)
    observed = DelegationObservations()
    await CloudWorker.consume_runtime(SimpleNamespace(stdout=Stream()), delegations=observed)
    assert not observed.all_terminal
    assert observed.runs == {start["run_id"]: start}


async def test_reporter_host_projects_native_terminal_and_preserves_failed_child(tmp_path):
    broker = SimpleNamespace(attempt_id=str(uuid4()), task_id=str(uuid4()), project_id=str(uuid4()), version=1,
        identity=SimpleNamespace(generation=1))
    async def validate(_):
        pass
    broker.validate_payload = validate
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=tmp_path / "workspace")
    captured = []
    async def deliver(intent):
        captured.append(intent)
        return SimpleNamespace(synced=True, receipt={"version": 2})
    reporter.core.deliver = deliver
    native = event("TERMINAL", reason="error")
    handoff = Handoff(profile="hypertest-cloud-handoff/v1alpha1", task_id=broker.task_id,
        attempt_id=broker.attempt_id, key="native-final", operation="SUBMIT_DELEGATION", payload={
            "delegation_key": "codex-analysis", "provider": "codex", "responsibility": "Analyze fixture risk",
            "native_ref": native["native_ref"], "asset_ids": []})
    try:
        await reporter.submit_handoff(handoff, digest(handoff.model_dump()), delegation_observation=native)
        assert captured[0].payload["status"] == "FAILED"
        assert captured[0].payload["terminal_observation"]["independent_execution_proof"] is False
        assert captured[0].payload["terminal_observation"]["source"] == "official-plugin-runtime-reported"
        claimed = handoff.model_copy(update={"key": "forged-terminal", "payload": {
            **handoff.payload, "status": "COMPLETED", "terminal_observation": {"claimed": True}}})
        with pytest.raises(CloudBlocked) as error:
            await reporter.submit_handoff(claimed, digest(claimed.model_dump()), delegation_observation=native)
        assert error.value.code == "DELEGATION_OBSERVATION_AUTHORITY"
    finally:
        reporter.close()


def test_model_broker_observes_admission_success_eof_and_actual_drain(tmp_path, monkeypatch):
    calls = []
    class Response:
        status = 200
        headers = {"Content-Type": "text/event-stream"}
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self, _):
            return b""
    class Opener:
        def open(self, request, **kwargs):
            calls.append(request)
            return Response()
    monkeypatch.setattr("hypertest.cloud.model_broker.urllib.request.build_opener", lambda *args: Opener())
    broker = ModelBroker(tmp_path / "model.sock", base_url="https://model.invalid",
        api_key=b"synthetic-host-only-key", model="fixture", max_requests=1)
    with broker:
        server, base = start_sandbox_relay(str(broker.path))
        try:
            port = int(base.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection("127.0.0.1", port)
            connection.request("POST", "/v1/messages", json.dumps(root_messages()), {"Content-Type": "application/json"})
            response = connection.getresponse()
            assert response.status == 200
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
    observed = broker.observation()
    assert observed == {"closed": True, "requests": 1, "inflight": 0, "drained": True,
                        "upstream_successes": 1, "upstream_completed": 1,
                        "upstream_status_counts": {"200": 1}, "transport_failure_counts": {},
                        "refused_scope_count": 0, "refused_category_counts": {}}
    assert len(calls) == 1 and calls[0].full_url == "https://model.invalid/anthropic/v1/messages"
    assert "synthetic-host-only-key" not in json.dumps(observed)
    broker.inflight = 1
    assert broker.observation()["drained"] is False


def test_native_protocol_mode_prepares_exact_profile_without_auth_relay_or_prompt(tmp_path, monkeypatch, capsys):
    from hypertest.cloud import sdk_driver
    configuration = {"mode": "NATIVE_PROTOCOL_PROBE", "dsh_home": str(tmp_path / "dsh"),
        "native_delegation": {"codex_model": "gpt-5.4"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(configuration)))
    monkeypatch.setattr(sdk_driver, "start_sandbox_relay", lambda *_: pytest.fail("model relay started"))
    monkeypatch.setattr(sdk_driver, "run_official_sdk", lambda *a, **k: pytest.fail("prompt path entered"))
    calls = []
    def protocol(config, **kwargs):
        calls.append(config)
        kwargs["before_close"]()
        return {"model_prompt_sent": False, "oauth_read": False, "native_delegation_observed": False}
    class Channel:
        def __init__(self, path):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def ensure_ready(self):
            return NATIVE_READY
        def ensure_closed(self):
            pass
    monkeypatch.setattr(sdk_driver, "DelegationChannel", Channel)
    monkeypatch.setattr(sdk_driver, "probe_official_sdk", protocol)
    assert sdk_driver.main() == 0
    assert len(calls[0]["patches"]) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["model_prompt_sent"] is False
    assert not (tmp_path / "codex/auth.json").exists()


def test_private_metadata_channel_requires_ordered_complete_frames(tmp_path):
    channel = DelegationChannel(tmp_path / "unused-no-socket-started")
    channel.receive({"sequence": 1, "kind": "READY", "data": NATIVE_READY})
    assert channel.ensure_ready() == NATIVE_READY
    native = event()
    channel.receive({"sequence": 2, "kind": "DELEGATION", "data": native})
    with pytest.raises(ValueError):
        channel.receive({"sequence": 3, "kind": "CLOSED", "data": None})
    channel.receive({"sequence": 3, "kind": "DELEGATION", "data": {**native, "state": "TERMINAL", "stop_reason": "completed"}})
    with pytest.raises(ValueError):
        channel.receive({"sequence": 5, "kind": "CLOSED", "data": None})
    channel.receive({"sequence": 4, "kind": "CLOSED", "data": None})
    channel.ensure_closed()
    with pytest.raises(ValueError):
        channel.receive({"sequence": 5, "kind": "DELEGATION", "data": native})


@pytest.mark.parametrize("field,code", [
    ("provider_registered", "NATIVE_PROVIDER_UNAVAILABLE"),
    ("tool_registered", "NATIVE_TOOL_UNAVAILABLE"),
    ("subprocess_shim", "NATIVE_SUBPROCESS_UNAVAILABLE"),
    ("node_available", "NATIVE_NODE_UNAVAILABLE"),
])
def test_native_readiness_reports_only_fixed_missing_capability_code(tmp_path, field, code):
    from hypertest.cloud.sdk import sdk_error_observation

    channel = DelegationChannel(tmp_path / "unused-no-socket")
    with pytest.raises(CloudBlocked) as caught:
        channel.receive({"sequence": 1, "kind": "READY", "data": {**NATIVE_READY, field: False}})
    assert caught.value.code == code
    assert not channel.ready.is_set() and channel.sequence == 0
    observed = sdk_error_observation(caught.value, "DELEGATE_READY")
    assert observed["native_capabilities"] == {name: name != field for name in (
        "provider_registered", "tool_registered", "subprocess_shim", "node_available")}


def test_native_metadata_handler_preserves_first_error_after_later_bad_frame(tmp_path):
    from hypertest.cloud.sdk import sdk_error_observation

    path = tmp_path / "metadata.sock"
    with DelegationChannel(path) as channel:
        for raw in (b'{"private-canary-invalid-json"\n',
                b'{"sequence":4,"kind":"CLOSED","data":null}\n'):
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2)
                connection.connect(str(path))
                connection.sendall(raw)
                assert connection.recv(16) == b""
        observed = sdk_error_observation(channel.error, "DELEGATE_READY")
        assert observed == {"phase": "DELEGATE_READY", "type": "CAPABILITY", "rpc_numeric_code": None,
            "boundary_code": "DELEGATION_METADATA_INVALID", "channel_failure": "JSON"}
        assert "private-canary" not in json.dumps(observed)


@pytest.mark.parametrize("raw,category", [
    (b"", "EMPTY_EOF"),
    (b"private-no-newline", "MISSING_NEWLINE"),
    (b"x" * 8193, "OVER_LIMIT"),
])
def test_native_channel_framing_failure_is_specific_and_never_ignored(tmp_path, raw, category):
    from hypertest.cloud.sdk import sdk_error_observation

    path = tmp_path / "framing.sock"
    with DelegationChannel(path) as channel:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(2)
            connection.connect(str(path))
            if raw:
                connection.sendall(raw)
            connection.shutdown(socket.SHUT_WR)
            assert connection.recv(16) == b""
        observed = sdk_error_observation(channel.error, "DELEGATE_CLOSED")
        assert observed["channel_failure"] == category
        assert channel.closed.is_set() is False
        assert "private-no-newline" not in json.dumps(observed)


@pytest.mark.parametrize("frame,category", [
    ({"sequence": 1, "kind": "READY", "data": {}}, "READY_SHAPE"),
    ({"sequence": 2, "kind": "READY", "data": NATIVE_READY}, "SEQUENCE"),
    ({"sequence": 1, "kind": "CLOSED", "data": None}, "CLOSED_ORDER"),
    ({"sequence": 1, "kind": "private-kind", "data": None}, "FRAME_KIND"),
])
def test_native_metadata_categories_are_closed_without_raw_values(tmp_path, frame, category):
    channel = DelegationChannel(tmp_path / "unused")
    with pytest.raises(ValueError) as caught:
        channel.receive(frame)
    assert caught.value.channel_failure == category
    assert "private-kind" not in str(caught.value)


def test_native_protocol_mode_rejects_prompt_before_configuration_or_any_sdk_call(monkeypatch, capsys):
    from hypertest.cloud import sdk_driver
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"mode": "NATIVE_PROTOCOL_PROBE", "prompt": "forbidden"})))
    monkeypatch.setattr(sdk_driver, "write_native_configuration", lambda *a, **k: pytest.fail("configuration touched"))
    monkeypatch.setattr(sdk_driver, "probe_official_sdk", lambda *a, **k: pytest.fail("runtime started"))
    assert sdk_driver.main() == 1
    assert json.loads(capsys.readouterr().out) == {"runtime_observation": "ERROR", "code": "SDK_RUN_FAILED",
        "sdk_error": {"phase": "CONFIGURATION", "type": "CONTRACT", "rpc_numeric_code": None}}


async def test_fencing_cancels_active_git_preparation_before_second_repo_or_model(tmp_path, monkeypatch):
    from hypertest.cloud import worker as module
    cancelled, preparing = asyncio.Event(), asyncio.Event()
    class Broker:
        def __init__(self, _, claim, worker_id):
            self.task_id, self.attempt_id = claim["task"]["id"], claim["attempt"]["id"]
            self.project_id = claim["task"]["project_id"]
            self.identity = SimpleNamespace(generation=1)
        async def assert_current(self):
            pass
        async def credentials(self):
            return {}
        async def renew(self, seconds):
            await preparing.wait()
            raise CloudBlocked("WORKER_FENCED", "fixture revoked authority")
    class Reporter:
        def __init__(self, **kwargs):
            pass
        async def recover(self):
            pass
        async def submit_handoff(self, *args, **kwargs):
            pytest.fail("fenced Worker submitted a transition")
        def pending(self):
            return []
        def close(self):
            pass
    monkeypatch.setattr(module, "CloudBroker", Broker)
    monkeypatch.setattr(module, "CloudTaskReporter", Reporter)
    monkeypatch.setattr(module, "inspect_sdk", lambda: {})
    monkeypatch.setattr(module, "read_model_key", lambda *_: pytest.fail("model key read after fence"))
    settings = SimpleNamespace(cloud_runtime_root=str(tmp_path / "state"), cloud_worker_lease_seconds=0.03,
        cloud_model_request_cost_microunits=1, cloud_attempt_timeout_seconds=60,
        cloud_model_max_requests=1, cloud_model_max_tokens=1024)
    manifest = {"inputs": {"authorization": {"network_targets": [], "permitted_actions": ["git:read", "framework:execute"]},
        "budgets": {"total_seconds": 60}}, "configuration": {"environment": {"connection": "NONE"}},
        "resolution": {"repositories": {"sut": {}, "framework": {}}}}
    claim = {"task": {"id": str(uuid4()), "project_id": str(uuid4()), "frozen_manifest": manifest,
                      "input_digest": digest(manifest)},
             "attempt": {"id": str(uuid4()), "input_digest": digest(manifest), "checkpoint": {}},
             "budget_remaining": {"seconds": 60, "cost_microunits": 10}}
    worker = CloudWorker(None, settings, "fixture")
    calls = []
    async def checkout(*args, **kwargs):
        calls.append("checkout")
        preparing.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
    worker.resolver = SimpleNamespace(checkout=checkout)
    with pytest.raises(CloudBlocked) as error:
        await asyncio.wait_for(worker.execute(claim), 1)
    assert error.value.code == "WORKER_FENCED"
    assert cancelled.is_set() and calls == ["checkout"]
