"""Launch one official SDK turn as the current OS user, without platform keys.

A process-group observation does not prove escaped descendants or external
operations stopped. The caller must preserve those outcomes as unknown.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from .errors import CloudBlocked

# Only host login and executable discovery settings flow to the SDK child.
# In particular, no platform token, database URL or worker identity is passed.
_HOST_ENV = frozenset({"HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "LANG",
                       "LC_ALL", "LC_CTYPE", "TERM", "SSH_AUTH_SOCK", "XDG_CONFIG_HOME",
                       "XDG_CACHE_HOME", "SYSTEMROOT", "WINDIR", "GH_CONFIG_DIR", "GLAB_CONFIG_DIR",
                       "GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN", "GLAB_TOKEN", "DEEPSEEK_API_KEY",
                       "DEEPSEEK_BASE_URL"})


def host_environment(source: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in source.items() if key in _HOST_ENV}
    # The host Worker may be installed from a fixed checkout rather than an
    # editable wheel. Derive its package root from this already-loaded module;
    # never inherit an arbitrary caller-supplied PYTHONPATH.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    return env


class NativeSdkAdapter:
    def __init__(self, *, workspace: Path, dsh_home: Path):
        self.workspace = Path(workspace).absolute()
        self.dsh_home = Path(dsh_home).absolute()
        self.process: asyncio.subprocess.Process | None = None
        self._started = False

    async def start(self, *, session_id: str, prompt: str, interaction_enabled: bool = False,
                    resume_identity: dict | None = None):
        if self._started:
            raise CloudBlocked("SDK_ORIGINAL_OPERATION_QUERY_ONLY", "An SDK prompt cannot be started twice")
        if not self.workspace.is_dir() or not self.dsh_home.is_dir() or not session_id or not prompt:
            raise CloudBlocked("HARNESS_CONFIGURATION_INVALID", "A workspace, Harness home and prompt are required")
        config = {"workspace": str(self.workspace), "dsh_home": str(self.dsh_home),
                              "session_id": session_id, "prompt": prompt,
                              "interaction_enabled": interaction_enabled}
        if resume_identity is not None:
            config["resume_identity"] = resume_identity
        payload = json.dumps(config).encode() + b"\n"
        if len(payload) > 1024 * 1024:
            raise CloudBlocked("HARNESS_CONFIGURATION_INVALID", "Harness prompt exceeds the input limit")
        # One start attempt per adapter, including uncertain subprocess failures.
        self._started = True
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-P", "-m", "hypertest.cloud.native_sdk_driver", cwd=str(self.workspace),
            env=host_environment(os.environ), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            limit=131073)
        try:
            self.process.stdin.write(payload)
            await self.process.stdin.drain()
        except BaseException:
            # The original child may already be running. Stop what can be
            # observed and propagate; never relaunch this adapter's prompt.
            await self.stop()
            raise
        finally:
            if not interaction_enabled:
                self.process.stdin.close()
        return self.process

    async def answer_question(self, request_id: str, answer: dict):
        """Send one answer to the original live child; a pipe write is not an SDK acknowledgement."""
        process = self.process
        if (process is None or process.returncode is not None or process.stdin is None
                or process.stdin.is_closing() or not isinstance(request_id, str) or not request_id
                or len(request_id) > 255 or not isinstance(answer, dict)):
            raise CloudBlocked("SDK_QUESTION_CHANNEL_CLOSED", "Original SDK question channel is unavailable")
        payload = json.dumps({"type": "question_response", "request_id": request_id, "answer": answer},
                             ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        if len(payload) > 131072:
            raise CloudBlocked("SDK_QUESTION_RESPONSE_INVALID", "SDK question response is too large")
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionError, RuntimeError):
            raise CloudBlocked("SDK_QUESTION_DELIVERY_UNKNOWN", "Original question response needs reconciliation") from None

    async def stop(self) -> dict:
        process = self.process
        if process is None:
            return {"direct_process_stopped": not self._started,
                    "all_local_processes_stopped": None, "external_operations_reconciled": None}
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    pass
        return {"direct_process_stopped": process.returncode is not None,
                "all_local_processes_stopped": None, "external_operations_reconciled": None}
