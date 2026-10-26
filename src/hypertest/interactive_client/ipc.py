"""Private bounded UDS RPC, separate from the managed Harness control socket."""
from __future__ import annotations

import asyncio
import fcntl
import hmac
import json
import os
import secrets
import signal
import stat
from contextlib import asynccontextmanager
from pathlib import Path

from hypertest.interactive_client import MAX_MESSAGE, PROFILE
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import peer_pid, peer_uid, private_create, private_read


class LocalServer:
    def __init__(self, config, service, *, stopping=None):
        from hypertest.interactive_client.runtime import runtime_identity
        self.config, self.service = config, service
        self.runtime = runtime_identity(config)
        self.stopping = stopping
        self.server = None
        self._lock = asyncio.Lock()
        self._lock_fd = None
        self._active_requests = 0
        self._draining = False

    @asynccontextmanager
    async def _request_lock(self, request):
        from hypertest.interactive_client.memory import MEMORY_TOOLS
        payload = request.get("payload")
        if (request.get("operation") == "call" and isinstance(payload, dict)
                and payload.get("name") in MEMORY_TOOLS):
            # Memory has its own atomic durable claims. A slow optional query
            # must never hold the task coordinator's transport serial slot.
            yield
        else:
            async with self._lock:
                yield

    async def start(self):
        path = self.config.socket_path
        lock_fd = os.open(self.config.state_dir / "daemon.lock",
                          os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
            os.close(lock_fd)
            raise ClientError("PRIVATE_FILE_REQUIRED")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(lock_fd)
            raise ClientError("LOCAL_CONNECTOR_ALREADY_RUNNING") from exc
        self._lock_fd = lock_fd
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                os.close(lock_fd)
                self._lock_fd = None
                raise ClientError("LOCAL_SOCKET_REJECTED")
            # Exclusive process lock proves that no other current daemon owns
            # this private socket. A killed predecessor may leave its inode.
            path.unlink()
        token_path = self.config.local_token_file
        if not token_path.exists():
            private_create(token_path, secrets.token_urlsafe(48).encode())
        self.token = private_read(token_path).decode()
        self.server = await asyncio.start_unix_server(self._handle, path=path, limit=MAX_MESSAGE + 1)
        os.chmod(path, 0o600)

    async def _handle(self, reader, writer):
        result = {"ok": False, "error": "LOCAL_REQUEST_REJECTED"}
        stop_after_reply = False
        try:
            stream = writer.get_extra_info("socket")
            if peer_uid(stream) != os.getuid():
                raise ClientError("LOCAL_PEER_REJECTED")
            pid = peer_pid(stream)
            raw = await asyncio.wait_for(reader.readline(), 15)
            if not raw:
                result = None
                return
            if len(raw) > MAX_MESSAGE or not raw.endswith(b"\n"):
                raise ClientError("LOCAL_MESSAGE_TOO_LARGE")
            request = json.loads(raw)
            if (set(request) != {"profile", "token", "operation", "payload"}
                    or request["profile"] != PROFILE
                    or not isinstance(request["token"], str)
                    or not hmac.compare_digest(request["token"], self.token)):
                raise ClientError("LOCAL_AUTHORIZATION_REJECTED")
            if request["operation"] == "runtime-info":
                result = {"ok": True, "result": {"runtime": self.runtime,
                    "pid": os.getpid(), "state": "DRAINING" if self._draining else "READY"}}
                return
            if request["operation"] == "runtime-stop":
                if self.stopping is None:
                    raise ClientError("LOCAL_RUNTIME_STOP_UNAVAILABLE")
                if self._active_requests:
                    raise ClientError("LOCAL_RUNTIME_BUSY")
                self._draining = True
                stop_after_reply = True
                result = {"ok": True, "result": {"state": "STOPPING"}}
                return
            if self._draining:
                raise ClientError("LOCAL_RUNTIME_DRAINING")
            self._active_requests += 1
            try:
                value = await self._dispatch(request, pid)
            finally:
                self._active_requests -= 1
            result = {"ok": True, "result": value}
        except ClientError as exc:
            result = {"ok": False, "error": exc.code}
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            pass
        finally:
            try:
                if result is not None:
                    raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
                    if len(raw) > MAX_MESSAGE:
                        raw = b'{"ok":false,"error":"LOCAL_RESPONSE_TOO_LARGE"}\n'
                    writer.write(raw)
                    await writer.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass
                if stop_after_reply:
                    self.stopping.set()

    async def _dispatch(self, request, pid):
        async with self._request_lock(request):
            if request["operation"] == "list":
                value = {"tools": await self.service.tools()}
                if hasattr(self.service, "local_capabilities"):
                    value["local_capabilities"] = self.service.local_capabilities
            elif request["operation"] == "call":
                payload = request["payload"]
                if set(payload) not in ({"name", "arguments"}, {"name", "arguments", "native_caller_context"}):
                    raise ClientError("LOCAL_REQUEST_REJECTED")
                if "native_caller_context" in payload:
                    value = await self.service.call(payload["name"], payload["arguments"], peer_pid=pid,
                                                   native_caller_context=payload["native_caller_context"])
                else:
                    value = await self.service.call(payload["name"], payload["arguments"], peer_pid=pid)
            elif request["operation"] == "local-hook":
                value = await self.service.local_hook(request["payload"])
            elif request["operation"] == "local-manifest":
                value = await self.service.local_manifest(request["payload"])
            elif request["operation"] == "local-source":
                value = await self.service.local_source(request["payload"])
            else:
                raise ClientError("LOCAL_OPERATION_UNSUPPORTED")
            return value

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.config.socket_path.unlink(missing_ok=True)
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None


class LocalClient:
    def __init__(self, socket_path: Path, token_file: Path):
        self.socket_path, self.token_file = socket_path, token_file

    async def exchange(self, operation: str, payload: dict, *, _legacy_stop=False) -> dict:
        try:
            info = self.socket_path.lstat()
        except OSError as exc:
            raise ClientError("LOCAL_CONNECTOR_UNAVAILABLE") from exc
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ClientError("LOCAL_SOCKET_REJECTED")
        token = private_read(self.token_file).decode()
        request = {"profile": PROFILE, "token": token, "operation": operation, "payload": payload}
        raw = json.dumps(request, separators=(",", ":")).encode() + b"\n"
        if len(raw) > MAX_MESSAGE:
            raise ClientError("LOCAL_MESSAGE_TOO_LARGE")
        try:
            reader, writer = await asyncio.open_unix_connection(self.socket_path, limit=MAX_MESSAGE + 1)
            try:
                stream = writer.get_extra_info("socket")
                if peer_uid(stream) != os.getuid():
                    raise ClientError("LOCAL_PEER_REJECTED")
                pid = peer_pid(stream) if _legacy_stop else None
                writer.write(raw)
                await writer.drain()
                response = await asyncio.wait_for(reader.readline(), 120)
                if len(response) > MAX_MESSAGE:
                    raise ClientError("LOCAL_RESPONSE_TOO_LARGE")
                result = json.loads(response)
                if not result.get("ok"):
                    if _legacy_stop and result.get("error") == "LOCAL_OPERATION_UNSUPPORTED":
                        # A legacy daemon has authenticated this same private
                        # connection before returning its unsupported reply.
                        # Use its existing SIGTERM shutdown, never a saved PID
                        # file, process-name search or unauthenticated socket.
                        os.kill(pid, signal.SIGTERM)
                        return {"state": "STOPPING", "legacy": True}
                    raise ClientError(result.get("error", "LOCAL_REQUEST_REJECTED"))
                return result["result"]
            finally:
                writer.close()
                await writer.wait_closed()
        except (OSError, ValueError, TimeoutError) as exc:
            raise ClientError("LOCAL_CONNECTOR_UNAVAILABLE") from exc

    async def stop(self) -> dict:
        return await self.exchange("runtime-stop", {}, _legacy_stop=True)
