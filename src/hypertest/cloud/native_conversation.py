"""Project public SDK messages; never persist reasoning or raw runtime events."""
from __future__ import annotations

import base64
import os
import re

MAX_MESSAGE_BYTES = 65536
_SECRET = re.compile(r"(?:gh[pousr]_|glpat-)[A-Za-z0-9_-]{16,}|-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
_SECRET_ENV = frozenset({"DEEPSEEK_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN", "GLAB_TOKEN"})


def visible_text(text: str, *, environment: dict | None = None) -> tuple[str, str]:
    """Reject a complete message before it reaches a durable private spool.

    The server additionally checks project credentials. Neither side publishes
    a partial secret-bearing message or an exception containing its contents.
    """
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return "", "TOO_LARGE"
    if _SECRET.search(text):
        return "", "REDACTED"
    source = os.environ if environment is None else environment
    for key in _SECRET_ENV:
        value = source.get(key)
        if isinstance(value, str) and value and (
                value in text or base64.b64encode(value.encode()).decode() in text):
            return "", "REDACTED"
    return text, "ACCEPTED"


def project_assistant_message(notification, session_id: str, *, environment: dict | None = None) -> dict | None:
    payload = notification.payload
    if notification.method != "session.event" or not isinstance(payload, dict) or payload.get("sessionId") != session_id:
        return None
    event = payload.get("event")
    if not isinstance(event, dict) or event.get("type") != "assistant/message":
        return None
    sequence = event.get("seq")
    if type(sequence) is not int or not 0 <= sequence <= 9223372036854775807:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    message = data.get("message")
    content = (message if isinstance(message, dict) else data).get("content")
    if not isinstance(content, list):
        return None
    # This mirrors the official SDK final_response projection, with strict text
    # types and a per-message bound rather than serializing arbitrary objects.
    parts = [block["text"] for block in content if isinstance(block, dict)
             and block.get("type") == "text" and isinstance(block.get("text"), str)]
    if not parts:
        return None
    text, status = visible_text("".join(parts), environment=environment)
    return {"session_id": session_id, "event_sequence": sequence, "text": text,
            "interrupted": data.get("interrupted") is True, "content_status": status}
