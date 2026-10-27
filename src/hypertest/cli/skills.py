"""Install only the explicit archive Skill; never edit harness hooks or MCP config."""
from __future__ import annotations

import hashlib
import os
import uuid
from importlib import resources
from pathlib import Path

from hypertest.cli import CLI_VERSION
from hypertest.cli.state import CLIError, State
from hypertest.sync_core import digest

SKILL_FILES = ("SKILL.md", "agents/openai.yaml", "references/manifest.md")


def bundled_files() -> dict[str, bytes]:
    bundled = resources.files("hypertest.cli").joinpath("assets/skills/hypertest-archive")
    if bundled.joinpath("SKILL.md").is_file():
        return {name: bundled.joinpath(name).read_bytes() for name in SKILL_FILES}
    source = Path(__file__).resolve().parents[3] / "skills" / "hypertest-archive"
    if source.joinpath("SKILL.md").is_file():
        return {name: source.joinpath(name).read_bytes() for name in SKILL_FILES}
    raise CLIError("BUNDLED_SKILL_UNAVAILABLE", 5)


def install(state: State, *, directory: Path | None, globally: bool, host: str | None) -> tuple[dict, int]:
    if globally:
        if directory is not None or host != "codex":
            raise CLIError("SUPPORTED_GLOBAL_HOST_REQUIRED", 5)
        directory = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills"
    elif directory is None or host is not None:
        raise CLIError("EXPLICIT_SKILL_DIRECTORY_REQUIRED")
    destination = directory.expanduser().absolute() / "hypertest-archive"
    if any(parent.is_symlink() for parent in (destination, *destination.parents)):
        raise CLIError("SKILL_DIRECTORY_SYMLINK_REJECTED")
    key = digest(str(destination))
    receipts = state.directory / "skill-receipts"
    receipts.mkdir(mode=0o700, exist_ok=True)
    with state.lock("skill:" + str(destination)):
        owned = state.read(receipts, key) if (receipts / (key + ".json")).exists() else None
        files = bundled_files()
        for name in files:
            path = destination / name
            if path.exists() or path.is_symlink():
                if path.is_symlink() or not path.is_file():
                    raise CLIError("SKILL_CUSTOMIZATION_CONFLICT", 5)
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if not owned or owned["files"].get(name) != actual:
                    raise CLIError("SKILL_CUSTOMIZATION_CONFLICT", 5)
        for name, content in files.items():
            path = destination / name
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            temporary = path.parent / ("." + uuid.uuid4().hex + ".tmp")
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        state.write(receipts, key, {"destination": str(destination), "version": CLI_VERSION,
                    "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}})
    return {"status": "INSTALLED", "skill": "hypertest-archive", "directory": str(destination),
            "version": CLI_VERSION, "implicit_invocation": False}, 0
