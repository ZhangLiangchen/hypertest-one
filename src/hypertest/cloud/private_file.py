"""Bounded host-only private files, including exact systemd credential ACLs.

Ordinary files remain owner-only 0400/0600. A group-readable mode is accepted
only for the current service's root-owned, readonly LoadCredential directory
with an exact ACL granting root and this non-root UID access and nobody else.
"""

from __future__ import annotations

import os
import re
import stat
import struct
import sys
from pathlib import Path

from .errors import CloudBlocked

_UNDEFINED_ID = 0xFFFFFFFF
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,254}")


def _open_parent(path: Path) -> int:
    """Walk descriptors instead of resolving a path and opening it again."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:-1]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _exact_acl(descriptor: int, *, uid: int, permissions: int) -> bool:
    # Linux UAPI posix_acl_xattr: little-endian version 2 plus 8-byte entries.
    # Five entries are required, so missing/duplicate/extra identities fail.
    raw = os.getxattr(descriptor, "system.posix_acl_access")
    if len(raw) != 44 or struct.unpack_from("<I", raw)[0] != 2:
        return False
    entries = list(struct.iter_unpack("<HHI", raw[4:]))
    expected = {(1, permissions, _UNDEFINED_ID), (2, permissions, uid),
        (4, 0, _UNDEFINED_ID), (16, permissions, _UNDEFINED_ID), (32, 0, _UNDEFINED_ID)}
    return len(entries) == len(expected) and set(entries) == expected


def _systemd_credential(descriptor: int, parent: int, path: Path,
                        expected_directory: str | Path | None, uid: int) -> bool:
    if sys.platform != "linux" or uid == 0 or expected_directory is None:
        return False
    parts = path.parts
    if (len(parts) != 5 or parts[:3] != ("/", "run", "credentials")
            or not _NAME.fullmatch(parts[3]) or not _NAME.fullmatch(parts[4])):
        return False
    expected = os.fspath(expected_directory)
    if expected != os.path.normpath(expected) or expected != str(path.parent):
        return False
    file_info, directory_info = os.fstat(descriptor), os.fstat(parent)
    if (file_info.st_uid != 0 or file_info.st_gid != 0 or stat.S_IMODE(file_info.st_mode) != 0o440
            or file_info.st_nlink != 1 or directory_info.st_uid != 0 or directory_info.st_gid != 0
            or not stat.S_ISDIR(directory_info.st_mode) or stat.S_IMODE(directory_info.st_mode) != 0o550):
        return False
    if not (os.fstatvfs(descriptor).f_flag & os.ST_RDONLY and os.fstatvfs(parent).f_flag & os.ST_RDONLY):
        return False
    return _exact_acl(descriptor, uid=uid, permissions=4) and _exact_acl(parent, uid=uid, permissions=5)


def read_private_file(path: str | Path, *, max_bytes: int,
                      credentials_directory: str | Path | None = None) -> bytes:
    """Read one fixed host-configured file; no paths or native errors escape.

    CREDENTIALS_DIRECTORY is non-secret service metadata, supplied by the host
    service manager or an explicit host-only expected directory. Never pass an
    Agent-controlled value. No key, OAuth refresh or file mutation occurs here.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1024 * 1024:
        raise CloudBlocked("PRIVATE_FILE_SIZE", "Private file limit is outside the supported bound")
    parent = descriptor = None
    try:
        original = os.fspath(path)
        absolute = Path(os.path.abspath(original))
        # Do not admit a disguised LoadCredential path containing '..'.
        if ".." in Path(original).parts:
            raise CloudBlocked("PRIVATE_FILE_UNSAFE", "Private file path must be canonical")
        parent = _open_parent(absolute)
        descriptor = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CloudBlocked("PRIVATE_FILE_UNSAFE", "Private input requires one regular file without aliases")
        if not 0 < info.st_size <= max_bytes:
            raise CloudBlocked("PRIVATE_FILE_SIZE", "Private input is empty or exceeds its byte bound")
        uid = os.geteuid()
        ordinary = stat.S_IMODE(info.st_mode) in {0o400, 0o600} and info.st_uid in {0, uid}
        expected = credentials_directory if credentials_directory is not None else os.environ.get("CREDENTIALS_DIRECTORY")
        if not ordinary and (original != str(absolute) or not _systemd_credential(descriptor, parent, absolute, expected, uid)):
            raise CloudBlocked("PRIVATE_FILE_UNSAFE", "Private input permissions are outside the supported file profiles")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            content = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
        if (len(content) > max_bytes or len(content) != info.st_size
                or (after.st_mode, after.st_uid, after.st_gid, after.st_nlink,
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns) !=
                   (info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
                    info.st_size, info.st_mtime_ns, info.st_ctime_ns)):
            raise CloudBlocked("PRIVATE_FILE_CHANGED", "Private input changed during its bounded read")
        return content
    except CloudBlocked:
        raise
    except (OSError, ValueError, TypeError):
        raise CloudBlocked("PRIVATE_FILE_UNAVAILABLE", "Private input cannot be safely opened or inspected") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)
