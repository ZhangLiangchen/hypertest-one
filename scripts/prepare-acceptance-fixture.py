"""Create real pinned backend commits for live Agent/Docker acceptance.

This creates application source only. No Agent result or generated test is supplied.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

PRD = (
    "The checkout backend submit_order(key) returns key. Repeated or concurrent calls "
    "with the same nonempty string key must store exactly one order for that key; "
    "distinct keys remain distinct. order_count() reports the total number of accepted "
    "unique keys. Acceptance covers idempotency only. State is in-memory; each test "
    "must start with fresh module state. HTTP, authentication, persistence, and invalid "
    "key handling are outside scope. Use only Python standard library and pytest."
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    destination = parser.parse_args().destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / "source"
    source.mkdir()
    git(source, "init", "--initial-branch=main")
    git(source, "config", "user.name", "HyperTest Acceptance")
    git(source, "config", "user.email", "acceptance@example.invalid")
    code = (
        '"""In-memory checkout backend: one order per idempotency key."""\n'
        "from threading import Lock\n\norders = []\nlock = Lock()\n\n"
        "def submit_order(key):\n"
        "    with lock:\n"
        "        if key not in orders:\n"
        "            orders.append(key)\n"
        "    return key\n\n"
        "def order_count():\n"
        "    return len(orders)\n"
    )
    (source / "checkout.py").write_text(code)
    (source / "PRD.md").write_text(PRD + "\n")
    git(source, "add", "checkout.py", "PRD.md")
    git(source, "commit", "-m", "Implement checkout idempotency")
    passing = git(source, "rev-parse", "HEAD")
    (source / "checkout.py").write_text(code.replace(
        "        if key not in orders:\n            orders.append(key)",
        "        orders.append(key)",
    ))
    git(source, "add", "checkout.py")
    git(source, "commit", "-m", "Introduce duplicate-order regression for acceptance")
    failing = git(source, "rev-parse", "HEAD")
    manifest = {"repository_url": str(source), "prd_text": PRD}
    for name, commit in (("passing", passing), ("failing", failing)):
        checkout = destination / name
        subprocess.run(["git", "clone", "--quiet", str(source), str(checkout)], check=True)
        git(checkout, "checkout", "--detach", commit)
        manifest[name] = {"workspace": str(checkout), "commit_sha": commit}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
