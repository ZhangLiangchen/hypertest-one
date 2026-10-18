#!/usr/bin/env python3
"""Paired cold backup and isolated restore; never restore over the application DB."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from stack import compose_command, read_env, validate


def compose(env: Path, *args: str, **kwargs):
    return subprocess.run(compose_command(env, *args), check=True, **kwargs)


def postgres(env: Path, command: str, *, stdout=None, input=None):
    return compose(env, "exec", "-T", "postgres", "sh", "-ec", command, stdout=stdout, input=input)


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def quiescent(env: Path, bridge_service: str = "hypertest-harness-bridge") -> None:
    if not re.fullmatch(r"hypertest-[a-zA-Z0-9_.-]{1,100}", bridge_service):
        raise ValueError("Bridge service requires an explicit hypertest- unit name")
    running = compose(env, "ps", "--status", "running", "--services", capture_output=True, text=True).stdout.splitlines()
    if set(running) & {"api", "worker", "migrate"}:
        raise ValueError("stop API/Worker/migration writers before a paired backup")
    result = subprocess.run(["systemctl", "is-active", bridge_service], capture_output=True, text=True)
    if result.stdout.strip() not in ("inactive", "failed"):
        raise ValueError("stop and verify the Host Harness Bridge before a paired backup")
    query = "SELECT count(*) FROM durable_jobs WHERE status IN ('QUEUED','RUNNING','CANCEL_REQUESTED')"
    result = compose(env, "exec", "-T", "postgres", "sh", "-ec",
                     f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "{query}"',
                     capture_output=True, text=True)
    if result.stdout.strip() != "0":
        raise ValueError("active requests remain; inspect and quiesce explicitly without deleting history")


def backup(env: Path, values: dict[str, str], target: Path, state: Path,
           bridge_service: str = "hypertest-harness-bridge") -> None:
    quiescent(env, bridge_service)
    if not state.is_absolute() or not state.is_dir():
        raise ValueError("provide the actual Bridge state directory")
    if target.exists() or not target.is_absolute():
        raise ValueError("backup output must be a new absolute directory")
    protected = [Path(values["HYPERTEST_ARTIFACT_ROOT"]), Path(values["HYPERTEST_WORKSPACE_ROOT"]), state]
    if any(root == target or root in target.parents for root in protected):
        raise ValueError("backup output must be outside all source directories")
    target.mkdir(mode=0o700)
    try:
        with (target / "database.dump").open("xb") as output:
            postgres(env, 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc', stdout=output)
        sources = {
            "artifacts": Path(values["HYPERTEST_ARTIFACT_ROOT"]),
            "workspaces": Path(values["HYPERTEST_WORKSPACE_ROOT"]),
            "bridge-state": state,
        }
        for name, path in sources.items():
            # Do not follow symlinks into provider auth or any other host directory.
            with tarfile.open(target / f"{name}.tar.gz", "x:gz", dereference=False) as archive:
                archive.add(path, arcname=name)
        manifest = {
            "format": "hypertest.paired-backup/v1", "created_at": datetime.now(UTC).isoformat(),
            "stack": values["HYPERTEST_STACK_NAME"], "postgres_volume": values["HYPERTEST_POSTGRES_VOLUME"],
            "bridge_service": bridge_service,
            "images": {key: value for key, value in values.items() if key.endswith("_IMAGE")},
            "source_paths": {name: str(path) for name, path in sources.items()},
            "files": {path.name: sha(path) for path in sorted(target.iterdir())},
            "provider_auth": "retained on host; never copied by this script",
            "provider_native_sessions": "retained in original host runtime; separate protected recovery needed",
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (target / "COMPLETE").write_text(sha(target / "manifest.json") + "\n")
    except BaseException:
        print(f"Incomplete backup retained for inspection: {target}", file=sys.stderr)
        raise
    print(f"paired backup complete: {target}")


def restore_verify(env: Path, source: Path, destination: Path, database: str) -> None:
    # New names and an empty destination prevent an accidental production restore.
    if not re.fullmatch(r"hypertest_verify_[a-z0-9_]{1,40}", database):
        raise ValueError("isolated database must start hypertest_verify_ and use lowercase letters/digits")
    if destination.exists() or not destination.is_absolute():
        raise ValueError("restore destination must be a new absolute directory")
    if (source / "COMPLETE").read_text().strip() != sha(source / "manifest.json"):
        raise ValueError("backup manifest is incomplete or modified")
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("format") != "hypertest.paired-backup/v1":
        raise ValueError("unsupported paired backup format")
    required = {"database.dump", "artifacts.tar.gz", "workspaces.tar.gz", "bridge-state.tar.gz"}
    if set(manifest["files"]) != required:
        raise ValueError("paired backup is missing a required component")
    for name, digest in manifest["files"].items():
        if sha(source / name) != digest:
            raise ValueError(f"backup hash mismatch: {name}")
    postgres(env, f'createdb -U "$POSTGRES_USER" "{database}"')
    with (source / "database.dump").open("rb") as dump:
        compose(env, "exec", "-T", "postgres", "sh", "-ec",
                f'exec pg_restore -U "$POSTGRES_USER" -d "{database}" --no-owner --exit-on-error --single-transaction', stdin=dump)
    destination.mkdir(mode=0o700)
    for name in ("artifacts", "workspaces", "bridge-state"):
        with tarfile.open(source / f"{name}.tar.gz", "r:gz") as archive:
            # Python 3.12+ rejects traversal, external links and special device files.
            archive.extractall(destination, filter="data")
    print(json.dumps({"restore_database": database, "restored_files": str(destination),
                      "checksums_verified": True, "application_data_verified": False,
                      "next": "Run application integrity checks and migration in this isolated DB; production untouched"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, default=Path("/run/lock/hypertest-maintenance.lock"))
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("backup")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--bridge-state", type=Path, required=True)
    create.add_argument("--bridge-service", default="hypertest-harness-bridge")
    restore = commands.add_parser("restore-verify")
    restore.add_argument("--source", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    restore.add_argument("--database", required=True)
    args = parser.parse_args()
    values = read_env(args.env)
    validate(values, live=True)
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "backup":
            backup(args.env, values, args.output, args.bridge_state, args.bridge_service)
        else:
            restore_verify(args.env, args.source, args.output, args.database)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"backup operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
