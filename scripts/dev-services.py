"""Supervise local services on macOS/Linux without GNU setsid or Bash wait -n."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    api_port = os.environ.get("HYPERTEST_DEV_API_PORT", "8000")
    web_port = os.environ.get("HYPERTEST_DEV_WEB_PORT", "3000")
    environment = dict(os.environ)
    environment.update(
        HYPERTEST_API_ORIGIN=f"http://127.0.0.1:{api_port}",
        NEXT_TELEMETRY_DISABLED="1",
    )
    commands = [
        [str(root / ".venv/bin/uvicorn"), "hypertest.main:app", "--host", "127.0.0.1",
         "--port", api_port],
        ["npm", "--prefix", "web", "run", "dev", "--", "--hostname", "127.0.0.1",
         "--port", web_port],
    ]
    processes: list[subprocess.Popen] = []
    stopping = False

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        for command in commands:
            processes.append(subprocess.Popen(
                command, cwd=root, env=environment, start_new_session=True,
            ))
        while not stopping:
            for process in processes:
                if (code := process.poll()) is not None:
                    return code if code >= 0 else 128 - code
            time.sleep(0.2)
        return 0
    finally:
        # Each child has its own process group, including npm's Next.js descendants.
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 10
        while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
            time.sleep(0.1)
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
