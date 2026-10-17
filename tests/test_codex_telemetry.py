"""Provider telemetry must not invalidate a saved, bounded TMP result."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_codex_adapter import mission_contract

from hypertest.agent.codex import CodexCliAdapter


def telemetry_provider(tmp_path: Path, *, oversized: bool, trailing_newline: bool) -> str:
    script = tmp_path / "telemetry_provider.py"
    script.write_text(f"""#!{sys.executable}
import json,pathlib,sys
mission=json.loads(sys.argv[-1].split("TEST_MISSION_JSON:\\n",1)[1])
output=pathlib.Path(sys.argv[sys.argv.index("--output-last-message")+1])
payload={{"protocol":mission["protocol"],"mission_id":mission["mission_id"],"status":"COMPLETED","summary":"ok" if {oversized!r} else "x"*70000,"proposals":[]}}
output.write_text(json.dumps(payload))
print(json.dumps({{"type":"review.marker","position":"before"}}),flush=True)
if {oversized!r}:
    telemetry=json.dumps({{"type":"review.oversized","text":"x"*2_100_000}})
    sys.stdout.write(telemetry + ("\\n" if {trailing_newline!r} else ""))
    if {trailing_newline!r}:
        print(json.dumps({{"type":"review.marker","position":"after"}}))
else:
    print(json.dumps({{"type":"item.completed","item":{{"type":"agent_message","text":json.dumps(payload)}}}}))
sys.stdout.flush()
""")
    script.chmod(0o700)
    return str(script)


@pytest.mark.asyncio
async def test_valid_70kb_final_message_survives_provider_jsonl(tmp_path: Path) -> None:
    adapter = CodexCliAdapter(binary=telemetry_provider(
        tmp_path, oversized=False, trailing_newline=True,
    ))
    session = await adapter.create_session(str(tmp_path))
    try:
        events = [event async for event in adapter.execute(
            session, mission_contract("MISSION-LARGE-TELEMETRY"),
        )]
        submitted = [event for event in events if event.type == "RESULT_SUBMITTED"]
        assert len(submitted) == 1
        assert submitted[0].payload["summary"] == "x" * 70000
        assert not any(event.type == "ERROR" for event in events)
    finally:
        await adapter.close(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("trailing_newline", [True, False])
async def test_oversized_telemetry_preserves_saved_result_and_recovers_next_line(
    tmp_path: Path, trailing_newline: bool,
) -> None:
    adapter = CodexCliAdapter(binary=telemetry_provider(
        tmp_path, oversized=True, trailing_newline=trailing_newline,
    ))
    session = await adapter.create_session(str(tmp_path))
    try:
        events = [event async for event in adapter.execute(
            session, mission_contract("MISSION-OVERSIZED-TELEMETRY"),
        )]
        submitted = [event for event in events if event.type == "RESULT_SUBMITTED"]
        assert len(submitted) == 1
        assert submitted[0].payload["summary"] == "ok"
        provider_events = [
            event.payload["provider_event"] for event in events
            if event.type == "ACTIVITY" and "provider_event" in event.payload
        ]
        positions = [
            event["position"] for event in provider_events
            if event.get("type") == "review.marker"
        ]
        assert positions == (["before", "after"] if trailing_newline else ["before"])
        assert all(event.get("type") != "review.oversized" for event in provider_events)
        assert all(len(json.dumps(event)) < 2_000_000 for event in provider_events)
        assert not any(event.type == "ERROR" for event in events)
    finally:
        await adapter.close(session)
