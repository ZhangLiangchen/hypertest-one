#!/usr/bin/env python3
"""Build a pinned, dependency-free CLI zipapp from a clean committed source tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["hypertest/__init__.py", "hypertest/sync_core/__init__.py", "hypertest/sync_core/core.py",
         "hypertest/sync_core/storage.py", "hypertest/interactive_client/__init__.py",
         "hypertest/interactive_client/errors.py", "hypertest/interactive_client/security.py",
         "hypertest/interactive_client/journal.py"]


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha) or args.source_sha != run_git("rev-parse", "HEAD"):
        parser.error("--source-sha must be the full checked-out commit")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", args.version):
        parser.error("invalid version")
    if run_git("status", "--porcelain", "--untracked-files=normal"):
        parser.error("build from a clean committed checkout")
    version_line = f'CLI_VERSION = "{args.version}"'
    if version_line not in (ROOT / "src/hypertest/cli/__init__.py").read_text():
        parser.error("release version does not match CLI_VERSION")
    output = args.output_dir.expanduser().absolute()
    if output.is_relative_to(ROOT):
        parser.error("release output must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"hypertest-cli-{args.version}.pyz"
    manifest = output / f"hypertest-cli-{args.version}.manifest.json"
    if artifact.exists() or manifest.exists():
        parser.error("release files already exist; never overwrite published identities")
    members = {name: (ROOT / "src" / name).read_bytes() for name in FILES}
    for path in sorted((ROOT / "src/hypertest/cli").glob("*.py")):
        members["hypertest/cli/" + path.name] = path.read_bytes()
    for path in sorted((ROOT / "skills/hypertest-archive").rglob("*")):
        if path.is_file():
            members["hypertest/cli/assets/skills/hypertest-archive/" +
                    path.relative_to(ROOT / "skills/hypertest-archive").as_posix()] = path.read_bytes()
    members["__main__.py"] = b'''import sys
if sys.version_info < (3, 12) or sys.platform not in {"linux", "darwin"}:
    raise SystemExit("HyperTest CLI requires Python >=3.12 on Linux or macOS")
from hypertest.cli.__main__ import main
raise SystemExit(main())
'''
    with artifact.open("xb") as stream:
        stream.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            # Directory entries allow importlib.resources to locate bundled skills in zipapps.
            directories = {str(parent) + "/" for name in members for parent in Path(name).parents
                           if str(parent) != "."}
            for name in sorted(directories | members.keys()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if name.endswith("/") else 0o644) << 16
                archive.writestr(info, members.get(name, b""))
    artifact.chmod(0o755)
    payload = {"schema": "hypertest.cli-release/v1", "version": args.version,
               "tag": "cli-v" + args.version, "source_sha": args.source_sha,
               "artifact": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
               "size_bytes": artifact.stat().st_size, "python": ">=3.12",
               "platforms": ["linux", "darwin"], "architecture": "python-portable",
               "dependencies": [], "entrypoint": "hypertest", "implicit_sync": False}
    manifest.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"artifact": str(artifact), "manifest": str(manifest), **payload}, sort_keys=True))


if __name__ == "__main__":
    main()
