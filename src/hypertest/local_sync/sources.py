"""Explicit file slots, bound once by a real native SessionStart per source.

Hooks supply identity and timing only. The approved policy supplies all initial
business fields and selects files; no conversation or tool body is inspected.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_directory, private_read
from hypertest.local_sync.hosts import HOST_PROVIDERS
from hypertest.local_sync.manifest import StrictModel, artifact_read, reject_secrets
from hypertest.sync_core import canonical_json, digest


class ArtifactSlot(StrictModel):
    kind: Literal["TEST_PLAN", "TEST_REPORT"]
    path: str = Field(min_length=1, max_length=128)
    key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    title: str | None = Field(default=None, min_length=1, max_length=512)
    reported_result: Literal["NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"] | None = None

    @field_validator("path")
    @classmethod
    def approved_filename(cls, value):
        path = Path(value)
        if (len(path.parts) != 1 or path.is_absolute() or path.name.startswith(".")
                or "transcript" in value.lower() or path.suffix.lower() not in {".md", ".markdown"}):
            raise ValueError("select one formal Markdown filename")
        return value


class InitialTaskFields(StrictModel):
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    objective: str = Field(max_length=16000)
    status: Literal["DRAFT", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"]
    plan_markdown: str = Field(max_length=262144)
    reported_result: Literal["NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"]


class ArtifactSource(StrictModel):
    workspace: Path
    initial: InitialTaskFields
    artifacts: list[ArtifactSlot] = Field(min_length=1, max_length=17)

    @field_validator("workspace")
    @classmethod
    def selected_workspace(cls, value):
        if not value.is_absolute() or ".." in value.parts or value == Path("/"):
            raise ValueError("select one absolute workspace")
        return value

    @field_validator("artifacts")
    @classmethod
    def unique_slots(cls, value):
        if len({slot.path for slot in value}) != len(value):
            raise ValueError("duplicate artifact filename")
        reports = [slot for slot in value if slot.kind == "TEST_REPORT"]
        if (sum(slot.kind == "TEST_PLAN" for slot in value) > 1
                or any(not slot.key or not slot.title or slot.reported_result is None for slot in reports)
                or len({slot.key for slot in reports}) != len(reports)):
            raise ValueError("each report requires an explicit key title and result")
        return value


def source_policy(config) -> ArtifactSource:
    policy = ArtifactSource.model_validate(config.local_sync["artifact_source"])
    reject_secrets(canonical_json(policy.model_dump(mode="json")))
    return policy


def source_binding(config, event: dict, *, create=False):
    policy = source_policy(config)
    if not policy.workspace.is_dir() or policy.workspace.resolve() != policy.workspace:
        raise ClientError("LOCAL_SOURCE_WORKSPACE_MISMATCH")
    if event.get("cwd") != str(policy.workspace):
        raise ClientError("LOCAL_SOURCE_WORKSPACE_MISMATCH")
    session = event.get("session_id")
    if not isinstance(session, str) or not session.strip() or len(session) > 512:
        raise ClientError("REAL_PARENT_SESSION_REQUIRED")
    identity = {"project_id": str(UUID(config.local_sync["project_id"])),
                "provider": HOST_PROVIDERS[config.local_sync["host"]], "session_id": session}
    source_key = digest({key: identity[key] for key in ("provider", "session_id")})
    local_directory = private_directory(config.state_dir / "local-sync")
    bindings = private_directory(local_directory / "native-sources")
    path = bindings / (source_key + ".json")
    record = {"identity": identity, "workspace": str(policy.workspace),
              "policy_digest": digest(policy.model_dump(mode="json")),
              "artifact_directory": str(policy.workspace / "hypertest-artifacts" / source_key)}
    if create:
        if event.get("hook_event_name") != "SessionStart":
            raise ClientError("NATIVE_SESSION_START_REQUIRED")
        # An existing real-source binding is immutable. Different sessions get
        # different paths; concurrent hooks cannot overwrite another source.
        try:
            private_create(path, canonical_json(record).encode())
        except FileExistsError:
            pass
    if not path.exists():
        raise ClientError("NATIVE_SESSION_START_REQUIRED")
    if json.loads(private_read(path)) != record:
        raise ClientError("LOCAL_SOURCE_BINDING_CONFLICT")
    root = private_directory(policy.workspace / "hypertest-artifacts")
    directory = private_directory(root / source_key)
    return policy, record, directory


def session_context(config, event):
    policy, binding, directory = source_binding(config, event, create=True)
    selected = "; ".join(slot.kind + ": " + str(directory / slot.path) for slot in policy.artifacts)
    return ("HyperTest automatic sync is configured for formal testing artifacts in this session. "
            "Native source provider=" + binding["identity"]["provider"] +
            ", session_id=" + binding["identity"]["session_id"] +
            ", project_id=" + binding["identity"]["project_id"] + ". "
            "When producing the selected artifacts, write their approved Markdown files at " + selected +
            ". Before the first asset sync, ask for the platform-created Local Task ID and use "
            "hypertest_bind_task with this exact native source and the current task version. "
            "Until binding is confirmed, hooks retain files and return TASK_BINDING_REQUIRED without POST. "
            "Do not write chat transcripts, reasoning or secrets. Hook success does not mean test PASS. "
            "Use explicit HyperTest MCP for case data and changes to task status or test results.")


def manifest_root(config, event, *, create=False):
    """Record a manifest-selected real SessionStart, without reading any chat."""
    from hypertest.local_sync.manifest import ArtifactManifest
    settings = config.local_sync
    manifest_path = Path(settings["manifest_file"])
    selected = ArtifactManifest.model_validate_json(private_read(manifest_path))
    identity = {"project_id": str(selected.identity.project_id),
                "provider": selected.identity.provider, "session_id": selected.identity.parent_session_id}
    workspace = event.get("cwd")
    roots = settings.get("allowed_roots", [])
    if (not isinstance(workspace, str) or workspace not in roots
            or Path(workspace).resolve() != Path(workspace) or not Path(workspace).is_dir()):
        raise ClientError("LOCAL_SOURCE_WORKSPACE_MISMATCH")
    if (identity["project_id"] != settings.get("project_id")
            or identity["provider"] != HOST_PROVIDERS.get(settings.get("host"))
            or identity["session_id"] != event.get("session_id")):
        raise ClientError("LOCAL_NATIVE_SOURCE_IDENTITY_MISMATCH")
    source_key = digest({field: identity[field] for field in ("provider", "session_id")})
    directory = private_directory(config.state_dir / "local-sync" / "manifest-roots")
    path = directory / (source_key + ".json")
    record = {"identity": identity, "workspace": workspace,
              "policy_digest": digest({"manifest_file": str(manifest_path), "allowed_roots": roots})}
    if create:
        if event.get("hook_event_name") != "SessionStart":
            raise ClientError("NATIVE_SESSION_START_REQUIRED")
        try:
            private_create(path, canonical_json(record).encode())
        except FileExistsError:
            pass
    if not path.exists():
        raise ClientError("NATIVE_SESSION_START_REQUIRED")
    if json.loads(private_read(path)) != record:
        raise ClientError("LOCAL_SOURCE_BINDING_CONFLICT")
    return record


def require_native_root(config, identity):
    """Bind only an existing native root, matching policy/workspace/source."""
    settings = config.local_sync
    if (not settings.get("enabled") or settings.get("host") not in HOST_PROVIDERS
            or not settings.get("harness_version")
            or (settings.get("host") == "deepseek-harness" and settings.get("event_bridge") != "native-root")):
        raise ClientError("LOCAL_NATIVE_SOURCE_CONFIGURATION_REQUIRED")
    if settings.get("artifact_source"):
        _, record, _ = source_binding(config, {"session_id": identity["session_id"],
            "cwd": settings["artifact_source"]["workspace"]})
    elif settings.get("manifest_file"):
        source_key = digest({field: identity[field] for field in ("provider", "session_id")})
        path = config.state_dir / "local-sync" / "manifest-roots" / (source_key + ".json")
        if not path.exists():
            raise ClientError("NATIVE_SESSION_START_REQUIRED")
        old = json.loads(private_read(path))
        record = manifest_root(config, {"session_id": identity["session_id"], "cwd": old["workspace"]})
    else:
        raise ClientError("LOCAL_NATIVE_SOURCE_CONFIGURATION_REQUIRED")
    if any(record["identity"][field] != identity[field] for field in ("project_id", "provider", "session_id")):
        raise ClientError("LOCAL_NATIVE_SOURCE_IDENTITY_MISMATCH")
    return record


async def submit_source(config, coordinator, event):
    policy, binding, directory = source_binding(config, event)
    changes, artifacts = {}, []
    for slot in policy.artifacts:
        path = directory / slot.path
        if not path.exists() and not path.is_symlink():
            continue
        data = artifact_read(path, [policy.workspace])
        text = data.decode("utf-8")
        reject_secrets(text)
        if len(text) > 262144:
            raise ClientError("ARTIFACT_SIZE_EXCEEDED")
        artifacts.append({"path": slot.path, "sha256": hashlib.sha256(data).hexdigest()})
        if slot.kind == "TEST_PLAN":
            changes["plan_markdown"] = text
        else:
            changes.setdefault("reports", []).append({"key": slot.key, "title": slot.title,
                "markdown": text, "reported_result": slot.reported_result,
                "source_ref": "local-artifact:" + slot.path, "artifact_uri": None})
    if not artifacts:
        return {"status": "UNCHANGED", "code": "NO_APPROVED_ARTIFACTS", "readback_complete": False}
    # A fresh observation id allows a legitimate A -> B -> A file revision;
    # semantic comparison under the writer lock removes unchanged repeats.
    return await coordinator.submit_partial(binding["identity"], changes, base_version=None,
        checkpoint_digest=digest({"observation": uuid4().hex, "artifacts": artifacts}),
        initial_fields=policy.initial.model_dump(), artifact_observation=True)
