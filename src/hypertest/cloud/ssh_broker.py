"""Host-only SSH broker. Canonical SENT admission always precedes network I/O."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Protocol

from .ssh_profile import (
    REMOTE_COMMAND,
    SSH_OBSERVATION,
    SshProfile,
    blocked,
    canonical_bytes,
    digest,
    exact,
    project_observation,
    unit_name,
    uuid_text,
    validate_request,
)
from .ssh_tickets import sign_ticket, signer_public_key

WIRE_LIMIT = 256 * 1024


class SshAuthority(Protocol):
    async def prepare_start(self, key: str, action_key: str) -> dict: ...
    async def get_operation(self, operation_id: str) -> dict: ...
    async def admit_control(self, operation_id: str, verb: str) -> dict: ...
    async def record_observation(self, operation_id: str, observation: dict) -> None: ...
    async def validate_output(self, stdout: bytes, stderr: bytes) -> None: ...
    async def remote_closed(self) -> bool: ...


def _write(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _epoch(value) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str):
        from datetime import datetime
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return int(parsed.timestamp())
    raise blocked("SSH_AUTHORITY_INVALID")


def _binary(path: Path, expected_sha256: str) -> Path:
    try:
        absolute = path.absolute()
        if absolute.resolve(strict=True) != absolute:
            raise ValueError
        fd = os.open(absolute, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                    or info.st_mode & 0o6022 or not os.access(absolute, os.X_OK)
                    or not os.fstatvfs(stream.fileno()).f_flag & os.ST_RDONLY
                    or info.st_size > 32 * 1024 * 1024):
                raise ValueError
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if checksum != expected_sha256:
                raise ValueError
        return absolute
    except (OSError, ValueError):
        raise blocked("SSH_EXECUTABLE_UNTRUSTED") from None


class OpenSSHTransport:
    def __init__(self, *, executable: Path, executable_sha256: str, profile: SshProfile,
                 private_root: Path, ssh_key: bytes):
        self.executable = _binary(executable, executable_sha256)
        self.profile, self.root = profile, private_root
        self.key_file, self.known_hosts = private_root / "identity", private_root / "known_hosts"
        alias = "hypertest-" + digest(profile.target)
        self.alias = alias
        _write(self.key_file, ssh_key)
        _write(self.known_hosts, f"{alias} {profile.host_key}\n[{alias}]:{profile.port} {profile.host_key}\n".encode())

    def argv(self) -> list[str]:
        options = {"BatchMode": "yes", "IdentitiesOnly": "yes", "IdentityAgent": "none",
            "StrictHostKeyChecking": "yes", "UserKnownHostsFile": str(self.known_hosts),
            "GlobalKnownHostsFile": "/dev/null", "HostKeyAlias": self.alias,
            "UpdateHostKeys": "no", "VerifyHostKeyDNS": "no", "ClearAllForwardings": "yes",
            "ForwardAgent": "no", "ForwardX11": "no", "PermitLocalCommand": "no",
            "ProxyCommand": "none", "ProxyJump": "none", "ControlMaster": "no",
            "ControlPath": "none", "ControlPersist": "no", "ConnectionAttempts": "1",
            "ConnectTimeout": "5", "PasswordAuthentication": "no", "KbdInteractiveAuthentication": "no",
            "GSSAPIAuthentication": "no", "HostbasedAuthentication": "no", "LogLevel": "ERROR"}
        command = [str(self.executable), "-F", "none", "-T", "-a", "-x", "-i", str(self.key_file)]
        for key, value in options.items():
            command.extend(["-o", key + "=" + value])
        command.extend(["-p", str(self.profile.port), "-l", self.profile.user,
                        self.profile.host, REMOTE_COMMAND])
        return command

    async def exchange(self, request: dict, ticket: dict, *, timeout: float) -> dict:
        process = await asyncio.create_subprocess_exec(*self.argv(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={"HOME": str(self.root), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            start_new_session=True)

        async def read(stream, limit):
            chunks, size = [], 0
            while chunk := await stream.read(65536):
                size += len(chunk)
                if size > limit:
                    raise blocked("SSH_TRANSPORT_OUTPUT_LIMIT")
                chunks.append(chunk)
            return b"".join(chunks)

        readers = [asyncio.create_task(read(process.stdout, WIRE_LIMIT)),
                   asyncio.create_task(read(process.stderr, 65536))]
        try:
            async with asyncio.timeout(timeout):
                process.stdin.write(canonical_bytes({"request": request, "ticket": ticket}))
                await process.stdin.drain()
                process.stdin.close()
                stdout, _ = await asyncio.gather(*readers)
                await process.wait()
                if process.returncode != 0:
                    raise blocked("SSH_TRANSPORT_UNCONFIRMED")
                return json.loads(stdout)
        finally:
            if process.returncode is None:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except TimeoutError:
                    pass
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)

    def close(self):
        for path in (self.key_file, self.known_hosts):
            path.unlink(missing_ok=True)


class SshBroker:
    def __init__(self, socket_path: Path, *, profile: SshProfile, authority: SshAuthority,
                 ssh_key: bytes, signing_key: bytes, private_root: Path, deadline: int,
                 ssh_executable: Path | None = None, ssh_executable_sha256: str = "", transport=None):
        if signer_public_key(signing_key) != profile.authority_public_key:
            raise blocked("SSH_SIGNER_MISMATCH")
        if signer_public_key(ssh_key) == profile.authority_public_key:
            raise blocked("SSH_KEY_REUSE")
        self.socket_path, self.profile, self.authority = socket_path, profile, authority
        self._ssh_key, self._signing_key = ssh_key, signing_key
        self.private_root, self.deadline = private_root, _epoch(deadline)
        self.executable, self.executable_sha = ssh_executable, ssh_executable_sha256
        self.transport = transport
        self.server = None
        self.closed = False
        self._lock = asyncio.Lock()
        self._handlers = set()
        self._operations: dict[str, dict] = {}
        self._admission_unknown = False
        self._authority_closed = False
        self._closing = False

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.close()

    async def start(self):
        if self.private_root.absolute() != self.private_root or self.private_root.parent.resolve() != self.private_root.parent:
            raise blocked("SSH_PRIVATE_ROOT_UNSAFE")
        self.private_root.mkdir(mode=0o700)
        if os.path.lexists(self.socket_path):
            raise blocked("SSH_LOCAL_RECOVERY_REQUIRED")
        if self.transport is None:
            if self.executable is None:
                raise blocked("SSH_EXECUTABLE_UNTRUSTED")
            self.transport = OpenSSHTransport(executable=self.executable, executable_sha256=self.executable_sha,
                profile=self.profile, private_root=self.private_root, ssh_key=self._ssh_key)
        self._ssh_key = b""
        self.server = await asyncio.start_unix_server(self._handle, path=self.socket_path, limit=8193)
        os.chmod(self.socket_path, 0o600)
        return self

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self._handlers.add(task)
        response = {"status": "REFUSED", "code": "SSH_REQUEST_UNAVAILABLE"}
        try:
            async with asyncio.timeout(40):
                raw = await reader.readline()
                if len(raw) > 8192 or not raw.endswith(b"\n"):
                    raise blocked()
                payload = json.loads(raw)
                if payload.get("verb") == "INVOKE":
                    exact(payload, {"verb", "key", "action_key"})
                    response = await self.invoke(payload["key"], payload["action_key"])
                elif payload.get("verb") == "QUERY":
                    exact(payload, {"verb", "operation_id"})
                    response = await self.query(uuid_text(payload["operation_id"]))
                else:
                    raise blocked()
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.write(canonical_bytes(response) + b"\n")
                await asyncio.wait_for(writer.drain(), 1)
            except (OSError, TimeoutError):
                pass
            writer.close()
            self._handlers.discard(task)

    def _record(self, record: dict) -> dict:
        request = validate_request(record["request"], self.profile)
        if record.get("request_digest") != digest(request) or record.get("id") != request["operation_id"]:
            raise blocked("SSH_AUTHORITY_INVALID")
        if request["hard_deadline"] > self.deadline:
            raise blocked("SSH_AUTHORITY_INVALID")
        self._operations.setdefault(record["id"], {"request": request, "observation": None})
        return request

    async def _exchange(self, record: dict, verb: str) -> dict:
        request = self._record(record)
        now = int(time.time())
        expiry = min(now + 60, _epoch(record["ticket_expires_at"]))
        if verb == "START":
            expiry = min(expiry, request["hard_deadline"])
        ticket = sign_ticket(self._signing_key, request, verb=verb,
            generation=record.get("ticket_generation", record["generation"]), expires_at=expiry, now=now)
        result = exact(await self.transport.exchange(request, ticket, timeout=8),
                       {"observation", "stdout_base64", "stderr_base64"})
        observation = project_observation(result["observation"], request)
        outputs = []
        for name in ("stdout", "stderr"):
            raw = base64.b64decode(result[name + "_base64"], validate=True)
            summary = observation[name]
            if len(raw) != summary["byte_count"] or hashlib.sha256(raw).hexdigest() != summary["sha256"]:
                raise blocked("SSH_OUTPUT_MISMATCH")
            outputs.append(raw)
        await self.authority.record_observation(record["id"], observation)
        self._operations[record["id"]]["observation"] = observation
        await self.authority.validate_output(*outputs)
        return {"status": "OBSERVED", "observation": observation,
                "stdout_base64": result["stdout_base64"], "stderr_base64": result["stderr_base64"]}

    async def _unknown(self, operation_id: str, reason="TRANSPORT_UNKNOWN") -> dict:
        previous = self._operations[operation_id]["observation"]
        if previous and previous["remote_stopped"]:
            return {"status": "REFUSED", "code": "SSH_OUTPUT_UNAVAILABLE", "observation": previous}
        request = self._operations[operation_id]["request"]
        empty = {"byte_count": 0, "sha256": hashlib.sha256(b"").hexdigest(), "truncated": False}
        observed = {"profile": SSH_OBSERVATION, "operation_id": operation_id,
            "request_digest": digest(request), "target": request["target"], "state": "UNKNOWN",
            "remote_identity": {"boot_id": None, "unit": unit_name(operation_id), "invocation_id": None},
            "remote_started_at": None, "remote_finished_at": None, "exit_code": None, "signal": None,
            "remote_stopped": False, "stdout": empty, "stderr": dict(empty), "reason": reason}
        self._operations[operation_id]["observation"] = observed
        try:
            async with asyncio.timeout(2):
                await self.authority.record_observation(operation_id, observed)
        except (Exception, asyncio.CancelledError):
            pass
        return {"status": "UNKNOWN", "observation": observed}

    async def invoke(self, key: str, action_key: str) -> dict:
        import re
        if (not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", key) is None
                or self.closed or self._closing):
            raise blocked("SSH_REQUEST_UNAVAILABLE")
        self.profile.action(action_key)
        async with self._lock:
            if self.closed or self._closing or time.time() >= self.deadline:
                raise blocked("SSH_REQUEST_UNAVAILABLE")
            self._admission_unknown = True
            record = await self.authority.prepare_start(key, action_key)
            request = self._record(record)
            self._admission_unknown = False
            try:
                if record.get("allow_send") is True:
                    result = await self._exchange(record, "START")
                else:
                    result = await self.query(record["id"])
                until = min(self.deadline, time.time() + request["action"]["timeout_seconds"] + 3)
                while result.get("observation", {}).get("state") in {"SENT", "RUNNING", "STOP_REQUESTED"}:
                    if self._closing or time.time() >= until:
                        return await self._unknown(record["id"])
                    await asyncio.sleep(0.25)
                    result = await self.query(record["id"])
                return result
            except asyncio.CancelledError:
                await self._unknown(record["id"])
                raise
            except Exception:
                return await self._unknown(record["id"])

    async def query(self, operation_id: str) -> dict:
        uuid_text(operation_id)
        record = await self.authority.admit_control(operation_id, "QUERY")
        self._record(record)
        try:
            result = await self._exchange(record, "QUERY")
            if result["observation"]["state"] == "NOT_FOUND":
                return await self._unknown(operation_id)
            return result
        except asyncio.CancelledError:
            await self._unknown(operation_id)
            raise
        except Exception:
            return await self._unknown(operation_id)

    async def reconcile_and_stop(self) -> dict:
        for operation_id, item in list(self._operations.items()):
            previous = item["observation"]
            if previous and previous["remote_stopped"]:
                continue
            try:
                record = await self.authority.admit_control(operation_id, "STOP")
                await self._exchange(record, "STOP")
                await self.query(operation_id)
            except asyncio.CancelledError:
                await self._unknown(operation_id, "CONTROL_UNAVAILABLE")
                raise
            except Exception:
                await self._unknown(operation_id, "CONTROL_UNAVAILABLE")
        try:
            self._authority_closed = await self.authority.remote_closed() is True
        except Exception:
            self._authority_closed = False
        return self.observation()

    def observation(self) -> dict:
        pending = [key for key, item in self._operations.items()
                   if not item["observation"] or not item["observation"]["remote_stopped"]]
        return {"closed": self.closed, "pending_operations": sorted(pending),
                "remote_closed": self._authority_closed and not pending and not self._admission_unknown,
                "inflight": len(self._handlers),
                "operations": [item["observation"] for item in self._operations.values() if item["observation"]]}

    async def close(self) -> dict:
        if self.closed:
            return self.observation()
        self._closing = True
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in tuple(self._handlers):
            task.cancel()
        if self._handlers:
            try:
                await asyncio.wait_for(asyncio.gather(*tuple(self._handlers), return_exceptions=True), 2)
            except TimeoutError:
                pass
        try:
            async with asyncio.timeout(24):
                await self.reconcile_and_stop()
        except (Exception, asyncio.CancelledError):
            self._authority_closed = False
        finally:
            self.closed = True
            if self.transport and hasattr(self.transport, "close"):
                self.transport.close()
            self._signing_key = b""
            if self.server is not None:
                self.socket_path.unlink(missing_ok=True)
        return self.observation()
