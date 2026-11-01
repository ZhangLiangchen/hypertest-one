"""Copy a dedicated cloud Harness SDK profile into one isolated Attempt.

The configured source is an operator-owned cloud DSH_HOME, not a user's local
login directory. Only the sdk profile (including its package tree) is copied;
session storage and DSH_HOME-level credentials are deliberately not copied.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from .errors import CloudBlocked


def _validate_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid profile root")
    real_root = root.resolve(strict=True)
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(current) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                # pnpm uses relative symlinks within its own package tree.
                target = os.readlink(path)
                if os.path.isabs(target) or not path.resolve(strict=True).is_relative_to(real_root):
                    raise ValueError("profile symlink escapes its tree")
            elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError("unsupported profile object")


def _sdk_directory(cloud_home: str) -> Path:
    source_home = Path(cloud_home)
    if not source_home.is_absolute() or source_home.is_symlink() or not source_home.is_dir():
        raise ValueError("dedicated cloud home unavailable")
    source = source_home / "profiles" / "sdk"
    if (source.is_symlink() or not source.is_dir()
            or not source.resolve(strict=True).is_relative_to(source_home.resolve(strict=True))
            or not os.access(source, os.R_OK | os.X_OK)):
        raise ValueError("profile unavailable or escapes cloud home")
    return source


def check_sdk_profile(cloud_home: str) -> None:
    """Check basic profile availability without changing it or reading secrets."""
    try:
        _sdk_directory(cloud_home)
    except (OSError, ValueError):
        raise CloudBlocked("HARNESS_PROFILE_UNAVAILABLE", "The dedicated cloud SDK profile is unavailable or unsafe") from None


def snapshot_sdk_profile(*, cloud_home: str, attempt_home: Path) -> None:
    """Snapshot the SDK profile; failure never falls back to a personal home."""
    try:
        source = _sdk_directory(cloud_home)
        _validate_tree(source)
        destination = attempt_home / "dsh" / "profiles" / "sdk"
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        shutil.copytree(source, destination, symlinks=True)
        _validate_tree(destination)
    except (OSError, ValueError, shutil.Error):
        raise CloudBlocked("HARNESS_PROFILE_UNAVAILABLE", "The dedicated cloud SDK profile is unavailable or unsafe") from None
