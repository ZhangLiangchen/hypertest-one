"""Fixed-SDK recovery probes: all providers and work are synthetic and local."""
import hashlib
import http.server
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from hypertest.cloud import native_cordis
from hypertest.cloud import native_session_restore as restore
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.native_resume_identity import record_initial_identity


class _SyntheticProvider(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append({"tools": bool(body.get("tools"))})
        start = {"type": "message_start", "message": {"id": "msg-test", "type": "message", "role": "assistant",
                 "model": "deepseek-flash", "content": [], "stop_reason": None, "stop_sequence": None,
                 "usage": {"input_tokens": 10, "output_tokens": 0}}}
        if body.get("tools"):
            arguments = {"description": "Run a synthetic interrupted local tool", "command": self.server.command}
            blocks = [
                ("content_block_start", {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "tool_use", "id": "toolu_synthetic", "name": "bash", "input": {}}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta", "partial_json": json.dumps(arguments)}}),
            ]
            reason = "tool_use"
        else:
            blocks = [
                ("content_block_start", {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "text_delta", "text": "Synthetic"}}),
            ]
            reason = "end_turn"
        events = [("message_start", start), *blocks,
                  ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                  ("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason, "stop_sequence": None},
                   "usage": {"output_tokens": 10}}), ("message_stop", {"type": "message_stop"})]
        payload = "".join(f"event: {event}\ndata: {json.dumps(value)}\n\n" for event, value in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def _synthetic_git(directory: Path) -> str:
    directory.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(directory), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(directory)], env=env, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(directory), "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "Synthetic"], env=env, check=True, stdout=subprocess.DEVNULL)
    return subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], env=env, text=True).strip()


@pytest.mark.asyncio
async def test_fixed_sdk_interrupted_tool_is_not_replayed(tmp_path, monkeypatch):
    sdk = pytest.importorskip("deepseek_harness")
    runtime = pytest.importorskip("deepseek_harness_runtime")
    binary = Path(runtime.resolve_bundled_launch_args()[0])
    with binary.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != native_cordis._RUNTIME_SHA256:
            pytest.skip("the audited native SDK runtime is not installed")
    root = tmp_path.resolve()
    attempt_id = str(uuid4())
    home, attempt_root = root / "dsh", root / ("attempt-" + attempt_id)
    workspace = attempt_root / "workspace"
    profile = home / "profiles" / "sdk"
    profile.mkdir(parents=True)
    attempt_root.mkdir(mode=0o700)
    workspace.mkdir()
    sut = _synthetic_git(workspace / "sut")
    framework = _synthetic_git(workspace / "framework")
    (profile / "package.json").write_text(json.dumps({"name": "dsh-profile-sdk", "private": True, "dependencies": {},
        "dsh": {"profile": {"bundles": [*restore._BASE, *sorted(restore._EXPERIMENTAL)]}}}))
    (profile / "cordis.patch.yml").write_text("[]\n")
    marker, tool_pid_file = workspace / "executions", workspace / "tool.pid"
    provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticProvider)
    provider.requests = []
    provider.command = f'printf "run\\n" >> {marker}; echo $$ > {tool_pid_file}; exec sleep 30'
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    fake_env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8", "DSH_PERMISSION_MODE": "danger-full-access",
                "DEEPSEEK_API_KEY": "synthetic-invalid", "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{provider.server_port}/v1"}
    monkeypatch.setattr(os, "environ", dict(fake_env))
    session_id = "cloud-" + attempt_id
    selection = {"provider": "deepseek-official", "model": "deepseek-flash"}
    identity = {"project_id": str(uuid4()), "task_id": str(uuid4()), "attempt_id": attempt_id,
                "session_id": session_id, "input_digest": "a" * 64, "prompt_sha256": "b" * 64,
                "title_sha256": hashlib.sha256(b"Synthetic task").hexdigest(),
                "workspace": workspace, "dsh_home": home, "sut_commit": sut, "framework_commit": framework,
                "selection": selection, "environment": dict(fake_env), "worker_id": "synthetic-worker",
                "original_generation": 1}
    tool_pid = None
    try:
        config = sdk.HarnessConfig(profile="sdk", dsh_home=str(home), cwd=str(workspace),
                                   env={"DSH_PERMISSION_MODE": "danger-full-access"}, request_timeout_seconds=12)
        with sdk.HarnessClient(config) as client:
            client.initialize(cwd=str(workspace), **selection)
            digest = record_initial_identity(attempt_root, **identity)
            intent = attempt_root / "prompt-intent.json"
            intent.write_text(json.dumps({"state": "SENT", "session_id": session_id, "prompt_sha256": "b" * 64}))
            intent.chmod(0o600)
            client.session_prompt(session_id, [{"type": "text", "text": "Synthetic local tool call."}])
            deadline = time.monotonic() + 12
            while not tool_pid_file.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            assert tool_pid_file.exists(), "synthetic tool did not start"
            tool_pid = int(tool_pid_file.read_text())
            assert marker.read_text().splitlines() == ["run"]
            # This second input remains pending while the first tool is running.
            client.session_prompt(session_id, [{"type": "text", "text": "Synthetic queued input."}])
            time.sleep(1)  # Allow the SDK's asynchronous persistence to flush.
            client._proc.kill()
            client._proc.wait(timeout=4)
        try:
            os.kill(tool_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # A malformed original credentials file would make default SDK startup
        # fail. Inspection must redirect credentials to its private empty file.
        (home / ".credentials.yaml").write_text("malformed: [\n")
        (home / ".credentials.yaml").chmod(0o600)
        before = len(provider.requests)
        python = next((path / "bin/python" for path in Path(runtime.__file__).resolve().parents
                       if (path / "bin/python").is_file()), None)
        if python is None:
            pytest.skip("the SDK virtual environment is unavailable")
        # Observe the inbox only on throwaway copies: SDK resume and close
        # mutate the persisted stream and can consume queued messages.
        session_file = next((home / "sessions").rglob("session.v4.jsonl.zstd"))
        before_bytes = session_file.read_bytes()

        def pending_on_copy(label):
            copied_home = root / ("home-copy-" + label)
            shutil.copytree(home, copied_home)
            probe_root = root / ("probe-" + label)
            probe_root.mkdir()
            overlay = restore._prepare_inspection_overlay(probe_root)
            hook, result_path = probe_root / "inbox-probe.mjs", probe_root / "result.json"
            hook.write_text(
                'import {writeFileSync} from "node:fs"; export const name="inbox-probe"; '
                'export function apply(ctx, config) {ctx.on("agent/created", ({agent})=>{'
                'if(agent.id===config.root) writeFileSync(config.out,JSON.stringify({pending:agent.inbox.hasPending}));});}\n'
            )
            with overlay.open("a") as stream:
                stream.write(yaml.safe_dump([{"insert": [{"id": "inbox-probe", "name": str(hook),
                    "config": {"root": session_id, "out": str(result_path)}}]}], sort_keys=False))
            probe_config = sdk.HarnessConfig(profile="sdk", dsh_home=str(copied_home), cwd=str(workspace),
                patches=(str(overlay),), env={"DSH_SDK_CORDIS_ROOT": session_id,
                    "DSH_SDK_CORDIS_NONCE": "a" * 64, "DSH_SDK_CORDIS_HANDSHAKE": str(probe_root / "registered.json")},
                request_timeout_seconds=12)
            with sdk.HarnessClient(probe_config) as client:
                client.initialize(cwd=str(workspace), **selection)
                client.resume_session(session_id)
                return json.loads(result_path.read_text())["pending"]

        assert pending_on_copy("before") is True
        inspection = {**identity, "identity_digest": digest}
        candidate = restore.anchored_identity_for_inspection(attempt_root=attempt_root, dsh_home=home,
            inspection=inspection, worker_id="synthetic-worker", environment=dict(fake_env))
        async def active():
            pytest.fail("disabled inspection must not request authority")
        for inspect in (restore._inspect_in_child, restore.inspect_original_session):
            with pytest.raises(CloudBlocked) as error:
                inspect(attempt_root=attempt_root, expected_identity_digest=digest, identity=candidate)
            assert error.value.code == "NATIVE_SESSION_RESTORE_UNAVAILABLE"
        with pytest.raises(CloudBlocked) as error:
            await restore.inspect_original_session_guarded(attempt_root=attempt_root,
                expected_identity_digest=digest, identity=candidate, assert_active=active)
        assert error.value.code == "NATIVE_SESSION_RESTORE_UNAVAILABLE"
        assert session_file.read_bytes() == before_bytes
        assert pending_on_copy("after") is True
        assert len(provider.requests) == before
        assert marker.read_text().splitlines() == ["run"]
    finally:
        if tool_pid is not None:
            try:
                os.kill(tool_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=5)
