"""Versioned DeepSeek Harness command-hook bridge configuration.

Reading installation metadata establishes a supported local layout, not package
origin, host authentication, or successful native acceptance. No model, profile,
credential, or subprocess is started by these helpers.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from hypertest.interactive_client.errors import ClientError

SUPPORTED_VERSION = "0.1.5-rc.1"
SUPPORTED_COMPONENT_VERSION = "0.1.5-rc.2"
OFFICIAL_SOURCE_COMMIT = "687f282e8625c6b8d11ff58211a90524be2e4317"
OFFICIAL_SOURCE = "https://github.com/deepseek-ai/deepseek-harness"
BRIDGES = {
    "claude-code": "@deepseek-ai/dsh-hooks-claude-code",
    "codex": "@deepseek-ai/dsh-hooks-codex",
}


def _metadata(path: Path) -> dict:
    try:
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            raise ValueError
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError, TypeError):
        raise ClientError("DEEPSEEK_INSTALL_METADATA_INVALID") from None


def _installation(executable: Path | None) -> Path:
    selected = executable if executable is not None else shutil.which("dsh")
    if selected is None:
        raise ClientError("DEEPSEEK_EXECUTABLE_NOT_FOUND")
    try:
        entry = Path(selected).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise ClientError("DEEPSEEK_EXECUTABLE_NOT_FOUND") from None
    if not entry.is_file():
        raise ClientError("DEEPSEEK_INSTALL_LAYOUT_UNSUPPORTED")
    # The supported npm CLI publishes lib/bin.js. Do not guess an install from
    # an unrelated executable, SDK runtime, global npm root, or a user profile.
    if entry.name != "bin.js" or entry.parent.name != "lib":
        raise ClientError("DEEPSEEK_INSTALL_LAYOUT_UNSUPPORTED")
    root = entry.parent.parent
    manifest = _metadata(root / "package.json")
    if manifest.get("name") != "@deepseek-ai/dsh":
        raise ClientError("DEEPSEEK_INSTALL_LAYOUT_UNSUPPORTED")
    if manifest.get("version") != SUPPORTED_VERSION:
        raise ClientError("DEEPSEEK_BRIDGE_VERSION_UNSUPPORTED")
    return root


def bridge_capability(*, bridge: str = "claude-code", executable: Path | None = None) -> dict:
    """Inspect the supported installed CLI and bridge without reading auth.

    An unknown version is refused for automatic triggers. Explicit MCP remains
    independently installable through the ordinary installer path.
    """
    if bridge not in BRIDGES:
        raise ClientError("DEEPSEEK_EVENT_BRIDGE_REQUIRED")
    root = _installation(executable)
    package_name = BRIDGES[bridge]
    package = root / "node_modules" / package_name
    metadata = _metadata(package / "package.json")
    if metadata.get("name") != package_name or metadata.get("version") != SUPPORTED_COMPONENT_VERSION:
        raise ClientError("DEEPSEEK_BRIDGE_VERSION_UNSUPPORTED")
    entry = package / "lib" / "index.js"
    try:
        if not entry.is_file() or entry.stat().st_size > 2 * 1024 * 1024:
            raise OSError
        entry_digest = hashlib.sha256(entry.read_bytes()).hexdigest()
    except OSError:
        raise ClientError("DEEPSEEK_BRIDGE_ENTRY_MISSING") from None
    return {
        "harness_version": SUPPORTED_VERSION,
        "bridge": bridge,
        "bridge_package": package_name,
        "bridge_version": SUPPORTED_COMPONENT_VERSION,
        "bridge_entry_sha256": entry_digest,
        "supported_events": ["SessionStart", "PostToolUse", "Stop"],
        "session_field": "session_id",
        "session_source": "agent.session.header.id",
        "workspace_field": "cwd",
        "workspace_source": "agent.session.header.cwd",
        "subagent_events": "UNSUPPORTED_CHILD_SESSION_ID",
        "session_end": "UNAVAILABLE",
        "configuration_reload": "PROCESS_RESTART_REQUIRED",
        "native_hooks": False,
        "automatic_trigger": "OFFICIAL_COMMAND_BRIDGE",
        "native_acceptance": "NOT_OBSERVED",
        "package_origin": "NOT_VERIFIED_BY_METADATA",
        "reference_source": OFFICIAL_SOURCE,
        "documentation_reference_commit": OFFICIAL_SOURCE_COMMIT,
    }


def bridge_descriptor(*, dsh_home: Path, profile: str, hook_config: Path,
                      bridge: str = "claude-code", executable: Path | None = None) -> dict:
    """Build one owned plugin row for an explicitly selected existing profile.

    The caller owns atomic merge/backup and the dedicated hook file. This helper
    neither reads nor changes that hook file and never initializes a profile.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        raise ClientError("DEEPSEEK_HOME_PROFILE_REQUIRED")
    home = dsh_home.expanduser().absolute()
    config = hook_config.expanduser().absolute()
    profile_dir = home / "profiles" / profile
    if profile_dir.is_symlink():
        raise ClientError("DEEPSEEK_EXISTING_PROFILE_REQUIRED")
    manifest = _metadata(profile_dir / "package.json")
    dsh_settings = manifest.get("dsh")
    settings = dsh_settings.get("profile") if isinstance(dsh_settings, dict) else None
    bundles = settings.get("bundles") if isinstance(settings, dict) else None
    if not isinstance(bundles, list) or not bundles or not all(
            isinstance(name, str) and name for name in bundles):
        raise ClientError("DEEPSEEK_EXISTING_PROFILE_REQUIRED")
    if config.is_symlink() or config == profile_dir / "package.json" or config == profile_dir / "cordis.patch.yml":
        raise ClientError("DEEPSEEK_DEDICATED_HOOK_CONFIG_REQUIRED")
    capability = bridge_capability(bridge=bridge, executable=executable)
    return {
        "id": "hypertest-local-hook-bridge",
        "name": capability["bridge_package"],
        "config": {
            "configPath": str(config),
            "defaultTimeoutMs": 15000,
            "stderrSummaryMaxChars": 128,
        },
    }


def root_bridge_descriptor(*, dsh_home: Path, profile: str, handler_command: list[str],
                           workspace: Path, executable: Path | None = None) -> dict:
    """Versioned HyperTest adapter over official root-registry/lifecycle APIs.

    Automatic source binding must use this adapter rather than the compatibility
    bridges: the latter cannot distinguish roots from a child's SessionStart.
    The adapter independently checks actual registry membership, not a caller's
    JSON ``is_root`` flag. The fixed argv starts only the private Hook handler.
    """
    if (not isinstance(handler_command, list) or len(handler_command) != 7
            or not all(isinstance(value, str) for value in handler_command)
            or not Path(handler_command[0]).is_absolute()
            or handler_command[1:6] != ["-I", "-m", "hypertest.local_sync", "hook", "--config"]
            or not Path(handler_command[6]).is_absolute()):
        raise ClientError("DEEPSEEK_FIXED_HOOK_HANDLER_REQUIRED")
    workspace = workspace.expanduser().absolute()
    if ".." in workspace.parts or workspace == Path("/") or workspace.is_symlink():
        raise ClientError("LOCAL_SOURCE_WORKSPACE_MISMATCH")
    # Reuse the read-only profile/version checks without creating a Hook file.
    bridge_descriptor(dsh_home=dsh_home, profile=profile,
                      hook_config=workspace / "hypertest-local-native-unused-reference.json",
                      executable=executable)
    root = _installation(executable)
    for name in ("dsh-agent", "dsh-llm"):
        package = root / "node_modules" / "@deepseek-ai" / name
        metadata = _metadata(package / "package.json")
        if metadata.get("name") != "@deepseek-ai/" + name or metadata.get("version") != SUPPORTED_COMPONENT_VERSION:
            raise ClientError("DEEPSEEK_ROOT_REGISTRY_VERSION_UNSUPPORTED")
        if not (package / "lib" / "index.js").is_file():
            raise ClientError("DEEPSEEK_ROOT_REGISTRY_VERSION_UNSUPPORTED")
    asset = Path(__file__).with_name("deepseek_root_bridge.mjs")
    if not asset.is_file():
        raise ClientError("DEEPSEEK_ROOT_BRIDGE_ASSET_MISSING")
    return {
        "id": "hypertest-local-hook-bridge",
        "name": str(asset),
        "config": {
            "handlerCommand": handler_command,
            "workspace": str(workspace),
            "createMessageModule": str(root / "node_modules" / "@deepseek-ai" / "dsh-llm" / "lib" / "index.js"),
            "harnessVersion": SUPPORTED_VERSION,
            "adapterSha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        },
    }
