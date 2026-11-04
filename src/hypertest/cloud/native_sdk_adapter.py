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
        self._write_lock = asyncio.Lock()
        self._messages: set[str] = set()
        self._closing = False

    async def start(self, *, session_id: str, title: str, prompt: str, interaction_enabled: bool = False,
                    resume_identity: dict | None = None, keep_alive: bool = False,
                    continuation: bool = False):
        if self._started:
            raise CloudBlocked("SDK_ORIGINAL_OPERATION_QUERY_ONLY", "An SDK prompt cannot be started twice")
        if (not self.workspace.is_dir() or not self.dsh_home.is_dir() or not session_id or not prompt
                or not isinstance(title, str) or not title.strip() or len(title) > 512):
            raise CloudBlocked("HARNESS_CONFIGURATION_INVALID", "A workspace, Harness home, task title and prompt are required")
        config = {"workspace": str(self.workspace), "dsh_home": str(self.dsh_home),
                              "session_id": session_id, "title": title, "prompt": prompt,
                              "interaction_enabled": interaction_enabled, "keep_alive": keep_alive,
                              "continuation": continuation}
        if continuation and resume_identity is None:
            raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Continuation requires an accepted identity baseline")
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
            if not interaction_enabled and not keep_alive:
                self.process.stdin.close()
        return self.process

    async def resume(self, *, session_id: str, title: str, continuation: str,
                     resume_identity: dict, interaction_enabled: bool = True, keep_alive: bool = True):
        """Restore the original session, then send only this new continuation."""
        return await self.start(session_id=session_id, title=title, prompt=continuation,
            interaction_enabled=interaction_enabled, resume_identity=resume_identity,
            keep_alive=keep_alive, continuation=True)

    async def _send_frame(self, frame: dict, *, error_code: str):
        async with self._write_lock:
            process = self.process
            if (process is None or process.returncode is not None or process.stdin is None
                    or process.stdin.is_closing()):
                raise CloudBlocked(error_code, "Original SDK command channel is unavailable")
            payload = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            if len(payload) > 131072:
                raise CloudBlocked(error_code, "SDK command exceeds its bounded channel")
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionError, RuntimeError):
                raise CloudBlocked(error_code, "Original SDK delivery requires reconciliation") from None

    async def send_message(self, request_id: str, text: str):
        if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 255
                or not isinstance(text, str) or not text.strip() or len(text) > 16384
                or request_id in self._messages or self._closing):
            raise CloudBlocked("SDK_MESSAGE_QUERY_ONLY", "Original SDK message cannot be delivered again")
        # Freeze consumption before the first pipe write, even if that write fails.
        self._messages.add(request_id)
        await self._send_frame({"type": "user_message", "request_id": request_id, "text": text},
                               error_code="SDK_MESSAGE_DELIVERY_UNKNOWN")

    async def close_session(self):
        """Stop accepting messages; the child waits for SDK idle and drains output."""
        if self._closing:
            return
        self._closing = True
        await self._send_frame({"type": "close"}, error_code="SDK_CLOSE_UNCONFIRMED")

    async def answer_question(self, request_id: str, answer: dict):
        """Send one answer to the original live child; a pipe write is not an SDK acknowledgement."""
        process = self.process
        if (process is None or process.returncode is not None or process.stdin is None
                or process.stdin.is_closing() or not isinstance(request_id, str) or not request_id
                or len(request_id) > 255 or not isinstance(answer, dict)):
            raise CloudBlocked("SDK_QUESTION_CHANNEL_CLOSED", "Original SDK question channel is unavailable")
        await self._send_frame({"type": "question_response", "request_id": request_id, "answer": answer},
                               error_code="SDK_QUESTION_DELIVERY_UNKNOWN")

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
