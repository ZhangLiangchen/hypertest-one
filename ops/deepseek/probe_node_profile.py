"""Explicit keyless Node/UserInfo diagnosis in the production Cloud namespace.

The fixed script neither starts the SDK nor reads model/OAuth identities. It
does not change resource limits, mount host /etc, or execute a Codex child.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from pathlib import Path

from probe_host_profile import inspect_outer_profile

from hypertest.cloud.delegation import verify_payload
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy, apply_resource_limits

ADDRESS_SPACE_BYTES = 4 * 1024**3
SCRIPT = r"""import { existsSync } from 'node:fs';
import { userInfo } from 'node:os';
const result = {node_started:true,node_version:process.versions.node,
  passwd_present:existsSync('/etc/passwd'),user_info_available:false,
  user_info_code:null,shell_present:false};
try {
  const info = userInfo();
  result.user_info_available = true;
  result.shell_present = typeof info.shell === 'string' && info.shell.length > 0;
} catch (error) {
  result.user_info_code = ['ERR_SYSTEM_ERROR','UV_ENOENT','ENOENT'].includes(error?.code)
    ? error.code : 'OTHER';
}
process.stdout.write(JSON.stringify(result) + '\n');
"""


def project_node_metadata(output: bytes) -> dict:
    """A bounded fixed projection never retains user names, homes or errors."""
    try:
        if len(output) > 4096:
            raise ValueError
        value = json.loads(output)
        booleans = ("node_started", "passwd_present", "user_info_available", "shell_present")
        expected = {*booleans, "node_version", "user_info_code"}
        if (not isinstance(value, dict) or not expected <= value.keys()
                or any(type(value[key]) is not bool for key in booleans)
                or value["node_started"] is not True
                or not isinstance(value["node_version"], str)
                or re.fullmatch(r"22\.[0-9]{1,3}\.[0-9]{1,3}", value["node_version"]) is None
                or value["user_info_code"] not in {None, "ERR_SYSTEM_ERROR", "UV_ENOENT", "ENOENT", "OTHER"}):
            raise ValueError
        return {key: value[key] for key in sorted(expected)}
    except (ValueError, TypeError, UnicodeDecodeError):
        raise CloudBlocked("NODE_METADATA_INVALID", "Node did not emit the fixed diagnostic shape") from None


async def read_node_output(stream) -> bytes:
    output = bytearray()
    while chunk := await stream.read(4097 - len(output)):
        output.extend(chunk)
        if len(output) > 4096:
            raise CloudBlocked("NODE_METADATA_INVALID", "Node diagnostic output exceeds its fixed bound")
    return bytes(output)


async def probe(payload: Path, manifest_sha256: str, *, timeout_seconds: int = 10) -> dict:
    inspect_outer_profile()
    verify_payload(payload, manifest_sha256)
    root = Path(tempfile.mkdtemp(prefix="hypertest-node-profile-"))
    stopped = {"local_processes_stopped": False}
    sandbox = None
    reason, metadata, returncode = None, None, None
    try:
        workspace, home = root / "workspace", root / "home"
        for directory in (workspace, workspace / "sut", workspace / "framework", home):
            directory.mkdir(mode=0o700)
        with socket.socket(socket.AF_UNIX) as inert:
            inert.bind(str(root / "unused-model.sock"))
            policy = SandboxPolicy(timeout_seconds, 1, 1024, memory_bytes=ADDRESS_SPACE_BYTES,
                aggregate_memory_bytes=2 * 1024**3, aggregate_processes=256)
            sandbox = BubblewrapSandbox(workspace=workspace, dsh_home=home,
                broker_socket=root / "unused-model.sock", delegate_payload=payload, policy=policy)
            command = sandbox.command()
            if command[-3:] != [sys.executable, "-m", "hypertest.cloud.sdk_driver"]:
                raise CloudBlocked("NODE_NAMESPACE_CONTRACT_CHANGED", "Production namespace command has changed")
            command[-3:] = ["/opt/hypertest-delegates/bin/node", "--input-type=module", "-e", SCRIPT]
            try:
                process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    env={"PATH": os.defpath}, start_new_session=True,
                    preexec_fn=lambda: apply_resource_limits(policy))
                sandbox.process = process
                output = await asyncio.wait_for(read_node_output(process.stdout), timeout_seconds)
                # The fixed Node script emits exactly one terminal frame, but
                # still observe actual exit independently of receiving bytes.
                await asyncio.wait_for(process.wait(), max(1, timeout_seconds))
                returncode = process.returncode
                if returncode != 0:
                    reason = "NODE_EXECUTION_FAILED"
                else:
                    metadata = project_node_metadata(output)
            except TimeoutError:
                reason = "NODE_EXECUTION_TIMEOUT"
            except CloudBlocked as error:
                reason = error.code if error.code == "NODE_METADATA_INVALID" else "NODE_PROBE_FAILED"
            finally:
                stopped = await sandbox.stop()
    finally:
        # Keep an unconfirmed namespace's workspace intact for operator recovery.
        if stopped.get("local_processes_stopped") is True:
            shutil.rmtree(root)
    observed = reason is None and stopped.get("local_processes_stopped") is True and metadata is not None
    result = {"status": "OBSERVED" if observed else "BLOCKED", "scope": "PINNED_NODE_JS_AND_USER_LOOKUP_ONLY",
        "outer_admitted": True, "payload_manifest_verified": True, "address_space_bytes": ADDRESS_SPACE_BYTES,
        "namespace": stopped, "model_started": False, "sdk_started": False, "codex_started": False,
        "test_result": "NOT_RUN"}
    if metadata is not None:
        result["node"] = metadata
    if reason is not None:
        result["code"] = reason
    if type(returncode) is int and -255 <= returncode <= 255:
        result["return_code"] = returncode
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-node-profile-probe", action="store_true")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=int, choices=range(5, 31), default=10)
    args = parser.parse_args(argv)
    if not args.allow_node_profile_probe:
        print(json.dumps({"status": "NOT_RUN", "code": "EXPLICIT_NODE_PROFILE_PROBE_REQUIRED", "model_started": False}))
        return 2
    try:
        result = asyncio.run(probe(args.payload, args.manifest_sha256, timeout_seconds=args.timeout_seconds))
    except Exception:
        result = {"status": "BLOCKED", "code": "NODE_PROBE_FAILED", "model_started": False,
            "sdk_started": False, "codex_started": False, "test_result": "NOT_RUN"}
    print(json.dumps(result))
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
