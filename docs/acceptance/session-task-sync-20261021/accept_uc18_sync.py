"""Local-only official MCP SDK acceptance using existing UC18 assets; never runs SUT tests.

Re-running uses the same private intent/journal and queries previously sent writes.
The exported source bundle has no destination Project UUID; production mapping is separate.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import yaml
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = Path.home() / ".local/share/hypertest/session-sync-dev-20261021"
SOURCE = Path("/Users/zhangliangchen/PycharmProjects/hypervise_pure/docs/usecases/UC-TX-18-dev166-multi-energy-provider-routing")
SESSION = "01a143f4-4ec0-7451-ab23-8e59c6deb223"
API = "http://127.0.0.1:8101/api/v1"
SGT = timezone(timedelta(hours=8))


def private_json(path, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode()
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def capture():
    target = OUT / "UC18_SOURCE_BUNDLE.json"
    if target.exists():
        return json.loads(target.read_text())
    names = ["01_business_brief.md", "03_inventory.yaml", "03a_test_cases.md",
             "04_execution_report.md", "completion.json",
             "00_multiview/regression-independent-20261021.md"]
    raw = {name: (SOURCE / name).read_bytes() for name in names}
    decoded = {name: value.decode("utf-8") for name, value in raw.items()}
    # These are credential assignments, not public chain contract addresses or
    # references to the word Key. Stop without printing any matching content.
    secret_pattern = re.compile(r"(?i)(?:authorization\s*:\s*bearer\s+\S+|"
                                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
                                r"(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_+/=-]{16,})")
    if any(secret_pattern.search(value) for value in decoded.values()):
        raise RuntimeError("Potential credential assignment in source; inspect privately before capture")
    inventory = yaml.safe_load(decoded["03_inventory.yaml"])
    original_report = decoded["04_execution_report.md"]
    rows = {}
    for line in original_report.splitlines():
        match = re.match(r"\|\s*([A-Z]{2}\d{2})\s*/\s*(CASE-\d{3})\s*\|.*?\|\s*(PASS|FAIL)\s*\|", line)
        if match:
            rows[match[2]] = {"step": match[1], "result": match[3], "row": line}
    assert len(rows) == 12
    selected_cases = [case for case in inventory["cases"] if case["id"] in rows]
    assert len(selected_cases) == 12
    assert {key for key, value in rows.items() if value["result"] == "FAIL"} == {"CASE-002", "CASE-009"}
    cases = []
    for case in selected_cases:
        observed = rows[case["id"]]
        cases.append({"key": case["id"], "title": f'{case["step_id"]}：{case["intent"]}',
            "steps": ["原设计前置：" + item for item in case.get("preconditions", [])] + [
                f'既有逻辑步骤 {case["step_id"]}；scenario={case["scenario"]}；first_provider={case["first_provider"]}'],
            "expected": "\n".join(case["expected_observations"]),
            "actual": "原自动化报告结果（保留中断后 oracle 局限，业务独立复核见独立报告）：\n" + observed["row"],
            "reported_result": observed["result"], "implementation_ref": case["implementation_target"]})
    captured_at = datetime.now(SGT).isoformat()
    metadata = {"source_session_id": SESSION, "source_session_title": "xblock异步接口能量购买供应商接入",
        "source_session_state_at_capture": "ACTIVE_REPORTED_BY_PARENT",
        "captured_at": captured_at, "source_root": str(SOURCE),
        "scope": "Existing assets only; no SUT command, transaction, CI or test executed by this acceptance",
        "inventory_total": len(inventory["cases"]),
        "selected_executed_case_count": len(selected_cases),
        "not_imported_inventory_keys": [case["id"] for case in inventory["cases"] if case["id"] not in rows],
        "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in raw.items()],
        "automatic_results": {"PASS": 10, "FAIL": 2},
        "independent_business_results": {"PASS": 11, "FAIL": 1},
        "hash_semantics": "Captured content integrity only; not proof of test execution"}
    plan = (f"# UC18 测试任务资产快照\n\n来源会话 `{SESSION}`；captured_at `{captured_at}`。\n"
            "捕获时源会话仍在工作；本任务保持 IN_PROGRESS，本快照不宣称聊天或全部测试工作完成。\n"
            "自动断言10 PASS/2 FAIL，独立业务复核11 PASS/1 FAIL；两种口径分别保存，自动失败不改写。\n"
            "本同步不执行或重跑SUT测试，原执行/恢复/UNKNOWN与未完成项以原报告为准。\n\n"
            + decoded["01_business_brief.md"] + "\n\n" + decoded["03a_test_cases.md"])
    base = {"provider": "codex", "session_id": SESSION, "title": metadata["source_session_title"],
        "objective": "管理 UC-TX-18 dev166 多能源供应商路由的既有测试任务、12个用例与原始报告；不重跑测试。",
        "status": "IN_PROGRESS", "plan_markdown": plan, "reported_result": "FAIL"}
    reports = [{"key": "uc18-20261021-r1-automatic", "title": "UC18 原始执行报告：自动10 PASS / 2 FAIL",
        "markdown": original_report, "source_ref": str(SOURCE / "04_execution_report.md"), "reported_result": "FAIL"},
        {"key": "uc18-20261021-r1-independent", "title": "UC18 独立业务复核：11 PASS / 1 FAIL",
        "markdown": decoded["00_multiview/regression-independent-20261021.md"],
        "source_ref": str(SOURCE / "00_multiview/regression-independent-20261021.md"), "reported_result": "FAIL"}]
    bundle = {"metadata": metadata, "task": base, "cases": cases, "reports": reports,
              "destination": "Unbound: resolve the authorized target Project and latest task version before any non-local sync"}
    target.write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
    return bundle


async def execution_counts(database_url):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return {table: await connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in (
                "test_runs", "durable_jobs", "run_execution_bindings", "test_executions", "evidence", "verdicts", "native_test_runs")}
    finally:
        await engine.dispose()


async def prepare():
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = PRIVATE / "mcp-config.json"
    state_path = PRIVATE / "acceptance-bootstrap.json"
    env = dotenv_values(PRIVATE / "runtime.env")
    state = json.loads(state_path.read_text()) if state_path.exists() else {"client_instance_id": str(uuid4())}
    headers = {"X-Hypertest-Operator-Key": env["HYPERTEST_CONNECTOR_OPERATOR_KEY"]}
    async with httpx.AsyncClient(base_url=API, timeout=30, trust_env=False) as http:
        if not state.get("project_id"):
            projects = (await http.get("/projects")).json()
            existing = [item for item in projects if item["key"] == "XBLOCK"]
            if existing:
                state["project_id"] = existing[0]["id"]
            else:
                if state.get("project_intent"):
                    raise RuntimeError("Original project create needs readback; do not replay")
                state["project_intent"] = "SENT_OR_UNKNOWN"
                private_json(state_path, state)
                response = await http.post("/projects", headers=headers, json={
                    "key": "XBLOCK", "name": "XBlock", "description": "Existing SUT test tasks synchronized from Codex; local management acceptance."})
                response.raise_for_status()
                state["project_id"] = response.json()["id"]
            private_json(state_path, state)
        token_path = PRIVATE / "task-sync.integration-token"
        if not token_path.exists():
            if state.get("registration_intent"):
                raise RuntimeError("Original grant issuance needs administrator reconciliation; do not replay")
            state["registration_intent"] = "SENT_OR_UNKNOWN"
            private_json(state_path, state)
            response = await http.post("/interactive/registrations", headers=headers, json={
                "actor_ref": "codex-local-uc18-task-sync", "client_instance_id": state["client_instance_id"],
                "project_id": state["project_id"], "scopes": ["task:sync"], "expires_in_days": 30})
            response.raise_for_status()
            registered = response.json()
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(registered.pop("integration_token"))
            state["registration"] = registered
            private_json(state_path, state)
        if not config_path.exists():
            private_json(config_path, {"api_url": API, "state_dir": str(PRIVATE / "mcp-state"),
                "integration_token_file": str(token_path), "allow_insecure_loopback": True,
                "host_adapter": {"kind": "unsupported"}})
    return state, config_path, env["HYPERTEST_DATABASE_URL"]


async def read_current(session, identity):
    chunks, offset, version, task_id, total = [], 0, None, None, None
    while True:
        arguments = {**identity, "offset": offset, "limit": 24000}
        if version is not None:
            arguments["version"] = version
        result = await session.call_tool("hypertest_get_task", arguments)
        assert not result.isError
        page = result.structuredContent
        if version is None:
            version, task_id, total = page["version"], page["task_id"], page["total_chars"]
        assert (page["version"], page["task_id"], page["total_chars"]) == (version, task_id, total)
        chunks.append(page["content"])
        if page["complete"]:
            break
        offset = page["next_offset"]
    combined = "".join(chunks)
    assert len(combined) == total
    return json.loads(combined)


async def main():
    bundle = capture()
    state, config_path, database_url = await prepare()
    counts_before = await execution_counts(database_url)
    events = []
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "hypertest.interactive_client",
        "stdio", "--config", str(config_path), "--autostart"], cwd=str(ROOT))
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            assert {"hypertest_sync_task", "hypertest_get_task"} <= set(names)
            task_id = None
            for index, report in enumerate(bundle["reports"], start=1):
                payload = {**bundle["task"], "project_id": state["project_id"],
                    "idempotency_key": f"uc18-local-20261021-assets-{index}", "expected_version": index - 1,
                    "cases": bundle["cases"] if index == 1 else [], "reports": [report]}
                result = await session.call_tool("hypertest_sync_task", payload)
                assert not result.isError, result.content
                receipt = result.structuredContent
                assert receipt["status"] == "ACCEPTED" and receipt["version"] == index, receipt
                task_id = receipt["task_id"]
                replay = await session.call_tool("hypertest_sync_task", payload)
                assert not replay.isError and replay.structuredContent == receipt
                readback = await session.call_tool("hypertest_get_task", {
                    "project_id": state["project_id"], "idempotency_key": payload["idempotency_key"]})
                assert not readback.isError and readback.structuredContent == receipt
                events.append({"operation": "sync/replay-query/receipt-get", "receipt": receipt})
            task = await read_current(session, {"project_id": state["project_id"],
                "provider": "codex", "session_id": SESSION})
            assert task["task"]["status"] == "IN_PROGRESS" and task["task"]["reported_result"] == "FAIL"
            assert len(task["cases"]) == 12
            assert {item["key"] for item in task["cases"] if item["reported_result"] == "FAIL"} == {"CASE-002", "CASE-009"}
            assert len(task["reports"]) == 2
            for original in bundle["reports"]:
                saved = next(item for item in task["reports"] if item["key"] == original["key"])
                assert saved["markdown"].encode() == original["markdown"].encode()
                assert saved["reported_result"] == "FAIL" and saved["source"] == "AGENT_REPORTED"
    async with httpx.AsyncClient(base_url=API, timeout=30, trust_env=False) as http:
        detail = (await http.get(f"/tasks/{task_id}")).json()
        assert len(detail["case_history"]) == 12 and len(detail["report_history"]) == 2
        historic = (await http.get(f"/tasks/{task_id}", params={"version": 1})).json()
        assert historic["task"]["version"] == 1 and len(historic["reports"]) == 1
        assert len(historic["cases"]) == 12
    counts_after = await execution_counts(database_url)
    assert counts_after == counts_before, (counts_before, counts_after)
    observation = {"environment": "LOCAL_DEVELOPMENT_ONLY", "api_url": API,
        "sdk_transport": "Official MCP SDK stdio subprocess -> private daemon -> typed HTTP API",
        "project_id": state["project_id"], "task_id": task_id, "source_session_id": SESSION,
        "captured_at": bundle["metadata"]["captured_at"], "source_session_completed": False,
        "task_status": task["task"]["status"], "reported_result": task["task"]["reported_result"],
        "task_version": 2, "cases": 12, "automatic_results": {"PASS": 10, "FAIL": 2},
        "independent_business_results": {"PASS": 11, "FAIL": 1},
        "raw_reports_exact_readback": True, "reports": 2, "history_version1_readback": True,
        "events": events, "execution_counts_before": counts_before, "execution_counts_after": counts_after,
        "sut_tests_executed_by_acceptance": 0, "production_synced": False,
        "private_config_path": str(config_path), "tools": names,
        "checked_at": datetime.now(SGT).isoformat()}
    (OUT / "MCP_OBSERVATIONS.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2))
    print(json.dumps({key: observation[key] for key in ("environment", "project_id", "task_id", "task_version",
        "cases", "reports", "raw_reports_exact_readback", "sut_tests_executed_by_acceptance", "production_synced")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
