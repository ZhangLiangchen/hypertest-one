"""Explicit retirement and read-only recovery of an existing Local installation.

No old MCP, provider adapter, daemon launcher, or third-party dependency is imported.
The original private journal and approved snapshots are never rewritten.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import sqlite3
import ssl
import stat
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

from hypertest.cli.state import CLIError
from hypertest.cli.transport import NoRedirect
from hypertest.interactive_client.security import (
    peer_uid,
    private_create,
    private_directory,
    private_read,
)
from hypertest.sync_core import canonical_json, digest

BEGIN, END = "# BEGIN HYPERTEST LOCAL\n", "# END HYPERTEST LOCAL\n"
SYNC_PROFILE = "codex-session-task-sync/v1alpha1"
COLLAB_PROFILE = "local-task-collaboration/v1alpha1"


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


class ReadOnlyAPI:
    """Only exact historic GET routes; no generic method or write fallback exists."""
    def __init__(self, config):
        parts = urllib.parse.urlsplit(config["api_url"])
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path.rstrip("/") not in {"", "/api/v1"}):
            raise CLIError("LEGACY_HTTPS_API_REQUIRED", 5)
        self.base = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/api/v1", "", ""))
        self.secret = private_read(Path(config["integration_token_file"]), max_bytes=4096).decode().strip()
        self.timeout = min(max(float(config.get("timeout_seconds", 30)), 1), 120)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=config.get("ca_file"))))

    def get(self, path, query):
        import re
        if not re.fullmatch(r"interactive/tasks/(?:syncs/by-key|bindings/by-key|by-session|[0-9a-f-]{36}(?:/collaboration(?:/receipts/by-key)?)?)", path):
            raise CLIError("LEGACY_READ_ROUTE_REJECTED", 5)
        request = urllib.request.Request(self.base + "/" + path + "?" + urllib.parse.urlencode(query), method="GET",
            headers={"Authorization": "Bearer " + self.secret, "Accept": "application/json",
                "X-Hypertest-Interactive-Profile": "hypertest.interactive-mcp/v1alpha1"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1_000_001)
        except urllib.error.HTTPError as exc:
            raise CLIError("LEGACY_ORIGINAL_KEY_NOT_FOUND" if exc.code == 404 else "LEGACY_CURRENT_AUTHORIZATION_OR_READ_REJECTED",
                4 if exc.code == 404 or exc.code >= 500 else 3, status=exc.code) from None
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise CLIError("LEGACY_READ_UNCERTAIN", 4) from exc
        if len(raw) > 1_000_000:
            raise CLIError("LEGACY_RESPONSE_TOO_LARGE", 4)
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise CLIError("LEGACY_RESPONSE_INVALID", 4)
        return result


def _record(config, request_id):
    if request_id.startswith(("local-create:", "task-create:", "CREATE:")):
        raise CLIError("LEGACY_CREATE_REQUIRES_ORIGINAL_WEB_JOURNAL", 5)
    state = _existing_directory(config["state_dir"])
    journal_path = state / "client.sqlite3"
    private_read(journal_path, max_bytes=64_000_000)
    # URI mode=ro never initializes a missing journal or changes its schema/state.
    with sqlite3.connect(journal_path.as_uri() + "?mode=ro", uri=True) as db:
        if "/" in request_id:
            namespace, key = request_id.rsplit("/", 1)
            rows = db.execute("SELECT kind,key,digest,payload,state,result FROM intents WHERE kind=? AND key=?", (namespace, key)).fetchall()
        else:
            rows = db.execute("SELECT kind,key,digest,payload,state,result FROM intents WHERE key=?", (request_id,)).fetchall()
    rows = [row for row in rows if row[0].startswith(("session-task:", "task-bind:", "task-collaboration:"))]
    if len(rows) != 1:
        raise CLIError("LEGACY_REQUEST_NOT_FOUND" if not rows else "LEGACY_EXPLICIT_NAMESPACE_REQUIRED", 5)
    namespace, key, checksum, compact, status, result = rows[0]
    compact = json.loads(compact)
    frozen_file = state / "local-sync" / "approved-snapshots" / (digest([namespace, key]) + ".json")
    frozen = _json(frozen_file) if frozen_file.exists() else None
    if frozen:
        if (frozen.get("namespace") != namespace or frozen.get("key") != key
                or frozen.get("request_digest") != digest(frozen.get("payload"))
                or checksum != frozen["request_digest"]
                or any(frozen["target"].get(field) != compact.get(field) for field in ("project_id", "provider", "session_id"))):
            raise CLIError("LEGACY_FROZEN_REQUEST_CORRUPT", 5)
    elif compact.get("snapshot_schema"):
        raise CLIError("LEGACY_ORIGINAL_APPROVED_SNAPSHOT_REQUIRED", 5)
    return state, namespace, key, compact, frozen, status, json.loads(result) if result else None


def _receipt(receipt, namespace, key, target, frozen, previous):
    try:
        for field in ("task_id", "project_id"):
            if str(UUID(receipt[field])) != receipt[field]:
                raise ValueError
    except (KeyError, ValueError, TypeError):
        raise CLIError("LEGACY_RECEIPT_MISMATCH", 4) from None
    expected = frozen["expected_version"] if frozen else target.get("expected_version")
    profile = COLLAB_PROFILE if namespace.startswith("task-collaboration:") else SYNC_PROFILE
    if (receipt.get("status") != "ACCEPTED" or receipt.get("profile") != profile
            or receipt.get("idempotency_key") != key or type(receipt.get("version")) is not int
            or receipt["version"] < 1 or (expected is not None and receipt["version"] != expected + 1)
            or any(receipt.get(field) != target[field] for field in ("project_id", "provider", "session_id", "task_id") if target.get(field))
            or (previous and previous.get("task_id") != receipt.get("task_id"))):
        raise CLIError("LEGACY_RECEIPT_MISMATCH", 4)
    if namespace.startswith("session-task:") and receipt.get("source") != "AGENT_REPORTED":
        raise CLIError("LEGACY_RECEIPT_MISMATCH", 4)
    if namespace.startswith("task-bind:") and (receipt.get("operation") != "BIND" or receipt.get("binding_state") != "BOUND"
            or receipt.get("source") is not None):
        raise CLIError("LEGACY_RECEIPT_MISMATCH", 4)
    if namespace.startswith("task-collaboration:"):
        if not frozen:
            raise CLIError("LEGACY_ORIGINAL_APPROVED_SNAPSHOT_REQUIRED", 5)
        wire = {k: v for k, v in frozen["payload"].items() if k != "task_id"}
        if receipt.get("operation") != wire.get("operation") or receipt.get("request_digest") != digest(wire):
            raise CLIError("LEGACY_RECEIPT_MISMATCH", 4)


def _pages(api, path, query, receipt):
    offset, total, parts = 0, None, []
    while True:
        page = api.get(path, {**query, "version": receipt["version"], "offset": offset, "limit": 24000})
        content = page.get("content")
        count = page.get("total_chars")
        if (page.get("task_id") != receipt["task_id"] or page.get("version") != receipt["version"]
                or page.get("offset") != offset or not isinstance(content, str) or not 0 < len(content) <= 24000
                or type(count) is not int or count > 16 * 1024 * 1024 or count < offset + len(content)
                or (total is not None and total != count) or page.get("format") != "application/json"
                or page.get("complete") is not (offset + len(content) == count)
                or page.get("next_offset") != (None if offset + len(content) == count else offset + len(content))):
            raise CLIError("LEGACY_FIXED_READBACK_MISMATCH", 4)
        if ((receipt["profile"] == COLLAB_PROFILE and page.get("profile") != COLLAB_PROFILE)
                or (receipt["profile"] == SYNC_PROFILE and page.get("source") != receipt.get("source"))):
            raise CLIError("LEGACY_FIXED_READBACK_MISMATCH", 4)
        total = count
        parts.append(content)
        if page["complete"]:
            break
        offset = page["next_offset"]
    document = json.loads("".join(parts))
    task = document.get("task", {})
    if task.get("id") != receipt["task_id"] or task.get("project_id") != receipt["project_id"] or task.get("version") != receipt["version"]:
        raise CLIError("LEGACY_READBACK_IDENTITY_MISMATCH", 4)
    return document


def _validate_document(document, namespace, receipt, payload, target):
    task = document["task"]
    if namespace.startswith("task-collaboration:"):
        wire = {k: v for k, v in payload.items() if k != "task_id"}
        operation = next((row for row in document.get("operation_history", [])
            if row.get("response", {}).get("idempotency_key") == receipt["idempotency_key"]), None)
        if operation is None or operation.get("request_payload") != wire or operation.get("response") != receipt:
            raise CLIError("LEGACY_COLLABORATION_READBACK_MISMATCH", 4)
        collaboration = document.get("collaboration", {})
        participant = next((row for row in collaboration.get("participants", []) if row.get("id") == receipt.get("participant_id")), {})
        if (document.get("profile") != COLLAB_PROFILE or collaboration.get("enabled") is not True
                or participant.get("actor_ref") != receipt.get("actor_ref") or participant.get("status") != "ACTIVE"
                or any(participant.get(field) != target.get(field) for field in ("provider", "session_id"))):
            raise CLIError("LEGACY_COLLABORATION_READBACK_MISMATCH", 4)
        if wire["operation"] == "CONTRIBUTE":
            refs = receipt.get("contribution_refs", [])
            if len(refs) != len(wire["contributions"]):
                raise CLIError("LEGACY_CONTRIBUTION_READBACK_MISMATCH", 4)
            for submitted, ref in zip(wire["contributions"], refs, strict=True):
                found = next((row for row in collaboration.get("contributions", []) if row.get("id") == ref.get("contribution_id")), {})
                if (found.get("revision") != ref.get("revision") or ref["revision"] != submitted["expected_revision"] + 1
                        or found.get("participant_id") != receipt["participant_id"]
                        or any(found.get(k) != submitted[k] for k in ("kind", "stable_key", "content"))):
                    raise CLIError("LEGACY_CONTRIBUTION_READBACK_MISMATCH", 4)
        if wire["operation"] == "PUBLISH":
            found = next((row for row in collaboration.get("publications", []) if row.get("task_version") == receipt["version"]
                and row.get("participant_id") == receipt["participant_id"]), {})
            if (found.get("summary") != wire["summary"] or found.get("primary_generation") != wire["primary_generation"]
                    or any(task.get(k) != wire["summary"][k] for k in ("title", "objective", "status", "plan_markdown", "reported_result"))):
                raise CLIError("LEGACY_PUBLICATION_READBACK_MISMATCH", 4)
        return
    if not isinstance(document.get("cases"), list) or not isinstance(document.get("reports"), list):
        raise CLIError("LEGACY_READBACK_ASSETS_INVALID", 4)
    if namespace.startswith("session-task:") and task.get("source") != "AGENT_REPORTED":
        raise CLIError("LEGACY_READBACK_SOURCE_MISMATCH", 4)
    if any(task.get(field) != target.get(field) for field in ("provider", "session_id")):
        raise CLIError("LEGACY_READBACK_SOURCE_MISMATCH", 4)
    if namespace.startswith("task-bind:"):
        if (task.get("binding_state") != "BOUND" or task.get("binding_required") is not True
                or task.get("owner_actor_ref") != receipt.get("actor_ref") or not task.get("bound_at")
                or task.get("source") is not None or task.get("last_synced_at") is not None):
            raise CLIError("LEGACY_BIND_READBACK_MISMATCH", 4)
    elif payload:
        for field in ("title", "objective", "status", "plan_markdown", "reported_result"):
            if task.get(field) != payload.get(field):
                raise CLIError("LEGACY_ORIGINAL_CONTENT_MISMATCH", 4)
        for group in ("cases", "reports"):
            actual = {row["key"]: row for row in document.get(group, [])}
            for row in payload.get(group, []):
                if row["key"] not in actual or any(actual[row["key"]].get(k) != v for k, v in row.items()):
                    raise CLIError("LEGACY_ORIGINAL_CONTENT_MISMATCH", 4)


def reconcile(config: str, request_id: str):
    """Resolve one existing request using only original-key GET and fixed GET pages."""
    config = _json(config)
    state, namespace, key, compact, frozen, status, previous = _record(config, request_id)
    if status == "PENDING":
        return {"status": "PENDING", "code": "LEGACY_ORIGINAL_REQUEST_NOT_SENT", "request_id": request_id,
                "readback_complete": False, "replay_allowed": False}, 4
    target = frozen["target"] if frozen else compact
    api = ReadOnlyAPI(config)
    query = {"project_id": target["project_id"], "idempotency_key": key}
    collaboration = namespace.startswith("task-collaboration:")
    if collaboration:
        base = "interactive/tasks/" + target["task_id"] + "/collaboration"
        query.update({field: target[field] for field in ("provider", "session_id")})
        lookup = base + "/receipts/by-key"
    elif namespace.startswith("task-bind:"):
        lookup, base = "interactive/tasks/bindings/by-key", None
    else:
        lookup, base = "interactive/tasks/syncs/by-key", None
    receipt = api.get(lookup, query)
    _receipt(receipt, namespace, key, target, frozen, previous)
    if not collaboration:
        base = "interactive/tasks/" + receipt["task_id"]
    read_query = {"project_id": target["project_id"]}
    if collaboration:
        read_query.update({field: target[field] for field in ("provider", "session_id")})
    document = _pages(api, base, read_query, receipt)
    _validate_document(document, namespace, receipt, frozen["payload"] if frozen else None, target)
    # New recovery evidence is separate; the original journal/receipt stays intact.
    destination = private_directory(state / "legacy-readbacks")
    verified = frozen is not None
    record = {"namespace": namespace, "key": key, "receipt": receipt, "document": document,
        "original_request_verified": verified, "readback_complete": True}
    filename = destination / (digest([namespace, key, receipt["version"]]) + ".json")
    encoded = canonical_json(record).encode()
    if filename.exists():
        if private_read(filename, max_bytes=32 * 1024 * 1024) != encoded:
            raise CLIError("LEGACY_RECOVERY_RECORD_CONFLICT", 4)
    else:
        private_create(filename, encoded)
    return {"status": "LEGACY_RECOVERED" if verified else "LEGACY_ACCEPTED_READBACK", "request_id": request_id,
        "task_id": receipt["task_id"], "project_id": receipt["project_id"], "accepted_version": receipt["version"],
        "readback_complete": True, "original_request_verified": verified, "replay_allowed": False,
        "code": None if verified else "ORIGINAL_REQUEST_COMPARISON_UNAVAILABLE_LEGACY_COMPACT"}, 0
