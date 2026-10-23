"""Official SDK boundary. Import/metadata inspection never starts a model."""
from __future__ import annotations

import importlib.metadata
import inspect
import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import CloudBlocked
from .runtime_activity import project_finish_reason

SDK_VERSION = "0.2.1rc2"
SOURCE_COMMIT = "687f282e8625c6b8d11ff58211a90524be2e4317"
SDK_PHASES = frozenset({"CONFIGURATION", "CLIENT_CONFIGURATION", "SDK_START", "INITIALIZE",
    "SESSION_CREATE", "DELEGATE_READY", "PROMPT_ENQUEUE", "WAIT", "CLOSE", "DELEGATE_CLOSED", "OTHER"})
SDK_ERROR_TYPES = frozenset({"TIMEOUT", "JSON_RPC", "TRANSPORT_CLOSED", "PROTOCOL", "CAPABILITY",
    "DEPENDENCY", "OS", "CONTRACT", "OTHER"})
SDK_BOUNDARY_CODES = frozenset({"SDK_UNAVAILABLE", "SDK_VERSION_MISMATCH", "SDK_CONTRACT_MISMATCH",
    "SDK_PROTOCOL_MISMATCH", "SDK_WORKSPACE_MISMATCH", "SDK_RESUME_UNSUPPORTED", "PROBE_PROMPT_FORBIDDEN",
    "DELEGATION_METADATA_INVALID", "DELEGATION_METADATA_INCOMPLETE", "NATIVE_PROFILE_UNAVAILABLE",
    "NATIVE_PROVIDER_UNAVAILABLE", "NATIVE_TOOL_UNAVAILABLE", "NATIVE_SUBPROCESS_UNAVAILABLE",
    "NATIVE_NODE_UNAVAILABLE", "NATIVE_PAYLOAD_VERSION_MISMATCH", "TOOL_PROBE_CONFIGURATION_INVALID",
    "TOOL_PROBE_METADATA_INVALID"})
NATIVE_CAPABILITY_KEYS = frozenset({"provider_registered", "tool_registered", "subprocess_shim", "node_available"})
CHANNEL_FAILURES = frozenset({"FRAMING", "JSON", "FRAME_KEYS", "SEQUENCE", "AFTER_CLOSED", "FRAME_LIMIT",
    "READY_SHAPE", "READY_ORDER", "DELEGATION_ORDER", "CLOSED_ORDER", "FRAME_KIND", "TRANSPORT", "OTHER",
    "EMPTY_EOF", "OVER_LIMIT", "MISSING_NEWLINE", "TIMEOUT"})


def project_sdk_error(value: object) -> dict:
    """Treat even sandbox stdout as untrusted and copy only fixed diagnostic data."""
    source = value if isinstance(value, dict) else {}
    phase, kind, numeric = source.get("phase"), source.get("type"), source.get("rpc_numeric_code")
    result = {"phase": phase if isinstance(phase, str) and phase in SDK_PHASES else "OTHER",
        "type": kind if isinstance(kind, str) and kind in SDK_ERROR_TYPES else "OTHER",
        "rpc_numeric_code": numeric if type(numeric) is int and -99999 <= numeric <= 99999 else None}
    code = source.get("boundary_code")
    if isinstance(code, str) and code in SDK_BOUNDARY_CODES:
        result["boundary_code"] = code
    capabilities = source.get("native_capabilities")
    if (isinstance(capabilities, dict) and capabilities.keys() == NATIVE_CAPABILITY_KEYS
            and all(type(value) is bool for value in capabilities.values())):
        result["native_capabilities"] = dict(capabilities)
    channel_failure = source.get("channel_failure")
    if isinstance(channel_failure, str) and channel_failure in CHANNEL_FAILURES:
        result["channel_failure"] = channel_failure
    return result


class SdkOperationError(CloudBlocked):
    """Only an allowlisted phase/type/code may leave the private SDK process."""

    def __init__(self, observation: dict):
        self.sdk_error = observation
        super().__init__("SDK_RUN_FAILED", "Official SDK operation failed")


def sdk_error_observation(error: Exception, phase: str) -> dict:
    if isinstance(error, SdkOperationError):
        return project_sdk_error(error.sdk_error)
    kind, numeric = "OTHER", None
    try:
        from deepseek_harness.errors import JsonRpcError, SdkProtocolError, TransportClosedError
    except ImportError:
        JsonRpcError = SdkProtocolError = TransportClosedError = ()
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        kind = "TIMEOUT"
    elif isinstance(error, JsonRpcError):
        kind = "JSON_RPC"
        if type(error.code) is int and -99999 <= error.code <= 99999:
            numeric = error.code
    elif isinstance(error, TransportClosedError):
        kind = "TRANSPORT_CLOSED"
    elif isinstance(error, SdkProtocolError):
        kind = "PROTOCOL"
    elif isinstance(error, CloudBlocked):
        kind = "PROTOCOL" if error.code in {"SDK_PROTOCOL_MISMATCH", "SDK_WORKSPACE_MISMATCH"} else "CAPABILITY"
    elif isinstance(error, ImportError):
        kind = "DEPENDENCY"
    elif isinstance(error, OSError):
        kind = "OS"
    elif isinstance(error, (ValueError, TypeError, KeyError)):
        kind = "CONTRACT"
    result = {"phase": phase if phase in SDK_PHASES else "OTHER", "type": kind, "rpc_numeric_code": numeric}
    if isinstance(error, CloudBlocked) and error.code in SDK_BOUNDARY_CODES:
        result["boundary_code"] = error.code
        result["native_capabilities"] = getattr(error, "native_capabilities", None)
        result["channel_failure"] = getattr(error, "channel_failure", None)
    return project_sdk_error(result)


class _SdkPhases:
    def __init__(self, callback):
        self.phase, self.callback = "CONFIGURATION", callback

    def enter(self, phase):
        self.phase = phase
        if self.callback is not None:
            self.callback(phase)


@contextmanager
def _sdk_client(config: dict, on_phase):
    """Preserve the first failure even if official-client shutdown also fails."""
    phases, client, failure = _SdkPhases(on_phase), None, None
    try:
        phases.enter("CONFIGURATION")
        inspect_sdk()
        phases.enter("CLIENT_CONFIGURATION")
        client = _official_client(config)
        yield client, phases
    except Exception as error:
        failure = SdkOperationError(sdk_error_observation(error, phases.phase))
    finally:
        if client is not None:
            try:
                phases.enter("CLOSE")
                client.close()
            except Exception as error:
                if failure is None:
                    failure = SdkOperationError(sdk_error_observation(error, "CLOSE"))
    if failure is not None:
        raise failure from None


def inspect_sdk() -> dict[str, Any]:
    try:
        sdk = importlib.metadata.version("deepseek-harness-sdk")
        runtime = importlib.metadata.version("deepseek-harness-runtime-bin")
    except importlib.metadata.PackageNotFoundError as exc:
        raise CloudBlocked("SDK_UNAVAILABLE", "Install the pinned Cloud SDK/runtime pair") from exc
    if sdk != SDK_VERSION or runtime != SDK_VERSION:
        raise CloudBlocked("SDK_VERSION_MISMATCH", "Cloud SDK and runtime must match the pinned pair")
    try:
        from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
        from deepseek_harness_runtime import resolve_bundled_launch_args
        fields = inspect.signature(DeepSeekHarnessConfig).parameters
        required = {"dsh_home", "cwd", "runtime_cwd", "profile", "base_url", "api_key", "max_tokens"}
        if not required <= fields.keys():
            raise CloudBlocked("SDK_CONTRACT_MISMATCH", "Pinned SDK configuration contract is unavailable")
        launch = resolve_bundled_launch_args()
        return {"sdk_version": sdk, "runtime_version": runtime,
                "source_commit": SOURCE_COMMIT, "profile": "sdk",
                "launch_executable": launch[0], "launch_paths": list(launch),
                "sdk_resume_api_available": callable(getattr(DeepSeekHarness, "resume_session", None)),
                "supports_resume": False, "resume_reason": "SDK_RESUME_UNSUPPORTED",
                "per_session_cancel": False, "model_started": False}
    except ImportError as exc:
        raise CloudBlocked("SDK_UNAVAILABLE", "Pinned SDK/runtime cannot be loaded") from exc


def run_official_sdk(config: dict, prompt: str, *, on_notification=None, before_prompt=None, on_phase=None):
    """Called only from sdk_driver inside the enforced sandbox, never the API/Worker.

    No custom agent loop: one explicit prompt through the official client.
    The returned idle boundary is an observation, never Cloud completion.
    """
    if config.get("resume"):
        raise CloudBlocked("SDK_RESUME_UNSUPPORTED", "Resume requires an explicit reconciled checkpoint; no prompt is replayed")
    from pydantic import BaseModel

    class WaitResponse(BaseModel):
        pass

    session_id = config["session_id"]
    finish_reason = None

    def observe(notification):
        nonlocal finish_reason
        if notification.method == "session.event" and notification.payload.get("sessionId") == session_id:
            event = notification.payload.get("event")
            if isinstance(event, dict) and event.get("type") == "turn/end":
                data = event.get("data")
                reason = data.get("reason") if isinstance(data, dict) else None
                kind = reason.get("kind") if isinstance(reason, dict) else None
                if not isinstance(kind, str):
                    raise CloudBlocked("SDK_PROTOCOL_MISMATCH", "Root turn ending has no supported reason shape")
                finish_reason = project_finish_reason(kind)
        if on_notification is not None:
            on_notification(notification)

    # The SDK inherits environment; this entry is called only inside our clean
    # namespace. The real model key remains outside, in the host's model broker.
    with _sdk_client(config, on_phase) as (client, phases):
        # A consumer subscription drains payloads instead of Session.run retaining
        # the entire transcript in RunResult.notifications/events for a long task.
        with client.subscribe_notifications() as subscription:
            phases.enter("SDK_START")
            client.start()
            phases.enter("INITIALIZE")
            _initialize(client, config)
            if before_prompt is not None:
                phases.enter("SESSION_CREATE")
                if client.get_working_directory(session_id) != config["workspace"]:
                    raise CloudBlocked("SDK_WORKSPACE_MISMATCH", "Native delegation Session has a different workspace")
                phases.enter("DELEGATE_READY")
                before_prompt()
            phases.enter("PROMPT_ENQUEUE")
            message_id = client.session_prompt(session_id, [{"type": "text", "text": prompt}],
                on_notification=observe, notification_subscription=subscription)
            # This observes the official managed-descendant wait boundary. It is
            # still not a business completion, external-action reconciliation or PASS.
            phases.enter("WAIT")
            client.request("session/wait", {"sessionId": session_id}, response_model=WaitResponse,
                on_notification=observe, notification_subscription=subscription)
            subscription.drain(observe)
        return SdkRunObservation(session_id, message_id, finish_reason)


@dataclass(frozen=True)
class SdkRunObservation:
    session_id: str
    message_id: str
    finish_reason: str | None


def _official_client(config: dict):
    """Shared constructor for task execution and the no-prompt runtime probe."""
    from deepseek_harness import HarnessClient, HarnessConfig
    return HarnessClient(HarnessConfig(profile="sdk", patches=controlled_sdk_patches(config), dsh_home=config["dsh_home"],
        cwd=config["workspace"], env={"DEEPSEEK_BASE_URL": config["base_url"], "DEEPSEEK_API_KEY": "broker-managed"},
        initialize_timeout_seconds=min(30, config["timeout_seconds"]),
        request_timeout_seconds=config["timeout_seconds"],
        # SDK shutdown acknowledges before root plugin disposal. Native
        # metadata's bounded 3s ACK must fit before the client sends TERM/KILL.
        shutdown_timeout_seconds=5 if config.get("native_delegation") is not None else 1))


def controlled_sdk_patches(config: dict) -> tuple[str, ...]:
    """Disable optional history/inventory uploads in every controlled SDK path.

    Keep this last so the operator's fixed native composition cannot restore
    these provider extensions. The model broker still rejects extra fields.
    """
    patch = Path(config["dsh_home"]).parent / "hypertest-inference.patch.json"
    fd = os.open(patch, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump([
            {"id": "session-log-deepseek", "name": "@deepseek-ai/dsh-session-log-deepseek", "disabled": True},
            {"id": "plugin-package-inventory-deepseek", "name": "@deepseek-ai/dsh-plugin-package-inventory-deepseek", "disabled": True},
        ], stream)
    return (*config.get("patches", ()), str(patch))


def _initialize(client, config: dict):
    response = client.initialize(cwd=config["workspace"], provider="deepseek-official",
        model=config["model"], reasoning_effort=config.get("reasoning_effort"), max_tokens=config["max_tokens"])
    info = response.serverInfo
    if info is None or info.name != "deepseek-harness-sdk-runtime" or info.version != "0.0.1":
        raise CloudBlocked("SDK_PROTOCOL_MISMATCH", "Runtime handshake is outside the pinned protocol contract")
    return info


def probe_official_sdk(config: dict, *, on_phase=None, before_close=None) -> dict:
    """Host-selected no-prompt diagnostic, using the production SDK constructor.

    A never-listening loopback origin and inert sentinel replace the model relay;
    no real model identity or model request is needed. This is not task execution.
    """
    if "prompt" in config or config.get("resume"):
        raise CloudBlocked("PROBE_PROMPT_FORBIDDEN", "Protocol diagnostics never accept a prompt or resume")
    config = {**config, "base_url": "http://127.0.0.1:1"}
    with _sdk_client(config, on_phase) as (client, phases):
        phases.enter("SDK_START")
        client.start()
        phases.enter("INITIALIZE")
        info = _initialize(client, config)
        phases.enter("SESSION_CREATE")
        cwd = client.get_working_directory(config["session_id"])
        if cwd != config["workspace"]:
            raise CloudBlocked("SDK_WORKSPACE_MISMATCH", "Probe Session directory differs from its isolated workspace")
        if before_close is not None:
            phases.enter("DELEGATE_READY")
            before_close()
    result = {"runtime_observation": "PROTOCOL_OBSERVED", "initialized": True,
        "session_created": True, "runtime_closed": True,
        "server_name": info.name, "server_version": info.version,
        "model_prompt_sent": False, "test_result": "NOT_RUN"}
    return result
