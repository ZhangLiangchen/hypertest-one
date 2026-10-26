#!/usr/bin/env python3
"""Verify an independently pinned Local release and configure one host.

Verify THIS script before running it. A caller-trusted manifest digest binds the
payload; SHA256SUMS from the same download is never used as origin authorization.
HTTPS downloads are fixed to the selected release. No credential issuance,
model launch or task sync occurs here.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "hypertest.local-release/v1"
HOSTS = ("codex", "claude-code", "deepseek-harness")
MAX_TOTAL = 450 * 1024 * 1024
REPOSITORY = "https://github.com/ZhangLiangchen/hypertest-one"


def target_id() -> str:
    """CPython wheels are deliberately not reused for another minor ABI."""
    machine = {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    if (platform.system() not in {"Darwin", "Linux"} or machine not in {"arm64", "x86_64"}
            or sys.implementation.name != "cpython" or sys.version_info[:2] not in {(3, 12), (3, 13)}):
        raise ValueError("A published macOS/Linux x86_64/arm64 CPython 3.12/3.13 target is required")
    return f"{platform.system().lower()}-{machine}-py3{sys.version_info.minor}"


class HTTPSReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in {
                "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("Release download redirect left the trusted HTTPS distribution channel")
        return super().redirect_request(request, response, code, message, headers, newurl)


def download_bundle(url: str, trusted_digest: str, release_tag: str, directory: Path) -> Path:
    """Download bounded bytes, then extract only flat assets after outer hash validation."""
    if (re.fullmatch(r"[a-f0-9]{64}", str(trusted_digest)) is None
            or re.fullmatch(r"local-v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", release_tag) is None):
        raise ValueError("An independently trusted target bundle SHA-256 is required")
    expected_name = f"hypertest-{release_tag}-{target_id()}.zip"
    if url != f"{REPOSITORY}/releases/download/{release_tag}/{expected_name}":
        raise ValueError("Bundle URL must name the exact selected repository, tag and local target")
    opener = urllib.request.build_opener(HTTPSReleaseRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "hypertest-local-verified-bootstrap/1"})
    with opener.open(request, timeout=45) as response:
        raw = response.read(MAX_TOTAL + 1)
    if len(raw) > MAX_TOTAL or sha256(raw) != trusted_digest:
        raise ValueError("Target bundle does not match the independently trusted digest")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if (not 6 <= len(infos) <= 162 or len({row.filename for row in infos}) != len(infos)
                or sum(row.file_size for row in infos) > MAX_TOTAL):
            raise ValueError("Invalid target bundle size or duplicate assets")
        for row in infos:
            if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", row.filename) is None
                    or row.file_size > 80 * 1024 * 1024
                    or stat.S_IFMT(row.external_attr >> 16) not in {0, stat.S_IFREG}):
                raise ValueError("Target bundle contains a non-regular or non-flat asset")
            create_private(directory / row.filename, archive.read(row))
    return directory / "local-release-manifest.json"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def wheel_identity(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
        names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1 or wheel.getinfo(names[0]).file_size > 1024 * 1024:
            raise ValueError("Invalid wheel metadata")
        metadata = BytesParser().parsebytes(wheel.read(names[0]))
    return re.sub(r"[-_.]+", "-", str(metadata["Name"])).lower(), metadata["Version"]


def read_regular(path: Path, maximum: int, *, private=False) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > maximum
                or (private and (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            raise ValueError("A bounded regular private file is required" if private else "Invalid release file")
        raw = bytearray()
        while len(raw) <= maximum:
            part = os.read(fd, min(65536, maximum + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        if len(raw) > maximum:
            raise ValueError("Release file exceeds size limit")
        return bytes(raw)
    finally:
        os.close(fd)


def verify_release(manifest_path: Path, trusted_digest: str, source_commit: str,
                   release_tag: str) -> tuple[dict, dict[str, bytes]]:
    if (re.fullmatch(r"[a-f0-9]{64}", trusted_digest) is None
            or re.fullmatch(r"[a-f0-9]{40}", source_commit) is None
            or re.fullmatch(r"local-v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", release_tag) is None):
        raise ValueError("Preselected manifest SHA-256, full source commit and fixed Local tag are required")
    raw = read_regular(manifest_path, 2 * 1024 * 1024)
    if sha256(raw) != trusted_digest:
        raise ValueError("Manifest does not match the independently trusted digest")
    manifest = json.loads(raw)
    expected_version = re.sub(r"-(alpha|beta|rc)\.(\d+)$",
        lambda m: {"alpha": "a", "beta": "b", "rc": "rc"}[m[1]] + m[2], release_tag.removeprefix("local-v"))
    if (manifest.get("schema_version") != SCHEMA or manifest.get("source_commit") != source_commit
            or manifest.get("release_tag") != release_tag
            or manifest.get("version") != expected_version
            or manifest.get("source_repository") != "https://github.com/ZhangLiangchen/hypertest-one"
            or manifest.get("distribution_state") not in {"CANDIDATE", "RELEASE"}
            or manifest.get("compatibility", {}).get("task_profile") != "codex-session-task-sync/v1alpha1"
            or manifest.get("compatibility", {}).get("snapshot") != "hypertest.sync-snapshot/v1"
            or set(manifest.get("hosts", {})) != set(HOSTS)):
        raise ValueError("Unsupported release identity or compatibility")
    assets = manifest.get("assets")
    if not isinstance(assets, dict) or not 5 <= len(assets) <= 160:
        raise ValueError("Invalid release assets")
    required = {"install-local-release.py", "dependencies.lock.json", "requirements.lock", "INSTALL.md", manifest.get("wheel")}
    if None in required or not required <= assets.keys():
        raise ValueError("Release is missing required assets")
    verified, total = {}, 0
    for name, expected in assets.items():
        if (not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", name) is None
                or name in {"local-release-manifest.json", "SHA256SUMS"}
                or not isinstance(expected, dict) or set(expected) != {"sha256", "size_bytes"}
                or type(expected["size_bytes"]) is not int or not 0 <= expected["size_bytes"] <= 80 * 1024 * 1024
                or re.fullmatch(r"[a-f0-9]{64}", str(expected["sha256"])) is None):
            raise ValueError("Invalid asset name, hash or size")
        total += expected["size_bytes"]
        if total > MAX_TOTAL:
            raise ValueError("Release payload exceeds limit")
        data = read_regular(manifest_path.parent / name, expected["size_bytes"])
        if len(data) != expected["size_bytes"] or sha256(data) != expected["sha256"]:
            raise ValueError("Release asset integrity mismatch")
        verified[name] = data
    if not isinstance(manifest["wheel"], str) or not re.fullmatch(r"hypertest_local-[A-Za-z0-9.]+-py3-none-any\.whl", manifest["wheel"]):
        raise ValueError("Invalid Local payload wheel")
    if wheel_identity(verified[manifest["wheel"]]) != ("hypertest-local", expected_version):
        raise ValueError("Payload wheel does not match Local release version")
    with zipfile.ZipFile(io.BytesIO(verified[manifest["wheel"]])) as wheel:
        name = "hypertest/local_sync/release.json"
        if name not in wheel.namelist() or wheel.getinfo(name).file_size > 4096:
            raise ValueError("Local wheel has no fixed-source provenance")
        provenance = json.loads(wheel.read(name))
    if provenance.get("source_commit") != source_commit or provenance.get("release_version") != expected_version:
        raise ValueError("Local wheel provenance differs from manifest")
    lock = json.loads(verified["dependencies.lock.json"])
    if (lock.get("schema_version") != "hypertest.local-dependency-lock/v1"
            or lock.get("wheels") != manifest.get("dependencies")):
        raise ValueError("Dependency lock differs from release manifest")
    dependency_names = set()
    for row in lock["wheels"]:
        filename = row.get("filename")
        origin = urlsplit(row.get("origin_url", ""))
        if (filename not in verified or not filename.endswith(".whl") or filename in dependency_names
                or row.get("sha256") != assets[filename]["sha256"]
                or origin.scheme != "https" or not origin.hostname or origin.username is not None
                or origin.password is not None or origin.query or origin.fragment):
            raise ValueError("Dependency lock is incomplete or has an unsafe origin")
        distribution = re.sub(r"[-_.]+", "-", str(row.get("name"))).lower()
        if wheel_identity(verified[filename]) != (distribution, row.get("version")):
            raise ValueError("Dependency wheel identity differs from lock")
        dependency_names.add(filename)
    if {name for name in verified if name.endswith(".whl")} != dependency_names | {manifest["wheel"]}:
        raise ValueError("Unexpected unlocked wheel in release")
    return manifest, verified


def private_configuration(path: Path) -> dict:
    """Validate preexisting authorization files without issuing or copying secrets."""
    body = json.loads(read_regular(path, 1024 * 1024, private=True))
    if not isinstance(body, dict):
        raise ValueError("Existing private client configuration is required")
    token = body.get("integration_token_file")
    state = body.get("state_dir")
    if (not isinstance(token, str) or not Path(token).is_absolute()
            or not isinstance(state, str) or not Path(state).is_absolute()):
        raise ValueError("Existing private authorization and state paths are required; setup is not automatic")
    if not read_regular(Path(token), 4096, private=True).strip():
        raise ValueError("Existing private authorization is missing; obtain it through the private administrator flow")
    endpoint = urlsplit(body.get("api_url", ""))
    if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username is not None
            or endpoint.password is not None or endpoint.query or endpoint.fragment):
        raise ValueError("Existing client must use a trusted HTTPS platform URL")
    if Path(state).exists():
        info = Path(state).lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Existing client state directory must remain private")
    return body


def private_directory(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Private install directories cannot be symlinks")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Install root must be user-owned and private")
    return path


def create_private(path: Path, raw: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def installation(args: argparse.Namespace) -> tuple[Path, dict | None]:
    """Read only this host's explicitly selected owned receipt, never scan secrets."""
    directory = (getattr(args, "directory", None) or args.install_root / "host-installation").expanduser().absolute()
    path = directory / f"installed-{args.harness}.json"
    if not path.exists() and not path.is_symlink():
        return directory, None
    receipt = json.loads(read_regular(path, 1024 * 1024, private=True))
    if (receipt.get("profile") != "hypertest.local-install/v1"
            or receipt.get("host") != args.harness or receipt.get("configuration") != "WRITTEN"):
        raise ValueError("An existing owned WRITTEN installation receipt is required")
    for name in ("client_config", "host_config"):
        selected = getattr(args, name, None)
        value = receipt.get(name)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("Existing installation receipt has invalid configuration paths")
        if selected is not None and selected.expanduser().absolute() != Path(value):
            raise ValueError("Existing configuration migration requires an explicit separate operation")
        setattr(args, name, Path(value))
    return directory, receipt


def install_release(args: argparse.Namespace, manifest: dict, verified: dict[str, bytes]) -> dict:
    accepted = manifest.get("hosts", {}).get(args.harness, {})
    if manifest["distribution_state"] != "RELEASE" and not args.allow_candidate:
        raise ValueError("Host support is NOT_ACCEPTED; explicit --allow-candidate is required for candidate configuration")
    if args.harness not in HOSTS or args.install_root is None:
        raise ValueError("Select one host and a private release install root")
    directory, existing = installation(args)
    if args.client_config is None or args.host_config is None:
        raise ValueError("Existing authorized private client and selected host configuration paths are required")
    if not existing and getattr(args, "enable_hooks", False) and not (getattr(args, "workspace", None) or getattr(args, "artifact_source", None)):
        raise ValueError("Automatic Hooks require an explicitly selected workspace or approved private artifact policy")
    target_id()
    if getattr(args, "enable_hooks", False) and manifest["distribution_state"] == "RELEASE":
        if (accepted.get("native_acceptance") != "ACCEPTED" or accepted.get("mcp") != "ACCEPTED"
                or accepted.get("automatic_trigger") != "ACCEPTED"):
            raise ValueError("Automatic Hooks require accepted native integration for the selected host")
        if getattr(args, "harness_version", None) not in accepted.get("versions", []):
            raise ValueError("Automatic Hooks require an exact accepted installed host version")
    actual_target = {"system": platform.system(), "machine": platform.machine(),
                     "python": f"{sys.version_info.major}.{sys.version_info.minor}"}
    if any(manifest.get("target", {}).get(field) != value for field, value in actual_target.items()):
        raise ValueError("This wheelhouse was not validated for the current OS, architecture and Python")
    body = private_configuration(args.client_config)
    if body.get("local_sync", {}).get("host") not in {None, args.harness}:
        raise ValueError("Each host requires a separate private client configuration")
    root = args.install_root.expanduser().absolute()
    state = Path(body["state_dir"]).resolve(strict=False)
    # Never locate executable installation inside the existing transmission state.
    resolved_root = root.resolve(strict=False)
    if resolved_root == state or resolved_root.is_relative_to(state) or state.is_relative_to(resolved_root):
        raise ValueError("Release install root and existing private client state must be separate")
    root = private_directory(root)
    fd = os.open(root / "bootstrap.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Private bootstrap lock is required")
        fcntl.flock(fd, fcntl.LOCK_EX)
        release = root / (manifest["release_tag"] + "-" + args.trusted_manifest_sha256[:12])
        python = release / "venv/bin/python"
        completed = release / "bootstrap-complete.json"
        if release.exists():
            marker = json.loads(read_regular(completed, 4096, private=True))
            if marker.get("manifest_sha256") != args.trusted_manifest_sha256 or not python.is_file():
                raise ValueError("Incomplete or conflicting release install is preserved; inspect it before reuse")
        else:
            release = private_directory(release)
            create_private(release / "bootstrap-intent.json", json.dumps({"manifest_sha256": args.trusted_manifest_sha256,
                           "source_commit": args.source_commit, "release_tag": args.release_tag}).encode())
            wheelhouse = private_directory(release / "verified-assets")
            for name, raw in verified.items():
                create_private(wheelhouse / name, raw)
            venv.EnvBuilder(with_pip=True).create(release / "venv")
            subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
                            "--no-cache-dir", "--disable-pip-version-check",
                            *[str(wheelhouse / name) for name in sorted(verified) if name.endswith(".whl")]], check=True)
            subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "check"], check=True)
            create_private(completed, json.dumps({"manifest_sha256": args.trusted_manifest_sha256,
                           "source_commit": args.source_commit, "release_tag": args.release_tag}).encode())
        command = [str(python), "-I", "-m", "hypertest.local_sync", "install", "--directory", str(directory),
                   "--harness", args.harness, "--host-config", str(args.host_config.expanduser().absolute()),
                   "--client-config", str(args.client_config.expanduser().absolute()), "--version", manifest["release_tag"],
                   "--python", str(python)]
        for flag, value in (("--hook-config", getattr(args, "hook_config", None)), ("--harness-version", getattr(args, "harness_version", None)),
                            ("--dsh-home", getattr(args, "dsh_home", None)), ("--profile", getattr(args, "profile", None)),
                            ("--workspace", getattr(args, "workspace", None)), ("--artifact-source", getattr(args, "artifact_source", None)),
                            ("--event-bridge", getattr(args, "event_bridge", None)), ("--harness-binary", getattr(args, "harness_binary", None))):
            if value is not None:
                command += [flag, str(value)]
        if getattr(args, "enable_hooks", False):
            command.append("--enable-hooks")
        if existing:
            # Only the recorded ownership-aware path can preserve Hooks and policy.
            command = [str(python), "-I", "-m", "hypertest.local_sync", "upgrade-owned",
                       "--directory", str(directory), "--harness", args.harness,
                       "--version", manifest["release_tag"], "--python", str(python)]
        unchanged = existing and existing.get("version") == manifest["release_tag"] and existing.get("python") == str(python)
        if not unchanged:
            subprocess.run(command, check=True, capture_output=True, text=True)
        runtime = subprocess.run([str(python), "-I", "-m", "hypertest.local_sync", "runtime-check",
            "--config", str(args.client_config), "--start"], check=True, capture_output=True, text=True)
        runtime_result = json.loads(runtime.stdout)
        if runtime_result.get("status") != "MATCH":
            raise ValueError("LOCAL_RUNTIME_VERSION_UNCONFIRMED")
        if getattr(args, "skills_directory", None):
            subprocess.run([str(python), "-I", "-m", "hypertest.local_sync", "install-skill",
                "--directory", str(directory), "--skills-directory", str(args.skills_directory.expanduser().absolute())], check=True)
        return {"release_tag": args.release_tag, "source_commit": args.source_commit,
                "payload": "VERIFIED_AND_ISOLATED", "configuration": "WRITTEN_UNACCEPTED",
                "authorization": "EXISTING_PRIVATE_CREDENTIAL_NOT_SERVER_VERIFIED",
                "release_native_acceptance": accepted.get("native_acceptance", "NOT_ACCEPTED"),
                "native_acceptance": "NOT_OBSERVED_ON_THIS_INSTALL", "real_sync": "NOT_OBSERVED", "reload_required": True,
                "operation": "ALREADY_CURRENT" if unchanged else "UPGRADED" if existing else "INSTALLED",
                "runtime": runtime_result, "private_state": "PRESERVED"}
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--bundle-url", help="Fixed GitHub Local release target bundle HTTPS URL")
    parser.add_argument("--trusted-bundle-sha256")
    parser.add_argument("--trusted-manifest-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--allow-candidate", action="store_true")
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--directory", type=Path, help="Existing owned host installation receipt directory")
    parser.add_argument("--skills-directory", type=Path, help="Explicitly selected Agent skills directory")
    parser.add_argument("--harness", choices=HOSTS)
    parser.add_argument("--host-config", type=Path)
    parser.add_argument("--client-config", type=Path)
    parser.add_argument("--hook-config", type=Path)
    parser.add_argument("--enable-hooks", action="store_true")
    parser.add_argument("--harness-version")
    parser.add_argument("--harness-binary", type=Path, help="Explicit installed host executable for bounded actual version probe")
    parser.add_argument("--dsh-home", type=Path)
    parser.add_argument("--profile")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--workspace", type=Path, help="Explicitly selected workspace artifact policy")
    policy.add_argument("--artifact-source", type=Path, help="Existing private approved artifact policy JSON")
    parser.add_argument("--event-bridge", choices=("claude-code", "codex", "native-root"))
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="hypertest-local-download-") as temporary:
            selected_manifest = args.manifest
            if args.bundle_url:
                selected_manifest = download_bundle(args.bundle_url, args.trusted_bundle_sha256,
                                                     args.release_tag, Path(temporary))
            manifest, verified = verify_release(selected_manifest, args.trusted_manifest_sha256,
                                                args.source_commit, args.release_tag)
            if args.verify_only:
                result = {"release_tag": args.release_tag, "source_commit": args.source_commit,
                          "payload": "VERIFIED", "publication": "NOT_ASSERTED", "hosts": manifest["hosts"]}
            else:
                result = install_release(args, manifest, verified)
    except subprocess.CalledProcessError as exc:
        codes = re.findall(r"\b(?:LOCAL_|INSTALL_|MANAGED_|EXISTING_|SEPARATE_|TASK_)[A-Z0-9_]{3,100}\b", exc.stderr or "")
        code = codes[-1] if codes else "LOCAL_INSTALL_BLOCKED"
        parser.exit(1, code + ": Local bootstrap stopped; preserve existing credentials, private state and pending journals.\n")
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        parser.exit(1, "Local bootstrap BLOCKED; preserve existing credentials, private state and pending journals.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
