#!/usr/bin/env python3
"""Select exact committed publication targets independently of native acceptance."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RUNNERS = {("Linux", "x86_64"): "ubuntu-24.04", ("Linux", "aarch64"): "ubuntu-24.04-arm",
           ("Darwin", "arm64"): "macos-15", ("Darwin", "x86_64"): "macos-15-intel"}


def plan(root: Path, tag: str) -> dict:
    if re.fullmatch(r"local-v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", tag) is None:
        raise ValueError("A fixed Local release tag is required")
    stable = re.fullmatch(r"local-v\d+\.\d+\.\d+", tag) is not None
    catalog = json.loads((root / "scripts/local-release-targets.json").read_bytes())
    if catalog.get("schema_version") != "hypertest.local-release-targets/v1":
        raise ValueError("Reviewed exact target catalog required")
    selected, targets = [], set()
    for row in catalog["targets"]:
        if (set(row) != {"target", "runner", "python", "system", "machine", "publication", "acceptance_file"}
                or row["target"] in targets or row["python"] not in {"3.12", "3.13"}
                or RUNNERS.get((row["system"], row["machine"])) != row["runner"]
                or row["publication"] not in {"CANDIDATE", "RELEASE"}):
            raise ValueError("Invalid duplicate or unsupported Local publication target")
        machine = "arm64" if row["machine"] == "aarch64" else row["machine"]
        expected = f"{row['system'].lower()}-{machine}-py{row['python'].replace('.', '')}"
        if row["target"] != expected:
            raise ValueError("Target name differs from actual runner/Python architecture")
        targets.add(row["target"])
        if stable and row["publication"] != "RELEASE":
            continue
        acceptance_file = row["acceptance_file"]
        if stable and acceptance_file is not None:
            if (not isinstance(acceptance_file, str)
                    or re.fullmatch(r"docs/local-acceptance/[a-z0-9_-]+\.json", acceptance_file) is None):
                raise ValueError("Host acceptance must use committed exact source-bound evidence")
            evidence = json.loads((root / acceptance_file).read_bytes())
            target = {key: row[key] for key in ("system", "machine", "python")}
            if (evidence.get("schema_version") != "hypertest.local-host-acceptance/v1"
                    or evidence.get("release_tag") != tag or evidence.get("target") != target
                    or set(evidence.get("hosts", {})) != {"codex", "claude-code", "deepseek-harness"}
                    or any(host.get("native_acceptance") != "ACCEPTED" for host in evidence["hosts"].values())):
                raise ValueError("Formal target has incomplete or different native host acceptance")
        elif not stable:
            # A formal-tag evidence record must not be relabeled for a prerelease.
            acceptance_file = ""
        selected.append({key: row[key] for key in ("target", "runner", "python", "system", "machine")}
                        | {"acceptance_file": acceptance_file or ""})
    if not selected:
        raise ValueError("No RELEASE publication targets selected; use an explicit prerelease for candidate-only outputs")
    return {"include": selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        matrix = plan(args.root, args.tag)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Local release target planning BLOCKED: {exc}\n")
    print(json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
