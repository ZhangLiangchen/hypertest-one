"""Sandbox-only SDK entry. Stdout is bounded metadata, never model conversation."""
from __future__ import annotations

import json
import sys
import threading
from contextlib import ExitStack
from pathlib import Path

from .delegation import DelegationChannel, write_native_configuration
from .model_broker import start_sandbox_relay
from .runtime_activity import project_finish_reason, project_notification
from .sdk import SDK_PHASES, probe_official_sdk, run_official_sdk, sdk_error_observation


def main() -> int:
    phase = "CONFIGURATION"
    output_lock = threading.Lock()

    def emit(value):
        with output_lock:
            sys.stdout.write(json.dumps(value) + "\n")
            sys.stdout.flush()

    def enter_phase(value):
        nonlocal phase
        phase = value if value in SDK_PHASES else "OTHER"
        emit({"runtime_phase": phase})

    try:
        config = json.load(sys.stdin)
        if config.get("mode") == "SDK_TOOL_PROBE":
            from .tool_probe import read_tool_probe, write_tool_probe_configuration
            patch = write_tool_probe_configuration(config)
            config["patches"] = (str(patch),)
            result = probe_official_sdk(config, on_phase=enter_phase)
            observed = read_tool_probe(Path(config["workspace"]))
            emit({**result, "runtime_observation": "TOOL_PROBE_OBSERVED", "tool_probe": observed})
            return 0
        if config.get("mode") in {"PROTOCOL_PROBE", "NATIVE_PROTOCOL_PROBE"}:
            # Only the host controls this stdin envelope. There is deliberately
            # no model broker/relay, prompt, resume or live credential in a probe.
            native = config.get("mode") == "NATIVE_PROTOCOL_PROBE"
            if native:
                if "prompt" in config or config.get("resume"):
                    raise ValueError("native protocol probe never accepts a prompt")
                configuration = config.get("native_delegation")
                if not isinstance(configuration, dict) or set(configuration) != {"codex_model"}:
                    raise ValueError("native protocol probe needs the fixed Codex profile")
                patch = write_native_configuration(Path(config["dsh_home"]).parent,
                    model=configuration["codex_model"], codex_base_url="http://127.0.0.1:1")
                config["patches"] = (str(patch),)
                with DelegationChannel(Path("/run/delegation-observer.sock")) as channel:
                    ready_profile = None

                    def native_ready():
                        nonlocal ready_profile
                        ready_profile = channel.ensure_ready()

                    result = probe_official_sdk(config, on_phase=enter_phase, before_close=native_ready)
                    result.update(native_profile=ready_profile, native_child_started=False,
                        native_delegation_observed=False, oauth_read=False)
                    enter_phase("DELEGATE_CLOSED")
                    channel.ensure_closed()
            else:
                result = probe_official_sdk(config, on_phase=enter_phase)
            emit(result)
            return 0
        if config.get("mode", "RUN") != "RUN":
            raise ValueError("unsupported runtime mode")
        counter = 0

        def notification(item):
            nonlocal counter
            # Only live scalar event metadata is projected. No tool args, result
            # content, text, history, error messages or reasoning is retained.
            observed = project_notification(item, config["session_id"])
            if observed is not None and counter < 512:
                counter += 1
                emit({"runtime_activity": observed})
        with ExitStack() as relays:
            def relay(path):
                server, base = start_sandbox_relay(path)
                relays.callback(server.server_close)
                relays.callback(server.shutdown)
                return base
            config["base_url"] = relay("/run/model.sock")
            native = config.get("native_delegation")
            channel = None
            if native is not None:
                if not isinstance(native, dict) or set(native) != {"codex_model"}:
                    raise ValueError("unsupported native delegation profile")
                codex_base = relay("/run/codex.sock")
                patch = write_native_configuration(Path(config["dsh_home"]).parent,
                    model=native["codex_model"], codex_base_url=codex_base)
                config["patches"] = (str(patch),)
                channel = relays.enter_context(DelegationChannel(Path("/run/delegation-observer.sock"),
                    on_delegation=lambda data: emit({"delegation": data})))
            result = run_official_sdk(config, config["prompt"], on_notification=notification,
                before_prompt=channel.ensure_ready if channel is not None else None, on_phase=enter_phase)
            if channel is not None:
                enter_phase("DELEGATE_CLOSED")
                channel.ensure_closed()
                emit({"native_delegation_closed": True})
            reason = project_finish_reason(result.finish_reason)
            emit({"runtime_observation": "IDLE", "session_id": result.session_id, "finish_reason": reason})
        return 0
    except Exception as error:
        # SDK diagnostics may include raw tool/Provider text; keep them private.
        emit({"runtime_observation": "ERROR", "code": "SDK_RUN_FAILED",
            "sdk_error": sdk_error_observation(error, phase)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
