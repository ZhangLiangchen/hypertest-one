"""Read only public root messages from one explicitly selected SDK history.

This does not open an SDK runtime or read adjacent sessions. The caller must
validate every projected message with the project's secret scanner before
persisting it; source metadata is an operator assertion, not an old anchor.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from .native_conversation import project_assistant_message


def public_history(lines, *, session_id: str, workspace: str):
    header = json.loads(next(lines))
    if (header.get("type") != "session" or header.get("version") != 4
            or header.get("id") != session_id or header.get("cwd") != workspace
            or header.get("delegationDepth") != 0):
        raise ValueError("NATIVE_HISTORY_ROOT_IDENTITY_MISMATCH")
    seen = set()
    for line in lines:
        event = json.loads(line)
        projected = project_assistant_message(SimpleNamespace(method="session.event",
            payload={"sessionId": session_id, "event": event}), session_id)
        if projected is None:
            continue
        sequence = projected["event_sequence"]
        if sequence in seen:
            raise ValueError("NATIVE_HISTORY_DUPLICATE_SEQUENCE")
        seen.add(sequence)
        when = event.get("time")
        observed = datetime.fromtimestamp(when / 1000, UTC).isoformat() if type(when) is int else None
        yield {"event_key": f"history:assistant:{sequence}", "session_id": session_id,
            "role": "ASSISTANT", "text": projected["text"], "event_seq": sequence,
            "observed_at": observed, "reason_code": {"ACCEPTED": None,
                "REDACTED": "CONTENT_REJECTED", "TOO_LARGE": "MESSAGE_TOO_LARGE"}[projected["content_status"]]}
