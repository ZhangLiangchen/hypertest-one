"""Explicit single-prompt DeepSeek connectivity probe in the production sandbox.

Only the host broker reads the private model identity. This does not create or
complete a platform task and never reports a testing PASS.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from probe_cloud_sandbox import read_metadata_output
from probe_host_profile import inspect_outer_profile

from hypertest.cloud.artifacts import read_workspace_file
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.model_broker import REFUSED_CATEGORIES, ModelBroker
from hypertest.cloud.private_file import read_private_file
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy
from hypertest.cloud.sdk import SDK_PHASES, inspect_sdk, project_sdk_error

MAX_REQUESTS = 2
MAX_TOKENS = 1024
MARKER_PATH = "framework/hypertest-model-probe-marker.txt"
MARKER_CONTENT = b"hypertest-cloud-model-probe-v1\n"
PROMPT = (
    "This is a bounded connectivity probe. Use a file or shell tool to create "
    "/workspace/framework/hypertest-model-probe-marker.txt containing exactly "
    "hypertest-cloud-model-probe-v1 followed by one newline, then stop. "
    "Do not run tests, install packages, use subagents, make network requests, "
    "or modify any other file."
)


def _broker_diagnostics(observation: dict) -> dict:
    statuses = {str(code) for code in range(100, 600)} | {"OTHER"}
    transports = {"DNS", "TLS", "TIMEOUT", "CONNECT", "OTHER"}

    def counts(name, allowed):
        value = observation.get(name, {})
        return {key: min(count, 1000000) for key, count in value.items()
            if key in allowed and type(count) is int and count >= 0} if isinstance(value, dict) else {}

    refused = observation.get("refused_scope_count", 0)
    return {"upstream_status_counts": counts("upstream_status_counts", statuses),
        "transport_failure_counts": counts("transport_failure_counts", transports),
        "refused_category_counts": counts("refused_category_counts", REFUSED_CATEGORIES),
        "refused_scope_count": min(refused, 1000000) if type(refused) is int and refused >= 0 else 0}


def _write_once(path: Path, document: dict) -> None:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _new_private_state(path: Path) -> Path:
    root = path.absolute()
    if root.parent.resolve(strict=True) != root.parent:
        raise CloudBlocked("MODEL_PROBE_STATE_UNSAFE", "Probe state requires a canonical private directory")
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        raise CloudBlocked("MODEL_PROBE_STATE_EXISTS", "Existing probe intent requires review; a prompt is never replayed") from None
    if root.lstat().st_mode & 0o077:
        raise CloudBlocked("MODEL_PROBE_STATE_UNSAFE", "Probe state must be private")
    return root


def _read_private_key(path: Path) -> bytes:
    try:
        secret = read_private_file(path, max_bytes=65536).strip()
    except CloudBlocked as error:
        code = "MODEL_PROBE_IDENTITY_UNSAFE" if error.code == "PRIVATE_FILE_UNSAFE" else "MODEL_PROBE_IDENTITY_UNAVAILABLE"
        raise CloudBlocked(code, "Model identity is unavailable or outside its private file profile") from None
    if not secret:
        raise CloudBlocked("MODEL_PROBE_IDENTITY_UNAVAILABLE", "Model identity is unavailable")
    return secret


def _runtime_observation(output: bytes, returncode: int | None) -> dict:
    if len(output) > 65536:
        raise CloudBlocked("MODEL_PROBE_OUTPUT_LIMIT", "Runtime metadata exceeds its observation bound")
    terminal = None
    first_error = None
    last_phase = None
    invalid_metadata = False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            invalid_metadata = True
            continue
        if not isinstance(event, dict):
            invalid_metadata = True
            continue
        if "runtime_phase" in event:
            phase = event["runtime_phase"]
            last_phase = phase if isinstance(phase, str) and phase in SDK_PHASES else "OTHER"
        if event.get("runtime_observation") == "ERROR" and first_error is None:
            first_error = project_sdk_error(event.get("sdk_error"))
        state = event.get("runtime_observation")
        if isinstance(state, str) and state in {"IDLE", "ERROR"}:
            terminal = event
    idle = (returncode == 0 and terminal is not None and terminal.get("runtime_observation") == "IDLE"
        and first_error is None and not invalid_metadata)
    reason = terminal.get("finish_reason") if terminal else None
    if reason is not None and (not isinstance(reason, str) or reason not in {"completed", "max-tokens", "error", "cancelled", "OTHER"}):
        reason = "OTHER"
    result = {"idle_observed": idle, "finish_reason": reason}
    if first_error is not None:
        result["sdk_error"] = first_error
    if last_phase is not None:
        result["last_phase"] = last_phase
    if invalid_metadata:
        result["metadata_invalid"] = True
    return result


async def run_probe(*, state_directory: Path, key_file: Path, base_url: str, model: str,
                    credit_reserve_microunits: int, timeout_seconds: int) -> dict:
    # All admission and intent persistence precede model identity access.
    if type(credit_reserve_microunits) is not int or credit_reserve_microunits < 1:
        raise CloudBlocked("MODEL_PROBE_RESERVE_REQUIRED", "Explicit positive probe credit reservation is required")
    if base_url != "https://api.deepseek.com/anthropic":
        raise CloudBlocked("MODEL_PROBE_ENDPOINT_UNSUPPORTED", "This probe only authorizes the official DeepSeek API origin")
    outer = inspect_outer_profile()
    versions = inspect_sdk()
    root = _new_private_state(state_directory)
    for name in ("workspace", "workspace/sut", "workspace/framework", "dsh-home"):
        (root / name).mkdir(mode=0o700)
    config = {"mode": "RUN", "workspace": "/workspace", "dsh_home": "/home/agent/dsh",
        "session_id": "model-probe-" + uuid4().hex, "model": model,
        "max_tokens": MAX_TOKENS, "timeout_seconds": timeout_seconds, "prompt": PROMPT}
    _write_once(root / "intent.json", {"profile": "deepseek-model-connectivity-probe/v1alpha1",
        "created_at": datetime.now(UTC).isoformat(), "runtime_config": config,
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "max_model_requests": MAX_REQUESTS, "max_tokens_per_request": MAX_TOKENS,
        "declared_credit_reserve_microunits": credit_reserve_microunits,
        "reservation_state": "RESERVED", "automatic_replay": False,
        "sdk_version": versions["sdk_version"], "runtime_version": versions["runtime_version"]})
    policy = SandboxPolicy(timeout_seconds, MAX_REQUESTS, MAX_TOKENS)
    broker = ModelBroker(root / "model.sock", base_url=base_url, api_key=_read_private_key(key_file),
        model=model, max_requests=MAX_REQUESTS, max_tokens=MAX_TOKENS,
        deadline=time.monotonic() + timeout_seconds)
    sandbox = BubblewrapSandbox(workspace=root / "workspace", dsh_home=root / "dsh-home",
        broker_socket=root / "model.sock", policy=policy)
    reason = "MODEL_PROBE_NOT_OBSERVED"
    runtime = {"idle_observed": False, "finish_reason": None}
    stopped = {"local_processes_stopped": False}
    output_buffer = bytearray()
    process_exit_unobserved = False
    try:
        with broker:
            try:
                process = await sandbox.start(config)
                output = await asyncio.wait_for(read_metadata_output(process.stdout, output_buffer), timeout_seconds + 2)
                runtime = _runtime_observation(output, process.returncode)
                if "sdk_error" in runtime:
                    reason = "MODEL_PROBE_SDK_ERROR"
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except TimeoutError:
                    process_exit_unobserved = True
                    if "sdk_error" not in runtime:
                        reason = "MODEL_PROBE_PROCESS_EXIT_UNOBSERVED"
                else:
                    runtime = _runtime_observation(output, process.returncode)
            finally:
                stopped = await sandbox.stop()
    except TimeoutError:
        if output_buffer and "sdk_error" not in runtime:
            runtime = _runtime_observation(bytes(output_buffer), None)
        if "sdk_error" not in runtime:
            reason = "MODEL_PROBE_TIMEOUT"
        else:
            reason = "MODEL_PROBE_SDK_ERROR"
    except Exception:
        # No exception, SDK output, HTTP headers or model response is published.
        if "sdk_error" not in runtime:
            reason = "MODEL_PROBE_RUNTIME_FAILED"
    observation = broker.observation()
    try:
        marker_correct = read_workspace_file(root / "workspace", MARKER_PATH, max_bytes=128) == MARKER_CONTENT
    except CloudBlocked:
        marker_correct = False
    http_success = observation.get("upstream_successes", 0) > 0
    upstream_completed = observation.get("upstream_completed", 0) > 0
    closed = stopped.get("local_processes_stopped") is True
    drained = observation.get("drained") is True
    observed = (runtime["idle_observed"] and not process_exit_unobserved and marker_correct
        and http_success and upstream_completed and closed and drained)
    if observed:
        reason = "MODEL_MARKER_AND_CLEANUP_OBSERVED"
    elif reason == "MODEL_PROBE_NOT_OBSERVED":
        reason = "MODEL_MARKER_OR_CLEANUP_UNOBSERVED"
    report = {"status": "OBSERVED" if observed else "BLOCKED", "reason": reason,
        "prompt_intent_persisted": True, "model_http_success": http_success,
        "model_response_completed": upstream_completed, "marker_correct": marker_correct,
        "sdk_turn_succeeded": runtime["idle_observed"] and runtime["finish_reason"] == "completed",
        "runtime_closed": closed, "broker_drained": drained, "model_requests": observation["requests"],
        "process_exit_unobserved": process_exit_unobserved,
        "broker_counts": {name: observation.get(name, 0) for name in
            ("requests", "inflight", "upstream_successes", "upstream_completed")},
        "broker_diagnostics": _broker_diagnostics(observation),
        "max_model_requests": MAX_REQUESTS, "runtime": runtime, "outer_profile": outer,
        "declared_credit_reserve_microunits": credit_reserve_microunits,
        "reservation_release_eligible": closed and drained,
        "test_result": "NOT_RUN", "platform_task_created": False}
    _write_once(root / "observation.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-model-probe", action="store_true")
    parser.add_argument("--state-directory", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--base-url", default="https://api.deepseek.com/anthropic")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--credit-reserve-microunits", type=int)
    parser.add_argument("--timeout-seconds", type=int, choices=range(15, 121), default=60)
    args = parser.parse_args(argv)
    if not args.allow_model_probe:
        print(json.dumps({"status": "NOT_RUN", "reason": "EXPLICIT_MODEL_PROBE_FLAG_REQUIRED", "test_result": "NOT_RUN"}))
        return 1
    if args.state_directory is None or args.key_file is None or args.credit_reserve_microunits is None:
        print(json.dumps({"status": "NOT_RUN", "reason": "EXPLICIT_PROBE_INPUTS_REQUIRED", "test_result": "NOT_RUN"}))
        return 1
    try:
        result = asyncio.run(run_probe(state_directory=args.state_directory, key_file=args.key_file,
            base_url=args.base_url, model=args.model, credit_reserve_microunits=args.credit_reserve_microunits,
            timeout_seconds=args.timeout_seconds))
    except Exception as error:
        code = getattr(error, "code", "MODEL_PROBE_FAILED")
        if not isinstance(code, str) or not code.startswith(("MODEL_PROBE_", "OUTER_PROFILE_", "CGROUP_", "SDK_")):
            code = "MODEL_PROBE_FAILED"
        result = {"status": "BLOCKED", "reason": code, "test_result": "NOT_RUN", "platform_task_created": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
