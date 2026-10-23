#!/usr/bin/env python3
"""Render a new persistent Worker unit, or inspect its public deployment record.

No installation, daemon-reload, service start, DB, SDK or model call is performed.
The separately rendered doctor unit runs the real startup admission and /usr/bin/true.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

from release_files import canonical_directory, digest, json_new, write_new

HERE = Path(__file__).resolve().parent
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
PLACEHOLDER = re.compile(r"@[A-Z][A-Z0-9_]*@")
FORBIDDEN_ENV = {"CREDENTIALS_DIRECTORY", "HYPERTEST_CLOUD_SERVICE_RELEASE_SHA256",
    "HYPERTEST_CLOUD_RUNTIME_ROOT", "HYPERTEST_CLOUD_CREDENTIAL_KEY_FILE",
    "HYPERTEST_CLOUD_MODEL_KEY_FILE", "HYPERTEST_CLOUD_CODEX_ENABLED",
    "HYPERTEST_CLOUD_CODEX_OAUTH_FILE", "HYPERTEST_CLOUD_CODEX_PAYLOAD",
    "HYPERTEST_CLOUD_CODEX_PAYLOAD_SHA256", "HYPERTEST_CLOUD_SSH_ENABLED"}


def safe_path(value: Path) -> str:
    if (not value.is_absolute() or value.resolve(strict=True) != value
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(value))):
        raise ValueError("canonical existing unit path required")
    return str(value)


def private_env(path: Path) -> dict:
    safe_path(path)
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise ValueError("worker env requires root-owned 0600 regular file")
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if (not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
                or key in values or key in FORBIDDEN_ENV
                or any(char in value for char in "\r\n\x00$`\"'")):
            raise ValueError("worker environment overrides a controlled field or has unsupported syntax")
        values[key] = value
    if (values.get("HYPERTEST_CLOUD_ENABLED") != "true"
            or values.get("HYPERTEST_CLOUD_WORKER_ENABLED") != "true"
            or not values.get("HYPERTEST_DATABASE_URL", "").startswith("postgresql+asyncpg://")
            or int(values.get("HYPERTEST_CLOUD_MODEL_REQUEST_COST_MICROUNITS", "0")) <= 0):
        raise ValueError("explicit current database, Cloud flags and positive request rate required")
    return values


def render(template: str, substitutions: dict[str, str]) -> str:
    for key, value in substitutions.items():
        template = template.replace("@" + key + "@", value)
    if PLACEHOLDER.search(template):
        raise ValueError("unresolved template field")
    return template


def prepare(args: argparse.Namespace) -> dict:
    canonical_directory(args.release)
    canonical_directory(args.output.parent)
    manifest = json.loads((args.release / "release.json").read_text())
    preparation = json.loads((args.release / "preparation.json").read_text())
    expected = digest(args.release / "release.json")
    if (not HEX64.fullmatch(args.release_sha256) or expected != args.release_sha256
            or preparation["release_manifest_sha256"] != expected
            or manifest["source_commit"] != args.release.name
            or manifest["source_archive_sha256"] != digest(args.release / "source.tar")
            or manifest["venv_archive_sha256"] != digest(args.release / "venv.tar")
            or preparation["rootfs_archive_sha256"] != digest(args.release / "rootfs.tar")):
        raise ValueError("release preparation or immutable archives differ")
    private_env(args.env)
    if (args.runtime.stat().st_uid, args.runtime.stat().st_gid,
            stat.S_IMODE(args.runtime.stat().st_mode)) != (997, 988, 0o700):
        raise ValueError("persistent runtime must already be 997:988 0700")
    values = {"ROOTFS_HOST": safe_path(args.release / "rootfs"),
        "SOURCE_HOST": safe_path(args.release / "source"),
        "VENV_HOST": safe_path(args.release / "rootfs/opt/hypertest-cloud/venv"),
        "RELEASE_MANIFEST_HOST": safe_path(args.release / "release.json"),
        "RELEASE_MANIFEST_SHA256": expected, "CLOUD_ENV_HOST": safe_path(args.env),
        "WRAPPING_KEY_HOST": safe_path(args.wrapping_key),
        "DEEPSEEK_KEY_HOST": safe_path(args.deepseek_key),
        "RUNTIME_HOST": safe_path(args.runtime), "RESOLV_CONF_HOST": safe_path(args.resolv_conf)}
    service = render((HERE / "hypertest-cloud-worker.service.in").read_text(), values)
    # A different unit gets its own %d credential path. The real admission stays
    # intact; only the long-running Worker command is replaced. No claim or DB.
    doctor = service.replace("PrivateNetwork=no", "PrivateNetwork=yes").replace(
        "ExecStart=/opt/hypertest-cloud/venv/bin/python -m hypertest.cloud\n",
        "ExecStart=/usr/bin/true\nRuntimeMaxSec=180s\n")
    codex = None
    if args.codex_oauth:
        if not HEX64.fullmatch(args.codex_manifest_sha256):
            raise ValueError("explicit trusted Codex manifest required")
        if digest(args.release / "delegates/manifest.json") != args.codex_manifest_sha256:
            raise ValueError("Codex manifest differs")
        codex = render((HERE / "hypertest-cloud-worker-codex.conf.in").read_text(), {
            "CODEX_OAUTH_HOST": safe_path(args.codex_oauth),
            "CODEX_PAYLOAD_HOST": safe_path(args.release / "delegates"),
            "CODEX_PAYLOAD_MANIFEST_SHA256": args.codex_manifest_sha256})
    elif args.codex_manifest_sha256:
        raise ValueError("Codex identity and payload opt-in must be paired")
    args.output.mkdir(mode=0o700)
    paths = {"hypertest-cloud-worker.service": service,
             "hypertest-cloud-worker-doctor.service": doctor}
    for name, content in paths.items():
        write_new(args.output / name, content.encode(), mode=0o644)
        if codex:
            dropin = args.output / (name + ".d")
            dropin.mkdir(mode=0o755)
            write_new(dropin / "codex.conf", codex.encode(), mode=0o644)
    files = {path.relative_to(args.output).as_posix(): digest(path)
        for path in args.output.rglob("*") if path.is_file()}
    record = {"profile": "hypertest-cloud-service-render/v1", "source_commit": manifest["source_commit"],
        "release_manifest_sha256": expected, "release_directory": str(args.release),
        "runtime_directory": str(args.runtime), "codex_enabled": bool(codex), "ssh_enabled": False,
        "files": files, "installed": False, "service_started": False, "database_accessed": False,
        "model_started": False, "startup_admission": "NOT_RUN", "test_result": "NOT_RUN"}
    json_new(args.output / "render.json", record)
    return record


def doctor(directory: Path) -> dict:
    canonical_directory(directory)
    record = json.loads((directory / "render.json").read_text())
    if record.get("profile") != "hypertest-cloud-service-render/v1":
        raise ValueError("unknown render profile")
    for name, expected in record["files"].items():
        path = directory / name
        if (Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink()
                or path.resolve(strict=True) != path or digest(path) != expected):
            raise ValueError("rendered unit changed")
    release = Path(record["release_directory"])
    if digest(release / "release.json") != record["release_manifest_sha256"]:
        raise ValueError("release manifest changed")
    return {"status": "PREPARED", "source_commit": record["source_commit"],
        "release_manifest_sha256": record["release_manifest_sha256"], "codex_enabled": record["codex_enabled"],
        "startup_admission": "NOT_RUN", "sdk_started": False, "database_accessed": False,
        "model_started": False, "task_claimed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "doctor"))
    parser.add_argument("--output", type=Path, required=True)
    for name in ("release", "env", "runtime", "wrapping-key", "deepseek-key", "resolv-conf", "codex-oauth"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--release-sha256", default="")
    parser.add_argument("--codex-manifest-sha256", default="")
    args = parser.parse_args()
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("authorized Linux host operator required")
        if args.action == "doctor":
            result = doctor(args.output)
        else:
            if any(getattr(args, field) is None for field in
                   ("release", "env", "runtime", "wrapping_key", "deepseek_key", "resolv_conf")):
                raise ValueError("all deployment paths must be explicit")
            result = prepare(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "REFUSED", "code": "CLOUD_SERVICE_CONFIGURATION_INVALID"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
