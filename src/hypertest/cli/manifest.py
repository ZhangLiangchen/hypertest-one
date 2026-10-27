"""Read a finite manifest of explicit formal artifacts; preserve raw UTF-8 bytes."""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

from hypertest.cli import PROFILE
from hypertest.cli.state import CLIError, identifier
from hypertest.sync_core import canonical_json

RESULTS = {"NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"}
STATUSES = {"DRAFT", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"}
ORIGIN_FIELDS = {"origin_provider", "origin_session_ref", "producer", "source_ref",
                 "test_started_at", "test_finished_at", "report_created_at"}
MAX_BYTES = 2 * 1024 * 1024


def reject_secrets(text: str) -> None:
    if (re.search(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", text)
            or re.search(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_.=-]{16,}", text)
            or re.search(r"https?://[^\s/@:]+:[^\s/@]+@", text)
            or re.search(r'"(?:integration_token|device_token|execution_token|operator_key|credential_secret|credential|verifier|access_token|refresh_token|api_key|password)"\s*:\s*"[^\"]+"', text)):
        raise CLIError("SECRET_MATERIAL_REJECTED")


def read_formal_file(path: Path, *, manifest: bool = False) -> bytes:
    path = Path(os.path.abspath(path.expanduser()))
    blocked = {".ssh", ".aws", ".azure", ".config", ".codex", ".claude", ".hypertest-cli",
               "transcripts", "rollouts", "sessions", "credentials", "auth.json"}
    if any(part.lower() in blocked or part.lower().startswith(".env")
           or "transcript" in part.lower() for part in path.parts):
        raise CLIError("ARTIFACT_SOURCE_REJECTED")
    allowed = {".json"} if manifest else {".md", ".markdown", ".txt", ".log", ".json", ".xml", ".csv"}
    if path.suffix.lower() not in allowed:
        raise CLIError("ARTIFACT_FORMAT_UNSUPPORTED")
    descriptors = []
    try:
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(parent)
        for part in path.parts[1:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_size > MAX_BYTES):
            raise CLIError("ARTIFACT_FILE_REJECTED")
        chunks, length = [], 0
        while length <= MAX_BYTES:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
    except OSError as exc:
        raise CLIError("ARTIFACT_FILE_REJECTED") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    if length > MAX_BYTES:
        raise CLIError("ARTIFACT_SIZE_EXCEEDED")
    result = b"".join(chunks)
    try:
        text = result.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CLIError("UTF8_TEXT_REQUIRED") from exc
    if "\x00" in text:
        raise CLIError("BINARY_ARTIFACT_UNSUPPORTED")
    reject_secrets(text)
    return result


def text_field(value, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise CLIError("INVALID_ASSET_FIELD")
    return value


def normalize_asset(asset: dict, directory: Path) -> dict:
    if not isinstance(asset, dict):
        raise CLIError("INVALID_ASSET")
    kind = asset.get("kind")
    base_fields = {"kind", "stable_key", "title", "reported_result", "origin"}
    fields = ({"steps", "expected", "actual", "implementation_ref"} if kind == "CASE"
              else {"path", "artifact_uri"})
    if kind not in {"PLAN", "REPORT", "CASE"} or set(asset) - base_fields - fields:
        raise CLIError("INVALID_ASSET")
    stable_key = asset.get("stable_key")
    if not isinstance(stable_key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", stable_key):
        raise CLIError("INVALID_STABLE_KEY")
    origin = asset.get("origin", {})
    if not isinstance(origin, dict) or set(origin) - ORIGIN_FIELDS:
        raise CLIError("INVALID_ORIGIN")
    limits = {"origin_provider": 64, "origin_session_ref": 512, "producer": 512, "source_ref": 2048,
              "test_started_at": 64, "test_finished_at": 64, "report_created_at": 64}
    origin = {origin_key: (text_field(origin[origin_key], limits[origin_key])
                          if origin.get(origin_key) is not None else None)
              for origin_key in sorted(ORIGIN_FIELDS)}
    for timestamp_key in ("test_started_at", "test_finished_at", "report_created_at"):
        if origin[timestamp_key] is not None:
            try:
                parsed = datetime.fromisoformat(origin[timestamp_key].replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError as exc:
                raise CLIError("INVALID_ORIGIN_TIMESTAMP") from exc
    result = {"kind": kind, "stable_key": stable_key,
              "title": text_field(asset.get("title"), 512, required=True),
              "reported_result": asset.get("reported_result", "UNKNOWN" if kind == "REPORT" else "NOT_RUN"),
              "origin": origin}
    if result["reported_result"] not in RESULTS:
        raise CLIError("INVALID_REPORTED_RESULT")
    if kind == "CASE":
        steps = asset.get("steps", [])
        if not isinstance(steps, list) or len(steps) > 100:
            raise CLIError("INVALID_CASE_STEPS")
        result.update(steps=[text_field(step, 16000) for step in steps],
                      expected=text_field(asset.get("expected", ""), 16000),
                      actual=text_field(asset.get("actual", ""), 16000),
                      implementation_ref=(text_field(asset["implementation_ref"], 2048)
                                          if asset.get("implementation_ref") is not None else None))
    else:
        path = asset.get("path")
        if not isinstance(path, str) or not path:
            raise CLIError("EXPLICIT_ARTIFACT_PATH_REQUIRED")
        result["markdown"] = text_field(read_formal_file(directory / path).decode("utf-8"),
                                        262144, required=True)
        result["artifact_uri"] = (text_field(asset["artifact_uri"], 2048)
                                  if asset.get("artifact_uri") is not None else None)
    return result


def load_manifest(path: Path, *, project_id: str, task_id: str,
                  subtask_id: str | None = None) -> dict:
    try:
        manifest = json.loads(read_formal_file(path, manifest=True))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CLIError("INVALID_MANIFEST") from exc
    if not isinstance(manifest, dict) or set(manifest) - {
            "profile", "project_id", "task_id", "subtask_id", "assets", "subtask_update"}:
        raise CLIError("INVALID_MANIFEST")
    target = {"project_id": identifier(project_id), "task_id": identifier(task_id),
              "subtask_id": identifier(subtask_id) if subtask_id else None}
    actual = {key: identifier(manifest[key]) if manifest.get(key) else None for key in target}
    if actual != target or manifest.get("profile") != PROFILE:
        raise CLIError("MANIFEST_TARGET_MISMATCH")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) > 232:
        raise CLIError("INVALID_ASSET_COLLECTION")
    assets = [normalize_asset(asset, path.absolute().parent) for asset in assets]
    identities = [(a["kind"], a["stable_key"]) for a in assets]
    if len(identities) != len(set(identities)):
        raise CLIError("DUPLICATE_ASSET_KEY")
    if any(sum(a["kind"] == kind for a in assets) > limit
           for kind, limit in (("PLAN", 16), ("CASE", 200), ("REPORT", 16))):
        raise CLIError("ASSET_COUNT_EXCEEDED")
    result = {"profile": PROFILE, **target, "assets": sorted(assets, key=lambda a: (a["kind"], a["stable_key"]))}
    if "subtask_update" in manifest:
        update = manifest["subtask_update"]
        if (not subtask_id or not isinstance(update, dict) or not update
                or set(update) - {"status", "reported_result"}
                or ("status" in update and update["status"] not in STATUSES)
                or ("reported_result" in update and update["reported_result"] not in RESULTS)):
            raise CLIError("INVALID_SUBTASK_UPDATE")
        result["subtask_update"] = update
    if not assets and not result.get("subtask_update"):
        raise CLIError("EMPTY_ARCHIVE")
    if len(canonical_json(result).encode()) > MAX_BYTES - 256:
        raise CLIError("REQUEST_SIZE_EXCEEDED")
    return result
