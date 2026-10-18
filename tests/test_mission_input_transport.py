"""Large mission input must cross a real pipe, not the OS argument boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys

import pytest
from test_codex_adapter import mission_contract

from hypertest.agent.codex import CodexCliAdapter


def stdin_provider(tmp_path, *, reject_before_reading: bool = False) -> str:
    script = tmp_path / "stdin_provider.py"
    script.write_text(f"""#!{sys.executable}
import hashlib,json,pathlib,sys
assert sys.argv[-1] == "-"
assert max(map(len, sys.argv)) < 4096
assert sys.argv[sys.argv.index("--sandbox")+1] == "read-only"
if {reject_before_reading!r}:
    print("provider rejected before consuming input", file=sys.stderr, flush=True)
    sys.exit(2)
# Fill more than a pipe buffer before reading, to expose sequential write/read
# deadlocks. This is provider telemetry, never the official result channel.
print(json.dumps({{"type":"input.waiting","text":"x"*262144}}),flush=True)
prompt=sys.stdin.buffer.read().decode("utf-8")
mission=json.loads(prompt.split("TEST_MISSION_JSON:\\n",1)[1])
prd=mission["context"]["prd_text"]
output=pathlib.Path(sys.argv[sys.argv.index("--output-last-message")+1])
output.write_text(json.dumps({{
    "protocol":mission["protocol"],"mission_id":mission["mission_id"],
    "status":"COMPLETED","summary":hashlib.sha256(prd.encode("utf-8")).hexdigest(),
    "proposals":[]
}}))
""", encoding="utf-8")
    script.chmod(0o700)
    return str(script)


@pytest.mark.asyncio
async def test_two_million_character_prd_uses_stdin_with_concurrent_telemetry(tmp_path):
    # At six MB in UTF-8 this exceeds both common per-argument and total argv
    # limits, while remaining inside the Web's declared two-million-char limit.
    prd = "中" * 2_000_000
    contract = mission_contract("MISSION-LARGE-INPUT")
    contract["context"] = {"prd_text": prd}
    adapter = CodexCliAdapter(binary=stdin_provider(tmp_path))
    session = await adapter.create_session(str(tmp_path))

    async def collect():
        return [event async for event in adapter.execute(session, contract)]

    try:
        events = await asyncio.wait_for(collect(), timeout=10)
        submitted = [event for event in events if event.type == "RESULT_SUBMITTED"]
        assert len(submitted) == 1
        assert submitted[0].payload["summary"] == hashlib.sha256(prd.encode()).hexdigest()
        assert any(event.type == "ACTIVITY" for event in events)
        assert not any(event.type == "ERROR" for event in events)
    finally:
        await adapter.close(session)


@pytest.mark.asyncio
async def test_early_provider_exit_preserves_error_instead_of_stdin_pipe_failure(tmp_path):
    contract = mission_contract("MISSION-INPUT-REJECTED")
    contract["context"] = {"prd_text": "x" * 2_000_000}
    adapter = CodexCliAdapter(binary=stdin_provider(tmp_path, reject_before_reading=True))
    session = await adapter.create_session(str(tmp_path))

    async def collect():
        return [event async for event in adapter.execute(session, contract)]

    try:
        events = await asyncio.wait_for(collect(), timeout=10)
        errors = [event for event in events if event.type == "ERROR"]
        assert len(errors) == 1
        assert errors[0].payload["return_code"] == 2
        assert errors[0].payload["error_code"] == "PROVIDER_ERROR"
        assert errors[0].payload["message"] == "Codex process exited unsuccessfully"
        assert "stderr" not in errors[0].payload
        assert "provider rejected before consuming input" not in json.dumps([event.payload for event in events])
        assert not any(event.type == "RESULT_SUBMITTED" for event in events)
    finally:
        await adapter.close(session)
