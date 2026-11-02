"""Run the official Harness SDK in a dedicated host child process.

This module receives a single prompt from its private stdin and emits only
bounded, non-content observations. It never receives platform credentials.
"""
from __future__ import annotations

import json
import os
import sys

from .native_selection import read_native_selection
from .runtime_activity import project_finish_reason, project_notification


def run(config: dict, emit) -> None:
    from deepseek_harness import HarnessClient, HarnessConfig
    from pydantic import BaseModel

    class WaitResponse(BaseModel):
        pass

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

    # No env overrides or platform key are passed to the SDK. Its child inherits
    # only the already filtered host user environment of this driver.
    with HarnessClient(HarnessConfig(profile="sdk", dsh_home=config["dsh_home"],
                                    cwd=config["workspace"])) as client:
        info = client.initialize(cwd=config["workspace"], **selection).serverInfo
        if info is None or info.name != "deepseek-harness-sdk-runtime" or info.version != "0.0.1":
            raise ValueError("unexpected SDK protocol")
        with client.subscribe_notifications() as subscription:
            client.session_prompt(config["session_id"], [{"type": "text", "text": config["prompt"]}],
                                  on_notification=observe, notification_subscription=subscription)
            client.request("session/wait", {"sessionId": config["session_id"]},
                           response_model=WaitResponse, on_notification=observe,
                           notification_subscription=subscription)
            subscription.drain(observe)
    emit({"runtime_observation": "IDLE", "session_id": config["session_id"],
          "finish_reason": finish_reason})


def main() -> int:
    def emit(value):
        print(json.dumps(value, separators=(",", ":")), flush=True)

    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("input too large")
        config = json.loads(raw)
        if (not isinstance(config, dict) or set(config) != {"workspace", "dsh_home", "session_id", "prompt"}
                or any(not isinstance(value, str) or not value for value in config.values())):
            raise ValueError("invalid input")
        run(config, emit)
        return 0
    except Exception:
        # SDK exceptions can contain arbitrary content or credentials.
        emit({"runtime_observation": "ERROR", "code": "SDK_RUN_FAILED"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
