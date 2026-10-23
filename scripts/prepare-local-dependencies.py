#!/usr/bin/env python3
"""Download one target's already pinned, source-audited Local dependency closure.

No dependency resolution, sdist builds, project imports or host changes occur.
Run on the authorized release runner with CPython 3.12/3.13, not on a user's host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def catalog_rows(path: Path) -> list[dict]:
    body = json.loads(path.read_bytes())
    if (body.get("schema_version") != "hypertest.local-dependency-catalog/v1"
            or body.get("python") != ["3.12", "3.13"] or body.get("index_url") != "https://pypi.org/simple"
            or not isinstance(body.get("distributions"), list)):
        raise ValueError("Reviewed CPython 3.12/3.13 Local dependency catalog required")
    rows = body["distributions"]
    names, filenames = set(), set()
    for row in rows:
        if (set(row) != {"name", "version", "wheels"}
                or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", row["name"]) is None
                or re.fullmatch(r"\d+(?:\.\d+)*", row["version"]) is None
                or row["name"] in names or not row["wheels"]):
            raise ValueError("Invalid duplicate or unpinned dependency")
        names.add(row["name"])
        for wheel in row["wheels"]:
            origin = urlsplit(wheel["origin_url"])
            if (set(wheel) != {"filename", "origin_url", "sha256"}
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*\.whl", wheel["filename"]) is None
                    or wheel["filename"] in filenames
                    or re.fullmatch(r"[a-f0-9]{64}", wheel["sha256"]) is None
                    or origin.scheme != "https" or origin.hostname != "files.pythonhosted.org"
                    or origin.username is not None or origin.password is not None or origin.query or origin.fragment
                    or not origin.path.endswith("/" + wheel["filename"])):
                raise ValueError("Dependency provenance must be a fixed PyPI wheel and SHA-256")
            filenames.add(wheel["filename"])
    if not {"pydantic", "httpx", "jsonschema", "mcp"} <= names or not 4 <= len(rows) <= 150:
        raise ValueError("Local dependency closure is missing")
    return rows


def selected_lock(rows: list[dict], wheelhouse: Path) -> dict:
    available = {path.name: path for path in wheelhouse.iterdir()}
    selected = []
    for row in rows:
        matches = [wheel for wheel in row["wheels"] if wheel["filename"] in available]
        if len(matches) != 1:
            raise ValueError("Each dependency requires exactly one audited target wheel")
        wheel = matches[0]
        path = available.pop(wheel["filename"])
        if (path.is_symlink() or not path.is_file() or path.stat().st_size > 80 * 1024 * 1024
                or hashlib.sha256(path.read_bytes()).hexdigest() != wheel["sha256"]):
            raise ValueError("Downloaded dependency differs from reviewed origin/hash")
        selected.append({"name": row["name"], "version": row["version"], **wheel})
    if available:
        raise ValueError("Unreviewed file present in target wheelhouse")
    return {"schema_version": "hypertest.local-dependency-lock/v1", "wheels": selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).with_name("local-release-dependencies.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (sys.implementation.name != "cpython" or sys.version_info[:2] not in {(3, 12), (3, 13)}
            or platform.system() not in {"Darwin", "Linux"}):
        parser.error("Use a supported macOS/Linux CPython 3.12/3.13 release runner")
    try:
        rows = catalog_rows(args.catalog)
        if args.output.exists() and (args.output.is_symlink() or not args.output.is_dir() or any(args.output.iterdir())):
            raise ValueError("Dependency output must be absent or an empty real directory")
        args.output.mkdir(parents=True, exist_ok=True)
        requirements = args.output / "download-requirements.txt"
        requirements.write_text("".join(row["name"] + "==" + row["version"] + " "
            + " ".join("--hash=sha256:" + wheel["sha256"] for wheel in row["wheels"]) + "\n" for row in rows))
        wheelhouse = args.output / "wheelhouse"
        wheelhouse.mkdir()
        subprocess.run([sys.executable, "-I", "-m", "pip", "--isolated", "download", "--no-deps",
                        "--only-binary=:all:", "--require-hashes", "--index-url", "https://pypi.org/simple",
                        "--dest", str(wheelhouse), "--requirement", str(requirements)], check=True)
        lock = selected_lock(rows, wheelhouse)
        (args.output / "dependencies.lock.json").write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        parser.exit(1, "Local dependency preparation BLOCKED; preserve output for review.\n")
    print(json.dumps({"dependency_count": len(rows), "resolution": "NONE_FIXED_CATALOG", "target": {
        "system": platform.system(), "machine": platform.machine(),
        "python": f"3.{sys.version_info.minor}"}}))


if __name__ == "__main__":
    main()
