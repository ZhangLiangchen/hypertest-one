"""Small host-only release file primitives; no application/runtime imports."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def canonical_directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("canonical absolute directory required")


def write_new(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, mode)


def json_new(path: Path, value: dict, *, mode: int = 0o600) -> None:
    write_new(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(), mode=mode)


def extract_image(archive: Path, destination: Path) -> None:
    """Extract a pinned export without ever writing through an archive link.

    Directories/files first, hardlinks second, symlinks last. Absolute image
    symlink *values* are retained for RootDirectory use; never traversed here.
    Special device entries are refused. The outer release directory is 0700,
    so image setuid files cannot become an executable host installation.
    """
    canonical_directory(destination)
    with tarfile.open(archive) as source:
        members = source.getmembers()
        paths = {}
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise ValueError("archive path refused")
            key = name.as_posix()
            if key == "." and member.isdir():
                continue
            if key in paths or not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
                raise ValueError("archive member refused")
            paths[key] = member
        links = {key for key, item in paths.items() if item.issym() or item.islnk()}
        for key in paths:
            if any(parent.as_posix() in links for parent in PurePosixPath(key).parents):
                raise ValueError("archive link ancestor refused")
        for key, item in paths.items():
            if not item.isdir():
                continue
            (destination / key).mkdir(parents=True, exist_ok=True)
        for key, item in paths.items():
            if not item.isfile():
                continue
            target = destination / key
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as output, source.extractfile(item) as content:
                while block := content.read(1024 * 1024):
                    output.write(block)
            os.chmod(target, stat.S_IMODE(item.mode))
            os.chown(target, item.uid, item.gid)
        for key, item in paths.items():
            if not item.islnk():
                continue
            name = PurePosixPath(item.linkname)
            original = paths.get(name.as_posix())
            if (name.is_absolute() or ".." in name.parts or original is None
                    or not original.isfile() or (item.uid, item.gid, item.mode)
                    != (original.uid, original.gid, original.mode)):
                raise ValueError("archive hardlink refused")
            target = destination / key
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(destination / name, target, follow_symlinks=False)
        for key, item in paths.items():
            if item.issym():
                target = destination / key
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(item.linkname, target)
                os.lchown(target, item.uid, item.gid)
        for key, item in sorted(paths.items(), key=lambda pair: len(PurePosixPath(pair[0]).parts), reverse=True):
            if item.isdir():
                os.chmod(destination / key, stat.S_IMODE(item.mode))
                os.chown(destination / key, item.uid, item.gid)
