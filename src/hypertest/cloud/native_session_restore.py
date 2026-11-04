"""Identity helpers for native session inspection, currently fail-closed.

The pinned SDK's resume can append interrupted-turn repairs, and closing a
resumed agent can persistently clear its inbox. Until inspection runs against
a safely isolated copy, none of its entry points may open the original session.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
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
    _uuid,
)
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
_IDENTITY_FIELDS = frozenset({"project_id", "task_id", "attempt_id", "session_id", "input_digest", "prompt_sha256", "title_sha256",
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
    # The inspection guard returns before applying either a new preset or a
    # new title.  The fixed label only satisfies the adapter's input contract.
    overlay = prepare_cordis_overlay(directory, title="Original session inspection")
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
                "prompt_sha256": record["prompt_sha256"], "title_sha256": record["title_sha256"],
                "workspace": str(workspace), "dsh_home": str(home),
                "sut_commit": inspection["sut_commit"], "framework_commit": inspection["framework_commit"],
                "selection": None, "environment": {k: v for k, v in environment.items()
                    if k in _NONSECRET_ENV or k == "DEEPSEEK_BASE_URL"},
                "worker_id": worker_id, "original_generation": inspection["original_generation"]}
    except Exception:
        raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Original session identity is missing or changed") from None


def _inspection_unavailable() -> None:
    # The pinned SDK repairs interrupted turns on resume and clears a restored
    # inbox on disposal. No original session can safely be opened for inspection.
    raise CloudBlocked(
        "NATIVE_SESSION_RESTORE_UNAVAILABLE",
        "Original session inspection is disabled until it can preserve the original session and pending messages",
    )


def _inspect_in_child(*, attempt_root: Path, expected_identity_digest: str, identity: dict) -> dict:
    """Reject direct child entry as well as Worker entry, without opening the SDK."""
    _inspection_unavailable()


def inspect_original_session(*, attempt_root: Path, expected_identity_digest: str, identity: dict) -> dict:
    """Reject inspection before reading or starting any SDK process."""
    _inspection_unavailable()


async def inspect_original_session_guarded(*, attempt_root: Path, expected_identity_digest: str,
                                           identity: dict, assert_active) -> dict:
    """Reject inspection before starting a child or touching the original session."""
    _inspection_unavailable()


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
