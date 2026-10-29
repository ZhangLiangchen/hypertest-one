"""PID-1 guard contracts; no model, Docker daemon, or SUT calls."""
from __future__ import annotations

import io
import json
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
