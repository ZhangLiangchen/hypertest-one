"""Explicit keyless official Codex bundle composition in the production namespace.

No prompt, OAuth/API-key read, model broker or native child execution. A success
proves the fixed provider/tool/observer/subprocess seam loaded in the real SEA
runtime; it does not prove native delegation or a testing result.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import tempfile
from pathlib import Path
from uuid import uuid4

from hypertest.cloud.delegation import verify_payload
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy
from hypertest.cloud.sdk import SDK_PHASES, project_sdk_error


def runtime_observation(stdout: bytes) -> dict:
    """Keep the first fixed SDK error, never its message, transcript or data."""
    if len(stdout) > 65536:
        raise ValueError("native-protocol-unavailable")
    result, first_error, last_phase = {}, None, None
    for line in stdout.splitlines():
        frame = json.loads(line)
        if not isinstance(frame, dict):
            raise ValueError("native-protocol-unavailable")
        phase = frame.get("runtime_phase")
        if isinstance(phase, str) and phase in SDK_PHASES:
            last_phase = phase
        if frame.get("runtime_observation") == "ERROR" and first_error is None:
            first_error = project_sdk_error(frame.get("sdk_error"))
        if frame.get("runtime_observation") == "PROTOCOL_OBSERVED":
            result = frame
    if first_error is not None:
        return {"runtime_observation": "ERROR", "sdk_error": first_error, "last_phase": last_phase}
    return result


async def probe(payload: Path, manifest_sha256: str, *, timeout_seconds: int = 30) -> dict:
    verified = verify_payload(payload, manifest_sha256)
    with tempfile.TemporaryDirectory(prefix="hypertest-native-profile-") as directory:
        root = Path(directory)
        workspace, home = root / "workspace", root / "home"
        workspace.mkdir(mode=0o700)
        (workspace / "sut").mkdir(mode=0o700)
        (workspace / "framework").mkdir(mode=0o700)
        home.mkdir(mode=0o700)
        # A bound never-serving socket meets the existing namespace mount shape;
        # the provider-free SDK path never connects to it or starts any relay.
        with socket.socket(socket.AF_UNIX) as inert:
            inert.bind(str(root / "unused-model.sock"))
            sandbox = BubblewrapSandbox(workspace=workspace, dsh_home=home,
                broker_socket=root / "unused-model.sock", delegate_payload=payload,
                policy=SandboxPolicy(timeout_seconds, 1, 1024, aggregate_memory_bytes=2 * 1024**3))
            try:
                process = await sandbox.start({"mode": "NATIVE_PROTOCOL_PROBE", "workspace": "/workspace",
                    "dsh_home": "/home/agent/dsh", "session_id": "native-profile-" + uuid4().hex,
                    "model": "deepseek-flash", "max_tokens": 1024, "timeout_seconds": timeout_seconds,
                    "native_delegation": {"codex_model": "gpt-5.4"}})
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout_seconds + 3)
                observed = runtime_observation(stdout)
                if observed.get("runtime_observation") != "ERROR" and (process.returncode != 0
                        or observed.get("runtime_observation") != "PROTOCOL_OBSERVED"
                        or observed.get("native_delegation_observed") is not False
                        or observed.get("model_prompt_sent") is not False
                        or observed.get("oauth_read") is not False):
                    raise ValueError("native-protocol-unavailable")
            finally:
                stopped = await sandbox.stop()
            if not stopped["local_processes_stopped"]:
                raise ValueError("namespace-not-stopped")
            if observed.get("runtime_observation") == "ERROR":
                return {"status": "BLOCKED", "code": "NATIVE_PROTOCOL_SDK_ERROR",
                    "scope": "NATIVE_PROTOCOL_COMPOSITION_ONLY", "sdk": observed, "namespace": stopped,
                    "model_started": False, "native_delegation_observed": False, "test_result": "NOT_RUN"}
            return {"status": "OBSERVED", "scope": "NATIVE_PROTOCOL_COMPOSITION_ONLY",
                "payload": verified, "sdk": observed, "namespace": stopped,
                "model_started": False, "native_child_started": False, "test_result": "NOT_RUN"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-native-protocol-probe", action="store_true")
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30, choices=range(5, 61))
    args = parser.parse_args()
    if not args.allow_native_protocol_probe:
        print(json.dumps({"status": "BLOCKED", "code": "EXPLICIT_NATIVE_PROTOCOL_PROBE_REQUIRED", "model_started": False}))
        return 2
    try:
        result = asyncio.run(probe(args.payload, args.manifest_sha256, timeout_seconds=args.timeout_seconds))
    except Exception as error:
        print(json.dumps({"status": "BLOCKED", "code": getattr(error, "code", "NATIVE_PROTOCOL_PROBE_FAILED"),
            "model_started": False, "native_delegation_observed": False, "test_result": "NOT_RUN"}))
        return 1
    print(json.dumps(result))
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
