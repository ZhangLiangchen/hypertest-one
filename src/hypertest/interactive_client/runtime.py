"""Local process provenance. This module performs no platform or model calls."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

RUNTIME_PROFILE = "hypertest.local-runtime/v1"


def runtime_identity(config) -> dict:
    """Capture once at daemon startup; never relabel an old loaded process."""
    package = Path(__file__).resolve().parent.parent
    digest = hashlib.sha256()
    for component in ("interactive_client", "local_sync", "sync_core"):
        for path in sorted((package / component).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".js", ".json"} and "__pycache__" not in path.parts:
                digest.update(str(path.relative_to(package)).encode() + b"\0" + path.read_bytes() + b"\0")
    for name in ("task_schemas.py", "task_collaboration_schemas.py"):
        path = package / "api" / name
        if path.is_file():
            digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    release_file = package / "local_sync" / "release.json"
    release = json.loads(release_file.read_bytes()) if release_file.exists() else {}
    settings = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    return {"profile": RUNTIME_PROFILE, "python": os.path.abspath(sys.executable),
            "python_version": ".".join(str(value) for value in sys.version_info[:3]),
            "package_directory": str(package), "runtime_sha256": digest.hexdigest(),
            "configuration_sha256": hashlib.sha256(settings).hexdigest(),
            "release_version": release.get("release_version"),
            "source_commit": release.get("source_commit"),
            "local_source_sha256": release.get("local_source_sha256")}
