"""Forced-command SSH control helper; only fixed no-argument diagnostic scripts.

This module imports no API, database, model runtime or SDK. The dedicated SSH
account needs its own provisioned systemd user manager and private state root.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

from .ssh_profile import (
    SSH_OBSERVATION,
    blocked,
    canonical_bytes,
    digest,
    exact,
    project_observation,
    unit_name,
    validate_profile,
    validate_request,
)
from .ssh_tickets import verify_ticket

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _read(path: Path, limit: int, *, immutable=False) -> bytes:
    if path.absolute() != path or path.resolve(strict=True) != path:
        raise blocked("SSH_REMOTE_PATH_UNSAFE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit
                or before.st_uid not in {0, os.geteuid()} or before.st_mode & (0o222 if immutable else 0o077)):
            raise blocked("SSH_REMOTE_PATH_UNSAFE")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (len(raw) > limit or len(raw) != before.st_size
                or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise blocked("SSH_REMOTE_PATH_UNSAFE")
        return raw


def _write(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _private_directory(path: Path, *, create=False):
    if create:
        path.mkdir(mode=0o700)
    info = path.lstat()
    if (not path.is_absolute() or path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise blocked("SSH_REMOTE_STATE_UNSAFE")


def helper_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _scope_path(group: object, operation_id: str, uid: int) -> bool:
    import re
    return (isinstance(group, str) and len(group) <= 4096
        and re.fullmatch(r"/[A-Za-z0-9_.@:/-]+", group) is not None
        and group.startswith(f"/user.slice/user-{uid}.slice/")
        and str(Path(group)) == group and ".." not in Path(group).parts
        and Path(group).name == unit_name(operation_id))


def _execution_identity(request: dict, invocation: str, *, boot_id: str,
                        cgroup_text: str, uid: int) -> dict:
    lines = cgroup_text.splitlines()
    if len(lines) != 1 or not lines[0].startswith("0::"):
        raise blocked("SSH_REMOTE_SCOPE_UNAVAILABLE")
    group = lines[0][3:]
    if not _scope_path(group, request["operation_id"], uid):
        raise blocked("SSH_REMOTE_SCOPE_UNAVAILABLE")
    return {"request_digest": digest(request), "boot_id": boot_id, "invocation_id": invocation,
            "unit": unit_name(request["operation_id"]), "uid": uid, "control_group": group}


def _trusted_unit_wrapper(path: Path) -> Path:
    import re
    default = Path("/opt/hypertest-ssh/bin/unit")
    if path != default and re.fullmatch(r"/opt/hypertest-ssh/versions/[a-z0-9][a-z0-9.-]{0,31}/bin/unit", str(path)) is None:
        raise blocked("SSH_REMOTE_WRAPPER_UNTRUSTED")
    if path.resolve(strict=True) != path:
        raise blocked("SSH_REMOTE_WRAPPER_UNTRUSTED")
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise blocked("SSH_REMOTE_WRAPPER_UNTRUSTED")
    info = path.lstat()
    if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
        raise blocked("SSH_REMOTE_WRAPPER_UNTRUSTED")
    _read(path, 8192, immutable=True)
    return path


class SystemdUserManager:
    """No sudo, system manager access, unit collection or general manager API."""
    def __init__(self, *, runtime_directory: Path, catalog_path: Path,
                 unit_wrapper: Path = Path("/opt/hypertest-ssh/bin/unit")):
        runtime = Path("/run/user") / str(os.geteuid())
        if (os.geteuid() == 0 or runtime_directory != runtime or runtime.resolve() != runtime
                or runtime.stat().st_uid != os.geteuid() or not stat.S_ISSOCK((runtime / "bus").stat().st_mode)):
            raise blocked("SSH_REMOTE_MANAGER_UNAVAILABLE")
        self.catalog_path = catalog_path
        self.unit_wrapper = _trusted_unit_wrapper(unit_wrapper)
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
            "XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(runtime / "bus")}

    def _run(self, command: list[str], *, timeout=5, allowed_status=(0,)) -> bytes:
        with subprocess.Popen(command, env=self.environment, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            try:
                output = bytearray()
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                until = time.monotonic() + timeout
                while selector.get_map():
                    if time.monotonic() >= until:
                        raise blocked("SSH_REMOTE_MANAGER_UNAVAILABLE")
                    for key, _ in selector.select(0.1):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        output.extend(chunk)
                        if len(output) > 65536:
                            raise blocked("SSH_REMOTE_MANAGER_UNAVAILABLE")
                process.wait(timeout=max(0.1, until - time.monotonic()))
                if process.returncode not in allowed_status:
                    raise blocked("SSH_REMOTE_MANAGER_UNAVAILABLE")
                return bytes(output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)

    def start(self, request: dict, operation_root: Path, *, lifetime: int):
        command = ["/usr/bin/systemd-run", "--user", "--quiet", "--unit=" + unit_name(request["operation_id"])]
        # RemainAfterExit keeps a successful unit available until QUERY seals its
        # identity and empty cgroup. Never use --collect or infer a missing unit.
        properties = {"Type": "exec", "RemainAfterExit": "yes", "Restart": "no",
            "Description": "hypertest-ssh:" + digest(request),
            "RuntimeMaxSec": str(lifetime), "TimeoutStartSec": "5", "TimeoutStopSec": "2",
            "KillMode": "control-group", "SendSIGKILL": "yes", "NoNewPrivileges": "yes",
            "UMask": "0077", "MemoryMax": "128M", "MemorySwapMax": "0", "TasksMax": "16",
            "LimitCORE": "0", "LimitNOFILE": "64", "LimitFSIZE": "131072"}
        for key, value in properties.items():
            command.extend(["--property=" + key + "=" + value])
        # The readonly wrapper validates/preserves only systemd's invocation
        # identity before clearing every other ambient environment variable.
        _read(self.unit_wrapper, 8192, immutable=True)
        command.extend(["--", str(self.unit_wrapper),
            "--catalog", str(self.catalog_path), "--operation-root", str(operation_root)])
        self._run(command)

    def inspect(self, request: dict) -> dict:
        fields = ["LoadState", "ActiveState", "SubState", "InvocationID", "ControlGroup", "Result", "ExecMainCode", "ExecMainStatus", "Description"]
        raw = self._run(["/usr/bin/systemctl", "--user", "show", unit_name(request["operation_id"]),
                        "--property=" + ",".join(fields)], allowed_status=(0, 1))
        values = dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)
        if set(values) != set(fields):
            raise blocked("SSH_REMOTE_MANAGER_UNAVAILABLE")
        return values

    def empty(self, values: dict, *, allow_removed=False) -> bool:
        group = values.get("OriginalControlGroup", values.get("ControlGroup", ""))
        if not group.startswith("/user.slice/") or ".." in Path(group).parts:
            raise blocked("SSH_REMOTE_MANAGER_UNAVAILABLE")
        path = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.events"
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return allow_removed
        if len(raw) > 4096:
            raise blocked("SSH_REMOTE_MANAGER_UNAVAILABLE")
        fields = dict(line.split() for line in raw.decode().splitlines())
        return fields.get("populated") == "0"

    def stop(self, request: dict):
        self._run(["/usr/bin/systemctl", "--user", "stop", unit_name(request["operation_id"])], timeout=5)


class RemoteController:
    def __init__(self, *, catalog_path: Path, state_root: Path, manager,
                 now=time.time, boot_id=None, script_reader=None):
        environment = json.loads(_read(catalog_path, 32768, immutable=True))
        self.profile = validate_profile(environment)
        if self.profile.helper_sha256 != helper_sha256():
            raise blocked("SSH_REMOTE_HELPER_MISMATCH")
        _private_directory(state_root)
        self.root, self.manager, self.now = state_root, manager, now
        self.script_reader = script_reader or (lambda path: _read(path, 1024 * 1024, immutable=True))
        self.boot_id = boot_id or Path("/proc/sys/kernel/random/boot_id").read_text().strip()

    def exchange(self, envelope: object) -> dict:
        data = exact(envelope, {"request", "ticket"})
        request = validate_request(data["request"], self.profile)
        claims = verify_ticket(data["ticket"], request, self.profile.authority_public_key, now=int(self.now()))
        attempt_root = self.root / ("attempt-" + request["attempt_id"])
        try:
            _private_directory(attempt_root, create=True)
        except FileExistsError:
            _private_directory(attempt_root)
        lock_fd = os.open(attempt_root / "control.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            generations = [int(p.name.removeprefix("generation-")) for p in attempt_root.iterdir()
                           if p.name.startswith("generation-") and p.name.removeprefix("generation-").isdigit()]
            maximum = max(generations, default=0)
            if claims["generation"] < maximum:
                raise blocked("SSH_REMOTE_FENCED")
            if claims["generation"] > maximum:
                _write(attempt_root / ("generation-" + str(claims["generation"])), {"generation": claims["generation"]})
            operation_root = attempt_root / request["operation_id"]
            if claims["verb"] == "START":
                if operation_root.exists():
                    # Even a previously interrupted registration can never start
                    # through a duplicate START. It is query-only recovery.
                    return self._observe(request, operation_root)
                if any(p.is_dir() and not (p / "terminal.json").exists() for p in attempt_root.iterdir()):
                    raise blocked("SSH_REMOTE_PENDING_OPERATION")
                if len([p for p in attempt_root.iterdir() if p.is_dir()]) >= self.profile.max_operations:
                    raise blocked("SSH_REMOTE_OPERATION_LIMIT")
                _private_directory(operation_root, create=True)
                _write(operation_root / "request.json", request)
                _write(operation_root / "registered.json", {"request_digest": digest(request), "boot_id": self.boot_id,
                    "registered_at": int(self.now()), "ticket_expires_at": claims["expires_at"]})
                action = request["action"]
                script = self.script_reader(Path(action["script_path"]))
                if hashlib.sha256(script).hexdigest() != action["script_sha256"]:
                    raise blocked("SSH_REMOTE_SCRIPT_MISMATCH")
                lifetime = min(action["timeout_seconds"], claims["expires_at"] - int(self.now()), request["hard_deadline"] - int(self.now()))
                if lifetime < 1:
                    raise blocked("SSH_TICKET_EXPIRED")
                self.manager.start(request, operation_root, lifetime=lifetime)
            elif not operation_root.exists():
                return self._unknown(request, "NOT_FOUND", state="NOT_FOUND")
            if claims["verb"] == "STOP":
                self._same_request(request, operation_root)
                terminal = operation_root / "terminal.json"
                if terminal.exists():
                    return self._observe(request, operation_root)
                before, reason = self._bound_identity(request, operation_root, self.manager.inspect(request))
                if before is None or "OriginalControlGroup" not in before:
                    return self._unknown(request, reason)
                identity_file = operation_root / "identity.json"
                if identity_file.exists() and json.loads(_read(identity_file, 4096))["invocation_id"] != before["InvocationID"]:
                    return self._unknown(request, "IDENTITY_CHANGED")
                _write(operation_root / "stop-intent.json", {"request_digest": digest(request),
                    "boot_id": self.boot_id, "identity": before}) if not (operation_root / "stop-intent.json").exists() else None
                return self._seal(request, operation_root, before, cancelled=True)
            return self._observe(request, operation_root)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _same_request(self, request, root):
        _private_directory(root)
        stored = json.loads(_read(root / "request.json", 16384))
        registered = json.loads(_read(root / "registered.json", 4096))
        if stored != request or registered["request_digest"] != digest(request) or registered["boot_id"] != self.boot_id:
            raise blocked("SSH_REMOTE_IDENTITY_CHANGED")

    @staticmethod
    def _identity(values):
        import re
        return (values.get("LoadState") == "loaded" and
                re.fullmatch(r"[a-f0-9]{32}", values.get("InvocationID", "")) is not None
                and bool(values.get("ControlGroup")))

    def _bound_identity(self, request, root, values):
        import re
        if (values.get("LoadState") != "loaded"
                or re.fullmatch(r"[a-f0-9]{32}", values.get("InvocationID", "")) is None
                or values.get("Description") != "hypertest-ssh:" + digest(request)):
            return None, "START_UNCONFIRMED"
        scope_file = root / "execution-identity.json"
        if not scope_file.exists():
            # A startup observation may precede the wrapper's durable write.
            # No missing/legacy record can authorize a terminal or STOP claim.
            return (values if self._identity(values) else None), "START_UNCONFIRMED"
        raw = _read(scope_file, 8192)
        scope = exact(json.loads(raw), {"request_digest", "boot_id", "invocation_id", "unit", "uid", "control_group"})
        if (scope["request_digest"] != digest(request) or scope["boot_id"] != self.boot_id
                or scope["invocation_id"] != values["InvocationID"]
                or scope["unit"] != unit_name(request["operation_id"])
                or type(scope["uid"]) is not int or scope["uid"] != os.geteuid()
                or not _scope_path(scope["control_group"], request["operation_id"], scope["uid"])):
            return None, "IDENTITY_CHANGED"
        group = values.get("ControlGroup", "")
        if group and group != scope["control_group"]:
            return None, "IDENTITY_CHANGED"
        if not group and (values.get("ActiveState") not in {"active", "inactive", "failed"}
                          or values.get("SubState") not in {"exited", "dead", "failed"}):
            return None, "START_UNCONFIRMED"
        return dict(values, OriginalControlGroup=scope["control_group"],
                    ExecutionIdentitySHA256=hashlib.sha256(raw).hexdigest()), "START_UNCONFIRMED"

    def _observe(self, request, root):
        self._same_request(request, root)
        terminal = root / "terminal.json"
        if terminal.exists():
            return self._result(request, root, json.loads(_read(terminal, 16384)))
        proof_file = root / "stop-proof.json"
        if proof_file.exists():
            proof = json.loads(_read(proof_file, 16384))
            return self._seal(request, root, proof["before"], cancelled=proof["cancelled"])
        values, reason = self._bound_identity(request, root, self.manager.inspect(request))
        if values is None:
            return self._unknown(request, reason)
        identity_file = root / "identity.json"
        identity = {"boot_id": self.boot_id, "invocation_id": values["InvocationID"],
                    "unit": unit_name(request["operation_id"])}
        if identity_file.exists():
            if json.loads(_read(identity_file, 4096)) != identity:
                return self._unknown(request, "IDENTITY_CHANGED")
        else:
            _write(identity_file, identity)
        if values["SubState"] in {"exited", "dead", "failed"}:
            if "OriginalControlGroup" not in values:
                return self._unknown(request, "START_UNCONFIRMED")
            if self.manager.empty(values, allow_removed=True):
                return self._seal(request, root, values)
        observed = self._base(request, "RUNNING", "ACTIVE")
        observed["remote_identity"] = identity
        return self._result(request, root, observed)

    def _base(self, request, state, reason):
        empty = {"byte_count": 0, "sha256": EMPTY_SHA256, "truncated": False}
        return {"profile": SSH_OBSERVATION, "operation_id": request["operation_id"],
            "request_digest": digest(request), "target": request["target"], "state": state,
            "remote_identity": {"boot_id": None, "unit": unit_name(request["operation_id"]), "invocation_id": None},
            "remote_started_at": None, "remote_finished_at": None, "exit_code": None, "signal": None,
            "remote_stopped": False, "stdout": empty, "stderr": dict(empty), "reason": reason}

    def _unknown(self, request, reason, state="UNKNOWN"):
        observed = self._base(request, state, reason)
        return {"observation": project_observation(observed, request), "stdout_base64": "", "stderr_base64": ""}

    def _confirm_stop(self, request, root, before, *, cancelled):
        proof_file = root / "stop-proof.json"
        if proof_file.exists():
            proof = json.loads(_read(proof_file, 16384))
            return (proof.get("request_digest") == digest(request) and proof.get("boot_id") == self.boot_id
                and proof.get("before") == before and proof.get("cancelled") is cancelled
                and proof.get("stop_job_ack") is True and proof.get("cgroup_empty") is True
                and proof.get("post_state") in {"inactive", "failed", "not-found"})
        self.manager.stop(request)
        after = self.manager.inspect(request)
        if after.get("LoadState") == "not-found":
            post_state = "not-found"
        elif (after.get("LoadState") == "loaded" and after.get("ActiveState") in {"inactive", "failed"}
                and after.get("InvocationID") in {"", before["InvocationID"]}
                and after.get("ControlGroup") in {"", before.get("OriginalControlGroup", before["ControlGroup"])}):
            post_state = after["ActiveState"]
        else:
            return False
        if not self.manager.empty(before, allow_removed=True):
            return False
        _write(proof_file, {"request_digest": digest(request), "boot_id": self.boot_id,
            "before": before, "cancelled": cancelled, "stop_job_ack": True,
            "cgroup_empty": True, "post_state": post_state})
        return True

    def _seal(self, request, root, values, *, cancelled=False):
        # A normal success requires the separately durable command exit record.
        # Missing/GC'ed units alone are never completion evidence.
        result_file = root / "command-result.json"
        result = json.loads(_read(result_file, 4096)) if result_file.exists() else None
        if not cancelled and result is None:
            return self._unknown(request, "START_UNCONFIRMED")
        if result is not None and (result.get("request_digest") != digest(request)
                or result.get("invocation_id") != values["InvocationID"] or result.get("boot_id") != self.boot_id):
            return self._unknown(request, "IDENTITY_CHANGED")
        try:
            if not self._confirm_stop(request, root, values, cancelled=cancelled):
                return self._unknown(request, "START_UNCONFIRMED")
        except Exception:
            return self._unknown(request, "MANAGER_UNAVAILABLE")
        result = json.loads(_read(result_file, 4096)) if result_file.exists() else result
        if result is not None and (result.get("request_digest") != digest(request)
                or result.get("invocation_id") != values["InvocationID"] or result.get("boot_id") != self.boot_id):
            return self._unknown(request, "IDENTITY_CHANGED")
        state = "CANCELLED" if cancelled else ("COMPLETED" if result["exit_code"] == 0 and values["Result"] == "success" else "FAILED")
        observed = self._base(request, state, "STOP_OBSERVED" if cancelled else "EXIT_OBSERVED")
        observed.update(remote_identity={"boot_id": self.boot_id, "unit": unit_name(request["operation_id"]),
            "invocation_id": values["InvocationID"]}, remote_stopped=True,
            remote_started_at=result.get("started_at") if result else None,
            remote_finished_at=int(self.now()), exit_code=result.get("exit_code") if result else None,
            signal=result.get("signal") if result else None)
        for name in ("stdout", "stderr"):
            raw = _read(root / (name + ".raw"), request["action"][name + "_limit_bytes"]) if (root / (name + ".raw")).exists() else b""
            observed[name] = {"byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                              "truncated": result is None or bool(result.get("output_limit"))}
        if result and result.get("output_limit"):
            observed.update(state="FAILED", reason="OUTPUT_LIMIT")
        observed = project_observation(observed, request)
        _write(root / "terminal.json", observed)
        return self._result(request, root, observed)

    def _result(self, request, root, observation):
        observed = project_observation(observation, request)
        result = {"observation": observed}
        for name in ("stdout", "stderr"):
            raw = _read(root / (name + ".raw"), request["action"][name + "_limit_bytes"]) if observed["remote_stopped"] and observed[name]["byte_count"] else b""
            if len(raw) != observed[name]["byte_count"] or hashlib.sha256(raw).hexdigest() != observed[name]["sha256"]:
                raise blocked("SSH_REMOTE_OUTPUT_CHANGED")
            result[name + "_base64"] = base64.b64encode(raw).decode()
        return result


def run_unit(operation_root: Path, catalog_path: Path) -> int:
    """Capture one script. Only the outside controller can attest cgroup stop."""
    import re
    invocation = os.environ.get("INVOCATION_ID")
    if not isinstance(invocation, str) or re.fullmatch(r"[a-f0-9]{32}", invocation) is None or os.geteuid() == 0:
        raise blocked("SSH_REMOTE_INVOCATION_UNAVAILABLE")
    _private_directory(operation_root)
    profile = validate_profile(json.loads(_read(catalog_path, 32768, immutable=True)))
    request = validate_request(json.loads(_read(operation_root / "request.json", 16384)), profile)
    action = request["action"]
    raw = _read(Path(action["script_path"]), 1024 * 1024, immutable=True)
    if hashlib.sha256(raw).hexdigest() != action["script_sha256"]:
        raise blocked("SSH_REMOTE_SCRIPT_MISMATCH")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    cgroup_raw = Path("/proc/self/cgroup").read_bytes()
    if len(cgroup_raw) > 8192:
        raise blocked("SSH_REMOTE_SCOPE_UNAVAILABLE")
    scope = _execution_identity(request, invocation, boot_id=boot_id,
        cgroup_text=cgroup_raw.decode("ascii"), uid=os.geteuid())
    # Kernel-observed original scope is durable before any diagnostic process.
    # Never infer or backfill it from a later empty manager ControlGroup.
    _write(operation_root / "execution-identity.json", scope)
    started = int(time.time())
    process = subprocess.Popen([action["script_path"]], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}, cwd="/")
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    limit = False
    until = min(time.monotonic() + action["timeout_seconds"], time.monotonic() + max(0, request["hard_deadline"] - time.time()))
    try:
        while selector.get_map():
            if time.monotonic() >= until:
                raise TimeoutError
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output = streams[key.data]
                ceiling = action[key.data + "_limit_bytes"]
                if len(output) + len(chunk) > ceiling:
                    output.extend(chunk[:ceiling - len(output)])
                    limit = True
                    raise TimeoutError
                output.extend(chunk)
        process.wait(timeout=max(0.1, until - time.monotonic()))
    except (TimeoutError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            stream.close()
    for name, content in streams.items():
        fd = os.open(operation_root / (name + ".raw"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    code = process.returncode
    _write(operation_root / "command-result.json", {"request_digest": digest(request),
        "boot_id": boot_id,
        "invocation_id": invocation, "started_at": started,
        "finished_at": int(time.time()), "exit_code": code if code >= 0 else None,
        "signal": -code if code < 0 else None, "output_limit": limit})
    return code if code >= 0 else 128 - code


def main():
    parser = argparse.ArgumentParser(description="Forced fixed SSH diagnostic control")
    subs = parser.add_subparsers(dest="mode", required=True)
    serve = subs.add_parser("serve")
    serve.add_argument("--catalog", required=True, type=Path)
    serve.add_argument("--state-root", required=True, type=Path)
    serve.add_argument("--runtime-directory", required=True, type=Path)
    serve.add_argument("--unit-wrapper", type=Path, default=Path("/opt/hypertest-ssh/bin/unit"))
    runner = subs.add_parser("run-unit")
    runner.add_argument("--catalog", required=True, type=Path)
    runner.add_argument("--operation-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "run-unit":
            return run_unit(args.operation_root, args.catalog)
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise blocked()
        manager = SystemdUserManager(runtime_directory=args.runtime_directory, catalog_path=args.catalog,
            unit_wrapper=args.unit_wrapper)
        result = RemoteController(catalog_path=args.catalog, state_root=args.state_root, manager=manager).exchange(json.loads(raw))
        sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
        return 0
    except Exception:
        # Never relay paths, manager stderr, key values or arbitrary exception text.
        sys.stdout.write('{"status":"REFUSED","code":"SSH_REMOTE_UNAVAILABLE"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
