"""Explicit no-model Linux probe. Run only in a disposable acceptance container.

The address-space backend is an independent diagnosis, not a fallback sandbox.
Neither backend reads a model key, starts a broker, or sends a prompt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy, apply_resource_limits
from hypertest.cloud.sdk import SDK_PHASES, project_sdk_error
from hypertest.deepseek_harness.supervisor import clean_environment


async def read_metadata_output(stream, output: bytearray) -> bytes:
    """Bounded accumulation until EOF or a complete SDK ERROR frame.

    StreamReader.read(n) returns currently available bytes; a flushed phase is
    not EOF and must never start the short process-exit deadline.
    """
    while chunk := await stream.read(min(4096, 65537 - len(output))):
        output.extend(chunk)
        if len(output) > 65536:
            raise CloudBlocked("RUNTIME_OBSERVATION_LIMIT", "Protocol metadata exceeds its observation bound")
        for line in output.splitlines():
            try:
                frame = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(frame, dict) and frame.get("runtime_observation") == "ERROR":
                return bytes(output)
    return bytes(output)


def _protocol_observation(output: bytes) -> dict:
    if len(output) > 65536:
        raise CloudBlocked("RUNTIME_OBSERVATION_LIMIT", "Protocol metadata exceeds its observation bound")
    result = {"protocol_observed": False}
    terminal_count = 0
    invalid = False
    for line in output.splitlines():
        try:
            frame = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            invalid = True
            continue
        if not isinstance(frame, dict):
            invalid = True
            continue
        if "runtime_phase" in frame:
            phase = frame["runtime_phase"]
            result["last_phase"] = phase if isinstance(phase, str) and phase in SDK_PHASES else "OTHER"
        if frame.get("runtime_observation") == "ERROR":
            terminal_count += 1
            if "sdk_error" not in result:
                result["sdk_error"] = project_sdk_error(frame.get("sdk_error"))
        elif frame.get("runtime_observation") == "PROTOCOL_OBSERVED":
            terminal_count += 1
            result["protocol_observed"] = (frame.get("model_prompt_sent") is False
                and frame.get("initialized") is True and frame.get("session_created") is True
                and frame.get("runtime_closed") is True)
        elif "runtime_phase" not in frame:
            invalid = True
    if invalid or terminal_count != 1 or "sdk_error" in result:
        result["protocol_observed"] = False
    if invalid:
        result["metadata_invalid"] = True
    return result


async def probe(*, backend: str, address_space_gib: int, timeout: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="ht-dsh-ns-") as directory:
        root = Path(directory)
        for name in ("workspace", "workspace/sut", "workspace/framework", "dsh-home", "private-home", "tmp"):
            (root / name).mkdir(mode=0o700)
        policy = SandboxPolicy(timeout, 1, 1024, memory_bytes=address_space_gib * 1024 ** 3)
        config = {"mode": "PROTOCOL_PROBE", "session_id": "probe-" + uuid4().hex,
            "model": "deepseek-flash", "max_tokens": 1024, "timeout_seconds": timeout}
        assert "prompt" not in config and "resume" not in config
        dummy = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dummy.bind(str(root / "model.sock"))
        # No listener or model service exists. The socket is only a mount target
        # required by the unchanged production namespace command.
        sandbox = None
        process = None
        closed = False
        valid = False
        metadata = {"protocol_observed": False}
        output_buffer = bytearray()
        process_exit_unobserved = False
        reason = "PROTOCOL_NOT_OBSERVED"
        try:
            if backend == "sandbox":
                config.update(workspace="/workspace", dsh_home="/home/agent/dsh")
                sandbox = BubblewrapSandbox(workspace=root / "workspace", dsh_home=root / "dsh-home",
                    broker_socket=root / "model.sock", policy=policy)
                process = await sandbox.start(config)
            else:
                config.update(workspace=str(root / "workspace"), dsh_home=str(root / "dsh-home"))
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "hypertest.cloud.sdk_driver",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, cwd=root / "workspace",
                    env=clean_environment(root), start_new_session=True,
                    preexec_fn=lambda: apply_resource_limits(policy))
                process.stdin.write(json.dumps(config).encode())
                await process.stdin.drain()
                process.stdin.close()
            stdout = await asyncio.wait_for(read_metadata_output(process.stdout, output_buffer), timeout + 5)
            metadata = _protocol_observation(stdout)
            if "sdk_error" in metadata:
                reason = "SDK_PROTOCOL_INITIALIZATION_FAILED"
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                process_exit_unobserved = True
                if "sdk_error" not in metadata:
                    reason = "RUNTIME_PROCESS_EXIT_UNOBSERVED"
            else:
                valid = process.returncode == 0 and metadata["protocol_observed"]
                if "sdk_error" not in metadata:
                    reason = "NO_PROMPT_PROTOCOL_OBSERVED" if valid else (
                        ("NAMESPACE_SETUP_FAILED" if backend == "sandbox" else "SDK_PROCESS_START_FAILED")
                        if not stdout else "SDK_PROTOCOL_INITIALIZATION_FAILED")
        except TimeoutError:
            if output_buffer and "sdk_error" not in metadata:
                metadata = _protocol_observation(bytes(output_buffer))
            if "sdk_error" not in metadata:
                reason = "PROBE_TIMEOUT"
            else:
                reason = "SDK_PROTOCOL_INITIALIZATION_FAILED"
            valid = False
        except Exception as error:
            code = getattr(error, "code", None)
            if "sdk_error" not in metadata:
                reason = code if isinstance(code, str) and code.startswith(("CGROUP_", "OS_SANDBOX_", "RUNTIME_")) else "PROBE_FAILED"
            valid = False
        finally:
            try:
                if sandbox is not None:
                    stopped = await sandbox.stop()
                    closed = stopped.get("local_processes_stopped") is True
                elif process is not None:
                    for signum in (signal.SIGTERM, signal.SIGKILL):
                        try:
                            os.killpg(process.pid, signum)
                        except ProcessLookupError:
                            break
                        try:
                            await asyncio.wait_for(process.wait(), 1)
                        except TimeoutError:
                            continue
                    closed = process.returncode is not None
            except Exception:
                closed = False
                if "sdk_error" not in metadata:
                    reason = "RUNTIME_STOP_UNCONFIRMED"
            finally:
                dummy.close()
        return {"backend": backend, "address_space_gib": address_space_gib,
            "status": "OBSERVED" if valid and closed else "BLOCKED",
            "reason": reason,
            "production_namespace_proven": backend == "sandbox" and valid and closed,
            "model_prompt_sent": False, "broker_started": False, "model_identity_read": False,
            "runtime_closed": closed, "process_exit_unobserved": process_exit_unobserved,
            "runtime": metadata, "test_result": "NOT_RUN"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-protocol-probe", action="store_true")
    parser.add_argument("--backend", choices=("sandbox", "address-space"), default="sandbox")
    parser.add_argument("--address-space-gib", type=int, choices=(4, 8, 16, 32, 64, 2048), default=4)
    parser.add_argument("--timeout-seconds", type=int, choices=range(5, 61), default=30)
    args = parser.parse_args(argv)
    if not args.allow_protocol_probe:
        print(json.dumps({"status": "NOT_RUN", "reason": "EXPLICIT_PROTOCOL_PROBE_FLAG_REQUIRED"}))
        return 1
    result = asyncio.run(probe(backend=args.backend, address_space_gib=args.address_space_gib,
                              timeout=args.timeout_seconds))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
