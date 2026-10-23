"""Bounded MCP reads reconstruct immutable task versions without losing raw reports."""
import json

from test_session_tasks import body, sync
from test_session_tasks import context as context

from hypertest.interactive_client import MAX_MESSAGE


async def read_page(f, session_id, **params):
    return await f["c"].get("/api/v1/interactive/tasks/by-session", headers=f["headers"],
        params={"project_id": f["project_id"], "provider": "codex", "session_id": session_id, **params})


async def test_large_reports_roundtrip_in_bounded_pages_and_receipts_remain_thin(context):
    f = context
    originals = ["a" * 259000 + "\n第一行😀" * 100, "b" * 260000]
    payload = body(f, reports=[{"key": str(index), "title": "Large original report",
        "markdown": markdown, "reported_result": "FAIL"} for index, markdown in enumerate(originals)])
    accepted = await sync(f, payload)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    assert set(receipt) == {"status", "profile", "task_id", "project_id", "provider", "session_id",
                            "version", "idempotency_key", "source"}
    assert len(accepted.content) < 2000
    assert receipt["project_id"] == f["project_id"] and receipt["session_id"] == payload["session_id"]
    recovered = await f["c"].get("/api/v1/interactive/tasks/syncs/by-key", headers=f["headers"],
        params={"project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]})
    assert recovered.json() == receipt and len(recovered.content) < 2000
    # The original failure: unbounded Web detail duplicates current + historical
    # reports and exceeds the private client's message budget for valid inputs.
    web = await f["c"].get("/api/v1/tasks/" + receipt["task_id"])
    assert len(web.content) > MAX_MESSAGE
    chunks = []
    offset = 0
    selected = None
    while True:
        response = await read_page(f, payload["session_id"], offset=offset,
                                   **({"version": selected} if selected else {}))
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["task_id"] == receipt["task_id"] and page["version"] == receipt["version"]
        assert page["format"] == "application/json" and page["source"] == "AGENT_REPORTED"
        assert page["offset"] == offset and len(page["content"]) <= 24000
        assert len(response.content) < MAX_MESSAGE
        chunks.append(page["content"])
        selected = page["version"]
        if page["complete"]:
            assert page["next_offset"] is None
            break
        assert page["next_offset"] == offset + len(page["content"])
        offset = page["next_offset"]
    raw = "".join(chunks)
    assert len(raw) == page["total_chars"]
    document = json.loads(raw)
    assert set(document) == {"task", "cases", "reports"}
    assert [report["markdown"] for report in document["reports"]] == originals
    assert document["task"]["reported_result"] == "FAIL"


async def test_continuation_pins_original_version_across_a_new_sync(context):
    f = context
    payload = body(f)
    accepted = (await sync(f, payload)).json()
    first = (await read_page(f, payload["session_id"], limit=80)).json()
    assert first["version"] == 1 and not first["complete"]
    updated = {**payload, "idempotency_key": "changed-during-read", "expected_version": 1,
        "title": "New task version", "reported_result": "PASS",
        "reports": [{**payload["reports"][0], "markdown": "New report", "reported_result": "PASS"}]}
    assert (await sync(f, updated)).json()["version"] == 2
    continuation = (await read_page(f, payload["session_id"], version=first["version"],
                                   offset=first["next_offset"])).json()
    assert continuation["version"] == 1 and continuation["complete"]
    original = json.loads(first["content"] + continuation["content"])
    assert original["task"]["title"] == payload["title"]
    assert original["reports"][0]["markdown"] == payload["reports"][0]["markdown"]
    current = (await read_page(f, payload["session_id"])).json()
    assert current["version"] == 2
    assert json.loads(current["content"])["reports"][0]["markdown"] == "New report"
    receipt = await f["c"].get("/api/v1/interactive/tasks/syncs/by-key", headers=f["headers"],
        params={"project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]})
    assert receipt.json() == accepted  # original receipt is independent of the newer snapshot


async def test_page_boundaries_require_a_version_and_never_silently_mix_snapshots(context):
    f = context
    payload = body(f)
    await sync(f, payload)
    for params in ({"offset": 1}, {"limit": 24001}, {"limit": 0}, {"offset": -1},
                   {"version": 0}, {"version": 1, "offset": 1000000000}):
        response = await read_page(f, payload["session_id"], **params)
        assert response.status_code == 422, (params, response.text)
    missing = await read_page(f, payload["session_id"], version=999999)
    assert missing.status_code == 404
