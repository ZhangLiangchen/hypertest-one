"""Bridge live SDK questions through the fenced host Worker; never replay answers."""
from __future__ import annotations

import asyncio
import json

from hypertest.sync_core import digest

from .errors import CloudBlocked


class LiveQuestionBridge:
    def __init__(self, broker, adapter, session_id: str, *, conversation=None):
        self.broker, self.adapter, self.session_id = broker, adapter, session_id
        self.calls = {}
        self.tasks = set()
        self.total = 0
        self.conversation = conversation
        self.runtime_state = None
        self.finish_reason = None
        self.prompt_enqueued = None
        self.runtime_ready = asyncio.Event()

    async def read(self, process):
        while line := await process.stdout.readline():
            self.total += len(line)
            if (self.conversation is None and self.total > 4 * 1024 * 1024) or len(line) > 131072 or not line.endswith(b"\n"):
                raise CloudBlocked("SDK_QUESTION_CHANNEL_INVALID", "SDK channel exceeded its bound")
            try:
                frame = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                raise CloudBlocked("SDK_QUESTION_CHANNEL_INVALID", "Invalid SDK channel frame") from None
            if not isinstance(frame, dict):
                raise CloudBlocked("SDK_QUESTION_CHANNEL_INVALID", "Invalid SDK channel frame")
            if "runtime_ready" in frame:
                if frame != {"runtime_ready": {"session_id": self.session_id}} or self.runtime_ready.is_set():
                    raise CloudBlocked("SDK_RUNTIME_READY_INVALID", "Invalid SDK startup observation")
                self.runtime_ready.set()
            elif "runtime_observation" in frame:
                if frame["runtime_observation"] in {"RUNNING", "IDLE"} and frame.get("session_id") == self.session_id:
                    self.runtime_state = frame["runtime_observation"]
                    from .runtime_activity import project_finish_reason
                    self.finish_reason = project_finish_reason(frame.get("finish_reason"))
                if self.conversation is not None:
                    await self.conversation.accept_frame(frame)
            elif "runtime_activity" in frame:
                if self.conversation is not None:
                    await self.conversation.accept_frame(frame)
            elif "assistant_message" in frame or "user_message_ack" in frame:
                if self.conversation is not None:
                    await self.conversation.accept_frame(frame)
            elif "prompt_enqueued" in frame:
                value = frame["prompt_enqueued"]
                if (not isinstance(value, dict) or value.get("session_id") != self.session_id
                        or not isinstance(value.get("message_id"), str) or not 1 <= len(value["message_id"]) <= 255
                        or type(value.get("continuation")) is not bool):
                    raise CloudBlocked("SDK_PROMPT_RECEIPT_INVALID", "Invalid original SDK enqueue receipt")
                if self.prompt_enqueued is not None and self.prompt_enqueued != value:
                    raise CloudBlocked("SDK_PROMPT_RECEIPT_INVALID", "Original SDK enqueue receipt changed")
                self.prompt_enqueued = value
                if self.conversation is not None:
                    await self.conversation.accept_frame(frame)
            elif "user_question" in frame:
                value = frame["user_question"]
                if (set(frame) != {"user_question"} or not isinstance(value, dict)
                    or set(value) != {"request_id", "session_id", "questions"}
                    or value["session_id"] != self.session_id
                    or not isinstance(value["request_id"], str) or not 1 <= len(value["request_id"]) <= 255
                    or not isinstance(value["questions"], list) or not 1 <= len(value["questions"]) <= 16
                    or value["request_id"] in self.calls or len(self.tasks) >= 8):
                    raise CloudBlocked("SDK_QUESTION_CHANNEL_INVALID", "Invalid original SDK question")
                state = {"cancelled": asyncio.Event(), "handed_off": asyncio.Event(), "id": None, "delivering": False}
                self.calls[value["request_id"]] = state
                task = asyncio.create_task(self._handle(value, state))
                self.tasks.add(task)
            elif "user_question_cancelled" in frame or "user_question_handed_off" in frame:
                key = "user_question_cancelled" if "user_question_cancelled" in frame else "user_question_handed_off"
                value = frame[key]
                if (set(frame) != {key} or not isinstance(value, dict) or set(value) != {"request_id"}
                    or value["request_id"] not in self.calls):
                    raise CloudBlocked("SDK_QUESTION_CHANNEL_INVALID", "Unknown original SDK question")
                self.calls[value["request_id"]]["cancelled" if key.endswith("cancelled") else "handed_off"].set()
            self.check()

    def check(self):
        if self.conversation is not None:
            self.conversation.check()
        for task in tuple(self.tasks):
            if task.done():
                self.tasks.remove(task)
                task.result()

    async def _finish(self, state, outcome):
        if state["id"] is not None:
            await self.broker.api.request("live-question/finish", self.broker._body(question_id=state["id"], outcome=outcome))

    async def _handle(self, question, state):
        request_id = question["request_id"]
        original = self.broker._body(**question, timeout_seconds=600)
        try:
            try:
                opened = await self.broker.api.request("live-question/open", original)
            except Exception:
                # Read the original identity only; never resend an uncertain creation.
                opened = await self.broker.api.request("live-question/lookup", self.broker._body(
                    request_id=request_id, session_id=self.session_id))
            expected = digest({**question, "timeout_seconds": 600})
            if (opened.get("request_id") != request_id or opened.get("session_id") != self.session_id
                    or opened.get("request_digest") != expected or not isinstance(opened.get("id"), str)):
                raise CloudBlocked("SDK_QUESTION_IDENTITY_MISMATCH", "Original question readback does not match")
            state["id"] = opened["id"]
            while True:
                if state["cancelled"].is_set():
                    await self._finish(state, "CANCELLED")
                    return
                item = await self.broker.api.request("live-question/poll", self.broker._body(question_id=state["id"]))
                status = item.get("status")
                if status == "OPEN":
                    await asyncio.sleep(1)
                    continue
                if status in {"CANCELLED", "UNKNOWN", "EXPIRED"}:
                    return
                if status != "DELIVERING" or not ({"answers", "cancelled"} <= item.keys()):
                    raise CloudBlocked("SDK_QUESTION_DELIVERY_UNKNOWN", "Original answer cannot be safely replayed")
                state["delivering"] = True
                if state["cancelled"].is_set():
                    await self._finish(state, "UNKNOWN")
                    return
                await self.broker.assert_current()
                await self.adapter.answer_question(request_id, {"cancelled": True} if item["cancelled"] else {"answers": item["answers"]})
                try:
                    await asyncio.wait_for(state["handed_off"].wait(), 5)
                except TimeoutError:
                    await self._finish(state, "UNKNOWN")
                    raise CloudBlocked("SDK_QUESTION_DELIVERY_UNKNOWN", "Original SDK response is unconfirmed") from None
                if state["cancelled"].is_set():
                    await self._finish(state, "UNKNOWN")
                    return
                await self._finish(state, "DELIVERED")
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            # No retry after a claim or pipe write. Fence the original execution.
            raise CloudBlocked("SDK_QUESTION_DELIVERY_UNKNOWN", "Original question requires reconciliation") from None

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
