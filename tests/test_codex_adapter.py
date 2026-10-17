import asyncio
import re
import sys

import pytest

from hypertest.agent.codex import CodexCliAdapter, codex_output_schema
from hypertest.application.runtime import build_mission_contract
from hypertest.domain.enums import MissionType, Priority
from hypertest.domain.models import Mission
from hypertest.domain.models import TestRun as CanonicalRun


def mission_contract(key, mission_type=MissionType.ANALYZE_REQUIREMENTS):
    return build_mission_contract(
        Mission(
            key=key, mission_type=mission_type, spec={}, protocol_version="v1alpha1",
            objective="Analyze the pinned source", priority=Priority.P1,
        ),
        CanonicalRun(key="RUN-ADAPTER"),
    )


def make_provider(tmp_path, *, oversized=False):
    script = tmp_path / "provider.py"
    script.write_text(f"""#!{sys.executable}
import json,pathlib,re,sys,time
prompt=sys.argv[-1]
mission=json.loads(prompt.split("TEST_MISSION_JSON:\\n",1)[1])
assert sys.argv[1:4] == ["--ask-for-approval", "never", "exec"]
assert sys.argv[sys.argv.index("--sandbox")+1] == "read-only"
schema=json.loads(pathlib.Path(sys.argv[sys.argv.index("--output-schema")+1]).read_text())
assert schema["additionalProperties"] is False
assert schema["properties"]["mission_id"]["enum"] == [mission["mission_id"]]
assert "do not write a result file" in prompt
assert "Runner performs official validation AFTER" in prompt
prefix=prompt.split("idempotency_key use the prefix ",1)[1].split(" followed by",1)[0]
assert re.search(schema["properties"]["proposals"]["items"]["properties"]["idempotency_key"]["pattern"], prefix+"proposal")
output=pathlib.Path(sys.argv[sys.argv.index("--output-last-message")+1])
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
        return [event async for event in adapter.execute(session, mission_contract(key))]

    results = await asyncio.gather(collect(first, "MISSION-A"), collect(second, "MISSION-B"))
    for events, expected in zip(results, ["MISSION-A", "MISSION-B"], strict=True):
        submitted = [event for event in events if event.type == "RESULT_SUBMITTED"]
        assert len(submitted) == 1
        assert submitted[0].payload["mission_id"] == expected
    outputs = list((tmp_path / ".hypertest" / "results").glob("*.json"))
    assert len([path for path in outputs if not path.name.endswith(".schema.json")]) == 2
    assert len([path for path in outputs if path.name.endswith(".schema.json")]) == 2
    await adapter.close(first)
    await adapter.close(second)


@pytest.mark.asyncio
async def test_codex_result_size_limit_rejects_provider_payload(tmp_path):
    adapter = CodexCliAdapter(binary=make_provider(tmp_path, oversized=True))
    session = await adapter.create_session(str(tmp_path))
    events = [event async for event in adapter.execute(session, mission_contract("MISSION-LARGE"))]
    assert not any(event.type == "RESULT_SUBMITTED" for event in events)
    assert any(
        event.type == "ERROR" and event.payload["error_code"] == "RESULT_INVALID"
        for event in events
    )
    await adapter.close(session)


@pytest.mark.parametrize(
    ("mission_type", "proposal_type", "reference_field"),
    [
        (MissionType.ANALYZE_REQUIREMENTS, "REQUIREMENT", "source_ref"),
        (MissionType.ANALYZE_RISKS, "RISK", "requirement_keys"),
        (MissionType.DESIGN_TESTS, "TEST_CASE", "risk_keys"),
        (MissionType.IMPLEMENT_TESTS, "TEST_IMPLEMENTATION", "test_case_keys"),
        (MissionType.DIAGNOSE_FAILURE, "FINDING", "evidence_keys"),
    ],
)
def test_every_supported_mission_has_typed_strict_provider_output(
    mission_type, proposal_type, reference_field
):
    contract = mission_contract("MISSION-SCHEMA", mission_type)
    assert contract["output_contract"]["proposal_type"] == proposal_type
    schema = codex_output_schema(contract)
    proposal = schema["properties"]["proposals"]["items"]
    assert proposal["properties"]["proposal_type"]["enum"] == [proposal_type]
    payload = proposal["properties"]["object_payload"]
    assert reference_field in payload["properties"]
    # A domain field named 'title' must survive stripping schema annotations.
    if mission_type is not MissionType.IMPLEMENT_TESTS:
        assert "title" in payload["properties"]
    else:
        pattern = payload["properties"]["symbol"]["pattern"]
        assert re.fullmatch(pattern, "TestCheckout::test_idempotency")
        assert not re.fullmatch(pattern, "TestCheckout")
    assert "metrics" not in schema["properties"]
    assert "provider_metadata" not in schema["properties"]
    assert "result_schema" in contract["output_contract"]

    def assert_strict(value):
        if isinstance(value, list):
            for item in value:
                assert_strict(item)
        elif isinstance(value, dict):
            assert "$ref" not in value
            assert "default" not in value
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for item in value.values():
                assert_strict(item)

    assert_strict(schema)


def test_provider_proposal_keys_are_stable_per_session_and_distinct_across_retries():
    mission = mission_contract("MISSION-RETRY")
    first = codex_output_schema(mission, idempotency_prefix="AS-FIRST:")
    repeated = codex_output_schema(mission, idempotency_prefix="AS-FIRST:")
    retry = codex_output_schema(mission, idempotency_prefix="AS-RETRY:")
    assert first == repeated
    assert first != retry
    first_pattern = first["properties"]["proposals"]["items"]["properties"]["idempotency_key"]["pattern"]
    retry_pattern = retry["properties"]["proposals"]["items"]["properties"]["idempotency_key"]["pattern"]
    assert re.search(first_pattern, "AS-FIRST:requirement-addition")
    assert not re.search(retry_pattern, "AS-FIRST:requirement-addition")
    assert re.search(retry_pattern, "AS-RETRY:requirement-addition")
    assert "pattern" not in mission["output_contract"]["result_schema"]["$defs"]["ProposalSubmission"]["properties"]["idempotency_key"]
