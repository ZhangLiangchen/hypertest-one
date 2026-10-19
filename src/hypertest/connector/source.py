"""Narrow source adapter and independent Git-object verifier for ADR-015.

The wire is deliberately uncompressed: no archive extraction or repository code runs.
Credentials are used only by Git in an isolated acquisition directory.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from hypertest.harness_bridge.protocol import BridgeError

FORMAT = "hypertest.source-bundle/v1alpha1"
MAX_BUNDLE_BYTES = 48 * 1024 * 1024
MAX_OBJECT_BYTES = 24 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_OBJECTS = 50000
MAX_FILES = 25000


class SourceBundleError(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def validate_origin(value: str, *, allow_local: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        raise SourceBundleError("source origin must be a credential-free repository reference")
    if allow_local and (value.startswith("/") or value.startswith("file://")):
        return value
    if re.fullmatch(r"(?:git@)?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?:[A-Za-z0-9_./-]+", value):
        return value
    try:
        p = urlsplit(value)
        if (p.scheme not in {"https", "ssh"} or not p.hostname or p.password is not None
                or p.query or p.fragment or p.username not in {None, "git"}
                or (p.scheme == "https" and p.username is not None)
                or not p.path or p.path == "/"):
            raise ValueError
        try:
            ipaddress.ip_address(p.hostname)
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", p.hostname):
                raise ValueError("invalid repository hostname") from None
        _ = p.port  # Validate syntax and bounds without allowing SSH option hosts.
    except ValueError as exc:
        raise SourceBundleError("source origin must not contain credentials or arbitrary protocols") from exc
    return value


def _git(path: Path, *args: str, data: bytes | None = None, credentials: bool = True, deadline: float | None = None) -> bytes:
    # Preserve credential helper / SSH_AUTH_SOCK; never copy them into the bundle.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "2",
           "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
           "GIT_CONFIG_KEY_1": "protocol.ext.allow", "GIT_CONFIG_VALUE_1": "never"}
    if not credentials:
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_ATTR_NOSYSTEM": "1"})
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_REPLACE_REF_BASE",
                "GIT_SHALLOW_FILE", "GIT_CONFIG_PARAMETERS"):
        env.pop(key, None)
    remaining = min(120.0, deadline - time.monotonic()) if deadline else 120.0
    if remaining <= 0:
        raise SourceBundleError("source acquisition authorization expired")
    try:
        process = subprocess.Popen(["git", "-C", str(path), *args], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        try:
            output, _ = process.communicate(input=data, timeout=remaining)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceBundleError("controlled Git operation unavailable or deadline exceeded") from exc
    if process.returncode:
        raise SourceBundleError("controlled Git operation failed")
    if len(output) > MAX_EXPANDED_BYTES:
        raise SourceBundleError("Git response exceeds source bounds")
    return output


def _oid(kind: str, content: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, f"{kind} {len(content)}\0".encode() + content).hexdigest()


def _path(path: str) -> None:
    if (not path or len(path.encode()) > 4096 or path.startswith("/") or "\\" in path
            or ":" in path or any(ord(c) < 32 or unicodedata.category(c) == "Cf" for c in path)
            or any(p in {"", ".", ".."} or p.rstrip(" .").casefold() == ".git" for p in path.split("/"))):
        raise SourceBundleError("unsafe source path")


def _secret(path: str, content: bytes) -> None:
    name = posixpath.basename(path).lower()
    if (name in {"id_rsa", "id_ed25519", "id_dsa", ".git-credentials", ".netrc", ".npmrc"}
            or name == ".env" or (name.startswith(".env.") and name.rsplit(".", 1)[-1] not in {"example", "sample", "template"})
            or re.search(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s*$", content)
            or re.search(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|glpat-[A-Za-z0-9_-]{20,})", content)):
        raise SourceBundleError("fixed tree contains prohibited credentials; choose a new clean commit")
    if content.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise SourceBundleError("Git LFS objects require a separately supported source contract")


@dataclass(frozen=True)
class VerifiedSource:
    manifest: dict
    objects: dict[str, tuple[str, bytes]]
    files: dict[str, tuple[str, str]]
    bundle_sha256: str
    bundle_size: int


def verify_bundle(content: bytes, *, origin: str | None = None, commit_sha: str | None = None) -> VerifiedSource:
    if not content or len(content) > MAX_BUNDLE_BYTES:
        raise SourceBundleError("source bundle size exceeds limits")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SourceBundleError("duplicate bundle fields")
            result[key] = value
        return result
    try:
        wire = json.loads(content, object_pairs_hook=unique)
        if not isinstance(wire, dict) or set(wire) != {"format", "manifest", "objects"} or wire["format"] != FORMAT:
            raise SourceBundleError("unsupported source bundle format")
        manifest = wire["manifest"]
        if set(manifest) != {"origin", "commit_sha", "root_tree", "object_format", "files"}:
            raise SourceBundleError("invalid source manifest")
        algo = manifest["object_format"]
        if algo not in {"sha1", "sha256"}:
            raise SourceBundleError("unsupported Git object format")
        width = 40 if algo == "sha1" else 64
        def check_oid(value):
            if not isinstance(value, str) or not re.fullmatch(rf"[a-f0-9]{{{width}}}", value):
                raise SourceBundleError("invalid complete Git object identity")
        check_oid(manifest["commit_sha"])
        check_oid(manifest["root_tree"])
        if origin is not None and manifest["origin"] != origin:
            raise SourceBundleError("source bundle origin mismatch")
        if commit_sha is not None and manifest["commit_sha"] != commit_sha:
            raise SourceBundleError("source bundle commit mismatch")
        raw_objects = wire["objects"]
        if not isinstance(raw_objects, list) or not 1 <= len(raw_objects) <= MAX_OBJECTS:
            raise SourceBundleError("source object count exceeds limits")
        objects = {}
        expanded = 0
        for item in raw_objects:
            if not isinstance(item, dict) or set(item) != {"oid", "type", "data"}:
                raise SourceBundleError("invalid source object")
            check_oid(item["oid"])
            if item["type"] not in {"commit", "tree", "blob"} or item["oid"] in objects:
                raise SourceBundleError("unsupported or duplicate source object")
            if not isinstance(item["data"], str) or len(item["data"]) > (MAX_OBJECT_BYTES * 4 // 3 + 4):
                raise SourceBundleError("source object exceeds size bounds")
            raw = base64.b64decode(item["data"], validate=True)
            expanded += len(raw)
            if len(raw) > MAX_OBJECT_BYTES or expanded > MAX_EXPANDED_BYTES:
                raise SourceBundleError("source expanded bytes exceed limits")
            if _oid(item["type"], raw, algo) != item["oid"]:
                raise SourceBundleError("Git object hash mismatch")
            objects[item["oid"]] = (item["type"], raw)
        commit = objects.get(manifest["commit_sha"])
        if commit is None or commit[0] != "commit":
            raise SourceBundleError("target commit object missing")
        _secret("SOURCE_COMMIT", commit[1])
        first = commit[1].split(b"\n", 1)[0]
        if first != ("tree " + manifest["root_tree"]).encode():
            raise SourceBundleError("commit root tree mismatch")
        reachable = {manifest["commit_sha"]}
        files = {}
        tree_visits = 0
        def walk(oid: str, prefix: str, depth: int):
            nonlocal tree_visits
            tree_visits += 1
            if tree_visits > MAX_OBJECTS:
                raise SourceBundleError("expanded tree count exceeds source bounds")
            if depth > 100:
                raise SourceBundleError("source tree nesting exceeds limits")
            obj = objects.get(oid)
            if obj is None or obj[0] != "tree":
                raise SourceBundleError("source tree object missing")
            reachable.add(oid)
            data, offset, names = obj[1], 0, set()
            while offset < len(data):
                sep, nul = data.find(b" ", offset), data.find(b"\0", offset)
                if sep < offset or nul < sep or nul + 1 + width // 2 > len(data):
                    raise SourceBundleError("malformed Git tree")
                mode = data[offset:sep].decode("ascii")
                name = data[sep + 1:nul].decode("utf-8", "strict")
                if "/" in name or unicodedata.normalize("NFC", name).casefold() in names:
                    raise SourceBundleError("duplicate or unsafe Git tree name")
                names.add(unicodedata.normalize("NFC", name).casefold())
                path = prefix + name
                _path(path)
                child = data[nul + 1:nul + 1 + width // 2].hex()
                offset = nul + 1 + width // 2
                if mode == "40000":
                    walk(child, path + "/", depth + 1)
                    continue
                if mode not in {"100644", "100755", "120000"}:
                    raise SourceBundleError("submodule or unsupported file mode")
                blob = objects.get(child)
                if blob is None or blob[0] != "blob":
                    raise SourceBundleError("source blob missing")
                reachable.add(child)
                _secret(path, blob[1])
                if mode == "120000":
                    raise SourceBundleError("symbolic links are unsupported by the current trusted Runner")
                files[path] = (mode, child)
                if len(files) > MAX_FILES:
                    raise SourceBundleError("source file count exceeds limits")
        walk(manifest["root_tree"], "", 0)
        if reachable != objects.keys():
            raise SourceBundleError("bundle contains unrelated objects or parent history")
        expected = [{"path": path, "mode": mode, "oid": oid,
                     "sha256": hashlib.sha256(objects[oid][1]).hexdigest()}
                    for path, (mode, oid) in sorted(files.items())]
        if manifest["files"] != expected:
            raise SourceBundleError("manifest does not match complete fixed Git tree")
        return VerifiedSource(manifest, objects, files, hashlib.sha256(content).hexdigest(), len(content))
    except SourceBundleError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SourceBundleError("invalid bounded Git source bundle") from exc


def materialize(source: VerifiedSource, target: Path) -> Path:
    """Create a clean shallow checkout, without filters, hooks or origin credentials."""
    if target.exists():
        if target.is_symlink() or target.resolve() != target.absolute():
            raise SourceBundleError("source target may not traverse a symlink")
        if _git(target, "rev-parse", "HEAD", credentials=False).decode().strip() != source.manifest["commit_sha"]:
            raise SourceBundleError("existing checkout identity mismatch")
        # Verify the actual files from raw blob bytes, not only index / stat caches.
        actual = set()
        for base, dirs, entries in os.walk(target, followlinks=False):
            if Path(base) == target:
                dirs[:] = [name for name in dirs if name != ".git"]
            for name in entries + [name for name in dirs if (Path(base) / name).is_symlink()]:
                file = Path(base) / name
                actual.add(file.relative_to(target).as_posix())
        if actual != source.files.keys():
            raise SourceBundleError("existing checkout is not the accepted clean tree")
        for path, (mode, oid) in source.files.items():
            file = target / path
            if file.parent.resolve() != file.parent.absolute():
                raise SourceBundleError("existing checkout file traverses a symlink")
            if mode == "120000":
                if not file.is_symlink() or os.fsencode(os.readlink(file)) != source.objects[oid][1]:
                    raise SourceBundleError("existing checkout is not the accepted clean tree")
            elif (file.is_symlink() or not file.is_file() or file.read_bytes() != source.objects[oid][1]
                  or bool(file.stat().st_mode & 0o111) != (mode == "100755")):
                raise SourceBundleError("existing checkout is not the accepted clean tree")
        return target
    if target.parent.resolve() != target.parent.absolute():
        raise SourceBundleError("source target parent may not traverse a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".source-", dir=target.parent))
    try:
        _git(staging, "init", "--object-format=" + source.manifest["object_format"], credentials=False)
        for oid, (kind, data) in source.objects.items():
            path = staging / ".git" / "objects" / oid[:2] / oid[2:]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(zlib.compress(f"{kind} {len(data)}\0".encode() + data))
        (staging / ".git" / "shallow").write_text(source.manifest["commit_sha"] + "\n")
        (staging / ".git" / "HEAD").write_text(source.manifest["commit_sha"] + "\n")
        _git(staging, "config", "core.hooksPath", os.devnull, credentials=False)
        _git(staging, "config", "core.autocrlf", "false", credentials=False)
        _git(staging, "config", "remote.origin.url", source.manifest["origin"], credentials=False)
        # Populate bytes directly. git checkout would run global smudge filters.
        for path, (mode, oid) in sorted(source.files.items()):
            file = staging / path
            file.parent.mkdir(parents=True, exist_ok=True)
            if mode == "120000":
                file.symlink_to(source.objects[oid][1].decode("utf-8"))
            else:
                file.write_bytes(source.objects[oid][1])
                file.chmod(0o755 if mode == "100755" else 0o644)
        _git(staging, "read-tree", source.manifest["commit_sha"], credentials=False)
        if _git(staging, "write-tree", credentials=False).decode().strip() != source.manifest["root_tree"]:
            raise SourceBundleError("materialized checkout tree mismatch")
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


@dataclass(frozen=True)
class PreparedSource:
    bundle_path: Path
    manifest: dict
    receipt: dict


class LocalSourceAdapter:
    def __init__(self, root: Path, *, allowed_origins: list[str] | None = None, allow_local_origin: bool = False):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.allowed_origins = frozenset(allowed_origins or [])
        self.allow_local_origin = allow_local_origin

    def prepare(self, payload: dict, *, deadline: float | None = None) -> PreparedSource:
        transfer_id = str(UUID(payload["transfer_id"]))
        directory = self.root / "acquisitions" / transfer_id
        if directory.resolve() != directory.absolute():
            raise SourceBundleError("managed acquisition directory may not traverse a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(directory / ".acquisition.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        acquired = False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError as exc:
                raise SourceBundleError("original source preparation is in progress; reconcile it before retry") from exc
            try:
                return self._prepare(payload, deadline=deadline)
            except Exception:
                # Failures retain no fetched credential-bearing repository or
                # partial database; accepted bundles remain for original recovery.
                git = directory / "repository"
                if directory.resolve() == directory.absolute() and git.is_dir() and not git.is_symlink():
                    shutil.rmtree(git)
                pending = directory / "bundle.pending"
                if directory.resolve() == directory.absolute() and pending.is_file() and not pending.is_symlink():
                    pending.unlink()
                raise
        finally:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _prepare(self, payload: dict, *, deadline: float | None = None) -> PreparedSource:
        if deadline is not None and deadline <= time.monotonic():
            raise SourceBundleError("source acquisition authorization expired")
        transfer_id = str(UUID(payload["transfer_id"]))
        origin = validate_origin(payload["origin"], allow_local=self.allow_local_origin)
        if origin not in self.allowed_origins:
            raise SourceBundleError("origin is not in this device's explicitly approved source scope")
        commit = payload["commit_sha"]
        if not isinstance(commit, str) or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", commit):
            raise SourceBundleError("source input must fix a complete commit SHA")
        directory = self.root / "acquisitions" / transfer_id
        if directory.resolve() != directory.absolute():
            raise SourceBundleError("managed acquisition directory may not traverse a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        bundle = directory / "bundle.json"
        if bundle.is_symlink():
            raise SourceBundleError("managed source bundle may not be a symlink")
        if bundle.exists():
            verified = verify_bundle(bundle.read_bytes(), origin=origin, commit_sha=commit)
            return PreparedSource(bundle, verified.manifest, self._receipt(payload, verified))
        # Retain accepted objects for recovery, bounded by a local cache quota.
        # Never evict an active or uncertain Run to make room for new work.
        cached = sum(path.stat().st_size for path in (self.root / "acquisitions").glob("*/bundle.json")
                     if path.is_file() and not path.is_symlink())
        if cached + MAX_BUNDLE_BYTES > 2 * 1024 * 1024 * 1024:
            raise SourceBundleError("local source cache quota reached; clean completed Run caches explicitly")
        git = directory / "repository"
        if git.is_symlink():
            raise SourceBundleError("managed Git acquisition repository may not be a symlink")
        git.mkdir(exist_ok=True, mode=0o700)
        def command(*args):
            return _git(git, *args, deadline=deadline)
        command("init", "--bare", "--object-format=" + ("sha1" if len(commit) == 40 else "sha256"))
        command("remote", "add", "origin", origin)
        command("fetch", "--depth=1", "--no-tags", "origin", commit)
        if command("rev-parse", "FETCH_HEAD").decode().strip() != commit:
            raise SourceBundleError("origin did not return the approved commit")
        objects = {}
        expanded_bytes = 0
        def read(oid: str, expected: str):
            nonlocal expanded_bytes
            if oid in objects:
                return
            kind = command("cat-file", "-t", oid).decode().strip()
            if kind != expected:
                raise SourceBundleError("unexpected Git object type")
            size = int(command("cat-file", "-s", oid))
            if size > MAX_OBJECT_BYTES:
                raise SourceBundleError("source object exceeds bounds")
            raw = command("cat-file", kind, oid)
            objects[oid] = (kind, raw)
            expanded_bytes += len(raw)
            if len(objects) > MAX_OBJECTS or expanded_bytes > MAX_EXPANDED_BYTES:
                raise SourceBundleError("source closure exceeds bounds")
        read(commit, "commit")
        _secret("SOURCE_COMMIT", objects[commit][1])
        tree = objects[commit][1].split(b"\n", 1)[0].removeprefix(b"tree ").decode()
        if not re.fullmatch(rf"[a-f0-9]{{{len(commit)}}}", tree):
            raise SourceBundleError("fetched commit does not reference a complete root tree")
        oid_bytes = len(commit) // 2
        def tree_entries(oid):
            data, offset = objects[oid][1], 0
            while offset < len(data):
                sep, nul = data.find(b" ", offset), data.find(b"\0", offset)
                if sep < offset or nul < sep or nul + 1 + oid_bytes > len(data):
                    raise SourceBundleError("malformed fetched Git tree")
                mode, name = data[offset:sep].decode("ascii"), data[sep + 1:nul].decode("utf-8")
                child = data[nul + 1:nul + 1 + oid_bytes].hex()
                offset = nul + 1 + oid_bytes
                if "/" in name:
                    raise SourceBundleError("unsafe fetched Git tree name")
                _path(name)
                yield mode, name, child
        visited = set()
        def trees(oid, depth=0):
            if depth > 100:
                raise SourceBundleError("source tree nesting exceeds limits")
            if oid in visited:
                return
            visited.add(oid)
            read(oid, "tree")
            for mode, _, child in tree_entries(oid):
                if mode == "40000":
                    trees(child, depth + 1)
                elif mode in {"100644", "100755"}:
                    read(child, "blob")
                else:
                    raise SourceBundleError("submodules, symbolic links and special file modes are unsupported")
        trees(tree)
        files, visits = [], 0
        def manifest_tree(oid, prefix=""):
            nonlocal visits
            visits += 1
            if visits > MAX_OBJECTS:
                raise SourceBundleError("expanded tree count exceeds limits")
            for mode, name, child in tree_entries(oid):
                path = prefix + name
                _path(path)
                if mode == "40000":
                    manifest_tree(child, path + "/")
                else:
                    _secret(path, objects[child][1])
                    files.append({"path": path, "mode": mode, "oid": child,
                                  "sha256": hashlib.sha256(objects[child][1]).hexdigest()})
                    if len(files) > MAX_FILES:
                        raise SourceBundleError("source file count exceeds limits")
        manifest_tree(tree)
        manifest = {"origin": origin, "commit_sha": commit, "root_tree": tree,
                    "object_format": "sha1" if len(commit) == 40 else "sha256",
                    "files": sorted(files, key=lambda item: item["path"])}
        content = canonical({"format": FORMAT, "manifest": manifest,
                             "objects": [{"oid": oid, "type": kind, "data": base64.b64encode(raw).decode()}
                                         for oid, (kind, raw) in sorted(objects.items())]})
        verified = verify_bundle(content, origin=origin, commit_sha=commit)
        temporary = directory / "bundle.pending"
        with temporary.open("xb") as output:
            output.write(content)
        temporary.rename(bundle)
        # Remove the fetcher's repository including personal credential helper config.
        shutil.rmtree(git)
        return PreparedSource(bundle, manifest, self._receipt(payload, verified))

    @staticmethod
    def _receipt(payload: dict, verified: VerifiedSource) -> dict:
        return {**{key: payload.get(key) for key in ("transfer_id", "request_id", "project_id", "node_id", "origin", "ref", "commit_sha", "policy_version")},
                "root_tree": verified.manifest["root_tree"], "bundle_sha256": verified.bundle_sha256,
                "bundle_size": verified.bundle_size, "result": "ACQUIRED"}


    def install_workspace(self, payload: dict) -> Path:
        transfer_id = str(UUID(payload["transfer_id"]))
        str(UUID(payload["run_id"]))
        workspace_id = UUID(str(payload["workspace_id"])).hex
        target = self.root / ".hypertest-agent-sessions" / workspace_id / "repo"
        if payload.get("create") is False and not target.is_dir():
            raise BridgeError("WORKSPACE_UNAVAILABLE", "original accepted workspace is unavailable; recovery cannot recreate it")
        bundle = self.root / "acquisitions" / transfer_id / "bundle.json"
        try:
            if bundle.is_symlink() or bundle.parent.resolve() != bundle.parent.absolute():
                raise SourceBundleError("managed source bundle may not traverse a symlink")
            content = bundle.read_bytes()
            if hashlib.sha256(content).hexdigest() != payload["bundle_sha256"]:
                raise SourceBundleError("accepted source bundle digest mismatch")
            verified = verify_bundle(content, origin=payload["origin"], commit_sha=payload["commit_sha"])
            if verified.manifest["root_tree"] != payload["root_tree"]:
                raise SourceBundleError("accepted source root tree mismatch")
            if payload.get("create") is False and not (target / ".git").is_dir():
                raise SourceBundleError("original workspace Git identity is unavailable")
            return materialize(verified, target)
        except FileNotFoundError as exc:
            raise BridgeError("WORKSPACE_UNAVAILABLE", "original accepted workspace source identity is unavailable") from exc
        except SourceBundleError as exc:
            # Failure to launch Git or a local timeout is an operational unknown,
            # not proof that the original workspace was lost or changed.
            if str(exc).startswith("controlled Git operation"):
                raise
            raise BridgeError("WORKSPACE_INTEGRITY_REJECTED", "original workspace or accepted source identity changed") from exc
