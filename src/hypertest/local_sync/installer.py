"""Reversible, explicitly targeted host configuration. Never issues credentials.

All host support is UNACCEPTED until real sessions have been independently
tested. These operations configure files, not a running Agent or model login.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_directory, private_read
from hypertest.local_sync.hosts import HOST_PROVIDERS, probe_native_version
from hypertest.sync_core import canonical_json

BEGIN, END = "# BEGIN HYPERTEST LOCAL\n", "# END HYPERTEST LOCAL\n"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink():
        raise ClientError("INSTALL_SYMLINK_REJECTED")
    fd, temporary = tempfile.mkstemp(prefix=".hypertest-local-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_host(path: Path) -> bytes:
    if not path.exists():
        if path.is_symlink():
            raise ClientError("INSTALL_SYMLINK_REJECTED")
        return b""
    if path.is_symlink():
        raise ClientError("INSTALL_SYMLINK_REJECTED")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ClientError("INSTALL_HOST_FILE_REJECTED")
    if info.st_size > 4 * 1024 * 1024:
        raise ClientError("INSTALL_HOST_FILE_TOO_LARGE")
    return path.read_bytes()


@contextmanager
def install_lock(directory: Path):
    directory = private_directory(directory)
    fd = os.open(directory / "install.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _pending_transactions(directory):
    return [path for path in (directory / "backups").glob("*/transaction.json")
            if not (path.parent / "committed.json").exists()
            and not (path.parent / "rolled-back.json").exists()]


def _commit_changes(directory, changes):
    if _pending_transactions(directory):
        raise ClientError("INSTALL_RECOVERY_REQUIRED")
    transaction = private_directory(directory / "backups" / uuid4().hex)
    rows = []
    for index, (path, before, after) in enumerate(changes):
        private_create(transaction / f"{index}.before", before)
        rows.append({"path": str(path), "existed": path.exists(),
                     "before_sha256": hashlib.sha256(before).hexdigest(),
                     "after_sha256": hashlib.sha256(after).hexdigest()})
    private_create(transaction / "transaction.json", canonical_json({"changes": rows}).encode())
    try:
        for path, before, after in changes:
            if read_host(path) != before:
                raise ClientError("INSTALL_CONCURRENT_CONFIGURATION_CHANGE")
            atomic_write(path, after)
        private_create(transaction / "committed.json", b"{}")
    except BaseException:
        # Preserve the durable transaction even if rollback is interrupted.
        _recover_transaction(transaction)
        raise


def _recover_transaction(transaction):
    record = json.loads(private_read(transaction / "transaction.json"))
    # Verify every target before modifying any; user edits are never overwritten.
    for row in record["changes"]:
        current = hashlib.sha256(read_host(Path(row["path"]))).hexdigest()
        if current not in {row["before_sha256"], row["after_sha256"]}:
            raise ClientError("INSTALL_RECOVERY_CONFLICT_USER_CONFIGURATION_PRESERVED")
    for index, row in reversed(list(enumerate(record["changes"]))):
        path = Path(row["path"])
        before = private_read(transaction / f"{index}.before", max_bytes=4 * 1024 * 1024)
        if hashlib.sha256(before).hexdigest() != row["before_sha256"]:
            raise ClientError("INSTALL_RECOVERY_BACKUP_CORRUPT")
        if row["existed"]:
            atomic_write(path, before)
        else:
            path.unlink(missing_ok=True)
    private_create(transaction / "rolled-back.json", b"{}")


def recover_install(*, directory: Path) -> dict:
    with install_lock(directory):
        transactions = _pending_transactions(directory)
        for path in transactions:
            _recover_transaction(path.parent)
        return {"configuration": "RECOVERED" if transactions else "NO_PENDING_TRANSACTION",
                "transactions": len(transactions), "private_state": "PRESERVED", "reload_required": bool(transactions)}


def _remove_text(raw: str, old: dict | None):
    if BEGIN in raw or END in raw:
        if old is None or old.get("block") is None or raw.count(BEGIN) != 1 or raw.count(END) != 1:
            raise ClientError("INSTALL_UNOWNED_CONFIG_CONFLICT")
        if old["block"] not in raw:
            raise ClientError("MANAGED_CONFIG_CHANGED")
        return raw.replace(old["block"], "", 1)
    if old and old.get("block"):
        raise ClientError("MANAGED_CONFIG_CHANGED")
    return raw


def merge_host(host: str, raw: bytes, server: dict, *, old=None, remove=False, bridge_row=None):
    if host == "claude-code":
        document = json.loads(raw or b"{}")
        servers = document.setdefault("mcpServers", {})
        current = servers.get("hypertest-local")
        if current is not None and (not old or current != old.get("entry")):
            raise ClientError("INSTALL_UNOWNED_CONFIG_CONFLICT")
        if remove:
            servers.pop("hypertest-local", None)
        else:
            servers["hypertest-local"] = server
        return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(), {"entry": server}
    text = _remove_text(raw.decode(), old)
    if remove:
        if host == "codex":
            tomllib.loads(text)
        elif host != "deepseek-harness":
            raise ClientError("LOCAL_HOST_UNSUPPORTED")
        return text.encode(), {}
    if host == "codex":
        # Parse first; preserve every unowned byte, including comments. No
        # general TOML serializer or fragile global text substitution.
        parsed = tomllib.loads(text)
        if "hypertest_local" in parsed.get("mcp_servers", {}):
            raise ClientError("INSTALL_UNOWNED_CONFIG_CONFLICT")
        body = ("[mcp_servers.hypertest_local]\ncommand = " + json.dumps(server["command"])
                + "\nargs = " + json.dumps(server["args"], ensure_ascii=False)
                + "\nstartup_timeout_sec = 20\ntool_timeout_sec = 120\n")
    elif host == "deepseek-harness":
        if ("hypertest-local-mcp" in text or "hypertest-local-hook-bridge" in text
                or re.search(r"serverName:\s*['\"]?hypertest(?:['\"]|\s|$)", text)):
            raise ClientError("INSTALL_UNOWNED_CONFIG_CONFLICT")
        stripped = [line.strip() for line in text.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        if stripped == ["[]"]:
            text = ""
        elif stripped and not stripped[0].startswith("-"):
            raise ClientError("DEEPSEEK_PATCH_SHAPE_UNSUPPORTED")
        # JSON flow values are legal YAML. Only a pinned official insert patch
        # is appended; no YAML execution, module install or profile recreation.
        row = {"id": "hypertest-local-mcp", "name": "@deepseek-ai/dsh-mcp-client",
               "config": {"serverName": "hypertest", "transport": "stdio", **server}}
        body = "- insert:\n    - " + canonical_json(row) + "\n"
        if bridge_row is not None:
            body += "    - " + canonical_json(bridge_row) + "\n"
    else:
        raise ClientError("LOCAL_HOST_UNSUPPORTED")
    block = BEGIN + body + END
    if not remove:
        text += ("\n" if text and not text.endswith("\n") else "") + block
    if host == "codex":
        tomllib.loads(text)
    return text.encode(), {"block": block}


def merge_hooks(raw: bytes, command: str, *, old=None, remove=False, deepseek=False, host=None):
    document = json.loads(raw or b"{}")
    events = document.setdefault("hooks", {})
    old_groups = (old or {}).get("groups", {})
    for event, group in old_groups.items():
        values = events.get(event, [])
        if group not in values:
            raise ClientError("MANAGED_CONFIG_CHANGED")
        values.remove(group)
        if not values:
            events.pop(event, None)
    selected = ("SessionStart", "PostToolUse", "Stop") if deepseek else (
        "SessionStart", "PostToolUse", "Stop", "SessionEnd", "SubagentStop")
    if host == "codex":
        selected = tuple(event for event in selected if event != "SessionEnd")
    groups = {}
    if not remove:
        for event in selected:
            group = {"hooks": [{"type": "command", "command": command,
                                 "timeout": 3 if event == "SessionEnd" else 15}]}
            events.setdefault(event, []).append(group)
            groups[event] = group
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(), {"groups": groups}


def receipt_path(directory: Path, host: str):
    return directory / ("installed-" + host + ".json")


def install(*, directory: Path, host: str, host_config: Path, client_config: Path,
            version: str, python: Path | None = None, hook_config: Path | None = None,
            enable_hooks=False, harness_version: str | None = None,
            dsh_home: Path | None = None, profile: str | None = None,
            event_bridge: str | None = None, workspace: Path | None = None,
            artifact_source: Path | None = None, harness_binary: Path | None = None) -> dict:
    if host not in HOST_PROVIDERS or not re.fullmatch(r"local-v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
        raise ClientError("LOCAL_RELEASE_OR_HOST_INVALID")
    directory, host_config, client_config = directory.expanduser().absolute(), host_config.expanduser().absolute(), client_config.expanduser().absolute()
    config = ClientConfig.load(client_config, validate_credentials=False)
    if workspace is not None and artifact_source is not None:
        raise ClientError("SELECT_ONE_ARTIFACT_SOURCE_STRATEGY")
    source_policy = None
    if workspace is not None or artifact_source is not None:
        from hypertest.local_sync.sources import ArtifactSource
        if config.local_sync.get("manifest_file"):
            raise ClientError("EXPLICIT_MANIFEST_SOURCE_MIGRATION_REQUIRED")
        selected = (json.loads(private_read(artifact_source.expanduser().absolute()))
            if artifact_source is not None else {"workspace": str(workspace.expanduser().absolute()),
                "initial": {"title": "Local testing session", "objective": "", "status": "DRAFT",
                            "plan_markdown": "", "reported_result": "NOT_RUN"},
                "artifacts": [{"kind": "TEST_PLAN", "path": "analysis.md"}]})
        policy = ArtifactSource.model_validate(selected)
        if not policy.workspace.is_dir() or policy.workspace.resolve() != policy.workspace:
            raise ClientError("LOCAL_SOURCE_WORKSPACE_MISMATCH")
        source_policy = policy.model_dump(mode="json")
        config.local_sync["artifact_source"] = source_policy
    if config.local_sync.get("host") not in {None, host}:
        raise ClientError("SEPARATE_HOST_CLIENT_CONFIGURATION_REQUIRED")
    if hook_config is not None:
        hook_config = hook_config.expanduser().absolute()
    if len({path for path in (host_config, client_config, hook_config) if path is not None}) != (3 if hook_config else 2):
        raise ClientError("INSTALL_TARGET_FILES_MUST_DIFFER")
    python = python or Path(sys.executable)
    handler_arguments = [str(python), "-I", "-m", "hypertest.local_sync", "hook", "--config", str(client_config)]
    bridge_row = None
    native_root = False
    native_version = None
    if enable_hooks and host in {"codex", "claude-code"}:
        native_version = probe_native_version(host, executable=harness_binary)
        if harness_version is not None and harness_version != native_version["harness_version"]:
            raise ClientError("LOCAL_DECLARED_HOST_VERSION_MISMATCH")
        harness_version = native_version["harness_version"]
    if host == "deepseek-harness":
        if not dsh_home or not profile or not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
            raise ClientError("DEEPSEEK_HOME_PROFILE_REQUIRED")
        expected = dsh_home.expanduser().absolute() / "profiles" / profile / "cordis.patch.yml"
        if host_config != expected or not (expected.parent / "package.json").is_file():
            raise ClientError("DEEPSEEK_EXISTING_PROFILE_REQUIRED")
        if enable_hooks:
            event_bridge = event_bridge or ("native-root" if config.local_sync.get("artifact_source") else "claude-code")
            native_root = event_bridge == "native-root"
            if native_root:
                from hypertest.local_sync.deepseek_bridge import root_bridge_descriptor
                if not config.local_sync.get("artifact_source") or hook_config is not None:
                    raise ClientError("DEEPSEEK_NATIVE_ROOT_SOURCE_REQUIRED")
                bridge_row = root_bridge_descriptor(dsh_home=dsh_home, profile=profile,
                    handler_command=handler_arguments,
                    workspace=Path(config.local_sync["artifact_source"]["workspace"]))
            else:
                from hypertest.local_sync.deepseek_bridge import bridge_descriptor
                if config.local_sync.get("artifact_source"):
                    raise ClientError("DEEPSEEK_ROOT_SOURCE_BRIDGE_REQUIRED")
                if hook_config is None:
                    raise ClientError("DEEPSEEK_DEDICATED_HOOK_CONFIG_REQUIRED")
                bridge_row = bridge_descriptor(dsh_home=dsh_home, profile=profile,
                    hook_config=hook_config, bridge=event_bridge)
            if native_root:
                actual_version = bridge_row["config"]["harnessVersion"]
            else:
                from hypertest.local_sync.deepseek_bridge import bridge_capability
                actual_version = bridge_capability(bridge=event_bridge)["harness_version"]
            if harness_version is not None and harness_version != actual_version:
                raise ClientError("LOCAL_DECLARED_HOST_VERSION_MISMATCH")
            harness_version = actual_version
    if enable_hooks and ((hook_config is None and not native_root) or not harness_version
                         or not (config.local_sync.get("manifest_file") or config.local_sync.get("artifact_source"))
                         or not config.local_sync.get("project_id")):
        raise ClientError("EXPLICIT_HOOK_SOURCE_CONFIGURATION_REQUIRED")
    server = {"command": str(python), "args": ["-I", "-m", "hypertest.interactive_client", "stdio",
              "--config", str(client_config), "--autostart"]}
    command = shlex.join(handler_arguments)
    with install_lock(directory):
        if _pending_transactions(directory):
            raise ClientError("INSTALL_RECOVERY_REQUIRED")
        old_path = receipt_path(directory, host)
        old = json.loads(private_read(old_path)) if old_path.exists() else None
        if old and (old["host_config"] != str(host_config) or old["client_config"] != str(client_config)):
            raise ClientError("EXPLICIT_INSTALL_TARGET_MIGRATION_REQUIRED")
        raw = read_host(host_config)
        effective_old = old if old and old.get("configuration") != "REMOVED" else None
        merged, owned = merge_host(host, raw, server, old=effective_old.get("owned") if effective_old else None,
                                   bridge_row=bridge_row)
        changes = [(host_config, raw, merged)]
        hooks_owned = None
        if effective_old and effective_old.get("hook_config") and str(hook_config) != effective_old["hook_config"]:
            raise ClientError("EXPLICIT_HOOK_TARGET_MIGRATION_REQUIRED")
        if (enable_hooks and not native_root) or (effective_old and effective_old.get("hooks_owned")):
            target = hook_config or Path(old["hook_config"])
            hook_raw = read_host(target)
            updated, hooks_owned = merge_hooks(hook_raw, command,
                old=effective_old.get("hooks_owned") if effective_old else None, remove=not enable_hooks,
                deepseek=host == "deepseek-harness", host=host)
            changes.append((target, hook_raw, updated))
        original_config = private_read(client_config)
        body = json.loads(original_config)
        if body.get("local_sync", {}).get("host") not in {None, host}:
            raise ClientError("SEPARATE_HOST_CLIENT_CONFIGURATION_REQUIRED")
        body["local_sync"] = {**body.get("local_sync", {}), "enabled": True,
            "host": host, "hooks_enabled": bool(enable_hooks), "harness_version": harness_version}
        if source_policy is not None:
            body["local_sync"]["artifact_source"] = source_policy
        if host == "deepseek-harness":
            body["local_sync"]["event_bridge"] = event_bridge or "claude-code"
        changes.append((client_config, original_config,
                        (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode()))
        transaction = private_directory(directory / "backups" / uuid4().hex)
        if old:
            private_create(transaction / "previous-install.json", canonical_json(old).encode())
        for index, (_, before, _) in enumerate(changes):
            private_create(transaction / f"{index}.before", before)
        receipt = {"profile": "hypertest.local-install/v1", "host": host, "version": version,
            "host_config": str(host_config), "client_config": str(client_config), "owned": owned,
            "hook_config": str(hook_config) if hook_config else None, "hooks_owned": hooks_owned,
            "previous_receipt_file": str(transaction / "previous-install.json") if old else None,
            "backup_directory": str(transaction), "python": str(python),
            "harness_version": harness_version, "enable_hooks": bool(enable_hooks),
            "native_version_probe": native_version,
            "event_bridge": event_bridge,
            "dsh_home": str(dsh_home) if dsh_home else None, "dsh_profile": profile,
            "configuration": "WRITTEN", "reload_required": True,
            "native_acceptance": "NOT_OBSERVED", "real_sync": "NOT_OBSERVED",
            "automatic_trigger": "CONFIGURED_UNACCEPTED" if enable_hooks else "DISABLED"}
        changes.append((old_path, private_read(old_path) if old_path.exists() else b"",
                        canonical_json(receipt).encode()))
        _commit_changes(directory, changes)
        return {key: receipt[key] for key in ("host", "version", "configuration", "reload_required",
                 "native_acceptance", "real_sync", "automatic_trigger")}


def uninstall(*, directory: Path, host: str) -> dict:
    with install_lock(directory):
        record_path = receipt_path(directory, host)
        if not record_path.exists():
            return {"host": host, "configuration": "NOT_INSTALLED"}
        old = json.loads(private_read(record_path))
        if old.get("configuration") == "REMOVED":
            return {"host": host, "configuration": "REMOVED", "private_state": "PRESERVED"}
        target = Path(old["host_config"])
        before = read_host(target)
        after, _ = merge_host(host, before, {}, old=old["owned"], remove=True)
        changes = [(target, before, after)]
        if old.get("hooks_owned") and old.get("hook_config"):
            hooks = Path(old["hook_config"])
            prior = read_host(hooks)
            new, _ = merge_hooks(prior, "", old=old["hooks_owned"], remove=True)
            changes.append((hooks, prior, new))
        # Keep the private client's identity, credentials and pending ledger;
        # disable only automatic triggers in its existing configuration.
        client = Path(old["client_config"])
        prior = private_read(client)
        config = json.loads(prior)
        config.setdefault("local_sync", {})["hooks_enabled"] = False
        changes.append((client, prior, (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()))
        backup = private_directory(directory / "backups" / ("uninstall-" + uuid4().hex))
        for index, (_, prior, _) in enumerate(changes):
            private_create(backup / f"{index}.before", prior)
        changes.append((record_path, private_read(record_path),
                        canonical_json({**old, "configuration": "REMOVED"}).encode()))
        _commit_changes(directory, changes)
        return {"host": host, "configuration": "REMOVED", "private_state": "PRESERVED",
                "reload_required": True, "binary_cleanup": "RETAINED_FOR_PENDING_RECOVERY"}


def rollback(*, directory: Path, host: str) -> dict:
    current = json.loads(private_read(receipt_path(directory, host)))
    if not current.get("previous_receipt_file"):
        raise ClientError("PREVIOUS_LOCAL_RELEASE_REQUIRED")
    prior = json.loads(private_read(Path(current["previous_receipt_file"])))
    # Reapply only owned fragments through the same conflict-aware installer;
    # never restore an old complete host-config backup over subsequent edits.
    return install(directory=directory, host=host, host_config=Path(prior["host_config"]),
        client_config=Path(prior["client_config"]), version=prior["version"],
        python=Path(prior["python"]),
        hook_config=Path(prior["hook_config"]) if prior.get("hook_config") else None,
        enable_hooks=prior["enable_hooks"], harness_version=prior.get("harness_version"),
        dsh_home=Path(prior["dsh_home"]) if prior.get("dsh_home") else None,
        profile=prior.get("dsh_profile"), event_bridge=prior.get("event_bridge"),
        harness_binary=Path(prior["native_version_probe"]["executable"])
            if prior.get("native_version_probe") else None)


def doctor(*, directory: Path, host: str) -> dict:
    path = receipt_path(directory, host)
    if not path.exists():
        return {"host": host, "configuration": "NOT_INSTALLED", "real_sync": "NOT_OBSERVED"}
    record = json.loads(private_read(path))
    result = {"host": host, "version": record["version"],
              "configuration": record["configuration"], "native_acceptance": "NOT_OBSERVED",
              "mcp": "RELOAD_AND_NATIVE_PROBE_REQUIRED", "real_sync": "NOT_OBSERVED"}
    try:
        # Default doctor is strictly read-only, including a missing state dir.
        config = ClientConfig.model_validate(json.loads(private_read(Path(record["client_config"]))))
        url = urlsplit(config.api_url)
        if (url.username is not None or url.password is not None or url.query or url.fragment
                or not url.hostname or (url.scheme != "https" and not (
                    config.allow_insecure_loopback and url.scheme == "http"
                    and url.hostname in {"127.0.0.1", "::1", "localhost"}))):
            raise ClientError("HTTPS_PLATFORM_URL_REQUIRED")
        private_read(config.integration_token_file, max_bytes=4096)
        state_exists = config.state_dir.exists()
        if state_exists:
            info = config.state_dir.stat()
            if config.state_dir.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ClientError("PRIVATE_DIRECTORY_REQUIRED")
        result["authorization"] = "PRIVATE_CREDENTIAL_PRESENT_NOT_SERVER_VERIFIED"
        result["pending_state"] = "PRESERVED" if state_exists else "ABSENT"
        if sys.platform == "darwin":
            # sockaddr_un.sun_path is 104 bytes on this supported target;
            # Python's pathname socket includes a terminating NUL byte.
            socket_bytes = len(os.fsencode(config.socket_path)) + 1
            result["socket_path_bytes_including_nul"] = socket_bytes
            if socket_bytes > 104:
                result["mcp"] = "BLOCKED"
                result["mcp_code"] = "AF_UNIX_PATH_TOO_LONG"
                result["code"] = "AF_UNIX_PATH_TOO_LONG"
                result["recovery"] = "SELECT_SHORT_PRIVATE_STATE_DIRECTORY_PRESERVE_EXISTING_STATE"
    except ClientError as exc:
        result["authorization"] = "BLOCKED"
        result["code"] = exc.code
    result["automatic_trigger"] = record["automatic_trigger"]
    return result
