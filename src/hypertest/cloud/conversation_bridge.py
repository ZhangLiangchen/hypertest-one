"""Durable public conversation observations and single-delivery SDK inputs."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from hypertest.sync_core import digest

from .errors import CloudBlocked
from .native_conversation import MAX_MESSAGE_BYTES, visible_text
from .runtime_activity import project_finish_reason

_DESCRIPTOR_PROFILE = "hypertest-conversation-spool/v1"


def _checked_descriptor(value, worker_id):
    fields = {"profile", "project_id", "task_id", "attempt_id", "worker_id", "generation", "session_id"}
    try:
        if (not isinstance(value, dict) or set(value) != fields or value["profile"] != _DESCRIPTOR_PROFILE
                or value["worker_id"] != worker_id or not isinstance(worker_id, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", worker_id) is None
                or type(value["generation"]) is not int or value["generation"] < 1
                or any(str(UUID(value[field])) != value[field] for field in ("project_id", "task_id", "attempt_id"))
                or value["session_id"] != "cloud-" + value["attempt_id"]):
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise CloudBlocked("CONVERSATION_SPOOL_INVALID", "Original conversation identity is unavailable") from None
    return value


class ConversationBridge:
    """Only admitted visible text reaches the private spool.

    Append and acknowledgement retries repeat immutable observations; a user
    message's pipe delivery is attempted once. SDK/model operations are never
    recovered by this class.
    """

    def __init__(self, broker, adapter, session_id: str, *, private_root: Path):
        self.broker, self.adapter, self.session_id = broker, adapter, session_id
        self.generation = broker.identity.generation
        root = Path(private_root)
        root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
            raise CloudBlocked("CONVERSATION_SPOOL_INVALID", "Conversation spool must be private")
        path = root / "conversation.sqlite3"
        if path.is_symlink():
            raise CloudBlocked("CONVERSATION_SPOOL_INVALID", "Conversation spool must be private")
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.execute("CREATE TABLE IF NOT EXISTS observations (event_key TEXT PRIMARY KEY, payload TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0)")
        self.db.execute("CREATE TABLE IF NOT EXISTS inputs (message_id TEXT PRIMARY KEY, status TEXT NOT NULL, sdk_message_id TEXT, confirmed INTEGER NOT NULL DEFAULT 0)")
        self.db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        descriptor = _checked_descriptor({"profile": _DESCRIPTOR_PROFILE, "project_id": broker.project_id,
            "task_id": broker.task_id, "attempt_id": broker.attempt_id, "worker_id": broker.identity.worker_id,
            "generation": self.generation, "session_id": session_id}, broker.identity.worker_id)
        encoded = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
        previous = self.db.execute("SELECT payload FROM metadata WHERE key='descriptor'").fetchone()
        if previous is not None and previous[0] != encoded:
            self.db.close()
            raise CloudBlocked("CONVERSATION_SPOOL_INVALID", "Original conversation identity changed")
        self.db.execute("INSERT OR IGNORE INTO metadata(key,payload) VALUES('descriptor',?)", (encoded,))
        self.db.commit()
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=128)
        self.accepting = True
        self.stopping = asyncio.Event()
        self.idle = asyncio.Event()
        self.session_ready = asyncio.Event()
        self.runtime_state = None
        self.finish_reason = None
        self._state_serial = 0
        self._tasks: list[asyncio.Task] = []
        self._acks: dict[str, asyncio.Future] = {}
        self._feedback_receipts = {}
        self._failure: BaseException | None = None

    def _key(self, kind, sequence):
        return "conversation:" + digest([self.session_id, self.generation, kind, sequence])

    async def _request(self, operation, **fields):
        return await self.broker.api.request("conversation/" + operation, self.broker._body(**fields))

    def _matching_identity(self, response):
        return isinstance(response, dict) and all(response.get(key) == value for key, value in {
            "project_id": self.broker.project_id, "task_id": self.broker.task_id,
            "attempt_id": self.broker.attempt_id, "generation": self.generation,
            "session_id": self.session_id}.items())

    def _save(self, payload):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        previous = self.db.execute("SELECT payload FROM observations WHERE event_key=?", (payload["event_key"],)).fetchone()
        if previous is not None and previous[0] != encoded:
            raise CloudBlocked("CONVERSATION_EVENT_CHANGED", "An original conversation event changed")
        self.db.execute("INSERT OR IGNORE INTO observations(event_key,payload) VALUES(?,?)", (payload["event_key"], encoded))
        self.db.commit()

    async def accept_frame(self, frame: dict):
        if "session_ready" in frame:
            if frame != {"session_ready": {"session_id": self.session_id}} or self.session_ready.is_set():
                raise CloudBlocked("CONVERSATION_FRAME_INVALID", "Invalid SDK session readiness")
            self.session_ready.set()
        elif "assistant_message" in frame:
            item = frame["assistant_message"]
            if (not isinstance(item, dict) or item.get("session_id") != self.session_id
                    or type(item.get("event_sequence")) is not int or item["event_sequence"] < 0
                    or not isinstance(item.get("text"), str)
                    or len(item["text"].encode()) > MAX_MESSAGE_BYTES
                    or item.get("content_status") not in {"ACCEPTED", "REDACTED", "TOO_LARGE"}):
                raise CloudBlocked("CONVERSATION_FRAME_INVALID", "Invalid public SDK message")
            text, local_status = visible_text(item["text"])
            payload = {"event_key": self._key("assistant", item["event_sequence"]), "session_id": self.session_id,
                       "role": "ASSISTANT", "event_seq": item["event_sequence"], "text": text}
            if item["content_status"] != "ACCEPTED" or local_status != "ACCEPTED":
                payload.update(text="", reason_code="CONTENT_REJECTED")
            # A bounded memory queue applies backpressure while secret admission
            # is unavailable. Unvalidated text is never written to SQLite.
            await self.queue.put(payload)
        elif "runtime_observation" in frame:
            state = frame["runtime_observation"]
            if state in {"RUNNING", "IDLE"} and frame.get("session_id") == self.session_id:
                self.runtime_state = state
                self.finish_reason = project_finish_reason(frame.get("finish_reason"))
                if state == "IDLE":
                    self.idle.set()
                else:
                    self.idle.clear()
                self._state_serial += 1
                reason = {"completed": "TURN_COMPLETED", "blocked": "TURN_BLOCKED", "aborted": "TURN_ABORTED",
                          "interrupted": "TURN_ABORTED", "error": "TURN_ERROR"}.get(self.finish_reason)
                payload = {"event_key": self._key("state", self._state_serial), "session_id": self.session_id,
                           "role": "SYSTEM", "text": "", "state": "AWAITING_REPLY" if state == "IDLE" else "RUNNING"}
                if state == "IDLE" and reason:
                    payload["reason_code"] = reason
                await self.queue.put(payload)
            elif state == "ERROR":
                code = frame.get("code")
                await self.record_state("INTERRUPTED", code if code in {"SDK_SESSION_BUSY", "SDK_SESSION_UNAVAILABLE"} else "SDK_RUN_FAILED")
        elif "user_message_ack" in frame:
            item = frame["user_message_ack"]
            if (not isinstance(item, dict) or item.get("status") not in {"DELIVERED", "UNKNOWN"}
                    or not isinstance(item.get("request_id"), str)
                    or (item["status"] == "DELIVERED" and (not isinstance(item.get("message_id"), str)
                        or not 1 <= len(item["message_id"]) <= 255))):
                raise CloudBlocked("CONVERSATION_FRAME_INVALID", "Invalid SDK delivery receipt")
            future = self._acks.get(item["request_id"])
            callback = self._feedback_receipts.get(item["request_id"])
            if callback is not None:
                callback(item)
            if future is None:
                if callback is not None:
                    return
                raise CloudBlocked("CONVERSATION_FRAME_INVALID", "SDK receipt has no original delivery")
            if not future.done():
                future.set_result(item)
        elif "prompt_enqueued" in frame:
            item = frame["prompt_enqueued"]
            key = "prompt:" + str(self.generation)
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":"))
            existing = self.db.execute("SELECT payload FROM metadata WHERE key=?", (key,)).fetchone()
            if existing is not None and existing[0] != encoded:
                raise CloudBlocked("SDK_PROMPT_RECEIPT_INVALID", "SDK enqueue receipt changed")
            self.db.execute("INSERT OR IGNORE INTO metadata(key,payload) VALUES(?,?)", (key, encoded))
            self.db.commit()

    async def record_state(self, state: str, reason_code: str | None = None):
        self._state_serial += 1
        payload = {"event_key": self._key("state", self._state_serial), "session_id": self.session_id,
                   "role": "SYSTEM", "text": "", "state": state}
        if reason_code:
            payload["reason_code"] = reason_code
        await self.queue.put(payload)

    async def record_rejection(self, observation: dict):
        if (not isinstance(observation, dict) or set(observation) != {"key_sha256", "reason_code"}
                or not isinstance(observation["key_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", observation["key_sha256"]) is None
                or observation["reason_code"] not in {"ARTIFACT_REJECTED", "ARTIFACT_CONTENT_REJECTED"}):
            raise CloudBlocked("CONVERSATION_FRAME_INVALID", "Invalid fixed artifact admission notice")
        # This fixed, content-free observation needs no secret admission and
        # survives an already failed publisher or a full text-admission queue.
        self._save({"event_key": self._key("artifact_rejection", observation["key_sha256"]),
            "session_id": self.session_id, "role": "SYSTEM", "text": "", "reason_code": observation["reason_code"]})

    async def send_archive_feedback(self, reporter, workspace: Path, *, timeout: float = 30):
        """Wake even an idle Harness for a definite local archive rejection.

        The Attempt journal owns single delivery across Worker generations.
        Unknown delivery is retained; it never becomes a reason to stop chat.
        """
        if not self.session_ready.is_set() or not self.accepting:
            return
        for observation in reporter.pending_feedback():
            key = observation["key_sha256"]
            await self.broker.assert_current()
            if not reporter.start_feedback(key):
                continue
            request_id = "archive-feedback:" + key
            future = asyncio.get_running_loop().create_future()
            self._acks[request_id] = future
            self._feedback_receipts[request_id] = lambda receipt, key=key: reporter.finish_feedback(key, receipt)
            path = workspace / ".hypertest-cloud" / "rejections" / (key + ".json")
            text = ("HyperTest archive feedback: a contribution was rejected before submission. "
                f"Read the fixed validation feedback at {path}. "
                "Correct only that contribution and publish a new handoff key; preserve the rejected file. "
                "Do not repeat tests or external operations. Do not include secrets in the correction. "
                "This archive rejection does not end the conversation.")
            try:
                async with asyncio.timeout(timeout):
                    await self.adapter.send_message(request_id, text)
                    await asyncio.shield(future)
            except asyncio.CancelledError:
                reporter.finish_feedback(key, {"status": "UNKNOWN"})
                raise
            except Exception:
                reporter.finish_feedback(key, {"status": "UNKNOWN"})
            finally:
                # A late ACK is still accepted through its original callback.
                self._acks.pop(request_id, None)

    async def _validate(self, payload):
        if not payload["text"]:
            return payload
        response = await self._request("validate", text=payload["text"])
        if not isinstance(response, dict) or type(response.get("accepted")) is not bool:
            raise CloudBlocked("CONVERSATION_ADMISSION_UNKNOWN", "Public text admission is unconfirmed")
        return payload if response["accepted"] else {**payload, "text": "", "reason_code": "CONTENT_REJECTED"}

    async def _publish_saved(self):
        for key, encoded in self.db.execute("SELECT event_key,payload FROM observations WHERE accepted=0 ORDER BY rowid").fetchall():
            payload = json.loads(encoded)
            response = await self._request("append", **payload)
            expected = {"text": "", "event_seq": None, "state": None, "reason_code": None,
                        "observed_at": None, **payload}
            if (not self._matching_identity(response) or response.get("event_key") != key
                    or response.get("role") != payload["role"]
                    or response.get("request_digest") != digest(expected)):
                raise CloudBlocked("CONVERSATION_READBACK_MISMATCH", "Public message acceptance is unconfirmed")
            if response.get("status") == "REJECTED":
                payload = {**payload, "text": "", "reason_code": "CONTENT_REJECTED"}
                self.db.execute("UPDATE observations SET payload=? WHERE event_key=?",
                                (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), key))
            elif response.get("text") != payload["text"]:
                raise CloudBlocked("CONVERSATION_READBACK_MISMATCH", "Public message content is unconfirmed")
            self.db.execute("UPDATE observations SET accepted=1 WHERE event_key=?", (key,))
            self.db.commit()

    async def _publish(self):
        current = None
        failures = 0
        try:
            while not self.stopping.is_set() or current is not None or not self.queue.empty():
                try:
                    await self._publish_saved()
                    if current is None:
                        try:
                            current = await asyncio.wait_for(self.queue.get(), 0.2)
                        except TimeoutError:
                            continue
                    admitted = await self._validate(current)
                    self._save(admitted)
                    await self._publish_saved()
                    self.queue.task_done()
                    current = None
                    failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if isinstance(error, CloudBlocked) and error.code != "WORKER_API_UNCONFIRMED":
                        raise
                    # An API outage blocks only this bounded conversation queue.
                    # No exception body, rejected text, or credentials are logged.
                    failures += 1
                    await asyncio.sleep(min(0.25 * 2 ** min(failures, 5), 5))
        finally:
            if current is not None:
                # Covers cancellation during either API I/O or backoff.
                if self.db.execute("SELECT 1 FROM observations WHERE event_key=?", (current["event_key"],)).fetchone() is None:
                    self._save({**current, "text": "", "reason_code": "CONVERSATION_GAP"})
                self.queue.task_done()

    async def _confirm_saved(self):
        for message_id, status, sdk_id in self.db.execute(
                "SELECT message_id,status,sdk_message_id FROM inputs WHERE confirmed=0 AND status IN ('DELIVERED','UNKNOWN')").fetchall():
            fields = {"session_id": self.session_id, "message_id": message_id, "status": status}
            if sdk_id is not None:
                fields["sdk_message_id"] = sdk_id
            response = await self._request("ack", **fields)
            if (not self._matching_identity(response) or response.get("id") != message_id
                    or response.get("status") != status or response.get("sdk_message_id") != sdk_id):
                raise CloudBlocked("SDK_MESSAGE_DELIVERY_UNKNOWN", "Original SDK acknowledgement is unconfirmed")
            self.db.execute("UPDATE inputs SET confirmed=1 WHERE message_id=?", (message_id,))
            self.db.commit()

    async def _poll(self):
        await self.session_ready.wait()
        while self.accepting and not self.stopping.is_set():
            try:
                await self._confirm_saved()
                response = await self._request("poll", session_id=self.session_id)
                item = response.get("message") if isinstance(response, dict) else None
                if item is None:
                    pending = response.get("pending_message_id") if isinstance(response, dict) else None
                    if isinstance(pending, str) and pending not in self._acks:
                        self.db.execute("INSERT OR IGNORE INTO inputs(message_id,status) VALUES(?, 'UNKNOWN')", (pending,))
                        self.db.commit()
                    await asyncio.sleep(0.5)
                    continue
                message_id, text = item.get("id"), item.get("text")
                request_generation = item.get("request_generation", self.generation)
                expected = {"project_id": self.broker.project_id, "task_id": self.broker.task_id,
                            "attempt_id": self.broker.attempt_id, "text": text}
                if (not self._matching_identity(item) or item.get("role") != "USER" or item.get("status") != "DELIVERING"
                        or not isinstance(message_id, str) or not isinstance(text, str) or not text.strip() or len(text) > 16384
                        or type(request_generation) is not int or request_generation < 1
                        or item.get("request_digest") not in {digest(expected), digest({**expected, "generation": request_generation})}):
                    raise CloudBlocked("CONVERSATION_INPUT_INVALID", "Invalid original user message")
                old = self.db.execute("SELECT status FROM inputs WHERE message_id=?", (message_id,)).fetchone()
                if old is not None:
                    raise CloudBlocked("SDK_MESSAGE_QUERY_ONLY", "An original user message cannot be resent")
                future = asyncio.get_running_loop().create_future()
                self._acks[message_id] = future
                self.db.execute("INSERT INTO inputs(message_id,status) VALUES(?, 'DELIVERING')", (message_id,))
                self.db.commit()
                try:
                    await self.broker.assert_current()
                    await self.adapter.send_message(message_id, text)
                    receipt = await future
                    status, sdk_id = receipt["status"], receipt.get("message_id")
                except asyncio.CancelledError:
                    self.db.execute("UPDATE inputs SET status='UNKNOWN' WHERE message_id=?", (message_id,))
                    self.db.commit()
                    raise
                except Exception:
                    status, sdk_id = "UNKNOWN", None
                finally:
                    self._acks.pop(message_id, None)
                self.db.execute("UPDATE inputs SET status=?,sdk_message_id=? WHERE message_id=?", (status, sdk_id, message_id))
                self.db.commit()
                await self._confirm_saved()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if isinstance(error, CloudBlocked) and error.code != "WORKER_API_UNCONFIRMED":
                    raise
                await asyncio.sleep(0.5)

    async def run(self):
        self._tasks = [asyncio.create_task(self._publish()), asyncio.create_task(self._poll())]
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._failure = error
            raise
        finally:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def check(self):
        if self._failure is not None:
            raise self._failure

    def stop_accepting(self):
        self.accepting = False

    async def flush(self, timeout: float = 5):
        await asyncio.wait_for(self.queue.join(), timeout)
        await asyncio.wait_for(self._publish_saved(), timeout)
        await asyncio.wait_for(self._confirm_saved(), timeout)

    async def close(self):
        self.accepting = False
        self.stopping.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        # Drop only unadmitted in-memory text, retaining a content-free gap.
        while not self.queue.empty():
            payload = self.queue.get_nowait()
            if self.db.execute("SELECT 1 FROM observations WHERE event_key=?", (payload["event_key"],)).fetchone() is None:
                self._save({**payload, "text": "", "reason_code": "CONVERSATION_GAP"})
            self.queue.task_done()
        self.db.close()


async def recover_conversation_spool(api, root: Path, worker_id: str) -> bool:
    """Recover only immutable observations under the host's historical authority.

    No execution credential, model input, or SDK is recreated. The caller must
    select a spool from before this supervisor startup, never an active writer.
    """
    root = Path(root).absolute()
    db = None
    try:
        if root.resolve(strict=True) != root:
            raise ValueError
        for directory in (root, root.parent, root.parent.parent):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError
        path = root / "conversation.sqlite3"
        for candidate in (path, *(Path(str(path) + suffix) for suffix in ("-journal", "-wal", "-shm"))):
            if candidate == path or candidate.exists() or candidate.is_symlink():
                info = candidate.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_nlink != 1):
                    raise ValueError
        db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)
        row = db.execute("SELECT payload FROM metadata WHERE key='descriptor'").fetchone()
        descriptor = _checked_descriptor(json.loads(row[0]) if row is not None else None, worker_id)
        if (root.name != "generation-" + str(descriptor["generation"]) or root.parent.name != "conversation"
                or root.parent.parent.name != "attempt-" + descriptor["attempt_id"]):
            raise ValueError
        for key, encoded in db.execute("SELECT event_key,payload FROM observations WHERE accepted=0"):
            payload = json.loads(encoded)
            if (not isinstance(payload, dict) or set(payload) - {"event_key", "session_id", "role", "text", "event_seq", "state", "reason_code", "observed_at"}
                    or payload.get("event_key") != key or not isinstance(key, str)
                    or re.fullmatch(r"conversation:[0-9a-f]{64}", key) is None
                    or payload.get("session_id") != descriptor["session_id"]
                    or payload.get("role") not in {"ASSISTANT", "SYSTEM"}
                    or not isinstance(payload.get("text"), str) or len(payload["text"].encode()) > MAX_MESSAGE_BYTES):
                raise ValueError
        for message_id, status, sdk_id in db.execute("SELECT message_id,status,sdk_message_id FROM inputs WHERE confirmed=0"):
            if (not isinstance(message_id, str) or not 1 <= len(message_id) <= 255
                    or status not in {"DELIVERING", "DELIVERED", "UNKNOWN"}
                    or (status == "DELIVERED" and (not isinstance(sdk_id, str) or not 1 <= len(sdk_id) <= 255))
                    or (status != "DELIVERED" and sdk_id is not None)):
                raise ValueError
    except Exception:
        if db is not None:
            db.close()
        raise CloudBlocked("CONVERSATION_SPOOL_INVALID", "Original conversation spool cannot be recovered") from None

    class ObservationAPI:
        async def request(self, operation, body):
            if operation not in {"conversation/append", "conversation/ack"}:
                raise CloudBlocked("CONVERSATION_RECOVERY_OBSERVATION_ONLY", "Recovery cannot deliver model input")
            target = {key: descriptor[key] for key in ("project_id", "task_id", "attempt_id", "worker_id", "generation")}
            return await api.request(operation.replace("conversation/", "conversation/recover-"), {**target, **body})

    # Deliberately bypass the live constructor and never start run/_poll.
    bridge = object.__new__(ConversationBridge)
    bridge.db, bridge.generation, bridge.session_id = db, descriptor["generation"], descriptor["session_id"]
    bridge.broker = SimpleNamespace(api=ObservationAPI(), _body=lambda **fields: fields,
        **{key: descriptor[key] for key in ("project_id", "task_id", "attempt_id")})
    try:
        db.execute("UPDATE inputs SET status='UNKNOWN' WHERE status='DELIVERING' AND confirmed=0")
        db.commit()
        try:
            await asyncio.wait_for(bridge._publish_saved(), 5)
            await asyncio.wait_for(bridge._confirm_saved(), 5)
        except Exception as error:
            if isinstance(error, CloudBlocked) and error.code != "WORKER_API_UNCONFIRMED":
                raise
            return True
        return bool(db.execute("SELECT 1 FROM observations WHERE accepted=0 LIMIT 1").fetchone()
                    or db.execute("SELECT 1 FROM inputs WHERE confirmed=0 LIMIT 1").fetchone())
    finally:
        db.close()
