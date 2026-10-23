"""Read-only startup admission for the dedicated Cloud service template.

This module never imports persistence, starts an SDK, contacts a provider, or
claims work. The unit runs it before its separate long-lived Worker entrypoint.
Release archive digests are operator-attested deployment records, not a claim
that this process rehashed an entire rootfs or authenticated a model account.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

from hypertest.config import Settings

from .crypto import CredentialCipher
from .delegate_broker import read_cloud_codex_identity
from .delegation import verify_payload
from .errors import CloudBlocked
from .private_file import read_private_file
from .resources import inspect_resource_envelope
from .sandbox import require_readonly_shell

SDK_VERSION = "0.2.1rc2"
SOURCE_ROOT = Path("/opt/hypertest-cloud/source")
VENV_ROOT = Path("/opt/hypertest-cloud/venv")
RUNTIME_ROOT = Path("/var/lib/hypertest-cloud/runtime")
RELEASE_MANIFEST = Path("/opt/hypertest-cloud/release.json")
CREDENTIALS_ROOT = Path("/run/credentials")
PAYLOAD_ROOT = Path("/opt/hypertest-cloud/delegates")
_HEX = re.compile(r"[a-f0-9]{64}")
_RELEASE_FIELDS = frozenset({"profile", "source_commit", "source_archive_sha256",
    "rootfs_image_sha256", "venv_archive_sha256", "sdk_version", "runtime_version"})
_SAFE_CODES = frozenset({"CLOUD_WORKER_DISABLED", "WORKER_ADMISSION_FAILED",
    "WORKER_OUTER_PROFILE_UNSAFE", "WORKER_RELEASE_INVALID", "WORKER_RELEASE_MISMATCH",
    "WORKER_RELEASE_PATH_UNSAFE", "WORKER_PYTHON_MISMATCH", "WORKER_RUNTIME_ROOT_UNSAFE",
    "WORKER_CREDENTIAL_PATH_MISMATCH", "WORKER_MODEL_CONFIGURATION_INVALID",
    "WORKER_MODEL_KEY_INVALID", "WORKER_CODEX_CONFIGURATION_INVALID",
    "SSH_CLIENT_UNTRUSTED", "SSH_LOCAL_IDENTITY_UNAVAILABLE", "SSH_SIGNING_KEY_INVALID", "SSH_CRYPTO_UNAVAILABLE",
    "WORKER_SSH_CONFIGURATION_INVALID",
    "SDK_UNAVAILABLE", "SDK_VERSION_MISMATCH", "CREDENTIAL_KEY_INVALID",
    "CREDENTIAL_KEY_PERMISSIONS", "CREDENTIAL_KEY_UNAVAILABLE", "CRYPTO_UNAVAILABLE",
    "PRIVATE_FILE_UNSAFE", "PRIVATE_FILE_UNAVAILABLE", "PRIVATE_FILE_SIZE", "PRIVATE_FILE_CHANGED",
    "CODEX_OAUTH_UNAVAILABLE", "CODEX_OAUTH_EXPIRED", "DELEGATE_PAYLOAD_UNTRUSTED",
    "DELEGATE_PAYLOAD_INVALID", "SHELL_UNAVAILABLE", "CGROUP_V2_REQUIRED",
    "CGROUP_SCOPE_UNVERIFIED", "CGROUP_RESOURCE_LIMIT_UNAVAILABLE",
    "CGROUP_RESOURCE_LIMIT_UNBOUNDED", "CGROUP_RESOURCE_LIMIT_EXCEEDED"})


def _blocked(code):
    raise CloudBlocked(code, "Dedicated Cloud service startup admission refused")


def _canonical_directory(path: Path, *, readonly: bool, private: bool = False) -> None:
    try:
        info = os.stat(path, follow_symlinks=False)
        if path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode):
            raise ValueError
        if private:
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError
        elif info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError
        flags = os.statvfs(path).f_flag
        if bool(flags & os.ST_RDONLY) != readonly:
            raise ValueError
        if private and not os.access(path, os.W_OK | os.X_OK):
            raise ValueError
    except (OSError, ValueError):
        _blocked("WORKER_RUNTIME_ROOT_UNSAFE" if private else "WORKER_RELEASE_PATH_UNSAFE")


def _outer_profile() -> dict:
    try:
        if (sys.platform != "linux" or os.getuid() == 0 or os.getuid() != os.geteuid()
                or os.getgid() != os.getegid()):
            raise ValueError
        with Path("/proc/self/status").open() as stream:
            status = stream.read(65537)
        fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        if (len(status) > 65536 or fields.get("NoNewPrivs", "").strip() != "1"
                or any(int(fields[name].strip(), 16) for name in
                       ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))):
            raise ValueError
        if not all(os.statvfs(path).f_flag & os.ST_RDONLY for path in ("/", "/sys/fs/cgroup")):
            raise ValueError
        temporary = Path("/tmp").stat()
        mode = stat.S_IMODE(temporary.st_mode)
        if (not stat.S_ISDIR(temporary.st_mode)
                or not ((temporary.st_uid == 0 and mode == 0o1777)
                        or (temporary.st_uid == os.geteuid() and mode == 0o700))
                or not os.access("/tmp", os.W_OK | os.X_OK)):
            raise ValueError
        flags = os.statvfs("/tmp").f_flag
        if (flags & (os.ST_RDONLY | os.ST_NOEXEC)
                or flags & (os.ST_NOSUID | os.ST_NODEV) != os.ST_NOSUID | os.ST_NODEV):
            raise ValueError
        for tool in ("git", "bwrap"):
            selected = shutil.which(tool)
            if selected is None:
                raise ValueError
            info = Path(selected).stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o6022
                    or not os.statvfs(selected).f_flag & os.ST_RDONLY):
                raise ValueError
        require_readonly_shell()
    except (OSError, ValueError, KeyError):
        _blocked("WORKER_OUTER_PROFILE_UNSAFE")
    envelope = inspect_resource_envelope(max_memory_bytes=2 * 1024**3, max_processes=256)
    if envelope["swap_max_bytes"] != 0:
        _blocked("WORKER_OUTER_PROFILE_UNSAFE")
    return {"nonroot": True, "capabilities_empty": True, "no_new_privileges": True,
            "root_readonly": True, "private_exec_tmp": True, "resource_envelope": envelope}


def _release(expected_sha256: str) -> dict:
    if not isinstance(expected_sha256, str) or not _HEX.fullmatch(expected_sha256):
        _blocked("WORKER_RELEASE_INVALID")
    _canonical_directory(SOURCE_ROOT, readonly=True)
    _canonical_directory(VENV_ROOT, readonly=True)
    if sys.version_info[:2] != (3, 12) or Path(sys.prefix) != VENV_ROOT:
        _blocked("WORKER_PYTHON_MISMATCH")
    try:
        if RELEASE_MANIFEST.resolve(strict=True) != RELEASE_MANIFEST:
            raise ValueError
        descriptor = os.open(RELEASE_MANIFEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_mode & 0o022
                    or before.st_nlink != 1 or not 0 < before.st_size <= 16384
                    or not os.fstatvfs(stream.fileno()).f_flag & os.ST_RDONLY):
                raise ValueError
            raw = stream.read(16385)
            after = os.fstat(stream.fileno())
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError
        if len(raw) > 16384 or hashlib.sha256(raw).hexdigest() != expected_sha256:
            _blocked("WORKER_RELEASE_MISMATCH")
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict) or manifest.keys() != _RELEASE_FIELDS
                or manifest["profile"] != "hypertest-cloud-worker-release/v1"
                or not isinstance(manifest["source_commit"], str)
                or not re.fullmatch(r"[a-f0-9]{40}", manifest["source_commit"])
                or any(not isinstance(manifest[name], str) or not _HEX.fullmatch(manifest[name])
                       for name in ("source_archive_sha256", "rootfs_image_sha256", "venv_archive_sha256"))
                or manifest["sdk_version"] != SDK_VERSION or manifest["runtime_version"] != SDK_VERSION):
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError):
        _blocked("WORKER_RELEASE_INVALID")
    try:
        versions = {name: importlib.metadata.version(name)
                    for name in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin")}
    except importlib.metadata.PackageNotFoundError:
        _blocked("SDK_UNAVAILABLE")
    if any(value != SDK_VERSION for value in versions.values()):
        _blocked("SDK_VERSION_MISMATCH")
    return {"manifest_sha256": expected_sha256, "source_commit": manifest["source_commit"],
            "source_archive_sha256": manifest["source_archive_sha256"],
            "rootfs_image_sha256": manifest["rootfs_image_sha256"],
            "venv_archive_sha256": manifest["venv_archive_sha256"],
            "sdk_version": SDK_VERSION, "runtime_version": SDK_VERSION,
            "archive_digest_verification": "OPERATOR_DEPLOYMENT_RECORD"}


def _credential_paths(settings: Settings) -> None:
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    path = Path(directory)
    if (not path.is_absolute() or path.parent != CREDENTIALS_ROOT
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,246}\.service", path.name)
            or str(path) != directory):
        _blocked("WORKER_CREDENTIAL_PATH_MISMATCH")
    expected = {"cloud_credential_key_file": "wrapping-key", "cloud_model_key_file": "deepseek-key"}
    if settings.cloud_codex_enabled:
        expected["cloud_codex_oauth_file"] = "codex-oauth"
    if getattr(settings, "cloud_ssh_enabled", False):
        expected["cloud_ssh_authority_key_file"] = "ssh-authority"
    if any(str(getattr(settings, name)) != str(path / leaf) for name, leaf in expected.items()):
        _blocked("WORKER_CREDENTIAL_PATH_MISMATCH")


def inspect_ssh_local_identity() -> dict:
    """Resolve the current SSH client's NSS identity without exposing account data."""
    try:
        import pwd

        uid, gid = os.geteuid(), os.getegid()
        record = pwd.getpwuid(uid)
        if (type(record.pw_uid) is not int or record.pw_uid != uid
                or type(record.pw_gid) is not int or record.pw_gid != gid):
            raise ValueError
    except (ImportError, OSError, KeyError, ValueError, TypeError, AttributeError):
        raise CloudBlocked("SSH_LOCAL_IDENTITY_UNAVAILABLE",
                           "Dedicated Cloud service startup admission refused") from None
    return {"resolved": True, "primary_gid_matches": True}


def inspect_ssh_client(settings: Settings) -> dict:
    """Hash the same readonly executable descriptor; never use host PATH."""
    selected = Path(getattr(settings, "cloud_ssh_executable", ""))
    expected = getattr(settings, "cloud_ssh_executable_sha256", "")
    try:
        if (not selected.is_absolute() or selected.resolve(strict=True) != selected
                or not isinstance(expected, str) or _HEX.fullmatch(expected) is None):
            raise ValueError
        descriptor = os.open(selected, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o6022
                    or info.st_nlink != 1 or not 0 < info.st_size <= 16 * 1024**2
                    or not info.st_mode & 0o111 or not os.access(selected, os.X_OK)
                    or not os.fstatvfs(stream.fileno()).f_flag & os.ST_RDONLY):
                raise ValueError
            observed = hashlib.sha256()
            while chunk := stream.read(65536):
                observed.update(chunk)
            after = os.fstat(stream.fileno())
            if ((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or observed.hexdigest() != expected):
                raise ValueError
    except (OSError, ValueError):
        _blocked("SSH_CLIENT_UNTRUSTED")
    return {"client_sha256": expected, "readonly": True}


def read_ssh_authority(settings: Settings) -> bytes:
    """Independent host identity; no model/wrapping-key or inherited login reuse."""
    from .ssh_tickets import load_signing_key

    path = getattr(settings, "cloud_ssh_authority_key_file", "")
    if not path or path in {settings.cloud_credential_key_file, settings.cloud_model_key_file,
                            getattr(settings, "cloud_codex_oauth_file", "")}:
        _blocked("WORKER_SSH_CONFIGURATION_INVALID")
    key = read_private_file(path, max_bytes=65536)
    load_signing_key(key)
    return key


def admit_credentials(settings: Settings) -> dict:
    """Recheck before each next claim; no release/payload hashing or network I/O."""
    if not settings.cloud_enabled or not settings.cloud_worker_enabled:
        _blocked("CLOUD_WORKER_DISABLED")
    ssh_enabled = getattr(settings, "cloud_ssh_enabled", False)
    ssh_identity = inspect_ssh_local_identity() if ssh_enabled else None
    _credential_paths(settings)
    CredentialCipher.from_key_file(settings.cloud_credential_key_file)
    model_key = read_private_file(settings.cloud_model_key_file, max_bytes=65536).strip()
    if not model_key or b"\r" in model_key or b"\n" in model_key:
        _blocked("WORKER_MODEL_KEY_INVALID")
    del model_key
    credentials = {"wrapping_key_readable": True, "deepseek_key_readable": True}
    if settings.cloud_codex_enabled:
        read_cloud_codex_identity(settings.cloud_codex_oauth_file,
                                 required_seconds=settings.cloud_attempt_timeout_seconds + 60)
        credentials["codex_oauth_readable"] = True
    if ssh_enabled:
        key = read_ssh_authority(settings)
        del key
        credentials["ssh_authority_readable"] = True
        credentials["ssh_local_identity"] = ssh_identity
    return credentials


def inspect_admission(settings: Settings, *, release_sha256: str) -> dict:
    """Full startup check before importing persistence; never claims work."""
    if not settings.cloud_enabled or not settings.cloud_worker_enabled:
        _blocked("CLOUD_WORKER_DISABLED")
    configured = getattr(settings, "cloud_service_release_sha256", "")
    if configured != release_sha256:
        _blocked("WORKER_RELEASE_MISMATCH")
    outer = _outer_profile()
    release = _release(release_sha256)
    if Path(settings.cloud_runtime_root) != RUNTIME_ROOT:
        _blocked("WORKER_RUNTIME_ROOT_UNSAFE")
    _canonical_directory(RUNTIME_ROOT, readonly=False, private=True)
    if (settings.cloud_model != "deepseek-flash"
            or settings.cloud_model_base_url != "https://api.deepseek.com/anthropic"
            or settings.cloud_model_request_cost_microunits <= 0):
        _blocked("WORKER_MODEL_CONFIGURATION_INVALID")
    native = {"enabled": False}
    if settings.cloud_codex_enabled:
        if settings.cloud_codex_model != "gpt-5.6-sol" or Path(settings.cloud_codex_payload) != PAYLOAD_ROOT:
            _blocked("WORKER_CODEX_CONFIGURATION_INVALID")
        _canonical_directory(PAYLOAD_ROOT, readonly=True)
        verify_payload(PAYLOAD_ROOT, settings.cloud_codex_payload_sha256)
        native = {"enabled": True, "model": "gpt-5.6-sol",
                  "payload_manifest_sha256": settings.cloud_codex_payload_sha256}
    credentials = admit_credentials(settings)
    ssh = {"enabled": False}
    if getattr(settings, "cloud_ssh_enabled", False):
        ssh = {"enabled": True, **inspect_ssh_client(settings)}
    return {"status": "ADMITTED", "scope": "SERVICE_STARTUP_ONLY", "outer_profile": outer,
            "release": release, "credentials": credentials, "codex": native, "ssh": ssh,
            "database_contacted": False, "work_claimed": False, "sdk_started": False,
            "model_request_sent": False, "provider_authentication": "UNOBSERVED"}


def blocked_observation(error: Exception, *, scope: str) -> dict:
    code = error.code if isinstance(error, CloudBlocked) and error.code in _SAFE_CODES else "WORKER_ADMISSION_FAILED"
    return {"status": "BLOCKED", "code": code,
            "scope": scope if scope in {"SERVICE_STARTUP_ONLY", "BEFORE_NEXT_CLAIM"} else "OTHER",
            "check_database_contacted": False, "check_work_claimed": False,
            "check_sdk_started": False, "check_model_request_sent": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_admission(Settings(), release_sha256=args.release_sha256)
    except Exception as error:
        result = blocked_observation(error, scope="SERVICE_STARTUP_ONLY")
        print(json.dumps(result), flush=True)
        return 78 if result["code"] == "CLOUD_WORKER_DISABLED" else 1
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
