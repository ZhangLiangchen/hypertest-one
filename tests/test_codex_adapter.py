import asyncio
import sys

import pytest

from hypertest.agent.codex import CodexCliAdapter


def make_provider(tmp_path, *, oversized=False):
    script = tmp_path / "provider.py"
    script.write_text(f"""#!{sys.executable}
import json,pathlib,sys,time
prompt=sys.argv[-1]
mission=json.loads(prompt.split("TEST_MISSION_JSON:\\n",1)[1])
output=pathlib.Path(prompt.split("output contract to ",1)[1].split(". Do not use stdout",1)[0])
time.sleep(0.05)
payload={{"protocol":"hypertest.tmp/v1alpha1","mission_id":mission["mission_id"],"status":"COMPLETED","proposals":[]}}
if {oversized!r}: payload["summary"]="x"*2_000_001
output.write_text(json.dumps(payload))
print(json.dumps({{"type":"untrusted_stdout","mission_id":"wrong-mission"}}))
""")
    script.chmod(0o700)
    return str(script)


@pytest.mark.asyncio
async def test_concurrent_codex_sessions_keep_structured_results_separate(tmp_path):
    adapter = CodexCliAdapter(binary=make_provider(tmp_path))
    first = await adapter.create_session(str(tmp_path))
    second = await adapter.create_session(str(tmp_path))

    async def collect(session, key):
        return [event async for event in adapter.execute(session, {"mission_id": key})]

    results = await asyncio.gather(collect(first, "MISSION-A"), collect(second, "MISSION-B"))
    for events, expected in zip(results, ["MISSION-A", "MISSION-B"], strict=True):
        submitted = [event for event in events if event.type == "RESULT_SUBMITTED"]
        assert len(submitted) == 1
        assert submitted[0].payload["mission_id"] == expected
    assert len(list((tmp_path / ".hypertest" / "results").glob("*.json"))) == 2
    await adapter.close(first)
    await adapter.close(second)


@pytest.mark.asyncio
async def test_codex_result_size_limit_rejects_provider_payload(tmp_path):
    adapter = CodexCliAdapter(binary=make_provider(tmp_path, oversized=True))
    session = await adapter.create_session(str(tmp_path))
    events = [event async for event in adapter.execute(session, {"mission_id": "MISSION-LARGE"})]
    assert not any(event.type == "RESULT_SUBMITTED" for event in events)
    assert any(
        event.type == "ERROR" and event.payload["error_code"] == "RESULT_INVALID"
        for event in events
    )
    await adapter.close(session)
