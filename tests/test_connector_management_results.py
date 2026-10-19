"""Management call snapshots account old work without replaying a lost event window."""
from copy import deepcopy

import pytest
from test_connector_runtime import local_connector as _local_connector
from test_harness_bridge import context, contract, until_call

from hypertest.connector.results import normalize_result
from hypertest.harness_bridge.protocol import BridgeError

local_connector = _local_connector


async def test_long_call_management_snapshot_does_not_require_or_replay_evicted_events(local_connector):
    daemon, server, provider = local_connector
    ctx = context(server)
    await daemon.bridge.create_session(ctx)
    await daemon.bridge.start_call(ctx, contract(), call_id="long-call", resume=False)
    await until_call(daemon.bridge, ctx, "long-call", lambda value: value["stopped"])
    call = server.calls["long-call"]
    for _ in range(300):
        server.emit(call, {"type": "ACTIVITY", "payload": {"activity_kind": "MODEL_ACTIVITY"}})
    view = await daemon.bridge.get_call(ctx, "long-call", management=True)
    assert len(view["events"]) == 256 and view["events"][0]["sequence"] > 1
    payload = {"context": ctx.to_dict(), "call_id": "long-call", "cursor": 0}
    with pytest.raises(BridgeError, match="EVENT_CURSOR_GAP"):
        normalize_result("get_call", payload, view)
    projected = normalize_result("get_call", payload, view, management=True)
    assert projected["stopped"] and projected["elapsed_seconds"] == view["elapsed_seconds"]
    assert projected["call_id"] == "long-call" and projected["provider_session_id"] == view["provider_session_id"]
    assert projected["events"] == [] and projected["pending_tools"] == []
    assert len(view["events"]) == 256  # Projection does not mutate the local journal.
    assert len(provider.invocations) == 1
    with pytest.raises(BridgeError):
        normalize_result("get_call", payload, {**view, "raw_stdout": "provider transcript"}, management=True)


async def test_management_snapshot_strips_pending_work_and_rejects_internal_event_gaps(local_connector):
    daemon, server, _ = local_connector
    ctx = context(server)
    await daemon.bridge.create_session(ctx)
    await daemon.bridge.start_call(ctx, contract(), call_id="snapshot-call", resume=False)
    await until_call(daemon.bridge, ctx, "snapshot-call", lambda value: value["stopped"])
    view = await daemon.bridge.get_call(ctx, "snapshot-call", management=True)
    view = {**view, "cursor": 301, "events": [
        {"sequence": 300, "type": "ACTIVITY", "payload": {"activity_kind": "MODEL_ACTIVITY"}},
        {"sequence": 301, "type": "ACTIVITY", "payload": {"activity_kind": "TOOL_STARTED"}}],
        "pending_tools": [{"tool_call_id": "never-dispatch", "name": "request_execution",
            "arguments": {"idempotency_key": "original-pending-tool"}}]}
    payload = {"context": ctx.to_dict(), "call_id": "snapshot-call", "cursor": 0}
    projected = normalize_result("get_call", payload, view, management=True)
    assert projected["events"] == [] and projected["pending_tools"] == []
    bad = deepcopy(view)
    bad["events"][1]["sequence"] = 302
    bad["cursor"] = 302
    with pytest.raises(BridgeError, match="EVENT_CURSOR_GAP"):
        normalize_result("get_call", payload, bad, management=True)
    bad = {**view, "call_id": "other-call"}
    with pytest.raises(BridgeError):
        normalize_result("get_call", payload, bad, management=True)
