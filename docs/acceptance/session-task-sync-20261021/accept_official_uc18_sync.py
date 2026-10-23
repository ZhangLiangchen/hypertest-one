"""Remote-server official wheel + MCP SDK management acceptance.

Run only on the authorized remote test server. Requires an existing target
Project, scoped private config and installed fixed release. No deployment,
Project/grant creation, SUT execution, or automatic write replay occurs here.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import ssl
import stat
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from importlib.metadata import distribution, version as installed_version
from pathlib import Path
from uuid import UUID
from urllib.parse import urlsplit

import httpx

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hypertest.interactive_client.api_client import ApiClient, ApiError
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.security import private_create, private_directory, private_read
from hypertest.interactive_client.service import InteractiveService, validate_sync_receipt, validate_task_page
from hypertest.interactive_client.host_adapter import make_host_adapter
from hypertest.interactive_client.ipc import LocalServer
from hypertest.interactive_client.journal import Journal

SGT = timezone(timedelta(hours=8))


def save(path: Path, value: dict):
    temporary = path.with_name("." + path.name + ".tmp")
    private_create(temporary, json.dumps(value, ensure_ascii=False, indent=2).encode())
    os.replace(temporary, path)


def tls_api(config, uds):
    if urlsplit(config.api_url).hostname != "localhost" or not config.ca_file:
        raise RuntimeError("Private TLS transport requires explicit localhost CA configuration")
    if not uds.is_absolute() or uds.is_symlink() or any(parent.is_symlink() for parent in uds.parents):
        raise RuntimeError("Private TLS UDS must not be symlinked")
    socket_info, parent_info = uds.stat(), uds.parent.stat()
    if (not stat.S_ISSOCK(socket_info.st_mode) or stat.S_IMODE(socket_info.st_mode) != 0o600
            or not stat.S_ISDIR(parent_info.st_mode) or stat.S_IMODE(parent_info.st_mode) != 0o700
            or socket_info.st_uid != os.getuid() or parent_info.st_uid != os.getuid()):
        raise RuntimeError("Private TLS UDS must be 0600 in a 0700 directory")
    context = ssl.create_default_context(cafile=str(config.ca_file))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    return ApiClient(config, transport=httpx.AsyncHTTPTransport(
        uds=str(uds), verify=context, trust_env=False, retries=0))


@asynccontextmanager
async def transport_daemon(config, uds):
    # All components are the released library. Only bootstrap chooses its public
    # transport= injection point; the stock daemon CLI has no UDS transport option.
    api = tls_api(config, uds)
    journal = Journal(config.state_dir / "client.sqlite3")
    service = InteractiveService(config, api, journal, make_host_adapter(config.model_dump(mode="json")))
    server = LocalServer(config, service)
    try:
        await server.start()
        yield
    finally:
        await server.close()
        await api.close()
        journal.close()


async def read_pages(session, identity, version):
    chunks, offset, task_id, total = [], 0, None, None
    while True:
        result = await session.call_tool("hypertest_get_task", {
            **identity, "version": version, "offset": offset, "limit": 24000})
        if result.isError:
            raise RuntimeError("Official task read rejected; preserve original sync key")
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


async def verify_client_readonly(args):
    # The new Mac grant is checked here on the remote test server. This branch
    # has no call to sync_task, no write intent and no local Mac process.
    assert sys.flags.isolated == 1 and installed_version("hypertest-one") == "0.2.0"
    if not args.expected_task_id or not args.expected_owner_actor_ref:
        raise RuntimeError("Read-only verification needs the accepted task and fixed owner")
    bundle = json.loads(args.bundle.read_bytes())
    identity = {"project_id": str(UUID(args.project_id)), "provider": bundle["task"]["provider"],
                "session_id": bundle["task"]["session_id"]}
    config = ClientConfig.load(args.config)
    if not config.api_url.startswith("https://") or config.allow_insecure_loopback:
        raise RuntimeError("Read-only grant verification requires actual trusted HTTPS")
    api = tls_api(config, args.tls_uds)
    try:
        receipt = await api.request("GET", "interactive/tasks/syncs/by-key", params={
            "project_id": identity["project_id"], "idempotency_key": args.idempotency_key})
        validate_sync_receipt(receipt, args.idempotency_key, args.expected_version,
                              args.expected_task_id, identity)
        pieces, offset, version = [], 0, receipt["version"]
        while True:
            params = {**identity, "version": version, "offset": offset, "limit": 24000}
            page = await api.request("GET", "interactive/tasks/by-session", params=params)
            validate_task_page(page, params)
            assert page["task_id"] == args.expected_task_id
            pieces.append(page["content"])
            if page["complete"]:
                break
            offset = page["next_offset"]
        current = json.loads("".join(pieces))
        task = current["task"]
        assert task["id"] == args.expected_task_id and task["version"] == version
        assert task["owner_actor_ref"] == args.expected_owner_actor_ref
        assert all(task[field] == value for field, value in identity.items())
        assert all(task[field] == value for field, value in bundle["task"].items())
    finally:
        await api.close()
    observation = {"remote_read_only_new_mac_grant": True, "task_id": task["id"],
        "project_id": identity["project_id"], "version": version,
        "owner_actor_ref": task["owner_actor_ref"], "source_session_id": identity["session_id"],
        "original_receipt": receipt, "all_task_fields_exact": True, "pinned_pages": len(pieces),
        "task_posts": 0, "mac_connection_started": False, "checked_at": datetime.now(SGT).isoformat()}
    save(args.output, observation)
    print(json.dumps(observation, ensure_ascii=False))


async def main(args):
    assert installed_version("hypertest-one") == "0.2.0"
    assert sys.flags.isolated == 1, "Run official remote SDK with python -I"
    assert Path(args.client_python).absolute() == Path(sys.executable).absolute()
    direct_url = json.loads(distribution("hypertest-one").read_text("direct_url.json") or "{}")
    assert not direct_url.get("dir_info", {}).get("editable", False)
    assert direct_url.get("archive_info", {}).get("hashes", {}).get("sha256") == args.wheel_sha256
    bundle_path = args.bundle
    bundle_bytes = bundle_path.read_bytes()
    bundle = json.loads(bundle_bytes)
    # Static privacy review is performed on the remote server before any write;
    # findings expose neither matched values nor the original report text.
    review_text = bundle["task"]["plan_markdown"] + "\n" + "\n".join(
        report["markdown"] for report in bundle["reports"])
    secret_patterns = [
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)\bBearer\s+[A-Za-z0-9_.=-]{24,}",
        r"https?://[^\s/:]+:[^\s/@]+@",
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key|password)\s*[:=]\s*[\"']?[A-Za-z0-9_+/=-]{24,}",
    ]
    if any(re.search(pattern, review_text) for pattern in secret_patterns):
        raise RuntimeError("Suspected credential pattern in frozen source; no write sent, inspect privately")
    privacy_review = {"suspected_credential_patterns": 0, "source_modified": False,
                      "before_any_script_write": True, "checked_at": datetime.now(SGT).isoformat()}
    project_id = str(UUID(args.project_id))
    identity = {"project_id": project_id, "provider": bundle["task"]["provider"],
                "session_id": bundle["task"]["session_id"]}
    payload = {**bundle["task"], **identity, "cases": bundle["cases"], "reports": bundle["reports"],
               "idempotency_key": args.idempotency_key, "expected_version": args.expected_version}
    state_dir = private_directory(args.state_dir)
    intent_path = state_dir / "official-uc18-intent.json"
    request_digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    config = ClientConfig.load(args.config)
    if not config.api_url.startswith("https://") or config.allow_insecure_loopback:
        raise RuntimeError("Official acceptance requires actual trusted HTTPS, no HTTP exception")
    target = {"client_python": args.client_python, "config_path": str(args.config),
              "environment_label": args.environment_label, "api_url": config.api_url,
              "client_distribution": "hypertest-one==0.2.0", "source_commit": args.source_commit,
              "wheel_sha256": args.wheel_sha256, "sdk_version": installed_version("mcp"),
              "sdk_executable": sys.executable, "tls_uds": str(args.tls_uds),
              "daemon_bootstrap": "official public constructors with explicit TLS UDS transport"}
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
    params = StdioServerParameters(command=args.client_python, args=[
        "-I", "-m", "hypertest.interactive_client", "stdio", "--config", str(args.config)])
    preflight = None
    if state["state"] == "PREPARED":
        # A first-intent GET determines the actual target version. This branch
        # never interprets a post-send 404 as permission to replay a write.
        api = tls_api(config, args.tls_uds)
        try:
            try:
                page = await api.request("GET", "interactive/tasks/by-session", params=identity)
            except ApiError as exc:
                if exc.status != 404 or args.expected_version != 0:
                    raise RuntimeError("Target read failed or expected version differs; no write sent") from None
                preflight = {"http_status": 404, "expected_version": 0, "before_first_send": True}
            else:
                validate_task_page(page, identity)
                if page["version"] != args.expected_version:
                    raise RuntimeError("Target version changed; preserve intent and inspect without writing")
                preflight = {"http_status": 200, "task_id": page["task_id"],
                             "version": page["version"], "before_first_send": True}
        finally:
            await api.close()
        state["preflight"] = preflight
        save(intent_path, state)
    async with transport_daemon(config, args.tls_uds):
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
                validate_sync_receipt(receipt, args.idempotency_key, args.expected_version,
                                      (state.get("receipt") or {}).get("task_id"), payload)
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
                    assert all(saved[field] == value for field, value in report.items())
                    assert saved["markdown"].encode() == report["markdown"].encode()
                    assert saved["source_ref"] == report["source_ref"] and saved["reported_result"] == "FAIL"
    observation = {"environment": "REMOTE_TEST_ENVIRONMENT_CURRENT", "target": target,
        "transport": "Remote official MCP SDK -> released stock stdio -> official IPC/service with private transport bootstrap -> real TLS over private UDS -> current API",
        "preflight": state.get("preflight"), "privacy_review": privacy_review,
        "task_fields_exact_readback": True,
        "all_case_fields_exact_readback": True, "all_report_fields_exact_readback": True,
        "observed_distribution": installed_version("hypertest-one"),
        "advertised_tool_names": sorted(by_name),
        "management_tools_used": ["hypertest_sync_task", "hypertest_get_task"],
        "tool_catalog_filtered_by_scope": False,
        "api_listener_process": "Temporary private TLS ASGI process, not the current Docker API PID",
        "current_database_identity_proof": "Separate backend listener/runtime evidence required",
        "stock_daemon_cli_supports_uds_option": False,
        "receipt": receipt, "source_session_id": identity["session_id"], "cases": 15,
        "automatic_subset": {"cases": 12, "PASS": 10, "FAIL": 2},
        "designed_without_item_result": {"UNKNOWN": ["CASE-013", "CASE-014", "CASE-015"]},
        "independent_business_report": {"PASS": 11, "FAIL": 1}, "reports_exact_readback": True,
        "pages": page_count, "reconstructed_chars": total_chars,
        "source_bundle_sha256": immutable["bundle_sha256"], "original_receipt_readback": True,
        "sut_tests_executed": 0, "deployment_changed_by_script": False,
        "execution_count_verification": "Separate remote backend counter observation required",
        "checked_at": datetime.now(SGT).isoformat()}
    save(args.output, observation)
    print(json.dumps({key: observation[key] for key in ("environment", "receipt", "cases",
        "reports_exact_readback", "pages", "sut_tests_executed", "deployment_changed_by_script")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-python", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tls-uds", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--environment-label", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--verify-client-readonly", action="store_true")
    parser.add_argument("--expected-task-id")
    parser.add_argument("--expected-owner-actor-ref")
    try:
        args = parser.parse_args()
        asyncio.run(verify_client_readonly(args) if args.verify_client_readonly else main(args))
    except (RuntimeError, AssertionError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
