"""Resolve approved images without pulling, building or installing during a Run."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from hypertest.config import get_settings
from hypertest.domain.environments import EnvironmentRequest
from hypertest.runner.backends import run_process

LABEL_PREFIX = "org.hypertest.environment."
SCHEMA_VERSION = "hypertest.environment/v1"
PROFILE_IDS = ("python-pytest-v1", "python-api-v1", "python-api-v2")
CATALOG_PROFILE_IDS = ("python-pytest-v1", "python-api-v2")


def validate_service_app(source: Path, app: str, tracked_files: list[str]) -> None:
    """Pure pinned-checkout validation; starts no service and creates no fact."""
    from hypertest.runner.service_launcher import validate_app

    path = validate_app(source, app)
    if path.relative_to(source.resolve()).as_posix() not in set(tracked_files):
        raise ValueError("ASGI application module must be tracked in the pinned source")


def profile_manifest(profile_id: str) -> dict:
    if profile_id not in PROFILE_IDS:
        raise ValueError("unsupported controlled environment profile")
    root = Path(__file__).parent
    lock = (root / "locks" / f"{profile_id}.txt").read_bytes()
    launcher = "service_launcher.py" if profile_id == "python-api-v2" else "service_launcher_v1.py"
    dependencies = dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock.decode(), re.M))
    return {
        "profile_id": profile_id,
        "dependency_lock_sha256": hashlib.sha256(lock).hexdigest(),
        "dependencies": dependencies,
        "launcher_sha256": hashlib.sha256((root / launcher).read_bytes()).hexdigest(),
    }


async def inspect_bound_image(image: str, manifest: dict) -> dict:
    result = await run_process(
        ["docker", "image", "inspect", image, "--format", "{{json .}}"],
        cwd=Path("/tmp"), timeout=30, output_limit=1024 * 1024,
    )
    if result.exit_code != 0 or result.timed_out:
        raise RuntimeError("controlled environment image is unavailable")
    try:
        details = json.loads(result.stdout)
        if not isinstance(details, dict) or not isinstance(details.get("Config"), dict):
            raise ValueError("invalid controlled environment image inspection")
        labels = details.get("Config", {}).get("Labels") or {}
        if not isinstance(labels, dict):
            raise ValueError("invalid controlled environment image labels")
        for name in ("profile_id", "dependency_lock_sha256", "launcher_sha256"):
            if labels.get(LABEL_PREFIX + name) != manifest[name]:
                raise ValueError("controlled environment image manifest mismatch")
        if not re.fullmatch(r"[^\s@]+@sha256:[a-f0-9]{64}", labels.get(LABEL_PREFIX + "base_image_digest", "")):
            raise ValueError("controlled environment base image digest is missing")
        if (not re.fullmatch(r"sha256:[a-f0-9]{64}", details["Id"])
            or details["Os"] != "linux" or not isinstance(details["Architecture"], str)):
            raise ValueError("invalid controlled environment image identity")
        if image.startswith("sha256:") and details["Id"] != image:
            raise ValueError("controlled image identity changed")
        return details
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("controlled environment image identity is invalid") from exc


async def resolve_environment(request: EnvironmentRequest) -> dict:
    """Bind an approved request to the actual immutable image present on this host."""
    request = EnvironmentRequest.model_validate(request)
    manifest = profile_manifest(request.profile_id)
    settings = get_settings()
    if request.profile_id == "python-pytest-v1":
        image = settings.runner_controlled_image
    elif request.profile_id == "python-api-v1":
        image = settings.runner_api_image
    else:
        image = settings.runner_api_v2_image
    details = await inspect_bound_image(image, manifest)
    return {
        "schema_version": SCHEMA_VERSION,
        "request": request.model_dump(mode="json", exclude_none=True),
        "image_id": details["Id"], "image_os": details["Os"],
        "image_architecture": details["Architecture"],
        **{key: value for key, value in manifest.items() if key != "profile_id"},
    }


def validate_binding_content(binding: dict) -> EnvironmentRequest:
    """Pure validation for locked database transactions; performs no Docker I/O."""
    expected_keys = {"schema_version", "request", "image_id", "image_os", "image_architecture",
                     "dependency_lock_sha256", "dependencies", "launcher_sha256"}
    if not isinstance(binding, dict) or set(binding) != expected_keys or binding["schema_version"] != SCHEMA_VERSION:
        raise ValueError("invalid controlled environment binding")
    request = EnvironmentRequest.model_validate(binding["request"])
    if binding["request"] != request.model_dump(mode="json", exclude_none=True):
        raise ValueError("controlled environment request is not normalized")
    manifest = profile_manifest(request.profile_id)
    if any(binding[key] != manifest[key] for key in ("dependency_lock_sha256", "dependencies", "launcher_sha256")):
        raise ValueError("controlled environment binding manifest mismatch")
    if not isinstance(binding["image_id"], str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", binding["image_id"]):
        raise ValueError("invalid controlled image ID")
    if binding["image_os"] != "linux" or not isinstance(binding["image_architecture"], str):
        raise ValueError("invalid controlled environment platform")
    return request


async def validate_environment_binding(binding: dict) -> dict:
    """Validate frozen content and inspect its image ID, never a mutable tag."""
    request = validate_binding_content(binding)
    manifest = profile_manifest(request.profile_id)
    details = await inspect_bound_image(binding["image_id"], manifest)
    if (details["Os"], details["Architecture"]) != (binding["image_os"], binding["image_architecture"]):
        raise ValueError("controlled environment platform mismatch")
    return details


async def environment_catalog() -> list[dict]:
    """API-host inspection only; this does not assert independent Worker readiness."""
    catalog = []
    for profile_id in CATALOG_PROFILE_IDS:
        manifest = profile_manifest(profile_id)
        item = {**manifest, "kind": "pytest" if profile_id == "python-pytest-v1" else "asgi",
                "network": "none", "available": False,
                "checked_at": datetime.now(UTC).isoformat()}
        try:
            request = EnvironmentRequest(profile_id=profile_id, **(
                {"service": {"app": "application:app"}} if profile_id != "python-pytest-v1" else {}
            ))
            await resolve_environment(request)
            item["available"] = True
        except (OSError, RuntimeError, ValueError, KeyError):
            item["reason_code"] = "CONTROLLED_IMAGE_UNAVAILABLE"
        catalog.append(item)
    return catalog
