"""Persistent Codex turns: filtered environment, fixed executable, narrow MCP relay."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from hypertest.agent.codex import _drain_stderr, _read_jsonl_telemetry, provider_activity_kind
from hypertest.harness_bridge.protocol import BridgeError

_ENVIRONMENT_ALLOWLIST = frozenset({
    "HOME", "PATH", "CODEX_HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY",
    "https_proxy", "http_proxy", "all_proxy", "no_proxy", "OPENAI_API_KEY", "OPENAI_BASE_URL",
})


def provider_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Never inherit platform DB/lease/GitLab/Bridge credentials or Python injection vars."""
    source = dict(os.environ) if source is None else source
    return {key: value for key, value in source.items() if key in _ENVIRONMENT_ALLOWLIST}


def native_session_exists(reference: str, environment: dict[str, str]) -> bool:
    try:
        UUID(reference)
    except (TypeError, ValueError):
        return False
    root = Path(environment.get("CODEX_HOME", str(Path(environment.get("HOME", "")) / ".codex")))
    # Only filenames beneath Codex's own session store are inspected, never auth contents.
    sessions = root / "sessions"
    return sessions.is_dir() and any(sessions.glob(f"**/*{reference}.jsonl"))


def process_identity(pid: int) -> str | None:
    try:
        # Linux starttime distinguishes an orphan from a reused PID. Non-Linux
        # restarts fail closed; live in-process interruption remains supported.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


class PersistentCodex:
    def __init__(self, binary: str = "codex", *, environment: dict[str, str] | None = None) -> None:
        self.binary = binary
        self.environment = provider_environment(environment)
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.version: str | None = None

    async def validate_capabilities(self) -> None:
        """Probe installed CLI without starting a model or inspecting auth material."""
        required = {"shell_tool", "unified_exec", "multi_agent", "apps", "plugins", "browser_use", "computer_use"}
        async def probe(*arguments: str) -> str:
            process = await asyncio.create_subprocess_exec(
                self.binary, *arguments, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=self.environment,
            )
            try:
                async with asyncio.timeout(10):
                    output, _ = await process.communicate()
            except BaseException:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            if process.returncode or len(output) > 100_000:
                raise BridgeError("CAPABILITY_UNSUPPORTED")
            return output.decode("utf-8", errors="replace")
        try:
            version = (await probe("--version")).strip()
            features = {line.split()[0] for line in (await probe("features", "list")).splitlines() if line.split()}
            help_text = await probe("exec", "resume", "--help")
            if not required <= features or "--ignore-user-config" not in help_text or "--ignore-rules" not in help_text:
                raise BridgeError("CAPABILITY_UNSUPPORTED")
            self.version = version[:128]
        except (OSError, TimeoutError) as exc:
            raise BridgeError("PROVIDER_UNAVAILABLE") from exc

    def session_exists(self, reference: str) -> bool:
        return native_session_exists(reference, self.environment)

    async def run(self, *, call_id: str, workspace: Path, native_session: str | None,
                  contract: dict[str, Any], relay_socket: str, relay_token: str,
                  started: Callable[[int, str | None], None]) -> AsyncIterator[dict[str, Any]]:
        configuration = (
            "mcp_servers.hypertest={command=" + json.dumps(sys.executable)
            + ",args=[\"-I\"," + json.dumps(str(Path(__file__).with_name("relay.py")))
            + "],env={HYPERTEST_RELAY_SOCKET=" + json.dumps(relay_socket)
            + ",HYPERTEST_RELAY_TOKEN=" + json.dumps(relay_token)
            + ",HYPERTEST_RELAY_CALL_ID=" + json.dumps(call_id)
            + '},required=true,default_tools_approval_mode="approve",tool_timeout_sec=' + str(contract["timeout_seconds"]) + "}"
        )
        prompt = (
            "You are the persistent testing Harness for this one HyperTest Run. Continue this "
            "same native session through its serial typed missions. Use the hypertest MCP tools "
            "to read state, request permitted missions, submit proposals, request trusted Runner "
            "execution, inspect evidence, request Gate and submit the report. Never claim that "
            "your shell commands are official execution or that your narrative is a Verdict. "
            "Do not alter pinned application source. Tool responses are authoritative for "
            "accepted state. Keep idempotency keys stable for identical requests. If ask_user "
            "returns WAITING_INPUT, immediately end the turn; the operator's answer will resume "
            "this exact native session. If a tool rejects an action, inspect the returned reason "
            "and remain within the frozen contract. Do not bypass tools or invent success.\n\n"
            + contract["prompt"]
        )
        process = await asyncio.create_subprocess_exec(
            self.binary, "--ask-for-approval", "never", "exec", "--sandbox", "read-only",
            *(["resume", native_session] if native_session else []), "--json", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules",
            "--disable", "shell_tool", "--disable", "unified_exec", "--disable", "multi_agent",
            "--disable", "apps", "--disable", "plugins",
            "--disable", "browser_use", "--disable", "computer_use",
            "-c", 'web_search="disabled"', "-c", configuration,
            "-c", 'shell_environment_policy.inherit="none"', "-",
            cwd=workspace, env=self.environment, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )
        self.processes[call_id] = process
        started(process.pid, process_identity(process.pid))
        assert process.stdin and process.stdout and process.stderr
        stderr_task = asyncio.create_task(_drain_stderr(process.stderr))

        async def write_prompt() -> None:
            try:
                process.stdin.write(prompt.encode())
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        prompt_task = asyncio.create_task(write_prompt())
        try:
            async for event in _read_jsonl_telemetry(process.stdout):
                if isinstance(event, dict) and event.get("type") == "thread.started":
                    reference = event.get("thread_id")
                    try:
                        UUID(reference)
                    except (TypeError, ValueError, AttributeError) as exc:
                        raise BridgeError("PROVIDER_SESSION_INVALID") from exc
                    if native_session and reference != native_session:
                        raise BridgeError("PROVIDER_SESSION_CHANGED")
                    native_session = reference
                    yield {"type": "SESSION_STARTED", "payload": {"provider_session_id": reference}}
                yield {"type": "ACTIVITY", "payload": {"activity_kind": provider_activity_kind(event).value}}
            returncode = await process.wait()
            await prompt_task
            if returncode:
                raise BridgeError("PROVIDER_ERROR")
            if not native_session:
                raise BridgeError("PROVIDER_SESSION_MISSING")
            yield {"type": "TURN_FINISHED", "payload": {"return_code": 0}}
        finally:
            if process.returncode is None:
                await self.interrupt(call_id)
            prompt_task.cancel()
            await asyncio.gather(prompt_task, stderr_task, return_exceptions=True)
            self.processes.pop(call_id, None)

    async def interrupt(self, call_id: str) -> bool:
        process = self.processes.get(call_id)
        if process is None or process.returncode is not None:
            return True
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        except ProcessLookupError:
            await process.wait()
        return process.returncode is not None
