"""Host-visible persistent source copies; integrity derives from the pinned checkout."""
from __future__ import annotations

import hashlib
from pathlib import Path

from hypertest.agent.snapshot import _is_source_file
from hypertest.config import get_settings
from hypertest.harness_bridge.protocol import WORKSPACE
from hypertest.runner.source import copy_tracked_source, validate_checkout


def workspace_path(workspace_id: str) -> Path:
    if not WORKSPACE.fullmatch(workspace_id):
        raise RuntimeError("invalid persistent workspace identity")
    root = Path(get_settings().workspace_root).resolve() / ".hypertest-agent-sessions"
    target = root / workspace_id / "repo"
    if any(p.is_symlink() for p in (root, target.parent, target)) or target.resolve() != target:
        raise RuntimeError("persistent workspace must not traverse a symlink")
    return target


async def verify_workspace(source: str, workspace_id: str, commit: str, origin: str,
                           *, create: bool = False) -> list[str]:
    original = Path(source).resolve()
    allowed = Path(get_settings().workspace_root).resolve()
    if not original.is_relative_to(allowed) or not original.is_dir():
        raise RuntimeError("source checkout is outside the configured workspace root")
    tracked = await validate_checkout(original, commit, origin)
    tracked = [name for name in tracked if _is_source_file(name)]
    target = workspace_path(workspace_id)
    if create:
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=False)
        copy_tracked_source(original, target, tracked)
    if not target.is_dir():
        raise RuntimeError("persistent workspace is unavailable; start a new round or restore the original")
    for name in tracked:
        path = target / name
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(target)
                or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256((original / name).read_bytes()).digest()):
            raise RuntimeError("persistent workspace does not match its pinned source")
    return tracked
