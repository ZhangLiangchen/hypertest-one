#!/usr/bin/env python3
"""Install or update Local through the GitHub HTTPS release channel.

The caller pins THIS updater's source and SHA-256. Release discovery and catalog
hashes trust GitHub's HTTPS channel, not independent signatures. Downloaded code
is executed only after exact repository/tag/catalog digest checks. No platform
credential is created, copied or printed; --check never changes local files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

REPOSITORY = "https://github.com/ZhangLiangchen/hypertest-one"
RELEASES_API = "https://api.github.com/repos/ZhangLiangchen/hypertest-one/releases?per_page=100"
PROTOCOL = "hypertest.local-update/v1"
HOSTS = ("codex", "claude-code", "deepseek-harness")
TAG = re.compile(r"local-v(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")
DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


class UpdateBlocked(ValueError):
    pass


def version_key(value: str) -> tuple[int, int, int, int, int]:
    match = TAG.fullmatch(value)
    if match is None:
        raise UpdateBlocked("UNKNOWN_INSTALLED_VERSION: choose an explicit newer candidate; automatic downgrade is blocked")
    major, minor, patch, stage, number = match.groups()
    return int(major), int(minor), int(patch), {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage], int(number or 0)


class ChannelRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in DOWNLOAD_HOSTS
                or parsed.username is not None or parsed.password is not None or parsed.fragment):
            raise UpdateBlocked("UNTRUSTED_REDIRECT: release redirect left the GitHub HTTPS channel")
        return super().redirect_request(request, response, code, message, headers, newurl)


def fetch(url: str, maximum: int) -> bytes:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in DOWNLOAD_HOSTS | {"api.github.com"}
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise UpdateBlocked("UNTRUSTED_URL: exact GitHub HTTPS distribution URLs are required")
    opener = urllib.request.build_opener(ChannelRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "hypertest-local-updater/1",
                                                 "Accept": "application/vnd.github+json" if parsed.hostname == "api.github.com" else "application/octet-stream"})
    with opener.open(request, timeout=45) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise UpdateBlocked("DOWNLOAD_TOO_LARGE: release metadata or bootstrap exceeds its bound")
    return raw


def latest_release(channel: str) -> dict:
    rows = json.loads(fetch(RELEASES_API, 4 * 1024 * 1024))
    if not isinstance(rows, list):
        raise UpdateBlocked("INVALID_RELEASE_INDEX: GitHub must return a bounded release list")
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or row.get("draft") or not isinstance(row.get("tag_name"), str):
            continue
        tag = row["tag_name"]
        if TAG.fullmatch(tag) is None:
            continue
        if channel == "stable" and (row.get("prerelease") or TAG.fullmatch(tag)[4]):
            continue
        candidates.append(row)
    if not candidates:
        raise UpdateBlocked("NO_LOCAL_RELEASE: no published Local release exists in the selected channel")
    return max(candidates, key=lambda row: version_key(row["tag_name"]))


def release_catalog(release: dict) -> dict:
    tag = release["tag_name"]
    expected = f"{REPOSITORY}/releases/download/{tag}/local-install-catalog.json"
    assets = release.get("assets", [])
    if not any(isinstance(row, dict) and row.get("name") == "local-install-catalog.json"
               and row.get("browser_download_url") == expected for row in assets):
        raise UpdateBlocked("RELEASE_CATALOG_MISSING: this release has no unified installation catalog; select --channel candidate")
    catalog = json.loads(fetch(expected, 2 * 1024 * 1024))
    if not isinstance(catalog, dict):
        raise UpdateBlocked("INVALID_RELEASE_CATALOG: JSON object required")
    rows = catalog.get("targets")
    if (catalog.get("schema_version") != "hypertest.local-install-catalog/v1"
            or not isinstance(rows, list) or not 1 <= len(rows) <= 32):
        raise UpdateBlocked("INVALID_RELEASE_CATALOG: bounded Local target catalog required")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("release_tag") != tag
                or re.fullmatch(r"[a-f0-9]{40}", str(row.get("source_commit"))) is None
                or re.fullmatch(r"(?:darwin|linux)-(?:arm64|x86_64)-py3(?:12|13)", str(row.get("target_id"))) is None
                or row.get("target_id") in seen or row.get("python") not in {"3.12", "3.13"}
                or row.get("distribution_state") not in {"CANDIDATE", "RELEASE"}
                or ("-" + row["target_id"].split("-")[-1]) != "-py" + row["python"].replace(".", "")
                or row.get("bundle_url") != f"{REPOSITORY}/releases/download/{tag}/hypertest-{tag}-{row.get('target_id')}.zip"
                or any(re.fullmatch(r"[a-f0-9]{64}", str(row.get(field))) is None
                       for field in ("bootstrap_sha256", "manifest_sha256", "bundle_sha256"))):
            raise UpdateBlocked("INVALID_RELEASE_CATALOG: target identity, digest or URL mismatch")
        seen.add(row["target_id"])
    if len({(row["source_commit"], row["bootstrap_sha256"]) for row in rows}) != 1:
        raise UpdateBlocked("INVALID_RELEASE_CATALOG: targets must share one fixed source and bootstrap")
    return catalog


def private_receipt(directory: Path, host: str) -> dict | None:
    path = directory / f"installed-{host}.json"
    if not path.exists() and not path.is_symlink():
        return None
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or info.st_size > 1024 * 1024):
            raise UpdateBlocked("PRIVATE_RECEIPT_REQUIRED: existing installation receipt must remain user-owned and private")
        raw = os.read(fd, 1024 * 1024 + 1)
    finally:
        os.close(fd)
    receipt = json.loads(raw)
    if (not isinstance(receipt, dict) or receipt.get("profile") != "hypertest.local-install/v1"
            or receipt.get("host") != host or receipt.get("configuration") != "WRITTEN"):
        raise UpdateBlocked("OWNED_INSTALLATION_REQUIRED: select the existing written host receipt with --directory")
    for field in ("client_config", "host_config", "python"):
        if not isinstance(receipt.get(field), str) or not Path(receipt[field]).is_absolute():
            raise UpdateBlocked("INVALID_INSTALLATION_RECEIPT: absolute owned configuration/runtime paths required")
    return receipt


def installed_comparison(receipt: dict | None, selected_tag: str, *, replace_source: bool = False,
                         channel: str = "stable", check: bool = False) -> str:
    if receipt is None:
        return "NOT_INSTALLED"
    existing = str(receipt.get("version"))
    # Source snapshots cannot be ordered against a published artifact. Replacing
    # a recognized full-commit source install is an explicit candidate action.
    if re.fullmatch(r"local-v\d+\.\d+\.\d+-source\.[a-f0-9]{40}", existing):
        if replace_source and channel == "candidate":
            return "SOURCE_REPLACEMENT"
        if check:
            return "SOURCE_REPLACEMENT_REQUIRED"
        raise UpdateBlocked("SOURCE_REPLACEMENT_REQUIRED: recognized source installation is not semver-comparable; explicitly use --channel candidate --replace-source to replace its runtime while retaining private state")
    if replace_source:
        raise UpdateBlocked("SOURCE_REPLACEMENT_NOT_APPLICABLE: --replace-source only accepts a recognized full-commit source installation on the candidate channel")
    selected, current = version_key(selected_tag), version_key(existing)
    return "UPDATE_AVAILABLE" if selected > current else "CURRENT" if selected == current else "INSTALLED_NEWER"


def local_platform() -> tuple[str, str]:
    system = platform.system().lower()
    machine = {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    if system not in {"darwin", "linux"} or machine not in {"arm64", "x86_64"}:
        raise UpdateBlocked("UNSUPPORTED_PLATFORM: published macOS/Linux x86_64/arm64 targets are required")
    return system, machine


def select_target(catalog: dict, receipt: dict | None) -> tuple[dict, str]:
    system, machine = local_platform()
    targets = {row["python"]: row for row in catalog["targets"]
               if row["target_id"].startswith(f"{system}-{machine}-")}
    if not targets:
        raise UpdateBlocked("NO_PUBLISHED_TARGET: selected release has no exact OS/architecture target; no files were changed")
    choices = ([receipt["python"]] if receipt else []) + [sys.executable]
    choices += [path for name in ("python3.13", "python3.12") if (path := shutil.which(name))]
    observed = set()
    probe = "import json,platform,sys;print(json.dumps([sys.implementation.name, '%s.%s'%sys.version_info[:2], platform.system().lower(), platform.machine()]))"
    for executable in choices:
        if executable in observed:
            continue
        observed.add(executable)
        try:
            result = subprocess.run([executable, "-I", "-c", probe], check=True, capture_output=True, text=True, timeout=10)
            identity = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if (isinstance(identity, list) and len(identity) == 4 and identity[0] == "cpython"
                and identity[1] in targets and identity[2] == system
                and {"aarch64": "arm64", "AMD64": "x86_64"}.get(identity[3], identity[3]) == machine):
            return targets[identity[1]], executable
    versions = ", ".join(sorted(targets))
    raise UpdateBlocked(f"PYTHON_REQUIRED: install CPython {versions} for this exact published target, then repeat the same command; no files were changed")


def bootstrap_command(args: argparse.Namespace, record: dict, executable: str, script: Path,
                      root: Path, directory: Path, receipt: dict | None) -> list[str]:
    command = [executable, "-I", str(script), "--bundle-url", record["bundle_url"],
        "--trusted-bundle-sha256", record["bundle_sha256"], "--trusted-manifest-sha256", record["manifest_sha256"],
        "--source-commit", record["source_commit"], "--release-tag", record["release_tag"],
        "--install-root", str(root), "--directory", str(directory), "--harness", args.harness]
    if record["distribution_state"] == "CANDIDATE":
        if args.channel != "candidate":
            raise UpdateBlocked("CANDIDATE_OPT_IN_REQUIRED: use --channel candidate explicitly")
        command.append("--allow-candidate")
    if not receipt:
        client = args.client_config or root / "client.json"
        if not client.is_file():
            raise UpdateBlocked("AUTHORIZED_CLIENT_CONFIG_REQUIRED: supply --client-config /absolute/private/authorized-client.json from your existing Project task:sync setup; no credential was issued")
        defaults = {"codex": Path.home() / ".codex/config.toml", "claude-code": Path.home() / ".claude.json"}
        host_config = args.host_config or defaults.get(args.harness)
        if host_config is None:
            raise UpdateBlocked("HOST_CONFIG_REQUIRED: select your existing DeepSeek host configuration with --host-config")
        command += ["--client-config", str(client.expanduser().absolute()), "--host-config", str(host_config.expanduser().absolute())]
    else:
        for field in ("client_config", "host_config"):
            path = getattr(args, field)
            if path is not None and path.expanduser().absolute() != Path(receipt[field]):
                raise UpdateBlocked("CONFIGURATION_MIGRATION_BLOCKED: existing owned paths are preserved; do not select a second client/host configuration")
    for flag in ("skills_directory", "hook_config", "harness_version", "harness_binary", "dsh_home", "profile",
                 "workspace", "artifact_source", "event_bridge"):
        value = getattr(args, flag, None)
        if value is not None:
            command += ["--" + flag.replace("_", "-"), str(value.expanduser().absolute()) if isinstance(value, Path) else str(value)]
    if args.enable_hooks:
        command.append("--enable-hooks")
    return command


def update(args: argparse.Namespace) -> dict:
    root = (args.install_root or Path.home() / ".local/share/hypertest-local" / args.harness).expanduser().absolute()
    directory = (args.directory or root / "host-installation").expanduser().absolute()
    receipt = private_receipt(directory, args.harness)
    release = latest_release(args.channel)
    catalog = release_catalog(release)
    comparison = installed_comparison(receipt, release["tag_name"], replace_source=args.replace_source,
                                     channel=args.channel, check=args.check)
    supported = catalog.get("updater_protocol") == PROTOCOL
    result = {"schema_version": PROTOCOL, "channel": args.channel, "release_tag": release["tag_name"],
        "source_commit": catalog["targets"][0]["source_commit"],
        "available_targets": [row["target_id"] for row in catalog["targets"]], "installed_version": receipt.get("version") if receipt else None,
        "status": comparison, "unified_update_supported": supported,
        "metadata_trust": "GITHUB_HTTPS_RELEASE_CHANNEL", "native_acceptance": "NOT_OBSERVED_ON_THIS_INSTALL"}
    if args.check:
        try:
            record, _ = select_target(catalog, receipt)
            result.update({"target_id": record["target_id"], "distribution_state": record["distribution_state"]})
        except UpdateBlocked as exc:
            result["prerequisite"] = str(exc)
        if comparison == "SOURCE_REPLACEMENT_REQUIRED":
            result["action"] = "Explicit --channel candidate --replace-source is required to replace the recognized source runtime; private state will be preserved"
        if not supported:
            result["action"] = "NEW_UPDATER_RELEASE_REQUIRED: select --channel candidate; historical stable remains available through its fixed install commands"
        if comparison == "INSTALLED_NEWER":
            result["action"] = "DOWNGRADE_BLOCKED: choose a newer channel; use the explicit rollback operation separately"
        return result
    if comparison == "INSTALLED_NEWER":
        raise UpdateBlocked("DOWNGRADE_BLOCKED: selected channel is older than your installation; choose --channel candidate or use the separate explicit rollback command")
    if not supported:
        raise UpdateBlocked("NEW_UPDATER_RELEASE_REQUIRED: historical stable cannot preserve upgrade semantics through this entry; select --channel candidate explicitly")
    record, executable = select_target(catalog, receipt)
    result.update({"target_id": record["target_id"], "distribution_state": record["distribution_state"]})
    # Preflight required paths before downloading executable bytes or creating directories.
    bootstrap_url = f"{REPOSITORY}/releases/download/{record['release_tag']}/install-local-release.py"
    script_name = Path("<verified-bootstrap>")
    bootstrap_command(args, record, executable, script_name, root, directory, receipt)
    raw = fetch(bootstrap_url, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != record["bootstrap_sha256"]:
        raise UpdateBlocked("BOOTSTRAP_DIGEST_MISMATCH: release catalog did not match the downloaded executable")
    with tempfile.TemporaryDirectory(prefix="hypertest-local-update-") as temporary:
        script = Path(temporary) / "install-local-release.py"
        script.write_bytes(raw)
        completed = subprocess.run(bootstrap_command(args, record, executable, script, root, directory, receipt),
                                   check=True, capture_output=True, text=True)
    # pip and host installer output can precede the bootstrap's final JSON.
    decoder = json.JSONDecoder()
    installed = None
    for index, character in enumerate(completed.stdout):
        if character == "{":
            try:
                body, end = decoder.raw_decode(completed.stdout, index)
                if not completed.stdout[end:].strip() and isinstance(body, dict):
                    installed = body
                    break
            except ValueError:
                pass
    if installed is None:
        raise UpdateBlocked("INSTALL_RESULT_UNCONFIRMED: inspect the preserved owned receipt; do not replay pending task operations")
    return {**result, "status": "SOURCE_REPLACEMENT" if comparison == "SOURCE_REPLACEMENT" else installed.get("operation", "INSTALLED"), "installation": installed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", choices=HOSTS, default="codex")
    parser.add_argument("--channel", choices=("stable", "candidate"), default="stable")
    parser.add_argument("--replace-source", action="store_true", help="Explicitly replace a recognized full-commit source runtime; candidate channel only")
    parser.add_argument("--check", action="store_true", help="Read release metadata and selected receipt without changing local files")
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--directory", type=Path, help="Existing owned host receipt directory, including legacy installations")
    parser.add_argument("--client-config", type=Path)
    parser.add_argument("--host-config", type=Path)
    parser.add_argument("--skills-directory", type=Path)
    parser.add_argument("--hook-config", type=Path)
    parser.add_argument("--enable-hooks", action="store_true")
    parser.add_argument("--harness-version")
    parser.add_argument("--harness-binary", type=Path)
    parser.add_argument("--dsh-home", type=Path)
    parser.add_argument("--profile")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--workspace", type=Path)
    policy.add_argument("--artifact-source", type=Path)
    parser.add_argument("--event-bridge", choices=("claude-code", "codex", "native-root"))
    args = parser.parse_args()
    try:
        result = update(args)
    except UpdateBlocked as exc:
        parser.exit(1, str(exc) + "\n")
    except subprocess.CalledProcessError as exc:
        codes = re.findall(r"\b(?:LOCAL_|INSTALL_|MANAGED_|EXISTING_|SEPARATE_|TASK_|AUTHORIZED_)[A-Z0-9_]{3,100}\b", exc.stderr or "")
        code = codes[-1] if codes else "LOCAL_UPDATE_BLOCKED"
        parser.exit(1, code + ": verified installer stopped; inspect the selected owned installation; private credentials, state and pending journals are preserved.\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, urllib.error.URLError):
        parser.exit(1, "LOCAL_UPDATE_BLOCKED: release discovery, verification or installation failed; private credentials, state and pending journals are preserved.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
