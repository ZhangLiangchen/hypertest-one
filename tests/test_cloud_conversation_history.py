import json

import pytest

from hypertest.cloud.native_conversation_history import public_history


def history(*events, **header):
    return iter(json.dumps(row) for row in [{"type": "session", "version": 4,
        "id": "cloud-test", "cwd": "/fixed/workspace", "delegationDepth": 0, **header}, *events])


def test_root_public_projection_excludes_reasoning_tools_and_records_source_time():
    events = history({"type": "tool/result", "seq": 1, "data": {"text": "private"}},
        {"type": "assistant/message", "seq": 2, "time": 1000, "data": {"message": {"content": [
            {"type": "reasoning", "text": "private"}, {"type": "text", "text": "Blocked by login"}]}}})
    rows = list(public_history(events, session_id="cloud-test", workspace="/fixed/workspace"))
    assert len(rows) == 1 and rows[0]["text"] == "Blocked by login"
    assert rows[0]["observed_at"] == "1970-01-01T00:00:01+00:00"
    assert rows[0]["event_key"] == "history:assistant:2"


@pytest.mark.parametrize("header", [{"delegationDepth": 1}, {"id": "different"}, {"cwd": "/elsewhere"}])
def test_history_requires_exact_root(header):
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        list(public_history(history(**header), session_id="cloud-test", workspace="/fixed/workspace"))
