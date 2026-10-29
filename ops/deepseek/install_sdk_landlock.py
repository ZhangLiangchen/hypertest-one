"""Install the exact SDK's missing official Landlock launcher into its snapshot path.

The SDK runtime wheel's packaged Node snapshot contains the platform metadata and
system addon but omits the external executable resolved by sandbox-local. This
build-time helper fetches only the matching, integrity-pinned public npm archive;
it never consumes model or project credentials and never changes SDK policy.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import platform
import tarfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "0.1.2"
PACKAGES = {
    "aarch64": ("arm64", "sha512-Z/DQtqgEYzjBzb2ocHGjMzx51W7xDILkJKKj89nyErr8gZMNiLs+JNL1uKzJqc3VLZB+vYCPaHGyQ3oX6EzEmA==", 183),
    "x86_64": ("x64", "sha512-S2aPVHvYCpNCppCFyNlooMYuTB7ucK5lvD9oXQQ42v5Z2s5AoaiCdjz9r2l+ED2rI5oS1x0cUZmKjJH2dxV0pg==", 62),
}
MAX_ARCHIVE = 2 * 1024 * 1024


def validate_package(raw: bytes, arch: str, integrity: str, machine: int) -> tuple[bytes, bytes]:
    if len(raw) > MAX_ARCHIVE or "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode() != integrity:
        raise ValueError("official Landlock package integrity mismatch")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()

        def read(name: str, limit: int, *, executable: bool = False) -> bytes:
            matches = [member for member in members if member.name == name]
            if len(matches) != 1:
                raise ValueError("official Landlock package member mismatch")
            member = matches[0]
            if not member.isfile() or not 0 < member.size <= limit or executable and not member.mode & 0o111:
                raise ValueError("official Landlock package member invalid")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("official Landlock package member unavailable")
            return stream.read()

        metadata = json.loads(read("package/package.json", 16384))
        if metadata.get("name") != f"@deepseek-ai/node-addon-system-linux-{arch}" or metadata.get("version") != VERSION:
            raise ValueError("official Landlock package identity mismatch")
        binary = read("package/bin/landlock-run", 1024 * 1024, executable=True)
        license_text = read("package/LICENSE", 32768)
        if (len(binary) < 20 or binary[:4] != b"\x7fELF" or binary[4:6] != b"\x02\x01"
                or int.from_bytes(binary[18:20], "little") != machine):
            raise ValueError("official Landlock executable architecture mismatch")
        return binary, license_text


def main() -> None:
    try:
        arch, integrity, machine = PACKAGES[platform.machine()]
    except KeyError:
        raise SystemExit("unsupported Cloud Worker architecture") from None
    url = f"https://registry.npmjs.org/@deepseek-ai/node-addon-system-linux-{arch}/-/node-addon-system-linux-{arch}-{VERSION}.tgz"
    with urlopen(url, timeout=60) as response:
        raw = response.read(MAX_ARCHIVE + 1)
    binary, license_text = validate_package(raw, arch, integrity, machine)
    root = Path(f"/snapshot/node/node_modules/@deepseek-ai/node-addon-system-linux-{arch}")
    (root / "bin").mkdir(parents=True, exist_ok=True)
    for path, content, mode in ((root / "bin/landlock-run", binary, 0o755), (root / "LICENSE", license_text, 0o644)):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        path.chmod(mode)
    print(json.dumps({"package": f"@deepseek-ai/node-addon-system-linux-{arch}", "version": VERSION,
                      "launcher_sha256": hashlib.sha256(binary).hexdigest()}))


if __name__ == "__main__":
    main()
