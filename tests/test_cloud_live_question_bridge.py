"""Synthetic live-question delivery; no SDK, model or SUT is started."""
from types import SimpleNamespace

import pytest

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.live_question_bridge import LiveQuestionBridge
from hypertest.sync_core import digest


class API:
    def __init__(self, question, *, lose_answer=False):
        self.question = question
        self.lose_answer = lose_answer
        self.calls = []

    async def request(self, operation, body):
        self.calls.append(operation)
        if operation == "live-question/open":
            return {"id": "original", "request_id": self.question["request_id"],
                    "session_id": self.question["session_id"],
                    "request_digest": digest({**self.question, "timeout_seconds": 600})}
        if operation == "live-question/poll":
            return {"id": "original", "status": "DELIVERING"} if self.lose_answer else {
                "id": "original", "status": "DELIVERING", "answers": [{"id": "q", "selected": ["Yes"]}], "cancelled": False}
        return {"status": "DELIVERED"}


@pytest.mark.asyncio
async def test_original_question_answer_reaches_callback_once():
    question = {"request_id": "original-request", "session_id": "cloud-original", "questions": [{"id": "q", "question": "Continue?"}]}
    api = API(question)
    broker = SimpleNamespace(api=api, _body=lambda **fields: fields)
    async def current(): return True
    broker.assert_current = current
    received = []
    state = {"cancelled": __import__("asyncio").Event(), "handed_off": __import__("asyncio").Event(), "id": None, "delivering": False}
    async def answer(key, body):
        received.append((key, body))
        state["handed_off"].set()
    bridge = LiveQuestionBridge(broker, SimpleNamespace(answer_question=answer), question["session_id"])
    await bridge._handle(question, state)
    assert received == [("original-request", {"answers": [{"id": "q", "selected": ["Yes"]}]})]
    assert api.calls == ["live-question/open", "live-question/poll", "live-question/finish"]


@pytest.mark.asyncio
async def test_lost_answer_claim_is_not_delivered_or_replayed():
    question = {"request_id": "original-request", "session_id": "cloud-original", "questions": [{"id": "q", "question": "Continue?"}]}
    api = API(question, lose_answer=True)
    broker = SimpleNamespace(api=api, _body=lambda **fields: fields)
    async def answer(*args): pytest.fail("unconfirmed answer must not be delivered")
    bridge = LiveQuestionBridge(broker, SimpleNamespace(answer_question=answer), question["session_id"])
    state = {"cancelled": __import__("asyncio").Event(), "handed_off": __import__("asyncio").Event(), "id": None, "delivering": False}
    with pytest.raises(CloudBlocked, match="reconciliation"):
        await bridge._handle(question, state)
    assert api.calls == ["live-question/open", "live-question/poll"]
