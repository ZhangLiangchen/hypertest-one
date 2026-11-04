"""Actual installed Web reader before a separate SDK writer; no model input."""
import asyncio
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import websockets
import yaml
from test_cloud_native_cordis_sdk import _client
from test_cloud_native_cordis_sdk import fake_provider as fake_provider
from test_cloud_native_cordis_sdk import sdk as sdk

ROOT = "cloud-11111111-1111-4111-8111-111111111111"
PERSONAL = "personal-readonly-regression"
CLI = Path("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh")


def _session_bytes(home):
    return {str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (home / "sessions").rglob("*.jsonl.zstd")}


@contextmanager
def _actual_web(sdk, fake_provider, plugin):
    if not CLI.is_file():
        pytest.skip("installed native Web app is required for cross-host regression")
    _, home, private, _ = sdk
    patch = private / "native-readonly-web.yml"
    patch.write_text(yaml.safe_dump([{"insert": [{"id": "hypertest-readonly-sessions",
        "name": str(plugin), "config": {"pollIntervalMs": 250}}]}], sort_keys=False))
    # This is the installed App's Web profile, not the SDK's similar Controller.
    # Only persistence is shared. Auth, profiles and listener are synthetic.
    env = {"PATH": "/usr/bin:/bin", "HOME": str(private), "DSH_HOME": str(home), "LANG": "C.UTF-8",
        "DEEPSEEK_API_KEY": "synthetic-invalid-key",
        "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{fake_provider.server_port}/v1"}
    log = private / "isolated-web.log"
    with log.open("wb") as output:
        log.chmod(0o600)
        process = subprocess.Popen([str(CLI), "--profile", "isolated-readonly-web", "--from-default-profile", "web",
            "--patch", str(patch), "--host", "127.0.0.1", "--port", "0", "--no-open"],
            env=env, cwd=private, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.monotonic() + 25
        url = None
        while time.monotonic() < deadline:
            matches = re.findall(r"http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_-]+", log.read_text(errors="replace"))
            if matches:
                url = matches[-1]
                break
            if process.poll() is not None:
                pytest.fail("isolated actual Web host exited before readiness (private log retained)")
            time.sleep(.05)
        assert url is not None, "isolated actual Web host did not advertise readiness"
        base = url.split("/?", 1)[0]
        with httpx.Client(trust_env=False, timeout=10, follow_redirects=False) as client:
            auth = client.get(url)
            assert auth.status_code == 303 and client.cookies
            cookie = client.build_request("GET", base).headers["cookie"]
            yield process, base, client, cookie
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def _rpc(client, base, method, request):
    response = client.post(base + "/api/" + method, json={"type": "client-request",
        "rpcId": "synthetic-readonly-regression", "method": method, "payload": {"args": {"request": request}}})
    assert response.status_code == 200
    return response.json()["result"]


async def _open_follow(ws, session_id, stream_id):
    await ws.send(json.dumps({"type": "open", "streamId": stream_id, "endpoint": "session/follow",
        "payload": {"args": {"request": {"address": {"kind": "session", "sessionId": session_id},
            "assistantStream": True}}}}))
    return await _next_item(ws, stream_id)


async def _next_item(ws, stream_id):
    async with asyncio.timeout(10):
        while True:
            frame = json.loads(await ws.recv())
            if frame.get("streamId") != stream_id:
                continue
            assert frame.get("type") == "item", f"native follow returned {frame.get('type')}: {frame.get('error')}"
            return frame["value"]


async def test_actual_web_history_first_keeps_writer_free_and_follows_sdk_changes(sdk, fake_provider):
    _, home, private, _ = sdk
    plugin = Path(__file__).resolve().parents[1] / "src/hypertest/cloud/harness_readonly_sessions.mjs"
    with _client(sdk, fake_provider, extra_env={"DSH_SDK_CORDIS_ROOT": ROOT}) as seed:
        seed.initialize(cwd=str(private), provider="deepseek-official", model="deepseek-flash", reasoning_effort="max")
        seed.get_working_directory(ROOT)
        seed.get_working_directory(PERSONAL)
        deadline = time.monotonic() + 5
        while len(_session_bytes(home)) != 2 and time.monotonic() < deadline:
            await asyncio.sleep(.05)
        assert len(_session_bytes(home)) == 2, "seed persistence must finish before its host closes"
    original = _session_bytes(home)
    assert len(original) == 2

    writer_probe = private / "writer-title.mjs"
    writer_probe.write_text('''export const name="synthetic-writer-title";
export const inject=["sessionTitle"];
export function apply(ctx) {
  ctx.on("agent/created",({agent})=>{
    if(agent.id==="cloud-11111111-1111-4111-8111-111111111111") {
      ctx.sessionTitle.rename(agent.session,"Synthetic external writer revision");
      setTimeout(()=>ctx.sessionTitle.rename(agent.session,"Synthetic external writer revision 2"),750);
    }
  });
}
''')
    writer_patch = private / "writer-title.yml"
    writer_patch.write_text(yaml.safe_dump([{"insert": [{"id": "synthetic-writer-title", "name": str(writer_probe)}]}]))

    with _actual_web(sdk, fake_provider, plugin) as (reader, base, client, cookie):
        async with websockets.connect(base.replace("http:", "ws:") + "/api/remote.mux", origin=base,
                additional_headers={"Cookie": cookie}, proxy=None, open_timeout=10) as ws:
            snapshot = await _open_follow(ws, ROOT, "cloud-reader-first")
            assert snapshot["type"] == "snapshot" and snapshot["header"]["id"] == ROOT
            assert snapshot["records"], "the native page must still receive persisted history"
            # Opening and holding the history must not perform the old native
            # promotion into an Agent, which acquires the session's writer lock.
            await asyncio.sleep(.3)
            assert _session_bytes(home) == original
            renamed = _rpc(client, base, "session/rename", {"sessionId": ROOT, "title": "Forbidden native write"})
            assert renamed.get("ok") is False and renamed.get("error", {}).get("code") == "session/read-only"
            prompted = _rpc(client, base, "session/prompt", {"sessionId": ROOT,
                "requestId": "readonly-must-reject", "mode": "queue",
                "content": [{"type": "text", "text": "Must never be enqueued by the native reader"}]})
            assert prompted.get("ok") is False and prompted.get("error", {}).get("code") == "session/read-only"
            assert _session_bytes(home) == original

            # Keep the exact same Web stream open BEFORE starting this second
            # host. Success here is the real writer-lock assertion.
            (private / "ready").unlink(missing_ok=True)
            with _client(sdk, fake_provider, (str(writer_patch),), {"DSH_SDK_CORDIS_ROOT": ROOT}) as writer:
                writer.initialize(cwd=str(private), provider="deepseek-official", model="deepseek-flash", reasoning_effort="max")
                writer.resume_session(ROOT)
                seen = []
                async with asyncio.timeout(10):
                    while not any(item.get("type") == "event" and item.get("event", {}).get("type") == "session/title"
                            and "Synthetic external writer revision 2" in json.dumps(item) for item in seen):
                        seen.append(await _next_item(ws, "cloud-reader-first"))
                titles = [item["event"] for item in seen if item.get("type") == "event"
                    and item.get("event", {}).get("type") == "session/title"
                    and item["event"]["data"]["title"].startswith("Synthetic external writer revision")]
                assert len(titles) == 2
                assert titles[0]["seq"] < titles[1]["seq"]
                projections = _rpc(client, base, "session/projections", {"sessionId": ROOT})
                assert projections["ok"] is True
                assert projections["value"]["values"]["title"] == "Synthetic external writer revision 2"
                assert reader.poll() is None
                assert _session_bytes(home) != original
                # Native mutation remains refused while Worker owns the writer.
                refusal = _rpc(client, base, "session/rename", {"sessionId": ROOT, "title": "Still forbidden"})
                assert refusal.get("ok") is False and refusal.get("error", {}).get("code") == "session/read-only"
            durable_after_writer = _session_bytes(home)
            await asyncio.sleep(.3)
            assert _session_bytes(home) == durable_after_writer
            await ws.send(json.dumps({"type": "cancel", "streamId": "cloud-reader-first"}))

            personal = await _open_follow(ws, PERSONAL, "personal-original-behavior")
            assert personal["type"] == "snapshot" and personal["header"]["id"] == PERSONAL
            writable = _rpc(client, base, "session/rename", {"sessionId": PERSONAL, "title": "Personal remains writable"})
            assert writable.get("ok") is True
            await ws.send(json.dumps({"type": "cancel", "streamId": "personal-original-behavior"}))
        assert fake_provider.request_count == 0
