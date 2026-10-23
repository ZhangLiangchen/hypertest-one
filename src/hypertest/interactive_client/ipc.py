"""Private bounded UDS RPC, separate from the managed Harness control socket."""
from __future__ import annotations

import asyncio
import fcntl
import hmac
import json
import os
import secrets
import stat
from pathlib import Path

from hypertest.interactive_client import MAX_MESSAGE, PROFILE
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import peer_pid, peer_uid, private_create, private_read


class LocalServer:
    def __init__(self, config, service):
        self.config, self.service = config, service
        self.server = None
        self._lock = asyncio.Lock()
        self._lock_fd = None

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
            async with self._lock:
                if request["operation"] == "list":
                    value = {"tools": await self.service.tools()}
                    if hasattr(self.service, "local_capabilities"):
                        value["local_capabilities"] = self.service.local_capabilities
                elif request["operation"] == "call":
                    payload = request["payload"]
                    if set(payload) != {"name", "arguments"}:
                        raise ClientError("LOCAL_REQUEST_REJECTED")
                    value = await self.service.call(payload["name"], payload["arguments"], peer_pid=pid)
                elif request["operation"] == "local-hook":
                    value = await self.service.local_hook(request["payload"])
                elif request["operation"] == "local-manifest":
                    value = await self.service.local_manifest(request["payload"])
                elif request["operation"] == "local-source":
                    value = await self.service.local_source(request["payload"])
                else:
                    raise ClientError("LOCAL_OPERATION_UNSUPPORTED")
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

    async def exchange(self, operation: str, payload: dict) -> dict:
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
                writer.write(raw)
                await writer.drain()
                response = await asyncio.wait_for(reader.readline(), 120)
                if len(response) > MAX_MESSAGE:
                    raise ClientError("LOCAL_RESPONSE_TOO_LARGE")
                result = json.loads(response)
                if not result.get("ok"):
                    raise ClientError(result.get("error", "LOCAL_REQUEST_REJECTED"))
                return result["result"]
            finally:
                writer.close()
                await writer.wait_closed()
        except (OSError, ValueError, TimeoutError) as exc:
            raise ClientError("LOCAL_CONNECTOR_UNAVAILABLE") from exc
