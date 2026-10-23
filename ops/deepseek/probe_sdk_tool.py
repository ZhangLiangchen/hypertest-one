"""Explicit keyless official SDK ToolsService printf in the production namespace.

No model prompt, broker, credential read, SUT, history scan or policy override.
This tests tool capability only; it cannot complete a CloudTask or prove PASS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import socket
import tempfile
from pathlib import Path
from uuid import uuid4

from probe_cloud_sandbox import read_metadata_output
from probe_host_profile import inspect_outer_profile

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy
from hypertest.cloud.sdk import SDK_PHASES, project_sdk_error
from hypertest.cloud.tool_probe import project_tool_probe


def runtime_observation(output: bytes) -> dict:
    if len(output) > 65536:
        raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe output exceeds its fixed bound")
    result, terminal_count, first_error, last_phase = None, 0, None, None
    for line in output.splitlines():
        try:
            frame = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe output is not fixed metadata") from None
        if not isinstance(frame, dict):
            raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe output is not fixed metadata")
        phase = frame.get("runtime_phase")
        if isinstance(phase, str) and phase in SDK_PHASES:
            last_phase = phase
        elif frame.get("runtime_observation") == "ERROR":
            terminal_count += 1
            if first_error is None:
                first_error = project_sdk_error(frame.get("sdk_error"))
        elif frame.get("runtime_observation") == "TOOL_PROBE_OBSERVED":
            terminal_count += 1
            if (frame.get("model_prompt_sent") is not False or frame.get("initialized") is not True
                    or frame.get("session_created") is not True or frame.get("runtime_closed") is not True):
                raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe has no initialized, closed no-prompt boundary")
            result = project_tool_probe(frame.get("tool_probe"))
        else:
            raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe output has an unknown frame")
    if first_error is not None:
        return {"sdk_error": first_error, "last_phase": last_phase}
    if terminal_count != 1 or result is None:
        raise CloudBlocked("TOOL_PROBE_METADATA_INVALID", "Tool probe has no unique terminal observation")
    return {"tool_probe": result, "last_phase": last_phase}


async def probe(*, timeout_seconds: int = 30) -> dict:
    inspect_outer_profile()
    root = Path(tempfile.mkdtemp(prefix="hypertest-sdk-tool-"))
    workspace, home = root / "workspace", root / "home"
    for directory in (workspace, workspace / "sut", workspace / "framework", home):
        directory.mkdir(mode=0o700)
    stopped = {"local_processes_stopped": False}
    observed, reason, returncode, output = {}, None, None, bytearray()
    sandbox = None
    try:
        with socket.socket(socket.AF_UNIX) as inert:
            inert.bind(str(root / "unused-model.sock"))  # Bound, never listening.
            sandbox = BubblewrapSandbox(workspace=workspace, dsh_home=home, broker_socket=root / "unused-model.sock",
                policy=SandboxPolicy(timeout_seconds, 1, 1024, memory_bytes=4 * 1024**3,
                    aggregate_memory_bytes=2 * 1024**3, aggregate_processes=256))
            try:
                process = await sandbox.start({"mode": "SDK_TOOL_PROBE", "workspace": "/workspace",
                    "dsh_home": "/home/agent/dsh", "session_id": "tool-probe-" + uuid4().hex,
                    "model": "deepseek-flash", "max_tokens": 1024, "timeout_seconds": timeout_seconds})
                await asyncio.wait_for(read_metadata_output(process.stdout, output), timeout_seconds + 3)
                observed = runtime_observation(bytes(output))
                try:
                    await asyncio.wait_for(process.wait(), 3)
                    returncode = process.returncode
                except TimeoutError:
                    reason = "TOOL_PROBE_PROCESS_EXIT_UNOBSERVED"
            except TimeoutError:
                reason = "TOOL_PROBE_TIMEOUT"
                if output:
                    try:
                        observed = runtime_observation(bytes(output))
                    except CloudBlocked:
                        pass
            finally:
                stopped = await sandbox.stop()
    finally:
        if stopped.get("local_processes_stopped") is True:
            shutil.rmtree(root)
    metadata = observed.get("tool_probe", {})
    success = (reason is None and returncode == 0 and stopped.get("local_processes_stopped") is True
        and metadata.get("tool_registered") is True and metadata.get("executed") is True
        and metadata.get("is_error") is False and metadata.get("marker_match") is True
        and metadata.get("sandbox_mode") == "workspace-write" and metadata.get("approval_policy") == "ask")
    return {"status": "OBSERVED" if success else "BLOCKED", "scope": "SDK_FIXED_PRINTF_ONLY",
        "reason": reason or ("SDK_TOOL_AVAILABLE" if success else "SDK_TOOL_UNAVAILABLE"),
        "runtime": observed, "namespace": stopped, "return_code": returncode,
        "model_prompt_sent": False, "model_identity_read": False, "broker_started": False,
        "sut_started": False, "test_result": "NOT_RUN"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-sdk-tool-probe", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, choices=range(15, 61), default=30)
    args = parser.parse_args(argv)
    if not args.allow_sdk_tool_probe:
        print(json.dumps({"status": "NOT_RUN", "code": "EXPLICIT_SDK_TOOL_PROBE_REQUIRED", "model_prompt_sent": False}))
        return 2
    try:
        result = asyncio.run(probe(timeout_seconds=args.timeout_seconds))
    except Exception:
        result = {"status": "BLOCKED", "code": "SDK_TOOL_PROBE_FAILED", "model_prompt_sent": False, "test_result": "NOT_RUN"}
    print(json.dumps(result))
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
