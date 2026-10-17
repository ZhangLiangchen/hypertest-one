from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path
from typing import Any

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.common.ids import public_key

_MAX_TELEMETRY_LINE_BYTES = 2_000_000


async def _read_jsonl_telemetry(stream: asyncio.StreamReader) -> AsyncIterator[Any]:
    """Drain telemetry without StreamReader's 64 KiB readline ceiling.

    Telemetry is not the result channel. Oversized provider messages must not
    prevent consuming a valid final-response file or allocate unbounded memory.
    """
    pending = bytearray()
    discarded = False
    while chunk := await stream.read(65536):
        fragments = chunk.split(b"\n")
        for index, fragment in enumerate(fragments):
            if not discarded:
                if len(pending) + len(fragment) > _MAX_TELEMETRY_LINE_BYTES:
                    pending.clear()
                    discarded = True
                else:
                    pending.extend(fragment)
            if index == len(fragments) - 1:
                continue
            if discarded:
                yield {"type": "telemetry.line_discarded", "limit_bytes": _MAX_TELEMETRY_LINE_BYTES}
            elif line := pending.decode("utf-8", errors="replace").strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    yield {"raw": line}
            pending.clear()
            discarded = False
    if discarded:
        yield {"type": "telemetry.line_discarded", "limit_bytes": _MAX_TELEMETRY_LINE_BYTES}
    elif line := pending.decode("utf-8", errors="replace").strip():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            yield {"raw": line}


def _inline_schema(value: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [_inline_schema(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if not reference.startswith("#/$defs/"):
            raise ValueError("Codex output schema must use local definition references")
        resolved = deepcopy(definitions[reference.removeprefix("#/$defs/")])
        resolved.update({key: item for key, item in value.items() if key != "$ref"})
        return _inline_schema(resolved, definitions)
    return {
        key: (
            {name: _inline_schema(schema, definitions) for name, schema in item.items()}
            if key == "properties" else _inline_schema(item, definitions)
        )
        for key, item in value.items()
        if key not in {"$defs", "default", "title", "minLength", "maxLength"}
    }


def _close_schema(value: Any) -> Any:
    """Use the provider's strict subset without changing the TMP validator."""
    if isinstance(value, list):
        return [_close_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    closed = {key: _close_schema(item) for key, item in value.items()}
    if closed.get("type") == "object":
        properties = closed.setdefault("properties", {})
        closed["required"] = list(properties)
        closed["additionalProperties"] = False
    return closed


def codex_output_schema(
    mission: dict[str, Any], *, idempotency_prefix: str | None = None,
) -> dict[str, Any]:
    """Project the typed mission result into Codex Structured Outputs.

    TMP permits optional operational dictionaries. They are omitted here rather
    than silently narrowing their canonical meanings to empty objects. Current
    supported missions need only the envelope and typed proposals; HyperTest
    still applies the complete provider-independent validator on submission.
    """
    contract = mission["output_contract"]
    result = contract["result_schema"]
    proposal = _inline_schema(
        result["$defs"]["ProposalSubmission"], result.get("$defs", {})
    )
    payload = contract["object_payload_schema"]
    proposal["properties"]["object_payload"] = _inline_schema(
        payload, payload.get("$defs", {})
    )
    proposal["properties"]["proposal_type"] = {
        "type": "string", "enum": [contract["proposal_type"]],
    }
    proposal["properties"]["operation"] = {"type": "string", "enum": [contract["operation"]]}
    if idempotency_prefix is not None:
        proposal["properties"]["idempotency_key"]["pattern"] = f"^{re.escape(idempotency_prefix)}"
    properties = {
        key: _inline_schema(result["properties"][key], result.get("$defs", {}))
        for key in ("protocol", "mission_id", "status", "summary", "proposals")
    }
    properties["protocol"] = {"type": "string", "enum": [mission["protocol"]]}
    properties["mission_id"] = {"type": "string", "enum": [mission["mission_id"]]}
    properties["proposals"]["items"] = proposal
    return _close_schema({"type": "object", "properties": properties})


class CodexCliAdapter:
    """Thin Codex CLI adapter with an explicit TMP result boundary.

    Provider JSONL remains operational telemetry. The only final result exposed
    to the HyperTest runtime is the JSON object the CLI writes through its
    supported final-response output channel. Agent tools remain read-only.
    """

    def __init__(self, binary: str = "codex", extra_args: tuple[str, ...] = ()) -> None:
        self.binary = binary
        self.extra_args = extra_args
        self._workspaces: dict[str, str] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def create_session(self, workspace: str) -> AgentSession:
        session = AgentSession(id=public_key("AS"), provider="codex")
        self._workspaces[session.id] = workspace
        return session

    async def execute(
        self,
        session: AgentSession,
        mission: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]:
        workspace = self._workspaces.get(session.id)
        if workspace is None:
            raise RuntimeError(f"unknown agent session: {session.id}")

        workspace_path = Path(workspace)
        if not workspace_path.is_dir():
            raise RuntimeError(f"workspace does not exist: {workspace}")

        result_dir = workspace_path / ".hypertest" / "results"
        if not result_dir.resolve().is_relative_to(workspace_path.resolve()):
            raise RuntimeError("mission result directory must remain inside its workspace")
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{session.id}.json"
        result_path.unlink(missing_ok=True)
        schema_path = result_dir / f"{session.id}.schema.json"
        idempotency_prefix = f"{session.id}:"
        schema_path.write_text(
            json.dumps(
                codex_output_schema(mission, idempotency_prefix=idempotency_prefix),
                ensure_ascii=False,
            ), encoding="utf-8"
        )

        mission_json = json.dumps(mission, ensure_ascii=False, sort_keys=True)
        prompt = (
            "Execute the following HyperTest Test Mission as an immutable task contract. "
            "Use available repository and tools, do not redefine the mission. "
            "Return exactly one JSON object matching the supplied mission output contract as "
            "your final response. The CLI saves that response; do not write a result file or "
            "modify application source. Submit generated test source in proposal code fields.\n\n"
            "Follow context.testing_scope when provided: distinguish the pinned application's "
            "requested behavior from directions for producing or executing tests. Those directions "
            "remain binding, but do not make HyperTest's orchestration infrastructure an implicit "
            "test subject.\n\n"
            "Agent completion means the requested proposals are ready for HyperTest verification. "
            "HyperTest's trusted Runner performs official validation AFTER accepting implementation "
            "proposals. Do not mark otherwise complete proposals PARTIAL/BLOCKED merely because "
            "tests have not run, pytest is unavailable in this Agent workspace, or this read-only "
            "sandbox cannot materialize tests. runner_validation_required is a downstream Runner "
            "obligation, not an obligation to execute tests inside this Agent session. "
            "Each implementation symbol must identify an actual test_* function, optionally "
            "qualified as TestClass::test_function; a module or class alone is not a valid symbol.\n\n"
            f"For every proposal idempotency_key use the prefix {idempotency_prefix} followed by "
            "a distinct stable label for that proposal. This execution-specific prefix prevents "
            "a retry from reusing keys reserved by a rejected prior attempt.\n\n"
            f"TEST_MISSION_JSON:\n{mission_json}"
        )

        process = await asyncio.create_subprocess_exec(
            self.binary,
            "--ask-for-approval",
            "never",
            "exec",
            "--json",
            "--skip-git-repo-check",
            *self.extra_args,
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "-",
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._processes[session.id] = process

        async def send_prompt() -> None:
            assert process.stdin is not None
            try:
                process.stdin.write(prompt.encode("utf-8"))
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                # A CLI can fail before reading stdin. Its exit status and stderr
                # remain the result, rather than a pipe error masking the cause.
                pass
            finally:
                process.stdin.close()

        # Drain output while sending input: a provider can emit telemetry before
        # consuming a large prompt, so either pipe must not block the other.
        prompt_task = asyncio.create_task(send_prompt())
        stderr_task = None
        if process.stderr is not None:
            stderr_task = asyncio.create_task(process.stderr.read())

        try:
            yield AgentEvent(type="MISSION_STARTED", payload={"provider": "codex"})

            assert process.stdout is not None
            async for provider_event in _read_jsonl_telemetry(process.stdout):
                yield AgentEvent(
                    type="ACTIVITY",
                    payload={
                        "provider": "codex",
                        "provider_event": provider_event,
                    },
                )

            return_code = await process.wait()
            await prompt_task
        finally:
            if not prompt_task.done():
                prompt_task.cancel()
            await asyncio.gather(prompt_task, return_exceptions=True)
        self._processes.pop(session.id, None)
        stderr = ""
        if stderr_task is not None:
            stderr = (await stderr_task).decode("utf-8", errors="replace")

        if return_code != 0:
            yield AgentEvent(
                type="ERROR",
                payload={
                    "provider": "codex",
                    "return_code": return_code,
                    "stderr": stderr,
                },
            )
            return

        if not result_path.is_file():
            yield AgentEvent(
                type="ERROR",
                payload={
                    "provider": "codex",
                    "error_code": "RESULT_MISSING",
                    "message": f"mission result file not found: {result_path}",
                },
            )
            return

        try:
            if result_path.stat().st_size > 2_000_000:
                raise ValueError("mission result exceeds the 2 MB structured output limit")
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            yield AgentEvent(
                type="ERROR",
                payload={
                    "provider": "codex",
                    "error_code": "RESULT_INVALID",
                    "message": str(exc),
                },
            )
            return

        yield AgentEvent(type="RESULT_SUBMITTED", payload=result_payload)
        yield AgentEvent(type="MISSION_FINISHED", payload={"provider": "codex"})

    async def interrupt(self, session: AgentSession) -> None:
        process = self._processes.get(session.id)
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            except ProcessLookupError:
                await process.wait()

    async def close(self, session: AgentSession) -> None:
        await self.interrupt(session)
        self._processes.pop(session.id, None)
        self._workspaces.pop(session.id, None)
