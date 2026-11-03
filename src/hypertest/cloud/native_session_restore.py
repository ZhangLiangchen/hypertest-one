"""Read-only inspection of an independently anchored native SDK session.

This is an internal primitive, not an Attempt resume endpoint.  Its caller must
first recover the original receipt, fence the original owner and reconcile
external operations.  It neither submits a prompt nor exposes a live client.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from .errors import CloudBlocked
from .native_cordis import _HOOK, prepare_cordis_overlay
from .native_resume_identity import (
    _MAX_RECORD,
    _NONSECRET_ENV,
    FILENAME,
    _canonical,
    _digest,
    _directory,
    _environment_digest,
    _private_attempt_root,
    _runtime_identity,
    _selection_digest,
    _uuid,
    verify_original_identity,
)
from .native_sdk_adapter import host_environment
from .native_sdk_driver import _require_cordis_guard
from .native_selection import read_native_selection
from .private_file import read_private_file

# Read-only inspection only supports the audited built-in profile composition.
# Unknown package trees or profile patches can run arbitrary code at startup and
# cannot be treated as safe simply because their bytes match an old identity.
_BASE = ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-sdk-app")
_EXPERIMENTAL = frozenset({
    "@deepseek-ai/dsh-experimental-agent-team-profile",
    "@deepseek-ai/dsh-experimental-tool-worktree",
    "@deepseek-ai/dsh-experimental-terminal-bundle",
    "@deepseek-ai/dsh-experimental-session-search",
    "@deepseek-ai/dsh-experimental-session-titles-bundle",
    "@deepseek-ai/dsh-experimental-ralph-bundle",
})
_FILES = frozenset({"package.json", "pnpm-workspace.yaml", "cordis.yml", "cordis.patch.yml"})
_DISABLED_FOR_INSPECTION = (
    "tool-executor-native", "tool-executor-ptc", "llm-deepseek", "llm-deepseek-account", "llm-pi-ai",
    "deepseek-account",
)
_IDENTITY_FIELDS = frozenset({"project_id", "task_id", "attempt_id", "session_id", "input_digest", "prompt_sha256",
                              "workspace", "dsh_home", "sut_commit", "framework_commit", "selection", "environment",
                              "worker_id", "original_generation"})
_ERROR_CODES = frozenset({"NATIVE_SESSION_IDENTITY_UNAVAILABLE", "NATIVE_SESSION_RESTORE_UNAVAILABLE",
                          "HARNESS_CORDIS_UNAVAILABLE", "HARNESS_CONFIG_UNAVAILABLE"})


def _check_inspection_profile(dsh_home: Path) -> None:
    root = dsh_home / "profiles" / "sdk"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("unsafe SDK profile")
    entries = {item.name for item in root.iterdir()}
    if not {"package.json", "cordis.patch.yml"}.issubset(entries) or not entries <= _FILES:
        raise ValueError("unreviewed SDK profile contents")
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("unsafe SDK profile file")
    package = json.loads((root / "package.json").read_bytes())
    bundles = package["dsh"]["profile"]["bundles"]
    if (not isinstance(package, dict) or set(package) != {"name", "private", "dependencies", "dsh"}
            or package.get("name") != "dsh-profile-sdk" or package.get("private") is not True
            or set(package["dsh"]) != {"profile"} or set(package["dsh"]["profile"]) != {"bundles"}
            or not isinstance(bundles, list) or tuple(bundles[:2]) != _BASE
            or len(bundles) != len(set(bundles)) or not set(bundles[2:]) <= _EXPERIMENTAL
            or package.get("dependencies") != {}):
        raise ValueError("unreviewed SDK bundles")
    if (root / "pnpm-workspace.yaml").exists() and yaml.safe_load((root / "pnpm-workspace.yaml").read_bytes()) != {
            "packages": ["."], "nodeLinker": "hoisted", "autoInstallPeers": False}:
        raise ValueError("unreviewed SDK workspace")
    if (root / "cordis.yml").exists() and yaml.safe_load((root / "cordis.yml").read_bytes()) != []:
        raise ValueError("unreviewed SDK root")
    rows = yaml.safe_load((root / "cordis.patch.yml").read_bytes())
    if not isinstance(rows, list) or len(rows) > 1:
        raise ValueError("invalid SDK patch")
    for row in rows:
        if (not isinstance(row, dict) or set(row) - {"id", "name", "config"}
                or row.get("id") != "agent-default-model"
                or row.get("name", "@deepseek-ai/dsh-agent-default-model") != "@deepseek-ai/dsh-agent-default-model"
                or not isinstance(row.get("config"), dict)
                or set(row["config"]) - {"provider", "model", "reasoningEffort"}):
            raise ValueError("unreviewed SDK patch")


def _prepare_inspection_overlay(directory: Path) -> Path:
    overlay = prepare_cordis_overlay(directory)
    hook = directory / "hypertest-cordis-root.mjs"
    if hook.read_text(encoding="utf-8") != _HOOK:
        raise ValueError("unexpected admission hook")
    original = '    if (agent.id !== root) return;\n'
    if _HOOK.count(original) != 1:
        raise ValueError("unexpected admission hook")
    # Restoring an existing session must not select a new preset or write a
    # preset event.  New sessions continue to use the unmodified Cordis guard.
    hook.write_text(_HOOK.replace(original, original + "    return; // retain the original persisted preset\n"), encoding="utf-8")
    additions = [{"id": plugin, "disabled": True} for plugin in _DISABLED_FOR_INSPECTION]
    # The SDK's required connection service depends on its credentials service.
    # Redirect that service to a private empty file, never the real DSH_HOME
    # credential store.  The launcher may also load .env files, rejected below.
    credential_path = directory / "empty-credentials.yaml"
    fd = os.open(credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(b"{}\n")
    additions.append({"id": "credentials", "config": {"path": str(credential_path), "watch": False}})
    with overlay.open("a", encoding="utf-8") as stream:
        stream.write(yaml.safe_dump(additions, sort_keys=False))
    return overlay


def anchored_identity_for_inspection(*, attempt_root: Path, dsh_home: Path, inspection: dict,
                                     worker_id: str, environment: dict) -> dict:
    """Construct a candidate only from the server's anchor and original private record.

    The eventual isolated child rechecks every field against the accepted digest.
    This function never creates or repairs the original identity file.
    """
    try:
        root = _private_attempt_root(Path(attempt_root))
        digest = _digest(inspection["identity_digest"])
        fd = os.open(root / FILENAME, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("unsafe original identity")
            encoded = stream.read(_MAX_RECORD + 1)
        if len(encoded) > _MAX_RECORD or hashlib.sha256(encoded).hexdigest() != digest:
            raise ValueError("original anchor mismatch")
        record = json.loads(encoded)
        if not isinstance(record, dict) or _canonical(record) != encoded:
            raise ValueError("invalid original identity")
        attempt_id = _uuid(inspection["attempt_id"])
        project_id, task_id = _uuid(inspection["project_id"]), _uuid(inspection["task_id"])
        session_id = "cloud-" + attempt_id
        if (root.name != "attempt-" + attempt_id or inspection["session_id"] != session_id
                or inspection["worker_id"] != worker_id
                or any(record.get(k) != value for k, value in {
                    "project_id": project_id, "task_id": task_id, "attempt_id": attempt_id,
                    "session_id": session_id, "input_digest": inspection["input_digest"],
                    "worker_id": worker_id, "original_generation": inspection["original_generation"],
                }.items())):
            raise ValueError("original identity does not match server")
        if record.get("source") != {"sut": inspection["sut_commit"], "framework": inspection["framework_commit"]}:
            raise ValueError("original source does not match server")
        intent = json.loads(read_private_file(root / "prompt-intent.json", max_bytes=4096))
        if (not isinstance(intent, dict) or set(intent) != {"state", "session_id", "prompt_sha256"}
                or intent["state"] != "SENT" or intent["session_id"] != session_id
                or intent["prompt_sha256"] != record.get("prompt_sha256")):
            raise ValueError("original prompt intent is missing or changed")
        workspace, home = root / "workspace", Path(dsh_home)
        if (_directory(workspace)[1] != record.get("workspace") or _directory(home)[1] != record.get("dsh_home")
                or _runtime_identity() != record.get("runtime")):
            raise ValueError("original runtime or directories changed")
        _environment_digest(environment)
        return {"project_id": project_id, "task_id": task_id, "attempt_id": attempt_id,
                "session_id": session_id, "input_digest": inspection["input_digest"],
                "prompt_sha256": record["prompt_sha256"], "workspace": str(workspace), "dsh_home": str(home),
                "sut_commit": inspection["sut_commit"], "framework_commit": inspection["framework_commit"],
                "selection": None, "environment": {k: v for k, v in environment.items()
                    if k in _NONSECRET_ENV or k == "DEEPSEEK_BASE_URL"},
                "worker_id": worker_id, "original_generation": inspection["original_generation"]}
    except Exception:
        raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Original session identity is missing or changed") from None


def _inspect_in_child(*, attempt_root: Path, expected_identity_digest: str, identity: dict) -> dict:
    """Restore and immediately close one anchored session without a prompt.

    ``expected_identity_digest`` must come from the authenticated original
    fenced server receipt, not from the local file or Agent.  This primitive
    does not authorize continuation, reconcile external operations, change a
    lease, or establish that an interrupted tool had no side effects.
    """
    try:
        if not isinstance(identity, dict):
            raise ValueError("original identity required")
        if "selection" not in identity or identity["selection"] is not None:
            verify_original_identity(attempt_root, expected_identity_digest=expected_identity_digest, **identity)
        else:
            # The model selection is resolved only in this credential-free
            # child, but the original receipt, paths and SDK must be checked
            # before executing even the SDK's configuration-dump command.
            server = {"identity_digest": expected_identity_digest, **{key: identity[key] for key in (
                "project_id", "task_id", "attempt_id", "session_id", "input_digest", "worker_id",
                "original_generation", "sut_commit", "framework_commit")}}
            candidate = anchored_identity_for_inspection(attempt_root=attempt_root,
                dsh_home=Path(identity["dsh_home"]), inspection=server,
                worker_id=identity["worker_id"], environment=identity["environment"])
            if candidate != {**identity, "workspace": str(identity["workspace"]), "dsh_home": str(identity["dsh_home"])}:
                raise ValueError("original identity mismatch")
        workspace = Path(identity["workspace"]).resolve(strict=True)
        dsh_home = Path(identity["dsh_home"]).resolve(strict=True)
        session_id = identity["session_id"]
        # SDK boot reads both paths before the profile overlay can be applied.
        # Even an unreadable or dangling .env is a reason to decline inspection.
        if os.path.lexists(workspace / ".env") or os.path.lexists(dsh_home / ".env"):
            raise ValueError("SDK would load a dotenv file")
        _check_inspection_profile(dsh_home)
        selection = read_native_selection(dsh_home=str(dsh_home), cwd=str(workspace), environment=dict(os.environ))
        if (identity["selection"] is not None and selection != identity["selection"]) or selection.get("provider") != "deepseek-official":
            raise ValueError("original model selection changed")
        identity = {**identity, "selection": selection}
        verify_original_identity(attempt_root, expected_identity_digest=expected_identity_digest, **identity)
        from deepseek_harness import HarnessClient, HarnessConfig

        with tempfile.TemporaryDirectory(prefix="hypertest-resume-inspection-") as private:
            directory = Path(private)
            overlay = _prepare_inspection_overlay(directory)
            marker, nonce = directory / "registered.json", secrets.token_hex(32)
            config = HarnessConfig(
                profile="sdk", dsh_home=str(dsh_home), cwd=str(workspace), patches=(str(overlay),),
                env={"DSH_SDK_CORDIS_ROOT": session_id, "DSH_SDK_CORDIS_NONCE": nonce,
                     "DSH_SDK_CORDIS_HANDSHAKE": str(marker)}, request_timeout_seconds=30,
            )
            with HarnessClient(config) as client:
                info = client.initialize(cwd=str(workspace), **selection).serverInfo
                if info is None or info.name != "deepseek-harness-sdk-runtime" or info.version != "0.0.1":
                    raise ValueError("unexpected SDK protocol")
                _require_cordis_guard(marker, nonce, session_id)
                client.resume_session(session_id)
                actual = Path(client.get_working_directory(session_id))
                if not actual.is_absolute() or not actual.resolve(strict=True).is_relative_to(workspace):
                    raise ValueError("restored working directory outside original workspace")
        return {"session_id": session_id, "restored": True, "prompt_sent": False, "continuation_started": False}
    except CloudBlocked:
        raise
    except Exception:
        # SDK errors may contain prompts, paths or credentials.  Do not expose them.
        raise CloudBlocked("NATIVE_SESSION_RESTORE_UNAVAILABLE", "Original session inspection failed") from None


def inspect_original_session(*, attempt_root: Path, expected_identity_digest: str, identity: dict) -> dict:
    """Inspect through a credential-free child; this does not continue execution.

    The identity digest must be obtained from the authenticated original server
    receipt; this internal function does not authenticate caller-supplied data.
    """
    try:
        if (not isinstance(identity, dict) or set(identity) != _IDENTITY_FIELDS
                or not isinstance(identity.get("environment"), dict)):
            raise ValueError("original identity required")
        _digest(expected_identity_digest)
        if identity["selection"] is not None:
            _selection_digest(identity["selection"])
        # Reject credential-bearing endpoint values before creating any child.
        _environment_digest(identity["environment"])
        # Only the fields which the identity contract hashes may cross the IPC.
        # API keys, OAuth tokens and Worker/Memory credentials never do.
        allowed = _NONSECRET_ENV | {"DEEPSEEK_BASE_URL"}
        sanitized = dict(identity)
        sanitized["environment"] = {k: v for k, v in identity["environment"].items() if k in allowed}
        for key in ("workspace", "dsh_home"):
            sanitized[key] = str(sanitized[key])
        payload = json.dumps({"attempt_root": str(attempt_root), "expected_identity_digest": expected_identity_digest,
                              "identity": sanitized}, ensure_ascii=True).encode() + b"\n"
        if len(payload) > 131072:
            raise ValueError("identity too large")
        with tempfile.TemporaryDirectory(prefix="hypertest-resume-process-") as directory:
            env = host_environment({})
            env.update({"PATH": "/usr/bin:/bin", "HOME": directory, "TMPDIR": directory, "LANG": "C.UTF-8"})
            process = subprocess.Popen(
                [sys.executable, "-P", "-m", "hypertest.cloud.native_session_restore"],
                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                stdout, _ = process.communicate(payload, timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise ValueError("inspection timed out") from None
            if len(stdout) > 4096:
                raise ValueError("inspection failed")
            result = json.loads(stdout)
            if (process.returncode != 0 and isinstance(result, dict) and set(result) == {"error"}
                    and result["error"] in _ERROR_CODES):
                raise CloudBlocked(result["error"], "Original session inspection was refused")
            if process.returncode != 0:
                raise ValueError("inspection failed")
            if result != {"session_id": sanitized["session_id"], "restored": True,
                          "prompt_sent": False, "continuation_started": False}:
                raise ValueError("invalid inspection result")
            return result
    except CloudBlocked:
        raise
    except Exception:
        raise CloudBlocked("NATIVE_SESSION_RESTORE_UNAVAILABLE", "Original session inspection failed") from None


async def inspect_original_session_guarded(*, attempt_root: Path, expected_identity_digest: str,
                                           identity: dict, assert_active) -> dict:
    """Inspect once in an isolated process while the server authority remains live."""
    process = None
    running = None
    monitor = None
    try:
        if not isinstance(identity, dict) or set(identity) != _IDENTITY_FIELDS:
            raise ValueError("original identity required")
        _digest(expected_identity_digest)
        _environment_digest(identity["environment"])
        if identity["selection"] is not None:
            _selection_digest(identity["selection"])
        sanitized = dict(identity)
        sanitized["environment"] = {key: value for key, value in identity["environment"].items()
            if key in _NONSECRET_ENV or key == "DEEPSEEK_BASE_URL"}
        for key in ("workspace", "dsh_home"):
            sanitized[key] = str(sanitized[key])
        payload = json.dumps({"attempt_root": str(attempt_root), "expected_identity_digest": expected_identity_digest,
                              "identity": sanitized}, ensure_ascii=True).encode() + b"\n"
        if len(payload) > 131072:
            raise ValueError("identity too large")
        # Do not even start a child after revocation or a lost authority check.
        await asyncio.wait_for(assert_active(), 5)
        with tempfile.TemporaryDirectory(prefix="hypertest-resume-process-") as directory:
            env = host_environment({})
            env.update({"PATH": "/usr/bin:/bin", "HOME": directory, "TMPDIR": directory, "LANG": "C.UTF-8"})
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-P", "-m", "hypertest.cloud.native_session_restore",
                env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True, limit=4097)

            async def watch_authority():
                while True:
                    await asyncio.sleep(2)
                    await asyncio.wait_for(assert_active(), 5)

            running = asyncio.create_task(process.communicate(payload))
            monitor = asyncio.create_task(watch_authority())
            done, _ = await asyncio.wait({running, monitor}, timeout=60, return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                await monitor  # A failed or lost assertion is not a successful inspection.
                raise ValueError("authority monitor stopped")
            if running not in done:
                raise TimeoutError("inspection timed out")
            stdout, _ = await running
            await asyncio.wait_for(assert_active(), 5)
            if process.returncode != 0 or len(stdout) > 4096:
                raise ValueError("inspection failed")
            result = json.loads(stdout)
            if result != {"session_id": sanitized["session_id"], "restored": True,
                          "prompt_sent": False, "continuation_started": False}:
                raise ValueError("invalid inspection result")
            return result
    except asyncio.CancelledError:
        raise
    except Exception:
        raise CloudBlocked("NATIVE_SESSION_RESTORE_UNAVAILABLE", "Original session inspection was not confirmed") from None
    finally:
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
        if running is not None and not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


def main() -> int:
    try:
        raw = sys.stdin.buffer.readline(131073)
        if len(raw) > 131072 or not raw.endswith(b"\n"):
            raise ValueError("invalid request")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"attempt_root", "expected_identity_digest", "identity"}:
            raise ValueError("invalid request")
        result = _inspect_in_child(**payload)
        print(json.dumps(result, separators=(",", ":")), flush=True)
        return 0
    except CloudBlocked as error:
        code = error.code if error.code in _ERROR_CODES else "NATIVE_SESSION_RESTORE_UNAVAILABLE"
        print(json.dumps({"error": code}, separators=(",", ":")), flush=True)
        return 1
    except Exception:
        # SDK exceptions may contain session content or secrets: never print them.
        print('{"error":"NATIVE_SESSION_RESTORE_UNAVAILABLE"}', flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
