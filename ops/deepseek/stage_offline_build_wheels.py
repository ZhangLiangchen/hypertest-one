#!/usr/bin/env python3
"""Stage six locally cached public wheels after exact SHA256 verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from build_worker_offline import WHEELS

# Cache keys for the verified local PyPI HTTP cache; these are not content hashes.
CACHE_KEYS = {
    "hatchling-1.32.4-py3-none-any.whl": "4608312ae720d52c118fa96091f60fc9d595b0923e05a183afd56fbb",
    "packaging-26.1-py3-none-any.whl": "32183707ade182cd93fb4097d37847a6b2de228bb68baf4fbd49cedb",
    "pathspec-1.1.1-py3-none-any.whl": "5d7a24047f95e5c6b3ca5dc91bb2a0b9af66ac1055c47dfd38fafd9d",
    "pluggy-1.7.0-py3-none-any.whl": "15397fc65495072de65d48ede5abe894038eb774927b6d5c340d0342",
    "tomlkit-0.15.2-py3-none-any.whl": "6be18cfdfa4d2a9e80cf41acbb1e0ca24e997733d5ac996897b2ed00",
    "trove_classifiers-2026.9.21.13-py3-none-any.whl": "9e607aa87139e5c9ff9ad0069c9756e92fd6cab97eab4df7fbff067f",
}


def stage(cache: Path, destination: Path) -> None:
    if (not cache.is_absolute() or cache.resolve(strict=True) != cache or not destination.is_absolute()
            or destination.parent.resolve(strict=True) != destination.parent or destination.exists() or destination.is_symlink()):
        raise ValueError("unsafe cache or destination")
    destination.mkdir(mode=0o700)
    for name, key in CACHE_KEYS.items():
        source = cache.joinpath(*key[:5], key + ".body")
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 16 * 1024**2:
            raise ValueError("cache input unavailable")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != WHEELS[name]:
            raise ValueError("cached wheel hash mismatch")
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(content)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise OSError("wheel write failed")
                view = view[count:]
            os.fsync(fd)
        finally:
            os.close(fd)
    directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        stage(args.cache, args.destination)
    except (OSError, ValueError, KeyError):
        print(json.dumps({"status": "BLOCKED", "code": "OFFLINE_BUILD_WHEELHOUSE_UNAVAILABLE"}))
        return 1
    print(json.dumps({"status": "PREPARED", "wheel_count": len(WHEELS), "credentials_read": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
