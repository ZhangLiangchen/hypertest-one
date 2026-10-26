#!/usr/bin/env python3
"""Build an offline, fixed-source HyperTest Local candidate; never publish it.

Supply an already downloaded wheelhouse and an audited JSON dependency lock.
The builder does not resolve or download dependencies, install model CLIs, or
reuse the platform wheel. Run build/validation only in the authorized build host.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "hypertest.local-release/v1"
LOCK_SCHEMA = "hypertest.local-dependency-lock/v1"
REPOSITORY = "https://github.com/ZhangLiangchen/hypertest-one"
DIRECT_DEPENDENCIES = {"pydantic", "httpx", "jsonschema", "mcp"}
HOSTS = ("codex", "claude-code", "deepseek-harness")
SKILL_NAME = "hypertest-local-task-onboarding"
SKILL_FILES = (
    "SKILL.md", "agents/openai.yaml", "references/setup.md",
    "references/sync-contract.md", "references/troubleshooting.md",
)
SKILL_SOURCE_ROOT = f"skills/{SKILL_NAME}"
SKILL_WHEEL_ROOT = f"hypertest/local_sync/assets/skills/{SKILL_NAME}"
SOURCE_BOUND_FILES = (
    "pyproject.toml", "scripts/install-local-release.py", "scripts/build-local-release.py",
    "scripts/prepare-local-dependencies.py", "scripts/local-release-commands.py",
    "scripts/plan-local-release.py", "scripts/freeze-local-release-source.py",
    "scripts/local-release-dependencies.json", ".github/workflows/local-release.yml",
    "src/hypertest/api/task_schemas.py",
    *(f"{SKILL_SOURCE_ROOT}/{name}" for name in SKILL_FILES),
)
REQUIRED = {
    "hypertest/interactive_client/__main__.py", "hypertest/interactive_client/mcp_server.py",
    "hypertest/interactive_client/service.py", "hypertest/interactive_client/journal.py",
    "hypertest/local_sync/__main__.py", "hypertest/local_sync/coordinator.py",
    "hypertest/local_sync/adapter.py", "hypertest/local_sync/manifest.py",
    "hypertest/local_sync/hosts.py", "hypertest/local_sync/hooks.py",
    "hypertest/local_sync/deepseek_root_bridge.mjs",
    "hypertest/local_sync/installer.py", "hypertest/sync_core/core.py",
    "hypertest/sync_core/storage.py", "hypertest/api/task_schemas.py",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_source_requirements(project: dict, lock: dict) -> list[str]:
    versions = {normalize(row["name"]): row["version"] for row in lock["wheels"]}
    requirements = project["dependencies"] + project["optional-dependencies"]["interactive"]
    found = set()
    for requirement in requirements:
        match = re.fullmatch(r"([A-Za-z0-9_-]+)>=(\d+(?:\.\d+)*),<(\d+(?:\.\d+)*)", requirement)
        if match is None or normalize(match[1]) not in DIRECT_DEPENDENCIES:
            continue
        name = normalize(match[1])
        if re.fullmatch(r"\d+(?:\.\d+)*", versions[name]) is None:
            raise ValueError("Local dependency pins must be stable numeric versions")
        def parsed(value):
            return tuple(map(int, value.split("."))) + (0,) * (8 - len(value.split(".")))
        if not parsed(match[2]) <= parsed(versions[name]) < parsed(match[3]):
            raise ValueError("Locked dependency is outside the fixed source compatibility range")
        found.add(name)
    if found != DIRECT_DEPENDENCIES:
        raise ValueError("Source dependency constraints changed; review the Local package closure")
    return [name + "==" + versions[name] for name in sorted(found)]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   stderr=subprocess.PIPE).strip()


def release_identity(root: Path, tag: str, ref: str | None, require_tag: bool) -> tuple[str, str, str]:
    match = re.fullmatch(r"local-v(\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?)", tag)
    if match is None:
        raise ValueError("Expected local-vMAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N]")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Local releases require a clean checkout including untracked files")
    if ref is not None and re.fullmatch(r"[a-f0-9]{40}", ref) is None:
        raise ValueError("--ref must be a full fixed commit, never a branch or latest")
    commit = git(root, "rev-parse", "--verify", f"{ref or ('refs/tags/' + tag)}^{{commit}}")
    if re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise ValueError("A full source commit is required")
    try:
        tagged = git(root, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    except subprocess.CalledProcessError:
        tagged = None
    if tagged is not None and tagged != commit:
        raise ValueError("Local tag points at another source commit")
    if require_tag and tagged != commit:
        raise ValueError("An existing tag at the exact source commit is required")
    # Local distribution version is independent of the backend's pyproject version.
    version = re.sub(r"-(alpha|beta|rc)\.(\d+)$", lambda m: {"alpha": "a", "beta": "b", "rc": "rc"}[m[1]] + m[2], match[1])
    return commit, version, "VERIFIED" if tagged == commit else "PLANNED"


def wheel_metadata(raw: bytes) -> tuple[str, str]:
    with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
        names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("Expected exactly one wheel METADATA")
        metadata = BytesParser().parsebytes(wheel.read(names[0]))
    if not metadata["Name"] or not metadata["Version"]:
        raise ValueError("Wheel identity is missing")
    return normalize(metadata["Name"]), metadata["Version"]


def locked_dependencies(lock_path: Path, wheelhouse: Path) -> tuple[dict, dict[str, bytes]]:
    lock = json.loads(lock_path.read_bytes())
    if set(lock) != {"schema_version", "wheels"} or lock["schema_version"] != LOCK_SCHEMA:
        raise ValueError("Unsupported dependency lock")
    if not isinstance(lock["wheels"], list) or not 1 <= len(lock["wheels"]) <= 150:
        raise ValueError("An exact transitive dependency wheel lock is required")
    assets, distributions = {}, set()
    for row in lock["wheels"]:
        if set(row) != {"filename", "name", "version", "sha256", "origin_url"}:
            raise ValueError("Dependency lock rows require filename/name/version/sha256/origin_url")
        name = row["filename"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*\.whl", name):
            raise ValueError("Dependency wheels must be flat named wheel files")
        origin = urlsplit(row["origin_url"])
        if (origin.scheme != "https" or not origin.hostname or origin.username is not None
                or origin.password is not None or origin.query or origin.fragment):
            raise ValueError("Dependency origins must be non-secret fixed HTTPS URLs")
        path = wheelhouse / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 80 * 1024 * 1024:
            raise ValueError("Dependency wheel is missing, symlinked or too large")
        raw = path.read_bytes()
        identity = wheel_metadata(raw)
        if (sha256(raw) != row["sha256"] or identity != (normalize(row["name"]), row["version"])
                or identity[0] in distributions or name in assets
                or identity[0] in {"hypertest-local", "hypertest-one"}
                or identity[0].startswith("deepseek-harness")):
            raise ValueError("Dependency hash/identity conflict or excluded Cloud dependency")
        distributions.add(identity[0])
        assets[name] = raw
    if not DIRECT_DEPENDENCIES <= distributions:
        raise ValueError("Missing Local direct dependencies")
    if sum(map(len, assets.values())) > 400 * 1024 * 1024:
        raise ValueError("Dependency payload exceeds release limit")
    return lock, assets


def validate_catalog_lock(catalog_path: Path, lock: dict) -> None:
    """Bind ALL actual direct/transitive wheels to the fixed source's reviewed catalog.

    A self-consistent caller lock is insufficient. Target ABI compatibility is
    additionally enforced by the offline install/check before output is written.
    """
    catalog = json.loads(catalog_path.read_bytes())
    if (catalog.get("schema_version") != "hypertest.local-dependency-catalog/v1"
            or catalog.get("python") != ["3.12", "3.13"]
            or catalog.get("index_url") != "https://pypi.org/simple"
            or not isinstance(catalog.get("distributions"), list)):
        raise ValueError("Fixed-source dependency catalog is invalid")
    expected = {}
    for row in catalog["distributions"]:
        name = normalize(row["name"])
        if name in expected or not row.get("wheels"):
            raise ValueError("Fixed-source dependency catalog has duplicate or empty distributions")
        expected[name] = row
    observed = {}
    for row in lock["wheels"]:
        name = normalize(row["name"])
        if name in observed:
            raise ValueError("Actual dependency lock has duplicate distributions")
        observed[name] = row
    if set(observed) != set(expected):
        raise ValueError("Actual dependency closure differs from the fixed-source catalog")
    for name, row in observed.items():
        fixed = expected[name]
        wheel = {key: row[key] for key in ("filename", "sha256", "origin_url")}
        if row["version"] != fixed["version"] or wheel not in fixed["wheels"]:
            raise ValueError("Actual dependency version/wheel/hash/origin differs from the fixed-source catalog")


def onboarding_skill(source: Path) -> dict[str, bytes]:
    """Read only the reviewed skill files from the canonical repository source."""
    files = {}
    for name in SKILL_FILES:
        path = source / SKILL_SOURCE_ROOT / name
        for component in (path, *path.parents):
            if component.is_symlink():
                raise ValueError("Onboarding skill source must not contain symlinks")
            if component == source:
                break
        if not path.is_file():
            raise ValueError("Source is missing required onboarding skill files")
        files[f"{SKILL_WHEEL_ROOT}/{name}"] = path.read_bytes()
    return files


def make_local_wheel(source: Path, version: str, commit: str, dependencies: list[str], epoch: int) -> tuple[str, bytes]:
    files = {}
    for directory in ("interactive_client", "sync_core", "local_sync"):
        for path in (source / "src/hypertest" / directory).rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".mjs", ".cjs", ".js"}:
                continue
            if path.is_symlink():
                raise ValueError("Source package symlinks are not supported")
            files[str(path.relative_to(source / "src"))] = path.read_bytes()
    schema = source / "src/hypertest/api/task_schemas.py"
    if schema.is_symlink():
        raise ValueError("Source schema symlink is not supported")
    files["hypertest/api/task_schemas.py"] = schema.read_bytes()
    files["hypertest/api/__init__.py"] = b'"""Local wire schemas only; no platform service."""\n'
    files["hypertest/__init__.py"] = f'"""Isolated HyperTest Local distribution."""\n__version__ = {version!r}\n'.encode()
    for name in ("session-sync.config.example.json", "mcp.example.json"):
        path = source / "src/hypertest/interactive_client/assets" / name
        if path.is_symlink():
            raise ValueError("Source asset symlink is not supported")
        files["hypertest/interactive_client/assets/" + name] = path.read_bytes()
    files.update(onboarding_skill(source))
    if not REQUIRED <= files.keys():
        raise ValueError("Source is missing required Local components")
    files["hypertest/local_sync/release.json"] = encoded({"release_version": version, "source_commit": commit,
        "core_contract": "1", "native_acceptance": "NOT_ACCEPTED"})
    dist = f"hypertest_local-{version}.dist-info"
    metadata = (f"Metadata-Version: 2.3\nName: hypertest-local\nVersion: {version}\n"
                "Summary: HyperTest Local synchronization client\nRequires-Python: >=3.12\n"
                + "".join(f"Requires-Dist: {value}\n" for value in sorted(dependencies)) + "\n")
    files[f"{dist}/METADATA"] = metadata.encode()
    files[f"{dist}/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: hypertest-local-fixed-source\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    files[f"{dist}/entry_points.txt"] = b"[console_scripts]\nhypertest-local = hypertest.local_sync.__main__:main\nhypertest-interactive = hypertest.interactive_client.__main__:main\n"
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, raw in sorted(files.items()):
        writer.writerow((name, "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("="), len(raw)))
    writer.writerow((f"{dist}/RECORD", "", ""))
    files[f"{dist}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    import time
    timestamp = time.gmtime(max(epoch, 315532800))[:6]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            wheel.writestr(info, raw)
    return f"hypertest_local-{version}-py3-none-any.whl", output.getvalue()


def local_source_digest(source: Path) -> str:
    """Bind native acceptance to distributed source bytes without a self-referential commit."""
    onboarding_skill(source)  # Required assets and their parent directories cannot be symlinks.
    paths = [source / name for name in SOURCE_BOUND_FILES]
    for directory in ("interactive_client", "sync_core", "local_sync"):
        paths.extend(path for path in (source / "src/hypertest" / directory).rglob("*")
                     if path.is_file() and (path.suffix in {".py", ".mjs", ".cjs", ".js"} or path.name in {
                         "session-sync.config.example.json", "mcp.example.json"}))
    rows = {}
    for path in paths:
        if path.is_symlink():
            raise ValueError("Acceptance source must not contain symlinks")
        rows[str(path.relative_to(source))] = sha256(path.read_bytes())
    return sha256(encoded(rows))


def accepted_hosts(path: Path | None, source_digest: str, tag: str, target: dict) -> tuple[dict, bytes | None]:
    hosts = {host: {"native_acceptance": "NOT_ACCEPTED", "mcp": "NOT_ACCEPTED",
                    "automatic_trigger": "NOT_ACCEPTED"} for host in HOSTS}
    if path is None:
        return hosts, None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("Acceptance evidence must be a bounded regular file")
    raw = path.read_bytes()
    evidence = json.loads(raw)
    if (evidence.get("schema_version") != "hypertest.local-host-acceptance/v1"
            or evidence.get("local_source_sha256") != source_digest
            or evidence.get("release_tag") != tag or evidence.get("target") != target
            or set(evidence.get("hosts", {})) != set(HOSTS)):
        raise ValueError("Acceptance evidence differs from the exact Local source, tag or target")
    for host, row in evidence["hosts"].items():
        if (not isinstance(row, dict) or not isinstance(row.get("versions"), list) or not row["versions"]
                or not all(isinstance(version, str) and 1 <= len(version) <= 100 for version in row["versions"])
                or not isinstance(row.get("evidence_refs"), list) or not row["evidence_refs"]
                or not all(isinstance(ref, str) and 1 <= len(ref) <= 500 for ref in row["evidence_refs"])):
            raise ValueError("Acceptance requires actual host versions and non-secret evidence refs")
        for field in ("native_acceptance", "mcp", "automatic_trigger"):
            if row.get(field) not in {"ACCEPTED", "NOT_ACCEPTED", "BLOCKED"}:
                raise ValueError("Invalid native host acceptance state")
        if row["native_acceptance"] == "ACCEPTED" and (
                row["mcp"] != "ACCEPTED" or row["automatic_trigger"] != "ACCEPTED"
                or row.get("sync_proof") != "ACK_AND_FIXED_VERSION_FULL_READBACK"):
            raise ValueError("Native acceptance requires MCP, actual automatic trigger and fixed-version sync proof")
        hosts[host] = row
    return hosts, raw


def bundle_release(output: Path, tag: str, epoch: int) -> Path:
    machine = {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    target = f"{platform.system().lower()}-{machine}-py3{sys.version_info.minor}"
    archive = output.parent / f"hypertest-{tag}-{target}.zip"
    import time
    timestamp = time.gmtime(max(epoch, 315532800))[:6]
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.iterdir()):
            if not path.is_file() or path.is_symlink():
                raise ValueError("Target bundle only supports flat regular assets")
            info = zipfile.ZipInfo(path.name, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes())
    return archive


def check_environment(assets: dict[str, bytes], directory: Path) -> None:
    wheels = directory / "wheelhouse"
    wheels.mkdir()
    for name, raw in assets.items():
        (wheels / name).write_bytes(raw)
    environment = directory / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python"
    subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
                    "--no-cache-dir", "--disable-pip-version-check", *map(str, sorted(wheels.glob("*.whl")))], check=True)
    subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "check"], check=True)
    subprocess.run([str(python), "-I", "-c", "import hypertest.local_sync.coordinator; import hypertest.local_sync.installer; import hypertest.interactive_client.mcp_server"], check=True)
    # Exercise the real installed wheel's resource loader and public CLI offline.
    subprocess.run([str(python), "-I", "-m", "hypertest.local_sync", "install-skill",
                    "--directory", str(directory / "skill-receipts"),
                    "--skills-directory", str(directory / "agent-skills")], check=True)


def instructions(manifest: dict) -> bytes:
    return f"""# HyperTest Local {manifest['release_tag']} ({manifest['distribution_state']})

Source commit: `{manifest['source_commit']}`. This build does not assert publication.
Read the target-specific hosts matrix in local-release-manifest.json.
Configuration is not native sync acceptance on this machine.
The Local distribution version is independent of the backend package version.

First obtain the bootstrap SHA-256 and manifest SHA-256 through an independently
trusted channel for this exact tag and commit. Verify install-local-release.py
BEFORE executing it. SHA256SUMS downloaded alongside this bundle proves only
internal integrity, not origin. No public download URL is asserted by this build.

The bootstrap is standard-library Python 3.12/3.13 and accepts an offline asset directory:

    python3.12 -I install-local-release.py --manifest local-release-manifest.json \\
      --trusted-manifest-sha256 TRUSTED_MANIFEST_SHA256 \\
      --source-commit {manifest['source_commit']} --release-tag {manifest['release_tag']} --verify-only

Installation additionally requires --install-root, one --harness, --host-config,
and --client-config pointing to an existing private authorized configuration.
For an unaccepted CANDIDATE add --allow-candidate. Optional --hook-config,
--enable-hooks, --harness-version, --dsh-home and --profile are forwarded explicitly.
Hooks default off. No command fetches a moving branch, obtains an Operator key,
issues a grant, installs a model CLI, starts a model/test, or uploads history.

Each target host needs its own private client config / selected manifest. Existing
identity, external state directory and pending journal are retained. The bootstrap
uses an isolated versioned venv and never runs legacy Operator-key setup.
Run the packaged read-only doctor after reloading the actual host, then independently
verify real parent-session ACK and complete fixed-version readback. No READY claim
is made here. Uninstall/rollback/recover-install operate only package-owned host
fragments; do not remove private state or retry unknown platform writes.

dependencies.lock.json records exact original wheel URLs, versions and SHA-256.
requirements.lock pins this candidate and every included wheel. Installation is
offline with --no-index --no-deps followed by pip check; missing/incompatible
dependencies block installation, without changing host configuration.
""".encode()


def build(args: argparse.Namespace) -> dict:
    if (sys.implementation.name != "cpython" or sys.version_info[:2] not in {(3, 12), (3, 13)}
            or platform.system() not in {"Darwin", "Linux"}
            or platform.machine() not in {"x86_64", "arm64", "aarch64"}):
        raise ValueError("Build with target CPython 3.12/3.13 on macOS/Linux x86_64/arm64")
    root = args.root.expanduser().absolute()
    commit, version, tag_state = release_identity(root, args.tag, args.ref, args.require_tag)
    output = args.output.expanduser().absolute()
    if output.exists() and (output.is_symlink() or not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output must be absent or an empty real directory")
    lock, assets = locked_dependencies(args.dependency_lock, args.wheelhouse)
    epoch = int(git(root, "show", "-s", "--format=%ct", commit))
    with tempfile.TemporaryDirectory(prefix="hypertest-local-release-") as temporary:
        temporary = Path(temporary)
        archive = temporary / "source.tar"
        subprocess.run(["git", "-C", str(root), "archive", "--format=tar", commit, "--output", str(archive)], check=True)
        source = temporary / "source"
        source.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(source, filter="data")
        project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
        if project["name"] != "hypertest-one":
            raise ValueError("Unexpected source project")
        validate_catalog_lock(source / "scripts/local-release-dependencies.json", lock)
        dependencies = validate_source_requirements(project, lock)
        source_digest = local_source_digest(source)
        bridge_digest = sha256((source / "src/hypertest/local_sync/deepseek_root_bridge.mjs").read_bytes())
        skill_assets = {name.removeprefix(SKILL_WHEEL_ROOT + "/"): {
            "sha256": sha256(raw), "size_bytes": len(raw)}
            for name, raw in onboarding_skill(source).items()}
        target = {"system": platform.system(), "machine": platform.machine(),
                  "python": f"{sys.version_info.major}.{sys.version_info.minor}"}
        acceptance_path = source / args.acceptance_file if args.acceptance_file else None
        if acceptance_path is not None and (Path(args.acceptance_file).is_absolute()
                or ".." in Path(args.acceptance_file).parts):
            raise ValueError("Acceptance file must be a fixed-source relative file")
        hosts, acceptance = accepted_hosts(acceptance_path, source_digest, args.tag, target)
        state = "RELEASE" if args.release else "CANDIDATE"
        if args.release and (tag_state != "VERIFIED" or any(
                row["native_acceptance"] != "ACCEPTED" for row in hosts.values())):
            raise ValueError("Formal release requires the fixed tag and accepted native MCP/hooks for every host")
        if acceptance is not None:
            assets["host-acceptance.json"] = acceptance
        wheel_name, wheel_bytes = make_local_wheel(source, version, commit, dependencies, epoch)
        assets[wheel_name] = wheel_bytes
        validation = temporary / "validation"
        validation.mkdir()
        check_environment(assets, validation)
        bootstrap = source / "scripts/install-local-release.py"
        if bootstrap.is_symlink():
            raise ValueError("Bootstrap must be a regular fixed-source file")
        assets["install-local-release.py"] = bootstrap.read_bytes()
    assets["dependencies.lock.json"] = encoded(lock)
    locked = [("hypertest-local", version, wheel_name)] + [(normalize(row["name"]), row["version"], row["filename"]) for row in lock["wheels"]]
    assets["requirements.lock"] = "".join(f"{name}=={item_version} --hash=sha256:{sha256(assets[filename])}\n"
                                           for name, item_version, filename in sorted(locked)).encode()
    manifest = {"schema_version": SCHEMA, "release_tag": args.tag, "version": version,
        "source_commit": commit, "source_repository": REPOSITORY, "source_project_version": project["version"],
        "local_source_sha256": source_digest,
        "tag_verification": tag_state, "distribution_state": state, "publication": "NOT_ASSERTED",
        "requires_python": ">=3.12", "target": target, "wheel": wheel_name,
        "source_assets": {"deepseek-root-bridge": {"path": "hypertest/local_sync/deepseek_root_bridge.mjs",
            "sha256": bridge_digest}, "local-task-onboarding": {"path": SKILL_WHEEL_ROOT,
            "files": skill_assets}},
        "components": {name: {"version": version, "source_commit": commit} for name in
                       ("mcp", "private-client", "task-sync-core", "coordinator", "host-adapters", "installer", "templates", "onboarding-skill")},
        "compatibility": {"mcp_profile": "hypertest.interactive-mcp/v1alpha1",
            "task_profile": "codex-session-task-sync/v1alpha1", "journal": "existing-intents/v1+local-delivery/v1",
            "snapshot": "hypertest.sync-snapshot/v1", "core_contract": "1",
            "upgrade_policy": "PRESERVE_IDENTITY_AND_PENDING_NO_REPLAY", "downgrade": "REQUIRES_COMPATIBILITY_REVIEW"},
        "hosts": hosts,
        "dependencies": lock["wheels"], "assets": {name: {"size_bytes": len(raw), "sha256": sha256(raw)}
                                                     for name, raw in sorted(assets.items())}}
    assets["INSTALL.md"] = instructions(manifest)
    manifest["assets"]["INSTALL.md"] = {"size_bytes": len(assets["INSTALL.md"]), "sha256": sha256(assets["INSTALL.md"])}
    assets["local-release-manifest.json"] = encoded(manifest)
    assets["SHA256SUMS"] = "".join(f"{sha256(raw)}  {name}\n" for name, raw in sorted(assets.items())).encode()
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in assets.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
    bundle_release(output, args.tag, epoch)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--ref", help="Full 40-character commit; optional for an existing fixed tag")
    parser.add_argument("--require-tag", action="store_true")
    parser.add_argument("--release", action="store_true", help="Require committed acceptance for all three native host integrations")
    parser.add_argument("--acceptance-file", help="Project-relative committed target-specific host acceptance evidence")
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--dependency-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Local release rejected: {exc}\n")
    print(json.dumps({"release_tag": manifest["release_tag"], "source_commit": manifest["source_commit"],
                      "manifest_sha256": sha256((args.output / "local-release-manifest.json").read_bytes()),
                      "publication": "NOT_ASSERTED", "distribution_state": manifest["distribution_state"],
                      "hosts": manifest["hosts"]}))


if __name__ == "__main__":
    main()
