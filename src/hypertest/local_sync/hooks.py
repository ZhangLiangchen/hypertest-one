"""Bounded best-effort triggers. The selected manifest supplies all semantics."""
from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_directory, private_read
from hypertest.local_sync.hosts import HOST_PROVIDERS, parse_trigger
from hypertest.local_sync.manifest import ArtifactManifest, load_manifest
from hypertest.sync_core import canonical_json


def persist_trigger(config, trigger):
    local_directory = private_directory(config.state_dir / "local-sync")
    queue = private_directory(local_directory / "pending-events")
    if len(list(queue.glob("*.json"))) >= 1024:
        raise ClientError("LOCAL_EVENT_QUEUE_FULL_EXPLICIT_RECOVERY_REQUIRED")
    path = queue / (uuid4().hex + ".json")
    private_create(path, canonical_json(trigger.metadata()).encode())
    return path


def selected_trigger(config, event: dict):
    settings = config.local_sync
    if not settings.get("enabled") or not settings.get("hooks_enabled"):
        raise ClientError("LOCAL_HOOKS_DISABLED")
    host = settings.get("host")
    if host not in HOST_PROVIDERS or not settings.get("harness_version"):
        raise ClientError("LOCAL_HOST_VERSION_REQUIRED")
    if settings.get("artifact_source"):
        from hypertest.local_sync.sources import source_binding
        if host == "deepseek-harness" and settings.get("event_bridge") != "native-root":
            raise ClientError("DEEPSEEK_ROOT_SOURCE_BRIDGE_REQUIRED")
        # Validate the host event before creating any binding or directory.
        trigger = parse_trigger(host, event, selected_parent=event.get("session_id"),
                                bridge=settings.get("event_bridge"))
        if trigger is None:
            return None
        source_binding(config, event, create=trigger.event == "SessionStart")
        return trigger
    manifest_path = Path(settings["manifest_file"])
    manifest = ArtifactManifest.model_validate_json(private_read(manifest_path, max_bytes=2 * 1024 * 1024))
    if manifest.identity.provider != HOST_PROVIDERS[host]:
        raise ClientError("MANIFEST_HOST_PROVIDER_MISMATCH")
    if str(manifest.identity.project_id) != settings.get("project_id"):
        raise ClientError("MANIFEST_PARENT_PROJECT_MISMATCH")
    trigger = parse_trigger(host, event, selected_parent=manifest.identity.parent_session_id,
                            bridge=settings.get("event_bridge"))
    if trigger is not None and trigger.event == "SessionStart":
        from hypertest.local_sync.sources import manifest_root
        manifest_root(config, event, create=True)
    return trigger


async def handle_hook(config, coordinator, payload: dict) -> dict:
    if set(payload) not in ({"event"}, {"event", "event_id"}) or not isinstance(payload["event"], dict):
        raise ClientError("INVALID_LOCAL_EVENT")
    # IPC accepts only allowlisted metadata, not a raw host tool-event body.
    if not set(payload["event"]) <= {"session_id", "hook_event_name", "tool_name", "cwd"}:
        raise ClientError("RAW_LOCAL_EVENT_REJECTED")
    trigger = selected_trigger(config, payload["event"])
    if trigger is None:
        return {"status": "IGNORED", "code": "SYNC_EVENT_RECURSION"}
    pending = None
    if "event_id" in payload:
        identifier = payload["event_id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ClientError("INVALID_LOCAL_EVENT_REFERENCE")
        pending = config.state_dir / "local-sync" / "pending-events" / (identifier + ".json")
        if json.loads(private_read(pending)) != trigger.metadata():
            raise ClientError("LOCAL_EVENT_REFERENCE_MISMATCH")
    if config.local_sync.get("artifact_source"):
        from hypertest.local_sync.sources import submit_source
        if trigger.event == "SessionStart":
            return {"status": "BOUND", "business_sync": "NOT_TRIGGERED"}
        pending = pending or persist_trigger(config, trigger)
        captured = []
        for path in pending.parent.glob("*.json"):
            metadata = json.loads(private_read(path))
            if (metadata.get("provider") == trigger.provider
                    and metadata.get("session_id") == trigger.parent_session_id):
                captured.append(path)
        result = await submit_source(config, coordinator, payload["event"])
        if result.get("status") == "UNCHANGED" or result.get("_sync", {}).get("readback_complete"):
            # Clear only captured metadata for this real source, never later
            # observations or transmission requests awaiting reconciliation.
            for path in captured:
                path.unlink(missing_ok=True)
        return result
    settings = config.local_sync
    if trigger.event == "SessionStart":
        return {"status": "CONTEXT_READY", "business_sync": "NOT_TRIGGERED"}
    identity = {"project_id": settings["project_id"], "provider": trigger.provider,
                "session_id": trigger.parent_session_id}
    pending = pending or persist_trigger(config, trigger)
    result = await submit_manifest(config, coordinator, expected_identity=identity)
    if result.get("status") == "UNCHANGED" or result.get("_sync", {}).get("readback_complete"):
        # Keep later dirty observations independent; only this metadata record
        # is cleared. Snapshot and compact request journal are never deleted.
        pending.unlink(missing_ok=True)
    return result


async def drain_source(config, coordinator, session_id: str):
    """Explicit recovery for a previously bound source, even with a full queue.

    This does not fabricate a Hook or bind a new session. The private native
    binding must already exist and match the unchanged source policy.
    """
    from hypertest.local_sync.sources import source_binding, submit_source
    settings = config.local_sync
    if not settings.get("enabled") or not settings.get("artifact_source"):
        raise ClientError("EXPLICIT_ARTIFACT_SOURCE_REQUIRED")
    selection = {"session_id": session_id, "cwd": settings["artifact_source"]["workspace"]}
    _, binding, _ = source_binding(config, selection)
    captured = []
    queue = private_directory(config.state_dir / "local-sync" / "pending-events")
    for path in queue.glob("*.json"):
        metadata = json.loads(private_read(path))
        if (metadata.get("provider") == binding["identity"]["provider"]
                and metadata.get("session_id") == session_id):
            captured.append(path)
    recovered = await coordinator.reconcile_source(binding["identity"])
    if recovered.get("status") != "SETTLED":
        return recovered
    result = await submit_source(config, coordinator, selection)
    if result.get("status") == "UNCHANGED" or result.get("_sync", {}).get("readback_complete"):
        for path in captured:
            path.unlink(missing_ok=True)
    return result


async def submit_manifest(config, coordinator, *, expected_identity=None):
    """Explicit approved checkpoint; no Hook event or business state is invented."""
    settings = config.local_sync
    if not settings.get("enabled") or not settings.get("manifest_file"):
        raise ClientError("EXPLICIT_MANIFEST_CONFIGURATION_REQUIRED")
    selected = ArtifactManifest.model_validate_json(private_read(
        Path(settings["manifest_file"]), max_bytes=2 * 1024 * 1024))
    identity = {"project_id": str(selected.identity.project_id),
                "provider": selected.identity.provider, "session_id": selected.identity.parent_session_id}
    if (identity["project_id"] != settings.get("project_id")
            or identity["provider"] != HOST_PROVIDERS.get(settings.get("host"))
            or (expected_identity is not None and identity != expected_identity)):
        raise ClientError("MANIFEST_PARENT_PROJECT_MISMATCH")
    queue = private_directory(config.state_dir / "local-sync" / "pending-events")
    captured = []
    for path in queue.glob("*.json"):
        metadata = json.loads(private_read(path))
        if (metadata.get("provider") == identity["provider"]
                and metadata.get("session_id") == identity["session_id"]):
            captured.append(path)
    manifest, identity, changes, checkpoint_digest = load_manifest(
        Path(settings["manifest_file"]), [Path(root) for root in settings.get("allowed_roots", [])],
        expected_identity=identity)
    result = await coordinator.submit_partial(identity, changes, clear_fields=manifest.clear,
        base_version=manifest.base_version, checkpoint_digest=checkpoint_digest)
    if result.get("status") == "UNCHANGED" or result.get("_sync", {}).get("readback_complete"):
        for path in captured:
            path.unlink(missing_ok=True)
    return result


def sanitize_event(event: dict) -> dict:
    if not isinstance(event, dict):
        raise ClientError("INVALID_LOCAL_EVENT")
    return {key: event[key] for key in ("session_id", "hook_event_name", "tool_name", "cwd") if key in event}
