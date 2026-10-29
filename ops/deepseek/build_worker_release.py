#!/usr/bin/env python3
"""Build/export an immutable Cloud RootDirectory from an exact clean Git commit.

Run on the authorized Linux test server after fetch/checkout, never as a local
preflight. This prepares files only: no service, DB, model or test is started.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from release_files import canonical_directory, digest, extract_image, json_new

HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
DIGEST_IMAGE = re.compile(r"[^\s@]+@sha256:[a-f0-9]{64}\Z")


def output(command: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True, timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}).strip()


def regular_directory(path: Path) -> None:
    canonical_directory(path)


def worker_context(source: Path, destination: Path) -> None:
    """Derive the exact Worker inputs without modifying the Git source tree.

    Debian's legacy Docker builder ignores Dockerfile-specific ignore files.
    A separate narrow context gives it the same reviewed Worker root ignore.
    """
    regular_directory(source)
    regular_directory(source / "src")
    for path in (source / "src").rglob("*"):
        info = path.lstat()
        if (not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
            raise ValueError("runtime source context cannot contain aliases or special files")
    selected = {"pyproject.toml": "pyproject.toml", "README.md": "README.md",
        "requirements/cloud-runtime.lock": "requirements/cloud-runtime.lock",
        "ops/deepseek/Dockerfile.worker": "Dockerfile",
        "ops/deepseek/Dockerfile.worker.dockerignore": ".dockerignore"}
    for name in ("skills/hypertest-archive/SKILL.md",
                 "skills/hypertest-archive/agents/openai.yaml",
                 "skills/hypertest-archive/references/manifest.md",
                 "skills/hypertest-local-task-onboarding/SKILL.md",
                 "skills/hypertest-local-task-onboarding/agents/openai.yaml",
                 "skills/hypertest-local-task-onboarding/references/setup.md",
                 "skills/hypertest-local-task-onboarding/references/sync-contract.md",
                 "skills/hypertest-local-task-onboarding/references/troubleshooting.md"):
        selected[name] = name
    for name in selected:
        original = source / name
        if (not original.is_file() or original.resolve(strict=True) != original
                or original.stat().st_nlink != 1):
            raise ValueError("runtime context input must be a canonical Git file")
    destination.mkdir(mode=0o755)
    os.chmod(destination, 0o755)
    for name, target_name in selected.items():
        target = destination / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    shutil.copytree(source / "src", destination / "src", symlinks=False)


def build(args: argparse.Namespace) -> dict:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("release preparation requires the authorized Linux host operator")
    regular_directory(args.checkout)
    regular_directory(args.output.parent)
    if any(path.stat().st_uid != 0 or path.stat().st_mode & 0o022
           for path in (args.output.parent, *args.output.parent.parents)):
        raise ValueError("persistent release parent and ancestors must be root-owned and non-writable to others")
    if (not HEX40.fullmatch(args.commit) or not DIGEST_IMAGE.fullmatch(args.python_image)
            or args.output.name != args.commit or args.output.exists() or args.output.is_symlink()):
        raise ValueError("require exact commit, digest-qualified base and a new release named by commit")
    if output(["git", "rev-parse", "HEAD"], cwd=args.checkout) != args.commit:
        raise ValueError("checkout differs from the pushed target commit")
    if output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=args.checkout):
        raise ValueError("preserve the dirty checkout and use a clean Git release")
    if (not re.fullmatch(r"origin/[A-Za-z0-9_./-]+", args.remote_ref)
            or ".." in args.remote_ref
            or output(["git", "rev-parse", "refs/remotes/" + args.remote_ref], cwd=args.checkout) != args.commit):
        raise ValueError("exact fetched origin ref must equal the pushed commit")
    identity = pwd.getpwnam("hypertest-cloud")
    if (identity.pw_uid, identity.pw_gid) != (997, 988):
        raise ValueError("the dedicated host account must be exactly 997:988")
    if bool(args.codex_payload) != bool(args.codex_manifest_sha256):
        raise ValueError("optional official payload requires its separately trusted manifest digest")
    if args.codex_payload:
        regular_directory(args.codex_payload)
        if (not HEX64.fullmatch(args.codex_manifest_sha256)
                or digest(args.codex_payload / "manifest.json") != args.codex_manifest_sha256):
            raise ValueError("official payload manifest differs from the trusted deployment digest")
    args.output.mkdir(mode=0o700)
    # Keep a failed preparation and its originals for diagnosis; never delete an
    # existing release/state directory or retry a model / platform operation.
    archive = args.output / "source.tar"
    with archive.open("xb") as stream:
        subprocess.run(["git", "archive", "--format=tar", args.commit], cwd=args.checkout,
                       stdout=stream, check=True, timeout=60)
    context = args.output / "source"
    context.mkdir(mode=0o755)
    os.chmod(context, 0o755)
    extract_image(archive, context)
    # Git source remains verbatim. Docker receives only the derived Worker
    # closure, with its root ignore effective under both legacy and BuildKit.
    build_context = args.output / "build-context"
    worker_context(context, build_context)
    iid_file = args.output / "image.id"
    subprocess.run(["docker", "build", "--pull=false", "--iidfile", str(iid_file),
        "--build-arg", "PYTHON_IMAGE=" + args.python_image,
        "--build-arg", "SOURCE_COMMIT=" + args.commit,
        "--build-arg", "CLOUD_UID=" + str(identity.pw_uid),
        "--build-arg", "CLOUD_GID=" + str(identity.pw_gid),
        "-f", str(build_context / "Dockerfile"), str(build_context)], check=True, timeout=1800)
    image = iid_file.read_text().strip()
    if not image.startswith("sha256:") or not HEX64.fullmatch(image[7:]):
        raise ValueError("builder did not return an immutable local image ID")
    container = output(["docker", "create", "--network", "none", image])
    if not HEX64.fullmatch(container):
        raise ValueError("unexpected disposable export-container identity")
    rootfs_archive = args.output / "rootfs.tar"
    try:
        with rootfs_archive.open("xb") as stream:
            subprocess.run(["docker", "export", container], stdout=stream, check=True, timeout=180)
    finally:
        # This exact, never-started build container only; no service containers.
        subprocess.run(["docker", "rm", container], check=True, stdout=subprocess.DEVNULL, timeout=30)
    rootfs = args.output / "rootfs"
    rootfs.mkdir(mode=0o755)
    os.chmod(rootfs, 0o755)
    extract_image(rootfs_archive, rootfs)
    # Complete Git source is outside the image build's narrow runtime COPY and
    # is the exact read-only PYTHONPATH tree bound by the service template.
    venv = rootfs / "opt/hypertest-cloud/venv"
    regular_directory(venv)
    venv_archive = args.output / "venv.tar"
    subprocess.run(["tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0",
                    "-cf", str(venv_archive), "-C", str(venv), "."], check=True, timeout=180)
    if args.codex_payload:
        if any(path.is_symlink() or path.stat().st_mode & 0o022 for path in args.codex_payload.rglob("*")):
            raise ValueError("delegate closure must contain only immutable directories/files")
        shutil.copytree(args.codex_payload, args.output / "delegates", symlinks=False)
        if digest(args.output / "delegates/manifest.json") != args.codex_manifest_sha256:
            raise ValueError("copied payload manifest changed")
        # Full file closure is verified by the unchanged service admission, not
        # claimed from the manifest alone by this preparation command.
    manifest = {"profile": "hypertest-cloud-worker-release/v1", "source_commit": args.commit,
        "source_archive_sha256": digest(archive), "rootfs_image_sha256": image[7:],
        "venv_archive_sha256": digest(venv_archive), "sdk_version": "0.2.1rc2",
        "runtime_version": "0.2.1rc2"}
    manifest_path = args.output / "release.json"
    json_new(manifest_path, manifest, mode=0o644)
    record = {"profile": "hypertest-cloud-release-preparation/v1", "source_commit": args.commit,
        "python_base": args.python_image, "image": image, "release_directory": str(args.output),
        "release_manifest_sha256": digest(manifest_path), "rootfs_archive_sha256": digest(rootfs_archive),
        "service_uid": identity.pw_uid, "service_gid": identity.pw_gid,
        "fetched_remote_ref": args.remote_ref,
        "codex_manifest_sha256": args.codex_manifest_sha256 or None,
        "service_started": False, "database_accessed": False, "model_started": False,
        "test_result": "NOT_RUN"}
    json_new(args.output / "preparation.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--remote-ref", required=True, help="exact fetched origin/branch equal to commit")
    parser.add_argument("--python-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex-payload", type=Path)
    parser.add_argument("--codex-manifest-sha256", default="")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args), indent=2))
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        print("Cloud release preparation failed; preserve the output for diagnosis.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
