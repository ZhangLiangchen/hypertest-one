"""Read/write the Harness SDK patch inside its dedicated cloud volume."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

import yaml

LIMIT = 1024 * 1024
PROFILE = Path(os.environ["DSH_HOME"]) / "profiles" / "sdk"
PATCH = PROFILE / "cordis.patch.yml"


def current() -> bytes:
    if PATCH.is_symlink() or (PATCH.exists() and not PATCH.is_file()):
        raise ValueError("invalid patch file")
    if not PATCH.exists():
        return b"[]\n"
    descriptor = os.open(PATCH, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise ValueError("invalid patch file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read(LIMIT + 1)
    finally:
        os.close(descriptor)


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "read":
        sys.stdout.buffer.write(current())
        return 0
    if len(sys.argv) != 3 or sys.argv[1] != "write" or not re.fullmatch(r"[a-f0-9]{64}", sys.argv[2]):
        return 2
    content = sys.stdin.buffer.read(LIMIT + 1)
    if len(content) > LIMIT or hashlib.sha256(current()).hexdigest() != sys.argv[2]:
        raise ValueError("profile changed or patch exceeds size limit")

    class DataOnlyLoader(yaml.SafeLoader):
        pass
    DataOnlyLoader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node))
    if not isinstance(yaml.load(content, Loader=DataOnlyLoader), list):
        raise ValueError("profile patch must be a YAML array")
    PROFILE.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".cordis-patch-", dir=PROFILE)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, PATCH)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("SDK profile patch unavailable, invalid, or changed during editing.", file=sys.stderr)
        raise SystemExit(1) from None
