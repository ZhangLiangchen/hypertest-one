"""Private local files and peer-UID checks; no secrets enter MCP arguments."""
from __future__ import annotations

import ctypes
import os
import socket
import stat
from pathlib import Path

from hypertest.interactive_client.errors import ClientError


def private_directory(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ClientError("PRIVATE_DIRECTORY_REQUIRED")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = path.resolve(strict=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ClientError("PRIVATE_DIRECTORY_REQUIRED")
    return path


def private_read(path: Path, *, max_bytes: int = 1_000_000) -> bytes:
    try:
        fd = os.open(path.expanduser(), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > max_bytes):
                raise ClientError("PRIVATE_FILE_REQUIRED")
            data = os.read(fd, max_bytes + 1)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ClientError("PRIVATE_FILE_UNAVAILABLE") from exc
    if len(data) > max_bytes:
        raise ClientError("PRIVATE_FILE_REQUIRED")
    return data


def private_create(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def peer_uid(stream: socket.socket) -> int:
    if hasattr(socket, "SO_PEERCRED"):
        import struct
        return struct.unpack("3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    # Darwin/BSD expose getpeereid(2); use the accepted FD, never process env.
    libc = ctypes.CDLL(None, use_errno=True)
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    if libc.getpeereid(stream.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
        raise ClientError("LOCAL_PEER_REJECTED")
    return uid.value


def peer_pid(stream: socket.socket) -> int:
    import struct
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack("3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
    # Darwin LOCAL_PEERPID. Fail closed where the platform has no equivalent.
    try:
        return struct.unpack("i", stream.getsockopt(0, 2, 4))[0]
    except OSError as exc:
        raise ClientError("LOCAL_PEER_REJECTED") from exc
