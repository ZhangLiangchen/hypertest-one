"""A present-time, operator-adopted identity; never a historical prompt anchor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import CloudBlocked
from .native_resume_identity import (
    _MAX_RECORD,
    _checked_head,
    _digest,
    _directory,
    _environment_digest,
    _private_attempt_root,
    _profile_digest,
    _runtime_identity,
    _selection_digest,
    _uuid,
)
from .private_file import read_private_file
from .worker import save_once


def _adopted(*, project_id, task_id, attempt_id, session_id, worker_id, generation,
             input_digest, operation_key, adopted_at, title_sha256, workspace, dsh_home,
             sut_commit, framework_commit, selection, environment):
    attempt_id = _uuid(attempt_id)
    if session_id != "cloud-" + attempt_id or type(generation) is not int or generation < 1:
        raise ValueError("invalid adopted session identity")
    if not isinstance(worker_id, str) or not worker_id or not isinstance(operation_key, str) or not operation_key:
        raise ValueError("invalid adopted authority")
    workspace, workspace_id = _directory(Path(workspace))
    home, home_id = _directory(Path(dsh_home))
    return {"profile": "hypertest-adopted-session-identity/v1", "source": "OPERATOR_ADOPTED",
        "project_id": _uuid(project_id), "task_id": _uuid(task_id), "attempt_id": attempt_id,
        "session_id": session_id, "worker_id": worker_id, "generation": generation,
        "input_digest": _digest(input_digest), "operation_key": operation_key, "adopted_at": adopted_at,
        "title_sha256": _digest(title_sha256), "historical_identity_preanchored": False,
        "workspace": workspace_id, "dsh_home": home_id,
        "repositories": {"sut": _checked_head(workspace / "sut", sut_commit),
                         "framework": _checked_head(workspace / "framework", framework_commit)},
        "selection_sha256": _selection_digest(selection),
        "nonsecret_environment_sha256": _environment_digest(environment),
        "sdk_profile_sha256": _profile_digest(home, selection), "runtime": _runtime_identity(),
        "identity_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def record_adopted_identity(attempt_root: Path, **identity) -> str:
    try:
        root = _private_attempt_root(attempt_root)
        record = _adopted(**identity)
        save_once(root / ("adopted-identity-" + str(identity["generation"]) + ".json"), record)
        # save_once uses the same canonical JSON encoding as the other private
        # records; hash the actual bytes, not an inferred serialization.
        data = read_private_file(root / ("adopted-identity-" + str(identity["generation"]) + ".json"), max_bytes=_MAX_RECORD)
        if json.loads(data) != record:
            raise ValueError("adopted identity changed")
        return hashlib.sha256(data).hexdigest()
    except Exception:
        raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Current adopted identity could not be recorded") from None


def verify_adopted_identity(attempt_root: Path, *, expected_identity_digest: str, **identity) -> dict:
    try:
        root = _private_attempt_root(attempt_root)
        data = read_private_file(root / ("adopted-identity-" + str(identity["generation"]) + ".json"), max_bytes=_MAX_RECORD)
        if hashlib.sha256(data).hexdigest() != _digest(expected_identity_digest):
            raise ValueError("adopted identity digest changed")
        record = json.loads(data)
        if record != _adopted(**identity):
            raise ValueError("adopted identity changed")
        return record
    except Exception:
        raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Current adopted identity is missing or changed") from None
