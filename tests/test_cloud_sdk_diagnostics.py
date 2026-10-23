"""Safe first-error projection; fixtures never start a model or real runtime."""

import importlib
import io
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypertest.cloud import sdk, sdk_driver
from hypertest.cloud.errors import CloudBlocked


def test_initialization_rpc_error_survives_close_failure_without_private_data(monkeypatch):
    official_errors = pytest.importorskip("deepseek_harness.errors")
    phases, calls = [], []

    class Client:
        def start(self):
            calls.append("start")

        def initialize(self, **kwargs):
            raise official_errors.JsonRpcError(-32603, "private-provider-message", {"secret": "private-data"})

        def close(self):
            calls.append("close")
            raise TimeoutError("private-close-diagnostics")

    monkeypatch.setattr(sdk, "inspect_sdk", lambda: {})
    monkeypatch.setattr(sdk, "_official_client", lambda _: Client())
    with pytest.raises(sdk.SdkOperationError) as caught:
        sdk.probe_official_sdk({"session_id": "fixture", "workspace": "/workspace", "model": "fixture",
            "max_tokens": 10}, on_phase=phases.append)
    assert calls == ["start", "close"]
    assert phases == ["CONFIGURATION", "CLIENT_CONFIGURATION", "SDK_START", "INITIALIZE", "CLOSE"]
    assert caught.value.sdk_error == {"phase": "INITIALIZE", "type": "JSON_RPC", "rpc_numeric_code": -32603}
    assert "private" not in str(caught.value) + json.dumps(caught.value.sdk_error)


def test_prompt_enqueue_timeout_is_distinct_from_wait_and_shutdown(monkeypatch):
    phases = []
    subscription = SimpleNamespace(drain=lambda _: pytest.fail("wait reached after failed enqueue"))

    class Client:
        def subscribe_notifications(self):
            return nullcontext(subscription)

        def start(self):
            pass

        def initialize(self, **kwargs):
            return SimpleNamespace(serverInfo=SimpleNamespace(name="deepseek-harness-sdk-runtime", version="0.0.1"))

        def session_prompt(self, *args, **kwargs):
            raise TimeoutError("private-model-text")

        def close(self):
            raise OSError("private-close-text")

    monkeypatch.setattr(sdk, "inspect_sdk", lambda: {})
    monkeypatch.setattr(sdk, "_official_client", lambda _: Client())
    with pytest.raises(sdk.SdkOperationError) as caught:
        sdk.run_official_sdk({"session_id": "fixture", "workspace": "/workspace", "model": "fixture",
            "max_tokens": 10}, "fixture-only-no-model", on_phase=phases.append)
    assert caught.value.sdk_error == {"phase": "PROMPT_ENQUEUE", "type": "TIMEOUT", "rpc_numeric_code": None}
    assert "WAIT" not in phases and phases[-1] == "CLOSE"


def test_driver_keeps_original_phase_even_after_close_progress(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"mode":"PROTOCOL_PROBE"}'))

    def fail(_, *, on_phase):
        on_phase("INITIALIZE")
        on_phase("CLOSE")
        raise sdk.SdkOperationError({"phase": "INITIALIZE", "type": "TRANSPORT_CLOSED", "rpc_numeric_code": None})

    monkeypatch.setattr(sdk_driver, "probe_official_sdk", fail)
    assert sdk_driver.main() == 1
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert frames[-1] == {"runtime_observation": "ERROR", "code": "SDK_RUN_FAILED",
        "sdk_error": {"phase": "INITIALIZE", "type": "TRANSPORT_CLOSED", "rpc_numeric_code": None}}
    assert frames[:-1] == [{"runtime_phase": "INITIALIZE"}, {"runtime_phase": "CLOSE"}]


@pytest.mark.parametrize("numeric", [True, "-32000 private", 100000, -100000, 1.5, None])
def test_safe_error_projection_rejects_text_and_non_numeric_rpc_values(numeric):
    result = sdk.project_sdk_error({"phase": "private-phase", "type": "private-type",
        "rpc_numeric_code": numeric, "data": "private-data"})
    assert result == {"phase": "OTHER", "type": "OTHER", "rpc_numeric_code": None}


def test_native_probe_preserves_first_error_and_discards_untrusted_fields(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "ops" / "deepseek"))
    module = importlib.import_module("probe_native_profile")
    first = {"phase": "SESSION_CREATE", "type": "JSON_RPC", "rpc_numeric_code": -32000}
    frames = [{"runtime_phase": "SESSION_CREATE"},
        {"runtime_observation": "ERROR", "sdk_error": {**first, "message": "private"}},
        {"runtime_phase": "CLOSE"},
        {"runtime_observation": "ERROR", "sdk_error": {"phase": "CLOSE", "type": "TIMEOUT"}, "answer": "private"}]
    result = module.runtime_observation(b"\n".join(json.dumps(frame).encode() for frame in frames))
    assert result == {"runtime_observation": "ERROR", "sdk_error": first, "last_phase": "CLOSE"}
    assert "private" not in json.dumps(result)


def test_native_ready_is_checked_before_official_client_shutdown(monkeypatch):
    order = []

    class Client:
        def start(self):
            order.append("start")

        def initialize(self, **kwargs):
            return SimpleNamespace(serverInfo=SimpleNamespace(name="deepseek-harness-sdk-runtime", version="0.0.1"))

        def get_working_directory(self, _):
            order.append("session-created")
            return "/workspace"

        def close(self):
            order.append("close")

    monkeypatch.setattr(sdk, "inspect_sdk", lambda: {})
    monkeypatch.setattr(sdk, "_official_client", lambda _: Client())
    observed = sdk.probe_official_sdk({"session_id": "fixture", "workspace": "/workspace", "model": "deepseek-flash",
        "max_tokens": 10}, before_close=lambda: order.append("ready"))
    assert order == ["start", "session-created", "ready", "close"]
    assert observed["model_prompt_sent"] is False


def test_capability_boundary_code_is_closed_and_contains_no_message():
    error = CloudBlocked("NATIVE_SUBPROCESS_UNAVAILABLE", "private raw diagnostic")
    assert sdk.sdk_error_observation(error, "DELEGATE_READY") == {"phase": "DELEGATE_READY", "type": "CAPABILITY",
        "rpc_numeric_code": None, "boundary_code": "NATIVE_SUBPROCESS_UNAVAILABLE"}
    assert "boundary_code" not in sdk.sdk_error_observation(CloudBlocked("private-code", "private"), "DELEGATE_READY")


def test_native_capability_projection_retains_only_complete_fixed_booleans():
    fixed = {"provider_registered": False, "tool_registered": False, "subprocess_shim": False, "node_available": True}
    error = {"phase": "DELEGATE_READY", "type": "CAPABILITY", "rpc_numeric_code": None,
        "native_capabilities": fixed}
    assert sdk.project_sdk_error(error)["native_capabilities"] == fixed
    for altered in ({**fixed, "message": "private"}, {**fixed, "subprocess_shim": "private"}, {"provider_registered": False}):
        projected = sdk.project_sdk_error({**error, "native_capabilities": altered})
        assert "native_capabilities" not in projected and "private" not in json.dumps(projected)


def test_channel_failure_projection_accepts_only_fixed_categories():
    value = {"phase": "DELEGATE_READY", "type": "CAPABILITY", "rpc_numeric_code": None}
    assert sdk.project_sdk_error({**value, "channel_failure": "READY_SHAPE"}) == {**value, "channel_failure": "READY_SHAPE"}
    assert sdk.project_sdk_error({**value, "channel_failure": "private-diagnostic"}) == value


def test_all_official_client_modes_disable_raw_history_and_inventory_uploads_last(tmp_path, monkeypatch):
    captured = []
    official = SimpleNamespace(HarnessConfig=lambda **kwargs: kwargs,
        HarnessClient=lambda config: captured.append(config))
    monkeypatch.setitem(sys.modules, "deepseek_harness", official)
    for mode in ("RUN", "PROTOCOL_PROBE", "NATIVE_PROTOCOL_PROBE"):
        home = tmp_path / mode
        home.mkdir()
        config = {"mode": mode, "patches": ("fixed-native.patch.json",), "dsh_home": str(home / "dsh"),
            "workspace": str(tmp_path), "base_url": "http://127.0.0.1:1", "timeout_seconds": 10}
        if mode == "NATIVE_PROTOCOL_PROBE":
            config["native_delegation"] = {"codex_model": "fixture"}
        sdk._official_client(config)
        patches = captured[-1]["patches"]
        assert captured[-1]["shutdown_timeout_seconds"] == (5 if mode == "NATIVE_PROTOCOL_PROBE" else 1)
        assert patches[0] == "fixed-native.patch.json" and len(patches) == 2
        patch = Path(patches[-1])
        assert patch.stat().st_mode & 0o077 == 0
        assert json.loads(patch.read_text()) == [
            {"id": "session-log-deepseek", "name": "@deepseek-ai/dsh-session-log-deepseek", "disabled": True},
            {"id": "plugin-package-inventory-deepseek", "name": "@deepseek-ai/dsh-plugin-package-inventory-deepseek", "disabled": True},
        ]


