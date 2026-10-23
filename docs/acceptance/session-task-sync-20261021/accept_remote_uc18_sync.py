"""Official MCP SDK acceptance over an authorized SSH stdio command, without forwarding.

Requires an already prepared candidate, authorized Project and private scoped config.
Never creates a Project/grant, deploys code, migrates a DB, or executes SUT tests.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hypertest.interactive_client.security import private_create, private_directory, private_read

OUT = Path(__file__).resolve().parent
SGT = timezone(timedelta(hours=8))


def save(path: Path, value: dict):
    temporary = path.with_name("." + path.name + ".tmp")
    private_create(temporary, json.dumps(value, ensure_ascii=False, indent=2).encode())
    os.replace(temporary, path)


async def read_pages(session, identity, version):
    chunks, offset, task_id, total = [], 0, None, None
    while True:
        result = await session.call_tool("hypertest_get_task", {
            **identity, "version": version, "offset": offset, "limit": 24000})
        if result.isError:
            raise RuntimeError("Candidate task read rejected; preserve original sync key")
        page = result.structuredContent
        assert page["source"] == "AGENT_REPORTED" and page["format"] == "application/json"
        assert page["version"] == version and page["offset"] == offset
        if task_id is None:
            task_id, total = page["task_id"], page["total_chars"]
        assert page["task_id"] == task_id and page["total_chars"] == total
        chunks.append(page["content"])
        if page["complete"]:
            assert page["next_offset"] is None
            break
        offset = page["next_offset"]
    combined = "".join(chunks)
    assert len(combined) == total
    return json.loads(combined), len(chunks), total


async def main(args):
    bundle_path = OUT / "UC18_REMOTE_SOURCE_BUNDLE_V2.json"
    bundle_bytes = bundle_path.read_bytes()
    bundle = json.loads(bundle_bytes)
    project_id = str(UUID(args.project_id))
    identity = {"project_id": project_id, "provider": bundle["task"]["provider"],
                "session_id": bundle["task"]["session_id"]}
    payload = {**bundle["task"], **identity, "cases": bundle["cases"], "reports": bundle["reports"],
               "idempotency_key": args.idempotency_key, "expected_version": args.expected_version}
    state_dir = private_directory(args.state_dir)
    intent_path = state_dir / "remote-uc18-intent.json"
    request_digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    target = {"ssh_alias": args.ssh_alias, "remote_python": args.remote_python,
              "remote_config": args.remote_config, "candidate_label": args.candidate_label}
    immutable = {"target": target, "identity": identity, "idempotency_key": args.idempotency_key,
                 "expected_version": args.expected_version, "request_digest": request_digest,
                 "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest()}
    if intent_path.exists():
        state = json.loads(private_read(intent_path))
        if any(state.get(key) != value for key, value in immutable.items()):
            raise RuntimeError("Original remote intent differs; do not retarget or replace its key")
    else:
        state = {**immutable, "state": "PREPARED", "created_at": datetime.now(SGT).isoformat()}
        save(intent_path, state)
    command = "exec " + shlex.quote(args.remote_python) + " -m hypertest.interactive_client stdio --config " + shlex.quote(args.remote_config) + " --autostart"
    params = StdioServerParameters(command="ssh", args=["-T", "-o", "BatchMode=yes", "-o",
        "PreferredAuthentications=publickey", "-o", "StrictHostKeyChecking=yes", args.ssh_alias, command])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            by_name = {tool.name: tool for tool in tools.tools}
            assert {"hypertest_sync_task", "hypertest_get_task"} <= by_name.keys()
            assert "version" in by_name["hypertest_get_task"].inputSchema["properties"]
            if state["state"] == "PREPARED":
                state["state"] = "SENT_OR_UNKNOWN"
                save(intent_path, state)
                result = await session.call_tool("hypertest_sync_task", payload)
            else:
                # Process death before a response never authorizes a second POST.
                result = await session.call_tool("hypertest_get_task", {
                    "project_id": project_id, "idempotency_key": args.idempotency_key})
            if result.isError or result.structuredContent.get("status") != "ACCEPTED":
                state["state"] = "UNKNOWN"
                save(intent_path, state)
                raise RuntimeError("Original sync is not confirmed; query its original key only")
            receipt = result.structuredContent
            assert receipt["idempotency_key"] == args.idempotency_key
            assert receipt["version"] == args.expected_version + 1
            assert all(receipt[field] == identity[field] for field in identity)
            state.update(state="ACKED", receipt=receipt)
            save(intent_path, state)
            query = await session.call_tool("hypertest_get_task", {
                "project_id": project_id, "idempotency_key": args.idempotency_key})
            assert not query.isError and query.structuredContent == receipt
            current, page_count, total_chars = await read_pages(session, identity, receipt["version"])
            assert current["task"]["id"] == receipt["task_id"]
            assert all(current["task"][field] == identity[field] for field in identity)
            assert current["task"]["source"] == "AGENT_REPORTED"
            assert all(current["task"][field] == value for field, value in bundle["task"].items())
            assert current["task"]["status"] == "IN_PROGRESS" and current["task"]["reported_result"] == "FAIL"
            assert len(current["cases"]) == 15 and len(current["reports"]) == 2
            results = {case["key"]: case["reported_result"] for case in current["cases"]}
            assert {key for key, value in results.items() if value == "FAIL"} == {"CASE-002", "CASE-009"}
            assert {key for key, value in results.items() if value == "UNKNOWN"} == {"CASE-013", "CASE-014", "CASE-015"}
            for original in bundle["cases"]:
                saved = next(case for case in current["cases"] if case["key"] == original["key"])
                assert all(saved[field] == value for field, value in original.items())
                assert saved["source"] == "AGENT_REPORTED"
            for report in bundle["reports"]:
                saved = next(item for item in current["reports"] if item["key"] == report["key"])
                assert saved["markdown"].encode() == report["markdown"].encode()
                assert saved["source_ref"] == report["source_ref"] and saved["reported_result"] == "FAIL"
    observation = {"environment": "REMOTE_ISOLATED_CANDIDATE", "target": target,
        "transport": "Mac official MCP SDK -> SSH management stdio (no forwarding) -> remote private daemon -> candidate loopback API",
        "receipt": receipt, "source_session_id": identity["session_id"], "cases": 15,
        "automatic_subset": {"cases": 12, "PASS": 10, "FAIL": 2},
        "designed_without_item_result": {"UNKNOWN": ["CASE-013", "CASE-014", "CASE-015"]},
        "independent_business_report": {"PASS": 11, "FAIL": 1}, "reports_exact_readback": True,
        "pages": page_count, "reconstructed_chars": total_chars,
        "source_bundle_sha256": immutable["bundle_sha256"], "original_receipt_readback": True,
        "sut_tests_executed": 0, "production_current_changed_by_script": False,
        "execution_count_verification": "Separate remote backend counter observation required",
        "checked_at": datetime.now(SGT).isoformat()}
    (OUT / "REMOTE_MCP_OBSERVATIONS.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2))
    print(json.dumps({key: observation[key] for key in ("environment", "receipt", "cases",
        "reports_exact_readback", "pages", "sut_tests_executed", "production_current_changed_by_script")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-alias", default="hypertest-one")
    parser.add_argument("--remote-python", required=True)
    parser.add_argument("--remote-config", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--candidate-label", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    try:
        asyncio.run(main(parser.parse_args()))
    except (RuntimeError, AssertionError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
