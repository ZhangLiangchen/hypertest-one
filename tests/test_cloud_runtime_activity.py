"""Only live fixed event scalars can leave the SDK boundary; no runtime needed."""
import json
from types import SimpleNamespace

import pytest

from hypertest.cloud.runtime_activity import (
    FINISH_REASONS,
    project_finish_reason,
    project_notification,
    project_runtime_activity,
)


def event(kind, data, **metadata):
    return SimpleNamespace(method="session.event", payload={"sessionId": "root", "event": {"type": kind, "data": data, **metadata}})


def test_live_tool_events_never_copy_arguments_content_reason_or_arbitrary_names():
    call = event("tool/call", {"name": "bash", "arguments": "private-arguments", "callId": "private-id"}, seq=7)
    result = event("tool/result", {"message": {"isError": True, "content": [{"text": "private-output"}]},
        "error": {"code": "SANDBOX_UNAVAILABLE", "name": "private-name", "reason": "private-reason"}, "meta": "private-meta"}, sourceEventSeqs=[7])
    observations = [project_notification(item, "root") for item in (call, result)]
    assert observations == [{"kind": "TOOL_CALL", "tool": "BASH", "sequence": 7},
        {"kind": "TOOL_RESULT", "is_error": True, "error_code": "SANDBOX_UNAVAILABLE", "call_sequence": 7}]
    assert "private" not in json.dumps(observations)
    assert project_notification(event("tool/call", {"name": "private-tool", "arguments": "secret"}), "root")["tool"] == "OTHER"


@pytest.mark.parametrize("kind,data,expected", [
    ("approval/asked", {"toolName": "bash", "reason": "private", "id": "private"}, {"kind": "APPROVAL_ASKED", "tool": "BASH"}),
    ("approval/decided", {"outcome": "unavailable", "id": "private"}, {"kind": "APPROVAL_DECIDED", "outcome": "unavailable"}),
    ("step/start", {"step": 2, "turn": 1}, {"kind": "STEP_START", "step": 2}),
    ("turn/end", {"reason": {"kind": "blocked", "error": "private"}}, {"kind": "TURN_END", "reason": "blocked"}),
])
def test_official_event_shapes_are_projected_to_closed_metadata(kind, data, expected):
    assert project_notification(event(kind, data), "root") == expected


def test_conversation_other_sessions_and_malformed_values_are_not_retained():
    assert project_notification(event("assistant/message", {"message": "private-reasoning"}), "root") is None
    assert project_notification(event("system/message", {"message": "private-prompt"}), "root") is None
    assert project_notification(event("tool/call", {"name": "bash"}), "other") is None
    assert project_runtime_activity({"kind": ["private"]}) == {"kind": "OTHER"}
    assert project_runtime_activity({"kind": "TOOL_RESULT", "is_error": "private", "error_code": ["private"], "call_sequence": True}) == {
        "kind": "TOOL_RESULT", "is_error": None, "error_code": "OTHER", "call_sequence": None}
    assert project_runtime_activity({"kind": "TOOL_CALL", "tool": "private", "sequence": -1, "args": "private"}) == {
        "kind": "TOOL_CALL", "tool": "OTHER", "sequence": None}


@pytest.mark.parametrize("reason", sorted(FINISH_REASONS))
def test_all_official_turn_terminal_reasons_survive_without_changing_their_meaning(reason):
    assert project_finish_reason(reason) == reason
    assert project_notification(event("turn/end", {"reason": {"kind": reason, "message": "private"}}), "root") == {
        "kind": "TURN_END", "reason": reason}


def test_finish_reason_is_scalar_only():
    assert project_finish_reason(None) is None
    assert project_finish_reason({"private": "value"}) == "OTHER"
    assert project_finish_reason("private-reason") == "OTHER"


def test_second_worker_projection_is_idempotent_and_drops_added_fields():
    first = project_notification(event("tool/result", {"message": {"isError": False}}), "root")
    assert project_runtime_activity({**first, "body": "private"}) == first
