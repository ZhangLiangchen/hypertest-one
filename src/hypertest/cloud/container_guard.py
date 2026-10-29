"""Fixed PID-1 deadline guard for a proposed Cloud Attempt container.

The guard is a single execution component, not a launcher, external watchdog,
lease authority or proof of stopped brokers. It is intentionally not wired
into the current Worker. Docker identity, immutable mounts, resource envelopes,
external operations, original-key recovery and independent watchdog admission
must be established separately before any production Attempt can use it.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from uuid import UUID

from .clock_domain import clock_domain_digest
from .delegation import DelegationObservations
from .runtime_activity import project_finish_reason, project_runtime_activity
from .sdk import SDK_PHASES, project_sdk_error
from .tool_probe import project_tool_probe

_MAX_FRAME = 1024 * 1024
_MAX_OUTPUT = 2 * 1024 * 1024
_MAX_LINE = 65536
_MAX_DURATION = 7 * 24 * 60 * 60
_MAX_CONTROL = 4096
_MAX_HEARTBEAT_NS = 5_000_000_000
_MAX_TRANSIT_NS = 1_000_000_000
_DRIVER = "/opt/hypertest-cloud/venv/bin/python"
_ENV = {"HOME": "/home/agent", "DSH_HOME": "/home/agent/dsh", "SHELL": "/bin/sh",
        "PATH": "/opt/hypertest-cloud/venv/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
_FIELDS = {"mode", "workspace", "dsh_home", "session_id", "model", "max_tokens", "timeout_seconds",
           "prompt", "native_delegation", "reasoning_effort"}
_GUARD_ENV = {"PATH", "HOSTNAME", "HOME", "LANG", "SHELL", "DSH_HOME", "PYTHONDONTWRITEBYTECODE",
              "PYTHONUNBUFFERED", "PIP_DISABLE_PIP_VERSION_CHECK", "PYTHON_VERSION", "PYTHON_SHA256",
              "GPG_KEY", "HYPERTEST_CLOUD_CONTAINER_DEADLINE", "HYPERTEST_CLOUD_GUARD_PROFILE",
              "HYPERTEST_CLOUD_GUARD_KEY_SHA256", "HYPERTEST_CLOUD_GUARD_SPEC_SHA256",
              "HYPERTEST_CLOUD_GUARD_PROJECT_ID", "HYPERTEST_CLOUD_GUARD_TASK_ID",
              "HYPERTEST_CLOUD_GUARD_ATTEMPT_ID", "HYPERTEST_CLOUD_GUARD_GENERATION",
              "HYPERTEST_CLOUD_GUARD_CLOCK_SHA256"}
_wall_deadline = 0.0
_monotonic_deadline = 0.0
_authorization_deadline_ns = 0
_requires_authorization = False


def _reject() -> None:
    raise ValueError("invalid Cloud container guard input")


def deadline_seconds(value: str, *, now: float) -> float:
    """Require an explicit bounded absolute deadline, without granting more time."""
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]{0,11}", value) is None:
        _reject()
    remaining = int(value) - now
    if not 0 < remaining <= _MAX_DURATION:
        _reject()
    return remaining


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def validate_frame(raw: bytes) -> bytes:
    """Accept only the fixed SDK path and bounded, non-secret control fields."""
    if not isinstance(raw, bytes) or len(raw) > _MAX_FRAME:
        _reject()
    try:
        document = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError):
        _reject()
    if (not isinstance(document, dict) or set(document) - _FIELDS
            or document.get("workspace") != "/workspace" or document.get("dsh_home") != "/home/agent/dsh"
            or type(document.get("max_tokens")) is not int or not 1 <= document["max_tokens"] <= 49152
            or type(document.get("timeout_seconds")) is not int or not 1 <= document["timeout_seconds"] <= _MAX_DURATION
            or not isinstance(document.get("model"), str) or not 1 <= len(document["model"]) <= 255):
        _reject()
    mode = document.get("mode", "RUN")
    session = document.get("session_id")
    if mode == "RUN":
        if not isinstance(session, str) or not session.startswith("cloud-"):
            _reject()
        try:
            if str(UUID(session[6:])) != session[6:]:
                _reject()
        except (ValueError, AttributeError):
            _reject()
        if not isinstance(document.get("prompt"), str) or not document["prompt"]:
            _reject()
        if "native_delegation" in document:
            native = document["native_delegation"]
            if (not isinstance(native, dict) or set(native) != {"codex_model"}
                    or not isinstance(native["codex_model"], str) or not 1 <= len(native["codex_model"]) <= 255):
                _reject()
    elif mode == "SDK_TOOL_PROBE":
        if (not isinstance(session, str) or re.fullmatch(r"tool-probe-[a-f0-9]{32}", session) is None
                or "prompt" in document or "native_delegation" in document):
            _reject()
    else:
        _reject()
    return raw


def _secure_pid1() -> None:
    """Make this PID 1 non-dumpable before accepting any untrusted input."""
    if (sys.platform != "linux" or os.getpid() != 1 or os.getuid() == 0 or os.getuid() != os.geteuid()
            or os.getgid() != os.getegid() or not sys.flags.isolated or set(os.environ) - _GUARD_ENV):
        _reject()
    with open("/proc/self/status", encoding="utf-8") as stream:
        status = stream.read(65537)
    if len(status) > 65536:
        _reject()
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if (fields.get("NoNewPrivs", "").strip() != "1" or any(int(fields[name].strip(), 16) for name in
            ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))):
        _reject()
    libc = ctypes.CDLL(None, use_errno=True)
    # Linux prctl(PR_SET_DUMPABLE, 0) and PR_GET_DUMPABLE; no fallback.
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:
        _reject()


def _expire(signum, _frame) -> None:
    # As Linux namespace PID 1, exiting causes the kernel to kill remaining
    # namespace processes, including descendants that changed process group.
    # This does not prove host-side cgroup cleanup or external operation stop.
    if (signum == signal.SIGALRM and time.time() < _wall_deadline and time.monotonic() < _monotonic_deadline
            and (not _requires_authorization or time.monotonic_ns() < _authorization_deadline_ns)):
        return
    os._exit(124 if signum == signal.SIGALRM else 128 + signum)


def _read_frame() -> bytes:
    data = bytearray()
    while True:
        chunk = os.read(0, min(65536, _MAX_FRAME + 1 - len(data)))
        if not chunk:
            return validate_frame(bytes(data))
        data.extend(chunk)
        if len(data) > _MAX_FRAME:
            _reject()


def _write_all(fd: int, raw: bytes) -> None:
    view = memoryview(raw)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            _reject()
        view = view[written:]


def guard_scope(environ: dict, *, deadline: str) -> dict:
    """Freeze public attempt identity and key digest from the container spec."""
    values = {}
    for field in ("project_id", "task_id", "attempt_id"):
        value = environ.get("HYPERTEST_CLOUD_GUARD_" + field.upper())
        try:
            if not isinstance(value, str) or str(UUID(value)) != value:
                _reject()
        except (ValueError, AttributeError):
            _reject()
        values[field] = value
    generation = environ.get("HYPERTEST_CLOUD_GUARD_GENERATION")
    if not isinstance(generation, str) or re.fullmatch(r"[1-9][0-9]{0,17}", generation) is None:
        _reject()
    values["generation"] = int(generation)
    for field in ("key_sha256", "spec_sha256", "clock_sha256"):
        value = environ.get("HYPERTEST_CLOUD_GUARD_" + field.upper())
        if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
            _reject()
        values[field] = value
    values["deadline_epoch"] = int(deadline)
    return values


def _control_json(raw: bytes, *, limit: int) -> dict:
    if len(raw) > limit:
        _reject()
    try:
        document = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError):
        _reject()
    if not isinstance(document, dict):
        _reject()
    return document


def authenticate_bootstrap(raw: bytes, scope: dict) -> tuple[bytes, bytes]:
    """Extract a one-time key into PID-1 memory, never into SDK input or env."""
    document = _control_json(raw, limit=_MAX_FRAME + _MAX_CONTROL)
    if set(document) != {"kind", "key", "config"} or document["kind"] != "INIT" or not isinstance(document["key"], str):
        _reject()
    try:
        key = base64.b64decode(document["key"], validate=True)
    except (ValueError, TypeError):
        _reject()
    if len(key) != 32 or not hmac.compare_digest(hashlib.sha256(key).hexdigest(), scope["key_sha256"]):
        _reject()
    try:
        frame = json.dumps(document["config"], separators=(",", ":"), ensure_ascii=False).encode()
    except (ValueError, TypeError, UnicodeEncodeError):
        _reject()
    validate_frame(frame)
    config = document["config"]
    if config.get("mode", "RUN") == "RUN" and config["session_id"] != "cloud-" + scope["attempt_id"]:
        _reject()
    return key, frame


def authenticate_heartbeat(raw: bytes, *, key: bytes, scope: dict, previous_seq: int, now_ns: int) -> tuple[int, int]:
    """Accept a fresh signed, bounded lease window in the shared monotonic domain."""
    frame = _control_json(raw, limit=_MAX_CONTROL)
    if set(frame) != {"kind", "sequence", "issued_mono_ns", "lease_until_mono_ns", "mac"} or frame["kind"] != "HEARTBEAT":
        _reject()
    sequence, issued, expires, mac = (frame["sequence"], frame["issued_mono_ns"], frame["lease_until_mono_ns"], frame["mac"])
    if (type(sequence) is not int or sequence != previous_seq + 1 or type(issued) is not int
            or type(expires) is not int or type(now_ns) is not int or issued < 0 or issued > now_ns
            or now_ns - issued > _MAX_TRANSIT_NS or not now_ns < expires <= issued + _MAX_HEARTBEAT_NS
            or not isinstance(mac, str) or re.fullmatch(r"[a-f0-9]{64}", mac) is None):
        _reject()
    signed = {"scope": scope, "kind": "HEARTBEAT", "sequence": sequence,
              "issued_mono_ns": issued, "lease_until_mono_ns": expires}
    material = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode()
    if not hmac.compare_digest(hmac.new(key, material, hashlib.sha256).hexdigest(), mac):
        _reject()
    return sequence, expires


class _ControlStream:
    def __init__(self):
        self.pending = bytearray()

    def receive(self) -> None:
        chunk = os.read(0, 65536)
        if not chunk:
            _reject()  # watchdog EOF cannot authorize continued execution
        self.pending.extend(chunk)
        if len(self.pending) > _MAX_FRAME + _MAX_CONTROL:
            _reject()

    def line(self, limit: int) -> bytes | None:
        if b"\n" not in self.pending:
            if len(self.pending) > limit:
                _reject()
            return None
        line, _, rest = self.pending.partition(b"\n")
        self.pending = bytearray(rest)
        if len(line) > limit:
            _reject()
        return bytes(line)

    def wait_line(self, limit: int) -> bytes:
        while True:
            line = self.line(limit)
            if line is not None:
                return line
            self.receive()


def project_output(raw: bytes, *, session_id: str, probe: bool, delegations: DelegationObservations | None) -> bytes:
    """Project only typed, bounded metadata; never forward arbitrary stdout."""
    if len(raw) > _MAX_LINE:
        _reject()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError):
        _reject()
    if not isinstance(value, dict):
        _reject()
    if "runtime_phase" in value and isinstance(value["runtime_phase"], str) and value["runtime_phase"] in SDK_PHASES:
        projected = {"runtime_phase": value["runtime_phase"]}
    elif "runtime_activity" in value and not probe:
        projected = {"runtime_activity": project_runtime_activity(value["runtime_activity"])}
    elif value.get("runtime_observation") == "ERROR":
        projected = {"runtime_observation": "ERROR", "code": "SDK_RUN_FAILED",
                     "sdk_error": project_sdk_error(value.get("sdk_error"))}
    elif value.get("runtime_observation") == "IDLE" and not probe and value.get("session_id") == session_id:
        projected = {"runtime_observation": "IDLE", "session_id": session_id,
                     "finish_reason": project_finish_reason(value.get("finish_reason"))}
    elif value.get("runtime_observation") == "TOOL_PROBE_OBSERVED" and probe:
        if (value.get("initialized") is not True or value.get("session_created") is not True
                or value.get("runtime_closed") is not True or value.get("model_prompt_sent") is not False
                or value.get("server_name") != "deepseek-harness-sdk-runtime" or value.get("server_version") != "0.0.1"
                or value.get("test_result") != "NOT_RUN"):
            _reject()
        projected = {"runtime_observation": "TOOL_PROBE_OBSERVED", "initialized": True, "session_created": True,
                     "runtime_closed": True, "server_name": "deepseek-harness-sdk-runtime", "server_version": "0.0.1",
                     "model_prompt_sent": False, "test_result": "NOT_RUN", "tool_probe": project_tool_probe(value.get("tool_probe"))}
    elif "delegation" in value and not probe and delegations is not None:
        delegations.accept(value["delegation"])
        projected = {"delegation": dict(value["delegation"])}
    elif value.get("native_delegation_closed") is True and not probe and delegations is not None:
        if delegations.channel_closed or not delegations.all_terminal:
            _reject()
        delegations.channel_closed = True
        projected = {"native_delegation_closed": True}
    else:
        _reject()
    return json.dumps(projected, separators=(",", ":")).encode() + b"\n"


def run() -> int:
    """Run the single fixed SDK driver until it ends or the hard deadline expires."""
    _secure_pid1()
    global _wall_deadline, _monotonic_deadline, _authorization_deadline_ns, _requires_authorization
    value = os.environ.get("HYPERTEST_CLOUD_CONTAINER_DEADLINE", "")
    seconds = deadline_seconds(value, now=time.time())
    _wall_deadline = int(value)
    _monotonic_deadline = time.monotonic() + seconds
    profile = os.environ.get("HYPERTEST_CLOUD_GUARD_PROFILE", "SDK_TOOL_PROBE_V1")
    if profile not in {"SDK_TOOL_PROBE_V1", "WATCHDOG_V1"}:
        _reject()
    _requires_authorization = profile == "WATCHDOG_V1"
    if _requires_authorization:
        # The bootstrap window is itself bounded even when stdin never closes.
        _authorization_deadline_ns = time.monotonic_ns() + _MAX_HEARTBEAT_NS
    for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _expire)
    # A periodic check also catches a forward wall-clock adjustment; a
    # backward adjustment must never extend the original monotonic budget.
    signal.setitimer(signal.ITIMER_REAL, min(seconds, 0.1), 0.1)
    control = None
    key = scope = None
    sequence = 0
    if _requires_authorization:
        scope = guard_scope(os.environ, deadline=value)
        if not hmac.compare_digest(scope["clock_sha256"], clock_domain_digest()):
            _reject()
        control = _ControlStream()
        key, frame = authenticate_bootstrap(control.wait_line(_MAX_FRAME + _MAX_CONTROL), scope)
        first = authenticate_heartbeat(control.wait_line(_MAX_CONTROL),
            key=key, scope=scope, previous_seq=sequence, now_ns=time.monotonic_ns())
        _expire(signal.SIGALRM, None)
        sequence, _authorization_deadline_ns = first
    else:
        frame = _read_frame()
        # The unauthenticated path is diagnostic-only and cannot execute a task.
        if json.loads(frame).get("mode") != "SDK_TOOL_PROBE":
            _reject()
    document = json.loads(frame)
    probe = document.get("mode") == "SDK_TOOL_PROBE"
    delegations = DelegationObservations() if "native_delegation" in document else None
    _expire(signal.SIGALRM, None)
    child = subprocess.Popen([_DRIVER, "-I", "-m", "hypertest.cloud.sdk_driver"], cwd="/workspace",
        env=_ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True)
    assert child.stdin is not None and child.stdout is not None
    try:
        _write_all(child.stdin.fileno(), frame)
    finally:
        child.stdin.close()
    count, pending = 0, bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout.fileno(), selectors.EVENT_READ, "output")
        if control is not None:
            selector.register(0, selectors.EVENT_READ, "control")
        while True:
            if control is not None:
                while (line := control.line(_MAX_CONTROL)) is not None:
                    renewed = authenticate_heartbeat(line,
                        key=key, scope=scope, previous_seq=sequence, now_ns=time.monotonic_ns())
                    _expire(signal.SIGALRM, None)
                    sequence, _authorization_deadline_ns = renewed
            finished = False
            for selected, _ in sorted(selector.select(0.1), key=lambda item: item[0].data != "control"):
                if selected.data == "control":
                    control.receive()
                    continue
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    finished = True
                    continue
                count += len(chunk)
                if count > _MAX_OUTPUT:
                    _reject()
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    _write_all(1, project_output(line, session_id=document["session_id"], probe=probe, delegations=delegations))
                if len(pending) > _MAX_LINE:
                    _reject()
            if finished:
                if control is not None:
                    while (line := control.line(_MAX_CONTROL)) is not None:
                        renewed = authenticate_heartbeat(line,
                            key=key, scope=scope, previous_seq=sequence, now_ns=time.monotonic_ns())
                        _expire(signal.SIGALRM, None)
                        sequence, _authorization_deadline_ns = renewed
                    if control.pending:
                        _reject()
                _expire(signal.SIGALRM, None)
                break
    if pending:
        _reject()
    child.stdout.close()
    code = child.wait()
    return code if 0 <= code <= 125 else 1


def main() -> int:
    try:
        return run()
    except Exception:
        # No source, input, paths, native exceptions or secrets in output.
        return 70


if __name__ == "__main__":
    # Deliberately do not wait on or attempt to enumerate descendants here.
    # Exiting PID 1 terminates the complete namespace, including detached
    # subprocess groups; the trusted outer watchdog still verifies the result.
    os._exit(main())
