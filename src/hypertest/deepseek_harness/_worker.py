"""Private SDK host. Only the supervisor starts it, with a clean environment.

The line protocol here is HyperTest's private process control, not a replacement
for the official SDK transport. All Harness requests use HarnessClient.
"""

from __future__ import annotations

import contextlib
import json
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from .models import SERVER_NAME, SERVER_VERSION
from .supervisor import MAX_CONTROL_FRAME

_EVENT_TYPES = frozenset({"agent/inbox/spliced", "turn/start", "turn/end", "tool/start", "tool/end"})
_TURN_KINDS = frozenset({"completed", "max-tokens", "error", "cancelled"})


class SdkDriver:
    """Typed SDK use with a bounded, content-free activity projection."""

    def __init__(self, client: Any, session_id: str) -> None:
        self.client = client
        self.session_id = session_id
        self.counts: Counter[str] = Counter()
        self.root_status: str | None = None
        self.turn_kind: str | None = None
        self._lock = threading.Lock()
        self._subscription = client.subscribe_notifications()
        threading.Thread(target=self._consume, daemon=True, name="hypertest-dsh-observe").start()

    def _consume(self) -> None:
        try:
            while True:
                self.observe(self._subscription.next())
        except BaseException:
            return

    def observe(self, notification: Any) -> None:
        method = notification.method
        data = notification.payload
        if not isinstance(data, dict):
            return
        with self._lock:
            if method in {"subagent.started", "subagent.finished"}:
                # No prompt, native answer, error text, tool args or payload refs.
                self.counts[method] = min(self.counts[method] + 1, 1_000_000)
            elif data.get("sessionId") == self.session_id and method == "session.status":
                if data.get("status") in {"running", "idle"}:
                    self.root_status = data["status"]
            elif data.get("sessionId") == self.session_id and method == "session.event":
                event = data.get("event")
                kind = event.get("type") if isinstance(event, dict) else None
                if isinstance(kind, str) and kind in _EVENT_TYPES:
                    self.counts[kind] = min(self.counts[kind] + 1, 1_000_000)
                if kind == "turn/end":
                    value = event.get("data")
                    reason = value.get("reason") if isinstance(value, dict) else None
                    finish = reason.get("kind") if isinstance(reason, dict) else None
                    self.turn_kind = finish if isinstance(finish, str) and finish in _TURN_KINDS else "OTHER"

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"root_status": self.root_status, "turn_kind": self.turn_kind, "activity_counts": dict(self.counts)}

    def initialize(self, config: dict[str, Any]) -> dict[str, object]:
        self.client.start()
        result = self.client.initialize(
            cwd=config["workspace"], provider=config["provider"], model=config["model"],
            reasoning_effort=config.get("reasoning_effort"), max_tokens=config.get("max_tokens"),
        )
        info = result.serverInfo
        if info is None or info.name != SERVER_NAME or info.version != SERVER_VERSION:
            raise ValueError("SDK_PROTOCOL_UNSUPPORTED")
        # This official operation creates an unknown session without a model turn.
        cwd = self.client.get_working_directory(self.session_id)
        if Path(cwd).resolve() != Path(config["workspace"]).resolve():
            raise ValueError("SDK_PROTOCOL_UNSUPPORTED")
        return {"server_name": info.name, "server_version": info.version, "session_created": True}

    def close(self) -> dict[str, object]:
        self.client.close()
        self._subscription.close()
        return {"sdk_closed": True}


def main() -> int:
    output = sys.stdout
    driver: SdkDriver | None = None
    # Prevent third-party import or SDK diagnostics from becoming control output.
    with contextlib.redirect_stdout(sys.stderr):
        while line := sys.stdin.readline(MAX_CONTROL_FRAME + 1):
            if len(line.encode("utf-8")) > MAX_CONTROL_FRAME:
                return 2
            message: dict[str, Any] = {}
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("SDK_PROTOCOL_UNSUPPORTED")
                message = value
                sequence = message["sequence"]
                command = message["command"]
                payload = message["payload"]
                if command == "start" and driver is None:
                    from deepseek_harness import HarnessClient, HarnessConfig

                    from hypertest.cloud.sdk import controlled_sdk_patches

                    client = HarnessClient(HarnessConfig(
                        profile="sdk", dsh_home=payload["dsh_home"], cwd=payload["workspace"],
                        patches=controlled_sdk_patches({"dsh_home": payload["dsh_home"]}),
                        initialize_timeout_seconds=payload["timeout_seconds"],
                        request_timeout_seconds=payload["timeout_seconds"], shutdown_timeout_seconds=0.5,
                    ))
                    driver = SdkDriver(client, payload["session_id"])
                    result = driver.initialize(payload)
                elif driver is not None and command == "observe":
                    result = driver.snapshot()
                elif driver is not None and command == "close":
                    result = driver.close()
                else:
                    raise ValueError("SDK_PROTOCOL_UNSUPPORTED")
                response = {"sequence": sequence, "result": result}
            except ImportError:
                response = {"sequence": message.get("sequence"), "error": "SDK_IMPORT_FAILED"}
            except TimeoutError:
                response = {"sequence": message.get("sequence"), "error": "SDK_TIMEOUT"}
            except ValueError as error:
                code = "SDK_PROTOCOL_UNSUPPORTED" if str(error) == "SDK_PROTOCOL_UNSUPPORTED" else "SDK_OPERATION_FAILED"
                response = {"sequence": message.get("sequence"), "error": code}
            except Exception:
                response = {"sequence": message.get("sequence"), "error": "SDK_OPERATION_FAILED"}
            output.write(json.dumps(response, separators=(",", ":")) + "\n")
            output.flush()
            if message.get("command") == "close" or "error" in response:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
