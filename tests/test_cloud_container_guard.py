"""PID-1 guard contracts; no model, Docker daemon, or SUT calls."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import signal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud import container_guard as guard


def frame(**changes):
    payload = {"workspace": "/workspace", "dsh_home": "/home/agent/dsh", "session_id": "cloud-" + str(uuid4()),
               "model": "deepseek-flash", "max_tokens": 1024, "timeout_seconds": 30, "prompt": "synthetic test"}
    payload.update(changes)
    return json.dumps(payload).encode()


def test_guard_accepts_only_fixed_worker_and_no_model_probe_frame():
    data = frame()
    assert guard.validate_frame(data) == data
    probe = frame(mode="SDK_TOOL_PROBE", session_id="tool-probe-" + "a" * 32)
    document = json.loads(probe)
    del document["prompt"]
    probe = json.dumps(document).encode()
    assert guard.validate_frame(probe) == probe


@pytest.mark.parametrize("changes", [
    {"workspace": "/"}, {"dsh_home": "/tmp"}, {"mode": "PROTOCOL_PROBE"}, {"model": ""},
    {"prompt": ""}, {"session_id": "cloud-unknown"}, {"timeout_seconds": True}, {"max_tokens": 0},
    {"api_key": "synthetic-must-not-enter"}, {"native_delegation": {"provider": "anything"}},
])
def test_guard_rejects_unapproved_input(changes):
    with pytest.raises(ValueError):
        guard.validate_frame(frame(**changes))


def test_duplicate_and_oversized_frames_are_rejected():
    with pytest.raises(ValueError):
        guard.validate_frame(b'{"mode":"RUN","mode":"SDK_TOOL_PROBE"}')
    with pytest.raises(ValueError):
        guard.validate_frame(b"x" * (guard._MAX_FRAME + 1))


@pytest.mark.parametrize("value", ["", "-1", "0", "12.5", "001", "1000000000000"])
def test_guard_rejects_invalid_or_expired_absolute_deadlines(value):
    with pytest.raises(ValueError):
        guard.deadline_seconds(value, now=1000)


def test_guard_does_not_extend_original_budget():
    assert guard.deadline_seconds("1005", now=1000.5) == 4.5
    with pytest.raises(ValueError):
        guard.deadline_seconds("1000", now=1000)
    with pytest.raises(ValueError):
        guard.deadline_seconds(str(1000 + guard._MAX_DURATION + 1), now=1000)


def test_guard_only_forwards_projected_fixed_metadata():
    session = "cloud-" + str(uuid4())
    raw = json.dumps({"runtime_activity": {"kind": "TOOL_CALL", "tool": "BASH", "sequence": 1,
                                           "prompt": "synthetic private payload"},
                      "secret": "synthetic private payload"}).encode()
    result = guard.project_output(raw, session_id=session, probe=False, delegations=None)
    assert json.loads(result) == {"runtime_activity": {"kind": "TOOL_CALL", "tool": "BASH", "sequence": 1}}
    assert b"synthetic private payload" not in result
    raw = json.dumps({"runtime_observation": "ERROR", "sdk_error": {"phase": "WAIT", "type": "OTHER",
                                                                     "message": "synthetic private payload"}}).encode()
    assert b"synthetic private payload" not in guard.project_output(raw, session_id=session, probe=False, delegations=None)
    with pytest.raises(ValueError):
        guard.project_output(b'{"unapproved":"synthetic private payload"}', session_id=session, probe=False, delegations=None)
    with pytest.raises(ValueError):
        guard.project_output(json.dumps({"runtime_observation": "IDLE", "session_id": "wrong"}).encode(),
                             session_id=session, probe=False, delegations=None)


def test_guard_preserves_native_delegation_lifecycle_and_fixed_idle_metadata():
    session = "cloud-" + str(uuid4())
    collector = guard.DelegationObservations()
    event = {"profile": "hypertest-native-delegation-observation/v1", "run_id": str(uuid4()),
             "native_ref": str(uuid4()), "provider": "codex", "state": "RUNNING", "stop_reason": None}
    start = {"delegation": dict(event)}
    assert json.loads(guard.project_output(json.dumps(start).encode(), session_id=session,
                                           probe=False, delegations=collector)) == start
    event.update(state="TERMINAL", stop_reason="completed")
    terminal = {"delegation": dict(event)}
    assert json.loads(guard.project_output(json.dumps(terminal).encode(), session_id=session,
                                           probe=False, delegations=collector)) == terminal
    closed = {"native_delegation_closed": True}
    assert json.loads(guard.project_output(json.dumps(closed).encode(), session_id=session,
                                           probe=False, delegations=collector)) == closed
    idle = {"runtime_observation": "IDLE", "session_id": session, "finish_reason": "completed"}
    assert json.loads(guard.project_output(json.dumps(idle).encode(), session_id=session,
                                           probe=False, delegations=collector)) == idle


def authenticated_scope(key):
    deadline = "2000"
    environ = {"HYPERTEST_CLOUD_GUARD_PROJECT_ID": str(uuid4()), "HYPERTEST_CLOUD_GUARD_TASK_ID": str(uuid4()),
               "HYPERTEST_CLOUD_GUARD_ATTEMPT_ID": str(uuid4()), "HYPERTEST_CLOUD_GUARD_GENERATION": "3",
               "HYPERTEST_CLOUD_GUARD_KEY_SHA256": hashlib.sha256(key).hexdigest(),
               "HYPERTEST_CLOUD_GUARD_SPEC_SHA256": "a" * 64}
    return guard.guard_scope(environ, deadline=deadline)


def signed_heartbeat(key, scope, *, sequence=1, issued=1_000_000_000, expires=4_000_000_000):
    signed = {"scope": scope, "kind": "HEARTBEAT", "sequence": sequence,
              "issued_mono_ns": issued, "lease_until_mono_ns": expires}
    mac = hmac.new(key, json.dumps(signed, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    return json.dumps({key: value for key, value in signed.items() if key != "scope"} | {"mac": mac}).encode()


def test_bootstrap_binds_original_attempt_and_never_passes_key_to_sdk():
    key = b"x" * 32
    scope = authenticated_scope(key)
    config = json.loads(frame(session_id="cloud-" + scope["attempt_id"]))
    raw = json.dumps({"kind": "INIT", "key": base64.b64encode(key).decode(), "config": config}).encode()
    received_key, sdk_frame = guard.authenticate_bootstrap(raw, scope)
    assert received_key == key and json.loads(sdk_frame) == config
    assert base64.b64encode(key) not in sdk_frame
    with pytest.raises(ValueError):
        guard.authenticate_bootstrap(raw, scope | {"key_sha256": "f" * 64})
    config["session_id"] = "cloud-" + str(uuid4())
    with pytest.raises(ValueError):
        guard.authenticate_bootstrap(json.dumps({"kind": "INIT", "key": base64.b64encode(key).decode(), "config": config}).encode(), scope)


def test_authenticated_heartbeat_enforces_sequence_scope_and_lease_window():
    key = b"x" * 32
    scope = authenticated_scope(key)
    heartbeat = signed_heartbeat(key, scope)
    assert guard.authenticate_heartbeat(heartbeat, key=key, scope=scope, previous_seq=0,
                                        now_ns=1_100_000_000) == (1, 4_000_000_000)
    for changes in ({"key": b"z" * 32}, {"scope": scope | {"attempt_id": str(uuid4())}},
                    {"scope": scope | {"deadline_epoch": scope["deadline_epoch"] + 1}},
                    {"previous_seq": 1}, {"now_ns": 4_000_000_000}, {"now_ns": 3_000_000_000},
                    {"now_ns": 999_999_999}):
        args = {"key": key, "scope": scope, "previous_seq": 0, "now_ns": 1_100_000_000}
        with pytest.raises(ValueError):
            guard.authenticate_heartbeat(heartbeat, **(args | changes))
    too_long = signed_heartbeat(key, scope, expires=7_000_000_000)
    with pytest.raises(ValueError):
        guard.authenticate_heartbeat(too_long, key=key, scope=scope, previous_seq=0, now_ns=1_100_000_000)


def test_watchdog_eof_fails_closed(monkeypatch):
    monkeypatch.setattr(guard.os, "read", lambda *_: b"")
    with pytest.raises(ValueError):
        guard._ControlStream().receive()


def test_expired_lease_stops_even_before_periodic_signal(monkeypatch):
    monkeypatch.setattr(guard, "_requires_authorization", True)
    monkeypatch.setattr(guard, "_authorization_deadline_ns", 10)
    monkeypatch.setattr(guard, "_wall_deadline", 100)
    monkeypatch.setattr(guard, "_monotonic_deadline", 100)
    monkeypatch.setattr(guard.time, "time", lambda: 1)
    monkeypatch.setattr(guard.time, "monotonic", lambda: 1)
    monkeypatch.setattr(guard.time, "monotonic_ns", lambda: 10)
    monkeypatch.setattr(guard.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    with pytest.raises(SystemExit) as stopped:
        guard._expire(signal.SIGALRM, None)
    assert stopped.value.code == 124


@pytest.mark.parametrize("bad", ["prctl_set", "prctl_get", "capabilities", "no_new_privileges", "environment", "not_pid1"])
def test_guard_admission_fails_closed(monkeypatch, bad):
    monkeypatch.setattr(guard, "sys", SimpleNamespace(platform="linux", flags=SimpleNamespace(isolated=1)))
    monkeypatch.setattr(guard.os, "getpid", lambda: 2 if bad == "not_pid1" else 1)
    monkeypatch.setattr(guard.os, "getuid", lambda: 997)
    monkeypatch.setattr(guard.os, "geteuid", lambda: 997)
    monkeypatch.setattr(guard.os, "getgid", lambda: 988)
    monkeypatch.setattr(guard.os, "getegid", lambda: 988)
    monkeypatch.setattr(guard.os, "environ", {"UNTRUSTED_SECRET": "fixture"} if bad == "environment" else {})
    status = "NoNewPrivs:\t" + ("0" if bad == "no_new_privileges" else "1") + "\n"
    status += "\n".join(f"{name}:\t{'1' if bad == 'capabilities' and name == 'CapEff' else '0'}"
                        for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
    monkeypatch.setattr(guard, "open", lambda *_a, **_k: io.StringIO(status), raising=False)

    class Libc:
        def prctl(self, operation, *_args):
            return int((bad == "prctl_set" and operation == 4) or (bad == "prctl_get" and operation == 3))

    monkeypatch.setattr(guard.ctypes, "CDLL", lambda *_a, **_k: Libc())
    with pytest.raises(ValueError):
        guard._secure_pid1()


def test_guard_admission_requires_and_verifies_non_dumpable(monkeypatch):
    monkeypatch.setattr(guard, "sys", SimpleNamespace(platform="linux", flags=SimpleNamespace(isolated=1)))
    for name, value in (("getpid", 1), ("getuid", 997), ("geteuid", 997), ("getgid", 988), ("getegid", 988)):
        monkeypatch.setattr(guard.os, name, lambda value=value: value)
    monkeypatch.setattr(guard.os, "environ", {})
    status = "NoNewPrivs:\t1\n" + "\n".join(f"{name}:\t0" for name in
        ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
    monkeypatch.setattr(guard, "open", lambda *_a, **_k: io.StringIO(status), raising=False)
    calls = []

    class Libc:
        def prctl(self, operation, *_args):
            calls.append(operation)
            return 0

    monkeypatch.setattr(guard.ctypes, "CDLL", lambda *_a, **_k: Libc())
    guard._secure_pid1()
    assert calls == [4, 3]
