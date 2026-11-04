"""Run the official Harness SDK in a dedicated host child process.

This module owns one SDK runtime. Its single stdin reader routes questions,
new user messages and close requests; stdout contains projected public text
and bounded observations. It never receives platform credentials.
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import select
import sys
import tempfile
import threading
from pathlib import Path

from .native_conversation import project_assistant_message
from .native_selection import read_native_selection
from .runtime_activity import project_finish_reason, project_notification


def restored_session_hook(source: str) -> str:
    """Leave a restored Harness session's preset, title and inbox untouched."""
    original = '    if (agent.id !== root) return;\n'
    if source.count(original) != 1:
        raise ValueError("unexpected admission hook")
    return source.replace(original, original + "    return; // restored state belongs to Harness\n")


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
        self.commands: queue.Queue[dict] = queue.Queue(maxsize=128)
        self.message_ids: set[str] = set()
        self.closing = threading.Event()
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
                if not isinstance(frame, dict):
                    break
                if frame == {"type": "close"}:
                    self.closing.set()
                    self.commands.put_nowait(frame)
                    continue
                if frame.get("type") == "user_message":
                    request_id, text = frame.get("request_id"), frame.get("text")
                    if (set(frame) != {"type", "request_id", "text"}
                            or not isinstance(request_id, str) or not 1 <= len(request_id) <= 255
                            or not isinstance(text, str) or not text.strip() or len(text) > 16384
                            or request_id in self.message_ids or len(self.message_ids) >= 10000
                            or self.closing.is_set()):
                        break
                    self.message_ids.add(request_id)
                    self.commands.put_nowait(frame)
                    continue
                if (set(frame) != {"type", "request_id", "answer"}
                        or frame["type"] != "question_response" or not isinstance(frame["request_id"], str)
                        or not isinstance(frame["answer"], dict)):
                    break
                with self.lock:
                    pending = self.pending.get(frame["request_id"])
                    if pending is not None and pending["answer"] is None:
                        pending["answer"] = frame["answer"]
                        pending["ready"].set()
        except (OSError, ValueError, queue.Full):
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
        # Harness owns the question's meaning, including native approval intent.
        # Carry the original question and answer without granting platform rights.
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


def run(config: dict, emit, question_channel: QuestionChannel | None = None) -> None:
    from deepseek_harness import HarnessClient, HarnessConfig
    from pydantic import BaseModel

    class WaitResponse(BaseModel):
        pass

    from .native_framework_project import session_working_directory

    session_cwd = str(session_working_directory(Path(config["workspace"])))
    selection = read_native_selection(dsh_home=config["dsh_home"], cwd=session_cwd, environment=dict(os.environ))
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
        message = project_assistant_message(item, config["session_id"])
        if message is not None:
            emit({"assistant_message": message})
        if (item.method == "session.status" and isinstance(item.payload, dict)
                and item.payload.get("sessionId") == config["session_id"]
                and item.payload.get("status") in {"idle", "running"}):
            emit({"runtime_observation": "IDLE" if item.payload["status"] == "idle" else "RUNNING",
                  "session_id": config["session_id"], "finish_reason": finish_reason})

    # The SDK normally creates the root Agent inside session/prompt.  Require a
    # freshly registered pre-prompt preset guard before sending that request.
    # The directory and nonce are private to this child invocation; the marker
    # is consumed before the Agent can receive any prompt or use any tools.
    with tempfile.TemporaryDirectory(prefix="hypertest-cordis-") as directory:
        from .native_cordis import prepare_cordis_overlay

        overlay = prepare_cordis_overlay(Path(directory), title=config["title"])
        if config.get("resume", False):
            # Restoring a session retains its persisted preset and title. The
            # guard still authenticates this child invocation before any input.
            from .native_cordis import _HOOK
            hook = Path(directory) / "hypertest-cordis-root.mjs"
            if hook.read_text(encoding="utf-8") != _HOOK:
                raise ValueError("unexpected admission hook")
            hook.write_text(restored_session_hook(_HOOK), encoding="utf-8")
        marker = Path(directory) / "ready.json"
        nonce = secrets.token_hex(32)
        options = {"profile": "sdk", "dsh_home": config["dsh_home"], "cwd": session_cwd,
                   "patches": (str(overlay),),
                   "env": {"DSH_SDK_CORDIS_ROOT": config["session_id"],
                           "DSH_SDK_CORDIS_NONCE": nonce,
                           "DSH_SDK_CORDIS_HANDSHAKE": str(marker)}}
        if question_channel is not None:
            # Unsupported SDK versions fail closed rather than presenting a fake interaction.
            options["on_user_question"] = question_channel.ask
        with HarnessClient(HarnessConfig(**options)) as client:
            info = client.initialize(cwd=session_cwd, **selection).serverInfo
            if info is None or info.name != "deepseek-harness-sdk-runtime" or info.version != "0.0.1":
                raise ValueError("unexpected SDK protocol")
            _require_cordis_guard(marker, nonce, config["session_id"])
            emit({"runtime_ready": {"session_id": config["session_id"]}})
            with client.subscribe_notifications() as subscription:
                if config.get("resume", False):
                    client.resume_session(config["session_id"])
                    restored = Path(client.get_working_directory(config["session_id"]))
                    # The native session may use a worktree selected by the Agent.
                    # Its transport directory is not an execution sandbox.
                    if not restored.is_absolute() or not restored.is_dir():
                        raise ValueError("restored session directory unavailable")
                else:
                    initial_id = client.session_prompt(config["session_id"], [{"type": "text", "text": config["prompt"]}],
                        on_notification=observe, notification_subscription=subscription)
                    if not isinstance(initial_id, str) or not initial_id:
                        raise ValueError("SDK enqueue receipt missing")
                    emit({"prompt_enqueued": {"session_id": config["session_id"], "message_id": initial_id,
                          "continuation": False}})
                emit({"session_ready": {"session_id": config["session_id"]}})
                if config.get("keep_alive", False):
                    if question_channel is None:
                        raise ValueError("persistent SDK requires a command channel")
                    while True:
                        subscription.drain(observe)
                        try:
                            command = question_channel.commands.get(timeout=0.1)
                        except queue.Empty:
                            if question_channel.closed:
                                raise ValueError("Worker command channel closed") from None
                            continue
                        if command["type"] == "close":
                            break
                        request_id = command["request_id"]
                        try:
                            message_id = client.session_prompt(config["session_id"],
                                [{"type": "text", "text": command["text"]}],
                                on_notification=observe, notification_subscription=subscription)
                            if not isinstance(message_id, str) or not 1 <= len(message_id) <= 255:
                                raise ValueError("SDK enqueue receipt missing")
                        except Exception:
                            emit({"user_message_ack": {"request_id": request_id, "status": "UNKNOWN"}})
                            raise
                        emit({"user_message_ack": {"request_id": request_id, "status": "DELIVERED", "message_id": message_id}})
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
                or set(config) - {"workspace", "dsh_home", "session_id", "title", "prompt", "interaction_enabled", "keep_alive", "resume"}
                or any(not isinstance(config.get(key), str) or not config[key]
                       for key in ("workspace", "dsh_home", "session_id", "title"))
                or not config["title"].strip() or len(config["title"]) > 512
                or any(type(config.get(key, False)) is not bool for key in ("interaction_enabled", "keep_alive", "resume"))
                or (config.get("resume", False) and config.get("prompt") is not None)
                or (not config.get("resume", False) and (not isinstance(config.get("prompt"), str) or not config["prompt"]))):
            raise ValueError("invalid input")
        channel = QuestionChannel(config["session_id"], emit, source=source) if config.get("interaction_enabled", False) or config.get("keep_alive", False) else None
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
