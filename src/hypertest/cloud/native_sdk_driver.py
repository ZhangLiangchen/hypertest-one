"""Run the official Harness SDK in a dedicated host child process.

This module receives a single prompt from its private stdin and emits only
bounded, non-content observations. It never receives platform credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import select
import sys
import tempfile
import threading
from pathlib import Path

from .native_selection import read_native_selection
from .runtime_activity import project_finish_reason, project_notification


class _PipeInput:
    """Read bounded frames without holding Python's buffered stdin lock."""

    def __init__(self, fd):
        self.fd = fd
        self.buffer = bytearray()

    def readline(self, limit, stopped=None):
        while stopped is None or not stopped.is_set():
            newline = self.buffer.find(b"\n")
            if newline >= 0 or len(self.buffer) >= limit:
                end = min(newline + 1, limit) if newline >= 0 else limit
                line = bytes(self.buffer[:end])
                del self.buffer[:end]
                return line
            if not select.select([self.fd], [], [], 0.1)[0]:
                continue
            chunk = os.read(self.fd, min(65536, limit - len(self.buffer)))
            if not chunk:
                line = bytes(self.buffer)
                self.buffer.clear()
                return line
            self.buffer.extend(chunk)
        return b""


class QuestionChannel:
    """Bounded, private stdin/stdout bridge to the Worker, with no platform credential."""

    def __init__(self, session_id: str, emit, *, source=None):
        self.session_id = session_id
        self.emit = emit
        self.lock = threading.Lock()
        self.pending: dict[str, dict] = {}
        self.closed = False
        self.source = source if source is not None else _PipeInput(sys.stdin.fileno())
        self.stopping = threading.Event()
        self.reader = threading.Thread(target=self._read, name="cloud-question-input")
        self.reader.start()

    def _read(self):
        try:
            while not self.stopping.is_set():
                line = self.source.readline(131073, self.stopping)
                if not line or len(line) > 131072 or not line.endswith(b"\n"):
                    break
                try:
                    frame = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    break
                if (not isinstance(frame, dict) or set(frame) != {"type", "request_id", "answer"}
                        or frame["type"] != "question_response" or not isinstance(frame["request_id"], str)
                        or not isinstance(frame["answer"], dict)):
                    break
                with self.lock:
                    pending = self.pending.get(frame["request_id"])
                    if pending is not None and pending["answer"] is None:
                        pending["answer"] = frame["answer"]
                        pending["ready"].set()
        except (OSError, ValueError):
            pass  # A closed/invalid private pipe cannot deliver another answer.
        finally:
            with self.lock:
                self.closed = True
                for pending in self.pending.values():
                    pending["ready"].set()

    def close(self):
        self.stopping.set()
        self.reader.join(timeout=2)
        if self.reader.is_alive():
            raise RuntimeError("Question input thread did not stop")

    def ask(self, request, cancelled):
        request_id = request.request_id
        questions = request.questions
        if (not isinstance(request_id, str) or not request_id or len(request_id) > 255
                or request.session_id != self.session_id or not isinstance(questions, list)
                or not 1 <= len(questions) <= 16 or not all(isinstance(item, dict) for item in questions)):
            raise ValueError("invalid SDK question")
        # Questions cannot become an alternate path for extending execution authority.
        if any(isinstance(item.get("intent"), dict) and item["intent"].get("kind") == "approval"
               for item in questions):
            return {"cancelled": True}
        frame = {"user_question": {"request_id": request_id, "session_id": request.session_id,
                                   "questions": questions}}
        if len(json.dumps(frame, ensure_ascii=False).encode()) > 131072:
            raise ValueError("SDK question is too large")
        pending = {"ready": threading.Event(), "answer": None}
        with self.lock:
            if self.closed or request_id in self.pending or len(self.pending) >= 8:
                raise ValueError("SDK question channel unavailable")
            self.pending[request_id] = pending
        try:
            self.emit(frame)
            while not pending["ready"].wait(0.2):
                if cancelled.is_set():
                    self.emit({"user_question_cancelled": {"request_id": request_id}})
                    return {"cancelled": True}
            if cancelled.is_set():
                self.emit({"user_question_cancelled": {"request_id": request_id}})
                return {"cancelled": True}
            answer = pending["answer"]
            if answer is None:
                raise ValueError("SDK question channel closed")
            self.emit({"user_question_handed_off": {"request_id": request_id}})
            return answer
        finally:
            with self.lock:
                self.pending.pop(request_id, None)


def _verify_anchored_identity(config: dict, selection: dict | None = None) -> None:
    anchored = config.get("resume_identity")
    if anchored is None:
        return
    from .native_resume_identity import verify_original_identity

    if not isinstance(anchored, dict) or set(anchored) != {"attempt_root", "digest", "original"}:
        raise ValueError("invalid original identity")
    original = dict(anchored["original"])
    if ("environment" in original or not isinstance(original.get("selection"), dict)
            or (selection is not None and original["selection"] != selection)
            or original.get("workspace") != config["workspace"]
            or original.get("dsh_home") != config["dsh_home"]
            or original.get("session_id") != config["session_id"]
            or original.get("prompt_sha256") != hashlib.sha256(config["prompt"].encode()).hexdigest()):
        raise ValueError("original identity mismatch")
    original["environment"] = dict(os.environ)
    verify_original_identity(Path(anchored["attempt_root"]),
                             expected_identity_digest=anchored["digest"], **original)


def run(config: dict, emit, question_channel: QuestionChannel | None = None) -> None:
    from deepseek_harness import HarnessClient, HarnessConfig
    from pydantic import BaseModel

    class WaitResponse(BaseModel):
        pass

    # Validate the receipt-bound profile before even starting SDK configuration
    # resolution, which must never run an unreviewed, drifted profile.
    _verify_anchored_identity(config)
    selection = read_native_selection(dsh_home=config["dsh_home"], cwd=config["workspace"], environment=dict(os.environ))
    finish_reason = None
    count = 0

    def observe(item):
        nonlocal finish_reason, count
        if item.method == "session.event" and item.payload.get("sessionId") == config["session_id"]:
            event = item.payload.get("event")
            if isinstance(event, dict) and event.get("type") == "turn/end":
                data = event.get("data")
                reason = data.get("reason") if isinstance(data, dict) else None
                kind = reason.get("kind") if isinstance(reason, dict) else None
                finish_reason = project_finish_reason(kind)
        observation = project_notification(item, config["session_id"])
        if observation is not None and count < 512:
            count += 1
            emit({"runtime_activity": observation})

    # The SDK normally creates the root Agent inside session/prompt.  Require a
    # freshly registered pre-prompt preset guard before sending that request.
    # The directory and nonce are private to this child invocation; the marker
    # is consumed before the Agent can receive any prompt or use any tools.
    with tempfile.TemporaryDirectory(prefix="hypertest-cordis-") as directory:
        from .native_cordis import prepare_cordis_overlay

        overlay = prepare_cordis_overlay(Path(directory))
        marker = Path(directory) / "ready.json"
        nonce = secrets.token_hex(32)
        options = {"profile": "sdk", "dsh_home": config["dsh_home"], "cwd": config["workspace"],
                   "patches": (str(overlay),),
                   "env": {"DSH_SDK_CORDIS_ROOT": config["session_id"],
                           "DSH_SDK_CORDIS_NONCE": nonce,
                           "DSH_SDK_CORDIS_HANDSHAKE": str(marker)}}
        if question_channel is not None:
            # Unsupported SDK versions fail closed rather than presenting a fake interaction.
            options["on_user_question"] = question_channel.ask
        with HarnessClient(HarnessConfig(**options)) as client:
            info = client.initialize(cwd=config["workspace"], **selection).serverInfo
            if info is None or info.name != "deepseek-harness-sdk-runtime" or info.version != "0.0.1":
                raise ValueError("unexpected SDK protocol")
            _require_cordis_guard(marker, nonce, config["session_id"])
            _verify_anchored_identity(config, selection)
            with client.subscribe_notifications() as subscription:
                client.session_prompt(config["session_id"], [{"type": "text", "text": config["prompt"]}],
                                      on_notification=observe, notification_subscription=subscription)
                client.request("session/wait", {"sessionId": config["session_id"]},
                               response_model=WaitResponse, on_notification=observe,
                               notification_subscription=subscription)
                subscription.drain(observe)
    emit({"runtime_observation": "IDLE", "session_id": config["session_id"],
          "finish_reason": finish_reason})


def _require_cordis_guard(marker: Path, nonce: str, session_id: str) -> None:
    """Reject absent, malformed, stale or unexpected guard registrations."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(marker, flags)
        with os.fdopen(fd, "rb") as stream:
            payload = stream.read(4097)
        if len(payload) > 4096 or json.loads(payload) != {
                "phase": "registered", "nonce": nonce, "root": session_id}:
            raise ValueError("invalid preset guard")
        marker.unlink()
    except (OSError, ValueError, UnicodeError) as error:
        raise ValueError("SDK preset guard unavailable") from error


def main() -> int:
    output_lock = threading.Lock()
    channel = None

    def emit(value):
        with output_lock:
            print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)

    try:
        source = _PipeInput(sys.stdin.fileno())
        raw = source.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("input too large")
        config = json.loads(raw)
        if (not isinstance(config, dict)
                or set(config) - {"workspace", "dsh_home", "session_id", "prompt", "interaction_enabled", "resume_identity"}
                or any(not isinstance(config.get(key), str) or not config[key]
                       for key in ("workspace", "dsh_home", "session_id", "prompt"))
                or type(config.get("interaction_enabled", False)) is not bool):
            raise ValueError("invalid input")
        channel = QuestionChannel(config["session_id"], emit, source=source) if config.get("interaction_enabled", False) else None
        run(config, emit, channel)
        return 0
    except Exception:
        # SDK exceptions can contain arbitrary content or credentials.
        emit({"runtime_observation": "ERROR", "code": "SDK_RUN_FAILED"})
        return 1
    finally:
        if channel is not None:
            channel.close()


if __name__ == "__main__":
    raise SystemExit(main())
