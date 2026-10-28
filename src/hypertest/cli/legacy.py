"""Explicit retirement of an existing Local installation.

No old MCP, provider adapter, daemon launcher, or third-party dependency is imported.
The original private journal and approved snapshots are never rewritten.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import stat
import tempfile
import time
import tomllib
from pathlib import Path
from uuid import uuid4

from hypertest.cli.state import CLIError
from hypertest.interactive_client.security import (
    peer_uid,
    private_create,
    private_directory,
    private_read,
)
from hypertest.sync_core import canonical_json

BEGIN, END = "# BEGIN HYPERTEST LOCAL\n", "# END HYPERTEST LOCAL\n"


def _json(path, max_bytes=4 * 1024 * 1024):
    value = json.loads(private_read(Path(path), max_bytes=max_bytes))
    if not isinstance(value, dict):
        raise CLIError("LEGACY_RECORD_INVALID", 5)
    return value


def _existing_directory(path):
    path = Path(path).expanduser().absolute()
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise CLIError("LEGACY_PRIVATE_DIRECTORY_REQUIRED", 5)
    return path.resolve()


def _host_read(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022
                or info.st_size > 4 * 1024 * 1024):
            raise CLIError("LEGACY_HOST_FILE_REJECTED", 5)
        return os.read(fd, 4 * 1024 * 1024 + 1)
    finally:
        os.close(fd)


def _atomic(path, raw):
    path = Path(path)
    if path.is_symlink():
        raise CLIError("LEGACY_SYMLINK_REJECTED", 5)
    fd, name = tempfile.mkstemp(prefix=".hypertest-retire-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def _recover_retirement(directory):
    for pending in (directory / "legacy-retire").glob("*/transaction.json"):
        if (pending.parent / "committed.json").exists() or (pending.parent / "rolled-back.json").exists():
            continue
        rows = _json(pending)["changes"]
        for row in rows:
            if hashlib.sha256(_host_read(row["path"])).hexdigest() not in {row["before_sha256"], row["after_sha256"]}:
                raise CLIError("LEGACY_RETIRE_RECOVERY_CONFLICT_PRESERVED", 4)
        for index, row in reversed(list(enumerate(rows))):
            before = private_read(pending.parent / f"{index}.before", max_bytes=4 * 1024 * 1024)
            if hashlib.sha256(before).hexdigest() != row["before_sha256"]:
                raise CLIError("LEGACY_RETIRE_BACKUP_INVALID", 5)
            _atomic(row["path"], before)
        private_create(pending.parent / "rolled-back.json", b"{}")


def _commit(directory, changes):
    transaction = private_directory(directory / "legacy-retire" / uuid4().hex)
    rows = []
    for index, (path, before, after) in enumerate(changes):
        private_create(transaction / f"{index}.before", before)
        rows.append({"path": str(path), "before_sha256": hashlib.sha256(before).hexdigest(),
                     "after_sha256": hashlib.sha256(after).hexdigest()})
    private_create(transaction / "transaction.json", canonical_json({"changes": rows}).encode())
    try:
        for path, before, after in changes:
            if _host_read(path) != before:
                raise CLIError("LEGACY_CONFIGURATION_CHANGED_PRESERVED", 4)
            _atomic(path, after)
        private_create(transaction / "committed.json", b"{}")
    except BaseException:
        _recover_retirement(directory)
        raise


def _remove_host(host, raw, owned):
    if host == "claude-code":
        document = json.loads(raw)
        servers = document.get("mcpServers", {})
        if servers.get("hypertest-local") != owned.get("entry") or "entry" not in owned:
            raise CLIError("LEGACY_MANAGED_CONFIG_CHANGED_PRESERVED", 4)
        del servers["hypertest-local"]
        return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
    text = raw.decode()
    block = owned.get("block")
    if (not block or not block.startswith(BEGIN) or not block.endswith(END)
            or text.count(BEGIN) != 1 or text.count(END) != 1 or text.count(block) != 1):
        raise CLIError("LEGACY_MANAGED_CONFIG_CHANGED_PRESERVED", 4)
    remaining = text.replace(block, "", 1)
    if host == "codex":
        tomllib.loads(remaining)
    return remaining.encode()


def _remove_hooks(raw, owned):
    document = json.loads(raw)
    events = document.get("hooks", {})
    for event, group in owned.get("groups", {}).items():
        values = events.get(event, [])
        if values.count(group) != 1:
            raise CLIError("LEGACY_MANAGED_HOOK_CHANGED_PRESERVED", 4)
        values.remove(group)
        if not values:
            del events[event]
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()


def _rpc(config, operation):
    directory = _existing_directory(config["state_dir"])
    path = directory / "interactive.sock"
    if not path.exists():
        return None
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise CLIError("LEGACY_SOCKET_REJECTED", 5)
    secret = private_read(directory / "ipc.token", max_bytes=4096).decode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(5)
        try:
            stream.connect(str(path))
        except ConnectionRefusedError:
            return None  # A stale socket is preserved, not deleted.
        if peer_uid(stream) != os.getuid():
            raise CLIError("LEGACY_PEER_REJECTED", 5)
        stream.sendall((json.dumps({"profile": "hypertest.interactive-mcp/v1alpha1", "token": secret,
            "operation": operation, "payload": {}}, separators=(",", ":")) + "\n").encode())
        with stream.makefile("rb") as reader:
            line = reader.readline(65537)
        if len(line) > 65536 or not line.endswith(b"\n"):
            raise CLIError("LEGACY_RUNTIME_RESPONSE_REJECTED", 4)
        response = json.loads(line)
        if response.get("ok") is not True:
            raise CLIError("LEGACY_RUNTIME_BUSY_OR_UNSUPPORTED", 4)
        return response.get("result")


def _configuration_digest(config):
    # Match the frozen ClientConfig model_dump recorded by the legacy runtime,
    # without importing that Pydantic-dependent implementation into the CLI.
    value = {"device_token_file": None, "node_id": None, "ca_file": None,
        "allow_insecure_loopback": False, "host_adapter": {"kind": "unsupported"},
        "workspaces": {}, "timeout_seconds": 30.0, "local_sync": {},
        "memory_enabled": False, "memory_timeout_seconds": 5.0, **config}
    value["api_url"] = value["api_url"].rstrip("/")
    value["state_dir"] = str(_existing_directory(value["state_dir"]))
    for field in ("integration_token_file", "device_token_file", "ca_file"):
        if value.get(field) is not None:
            value[field] = str(Path(value[field]))
    for field in ("timeout_seconds", "memory_timeout_seconds"):
        value[field] = float(value[field])
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stop_owned(config, receipt):
    if not Path(config["state_dir"]).exists():
        return "NOT_RUNNING"
    observed = _rpc(config, "runtime-info")
    if observed is None:
        return "NOT_RUNNING"
    runtime = observed.get("runtime", {})
    if (runtime.get("profile") != "hypertest.local-runtime/v1"
            or runtime.get("python") != receipt.get("python")
            or runtime.get("configuration_sha256") != _configuration_digest(config)
            or not isinstance(runtime.get("runtime_sha256"), str) or len(runtime["runtime_sha256"]) != 64):
        raise CLIError("LEGACY_RUNTIME_IDENTITY_MISMATCH_PRESERVED", 4)
    stopped = _rpc(config, "runtime-stop")
    if stopped is not None and stopped.get("state") != "STOPPING":
        raise CLIError("LEGACY_RUNTIME_STOP_UNCONFIRMED", 4)
    deadline = time.monotonic() + 5
    while Path(config["state_dir"], "interactive.sock").exists() and time.monotonic() < deadline:
        if _rpc(config, "runtime-info") is None:
            return "STOPPED"
        time.sleep(0.05)
    if Path(config["state_dir"], "interactive.sock").exists():
        raise CLIError("LEGACY_RUNTIME_STOP_UNCONFIRMED", 4)
    return "STOPPED"


def retire(directory: str, host: str):
    """Remove only receipt-owned fragments; retain source, credentials and journals."""
    host = "deepseek-harness" if host == "deepseek" else host
    if host not in {"codex", "claude-code", "deepseek-harness"}:
        raise CLIError("LEGACY_HOST_UNSUPPORTED", 2)
    directory = _existing_directory(directory)
    record = directory / f"installed-{host}.json"
    if not record.exists():
        return {"status": "NOT_INSTALLED", "host": host, "private_state": "PRESERVED"}, 0
    fd = os.open(directory / "install.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise CLIError("LEGACY_PRIVATE_LOCK_REQUIRED", 5)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CLIError("LEGACY_INSTALLATION_BUSY", 4) from exc
        for transaction in (directory / "backups").glob("*/transaction.json"):
            if not any((transaction.parent / name).exists() for name in ("committed.json", "rolled-back.json")):
                raise CLIError("LEGACY_INSTALL_RECOVERY_REQUIRED", 4)
        _recover_retirement(directory)
        receipt = _json(record)
        if receipt.get("profile") != "hypertest.local-install/v1" or receipt.get("host") != host:
            raise CLIError("LEGACY_INSTALL_RECEIPT_INVALID", 5)
        client_path = Path(receipt["client_config"])
        config_raw = private_read(client_path, max_bytes=4 * 1024 * 1024)
        config = json.loads(config_raw)
        if receipt.get("configuration") == "REMOVED":
            runtime = _stop_owned(config, receipt)
            return {"status": "RETIRED", "host": host, "configuration": "REMOVED", "runtime": runtime,
                    "private_state": "PRESERVED", "reload_required": True}, 0
        target = Path(receipt["host_config"])
        before = _host_read(target)
        changes = [(target, before, _remove_host(host, before, receipt["owned"]))]
        if receipt.get("hooks_owned") and receipt.get("hook_config"):
            hooks = Path(receipt["hook_config"])
            raw = _host_read(hooks)
            changes.append((hooks, raw, _remove_hooks(raw, receipt["hooks_owned"])))
        # Preflight every owned fragment before stopping the authenticated runtime.
        original_config = dict(config)
        config = json.loads(config_raw)
        config.setdefault("local_sync", {}).update(enabled=False, hooks_enabled=False)
        changes.append((client_path, config_raw, (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()))
        changes.append((record, private_read(record), canonical_json({**receipt, "configuration": "REMOVED",
            "retired_by": "hypertest-cli", "private_state": "PRESERVED"}).encode()))
        if len({str(path) for path, _, _ in changes}) != len(changes):
            raise CLIError("LEGACY_DUPLICATE_CONFIGURATION_TARGET", 5)
        runtime = _stop_owned(original_config, receipt)
        _commit(directory, changes)
        return {"status": "RETIRED", "host": host, "configuration": "REMOVED", "runtime": runtime,
                "private_state": "PRESERVED", "reload_required": True}, 0
    finally:
        os.close(fd)
