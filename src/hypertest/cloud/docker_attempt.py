"""Single-use Docker Engine control for a fixed Cloud Attempt.

The owning Worker must first verify its Engine/volume/image identities and
persist the exact create intent. This adapter cannot grant admission and is
not wired into the Worker. All mutations refer to the original container only.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import http.client
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from .clock_domain import clock_domain_digest
from .docker_attempt_spec import create_body, verify_envelope, verify_inspect
from .errors import CloudBlocked

_API = "/v1.45"
_ID = re.compile(r"[a-f0-9]{64}\Z")
_HINT = re.compile(r"(?:[a-f0-9]{12}|[a-f0-9]{64})\Z")
_VOLUME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_NAME = re.compile(r"hypertest-attempt-[a-f0-9]{32}-[a-f0-9]{32}\Z")
_MAX_BODY = 4 * 1024 * 1024
_MAX_FRAME = 1024 * 1024 + 4096
_STOP_TIMEOUT = 7.0


def _blocked(code: str) -> CloudBlocked:
    return CloudBlocked(code, "Original Docker Attempt control requires reconciliation")


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost", timeout=3)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class DockerEngine:
    """Bounded Engine requests over the caller-verified private Unix socket."""

    def __init__(self, socket_path: str | Path):
        self.socket_path = os.fspath(socket_path)
        if not os.path.isabs(self.socket_path) or os.path.normpath(self.socket_path) != self.socket_path:
            raise _blocked("DOCKER_ENGINE_UNAVAILABLE")

    async def _exchange(self, method: str, path: str, body: dict | None = None):
        def run():
            conn = _UnixConnection(self.socket_path)
            try:
                encoded = None if body is None else json.dumps(body, separators=(",", ":")).encode()
                conn.request(method, _API + path, body=encoded,
                             headers={"Content-Type": "application/json"} if encoded is not None else {})
                response = conn.getresponse()
                raw = response.read(_MAX_BODY + 1)
                if len(raw) > _MAX_BODY:
                    raise ValueError
                result = json.loads(raw) if raw else {}
                return response.status, result
            finally:
                conn.close()
        try:
            return await asyncio.to_thread(run)
        except (OSError, ValueError, http.client.HTTPException, TimeoutError):
            raise _blocked("DOCKER_ENGINE_UNCONFIRMED") from None

    async def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        if method not in {"GET", "POST"} or not path.startswith("/containers/"):
            raise _blocked("DOCKER_ENGINE_REQUEST_INVALID")
        status, result = await self._exchange(method, path, body)
        if not isinstance(result, dict):
            raise _blocked("DOCKER_ENGINE_UNCONFIRMED")
        return status, result

    async def inspect_container(self, identity: str) -> dict:
        if not isinstance(identity, str) or _HINT.fullmatch(identity) is None:
            raise _blocked("DOCKER_CONTAINER_ID_INVALID")
        status, data = await self.request("GET", "/containers/" + identity + "/json")
        if (status != 200 or not isinstance(data.get("Id"), str) or _ID.fullmatch(data["Id"]) is None
                or not data["Id"].startswith(identity)):
            raise _blocked("DOCKER_INSPECT_UNCONFIRMED")
        return data

    async def inspect_image(self, image_id: str) -> dict:
        if not isinstance(image_id, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", image_id) is None:
            raise _blocked("DOCKER_IMAGE_INVALID")
        status, data = await self._exchange("GET", "/images/" + image_id + "/json")
        if status != 200 or not isinstance(data, dict) or data.get("Id") != image_id:
            raise _blocked("DOCKER_IMAGE_UNCONFIRMED")
        return data

    async def inspect_original_name(self, name: str) -> dict:
        """Recovery lookup only. An absent name does not prove no create."""
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise _blocked("DOCKER_CONTAINER_ID_INVALID")
        status, data = await self.request("GET", "/containers/" + name + "/json")
        if status != 200 or not isinstance(data.get("Id"), str) or _ID.fullmatch(data["Id"]) is None:
            raise _blocked("DOCKER_CREATE_UNCONFIRMED")
        return data

    async def inspect_volume(self, name: str) -> dict:
        if not isinstance(name, str) or _VOLUME.fullmatch(name) is None:
            raise _blocked("DOCKER_VOLUME_INVALID")
        status, data = await self._exchange("GET", "/volumes/" + name)
        if status != 200 or not isinstance(data, dict) or data.get("Name") != name:
            raise _blocked("DOCKER_VOLUME_UNCONFIRMED")
        return data

    async def list_attempts(self) -> list[str]:
        """Enumerate every Engine container carrying the fixed Attempt label."""
        return await self._list_labeled(["hypertest.cloud.attempt_id"])

    async def list_workers(self, project: str, service: str) -> list[str]:
        """Enumerate the configured Compose service; callers inspect every ID."""
        if (not isinstance(project, str) or not isinstance(service, str)
                or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project) is None
                or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", service) is None):
            raise _blocked("DOCKER_MEMBERS_UNCONFIRMED")
        return await self._list_labeled(["com.docker.compose.project=" + project,
                                         "com.docker.compose.service=" + service])

    async def _list_labeled(self, labels: list[str]) -> list[str]:
        query = urlencode({"all": "1", "filters": json.dumps({"label": labels}, separators=(",", ":"))})
        status, data = await self._exchange("GET", "/containers/json?" + query)
        if status != 200 or not isinstance(data, list) or len(data) > 2048:
            raise _blocked("DOCKER_MEMBERS_UNCONFIRMED")
        ids = []
        for item in data:
            identity = item.get("Id") if isinstance(item, dict) else None
            if not isinstance(identity, str) or _ID.fullmatch(identity) is None or identity in ids:
                raise _blocked("DOCKER_MEMBERS_UNCONFIRMED")
            ids.append(identity)
        return ids

    async def attach(self, container_id: str):
        if _ID.fullmatch(container_id) is None:
            raise _blocked("DOCKER_CONTAINER_ID_INVALID")
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(self.socket_path), 3)
            path = _API + "/containers/" + container_id + "/attach?stream=1&stdin=1&stdout=1&stderr=0&logs=0"
            writer.write(("POST " + path + " HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\n"
                          "Upgrade: tcp\r\nContent-Length: 0\r\n\r\n").encode())
            await asyncio.wait_for(writer.drain(), 3)
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
            if len(header) > 16384 or header.split(b"\r\n", 1)[0] not in (b"HTTP/1.1 101 UPGRADED", b"HTTP/1.1 101 Switching Protocols"):
                raise ValueError
            return reader, writer
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            if writer is not None:
                writer.close()
            raise _blocked("DOCKER_ATTACH_UNCONFIRMED") from None


class DockerOriginalObservation:
    """Read-only original-name recovery; never creates, starts, or stops."""

    def __init__(self, *, engine: DockerEngine, receipt: dict):
        try:
            intent = receipt["container_create_intent"]
            spec = copy.deepcopy(intent["spec"])
            create_body(spec)
            scope = spec["scope"]
            if (receipt["status"] != "ACCEPTED" or receipt["operation"] != "PREPARE_CONTAINER_CREATE"
                    or receipt["operation_key"] != intent["operation_key"]
                    or any(receipt[field] != scope[field] or intent[field] != scope[field]
                           for field in ("project_id", "task_id", "attempt_id"))
                    or intent["generation"] != scope["generation"]
                    or intent["container_name"] != spec["container_name"]
                    or intent["image_id"] != spec["image_id"] or intent["spec_sha256"] != spec["spec_sha256"]
                    or intent["key_sha256"] != scope["key_sha256"] or intent["clock_sha256"] != scope["clock_sha256"]
                    or intent["hard_deadline"] != scope["deadline_epoch"]
                    or intent["state"] != "UNCONFIRMED" or intent["container_id"] is not None):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise _blocked("DOCKER_INTENT_MISMATCH") from None
        self.engine, self.spec = engine, spec
        self.container_id = None

    async def inspect_raw(self) -> dict:
        raw = await self.engine.inspect_original_name(self.spec["container_name"])
        identity = raw.get("Id")
        try:
            if self.container_id is not None and self.container_id != identity:
                raise ValueError
            verify_inspect(self.spec, container_id=identity, observed=raw)
        except (TypeError, ValueError):
            raise _blocked("DOCKER_SPEC_MISMATCH") from None
        self.container_id = identity
        return raw

    async def inspect_raw_id(self, container_id: str) -> dict:
        if self.container_id is None or container_id != self.container_id:
            raise _blocked("DOCKER_CONTAINER_ID_INVALID")
        raw = await self.engine.inspect_container(container_id)
        try:
            verify_inspect(self.spec, container_id=container_id, observed=raw)
        except (TypeError, ValueError):
            raise _blocked("DOCKER_SPEC_MISMATCH") from None
        return raw

class DockerAttempt:
    """One intent, one create/start, one original ID; no automatic replay.

    ``intent`` must be the persisted original receipt, ``bind_id`` must durably
    bind this exact Engine ID before start, ``prepare_start`` must persist the
    original start intent, and ``authority_window`` must return
    a DB-verified remaining lease deadline in the shared CLOCK_MONOTONIC domain.
    ``observe_envelope`` must freshly inspect every member in the frozen scope.
    These callbacks are trusted Worker responsibilities, not Agent inputs.
    """

    def __init__(self, *, engine: DockerEngine, spec: dict, intent: dict, key: bytes,
                 bind_id, prepare_start, authority_window, observe_envelope):
        self.engine, self.spec = engine, copy.deepcopy(spec)
        self.bind_id, self.prepare_start = bind_id, prepare_start
        self.authority_window, self.observe_envelope = authority_window, observe_envelope
        self.container_id = None
        self.stdout = asyncio.StreamReader(limit=65536)
        self.returncode = None
        self._writer = None
        self._pump = self._heartbeat = self._waiter = None
        self._used = False
        self._output_ended = False
        self._stop_observation = None
        self._key = key
        create_body(self.spec)  # validate the complete frozen spec, not only its digest
        spec = self.spec
        scope = spec["scope"]
        required = {"project_id": scope["project_id"], "task_id": scope["task_id"],
            "attempt_id": scope["attempt_id"], "generation": scope["generation"],
            "container_name": spec["container_name"], "image_id": spec["image_id"],
            "spec_sha256": spec["spec_sha256"], "key_sha256": scope["key_sha256"],
            "hard_deadline": scope["deadline_epoch"], "state": "UNCONFIRMED", "container_id": None}
        if (not isinstance(intent, dict) or any(intent.get(name) != value for name, value in required.items())
                or not isinstance(intent.get("operation_key"), str) or not intent["operation_key"]
                or not isinstance(key, bytes) or len(key) != 32
                or not hmac.compare_digest(hashlib.sha256(key).hexdigest(), scope["key_sha256"])):
            raise _blocked("DOCKER_INTENT_MISMATCH")

    async def inspect_raw(self):
        """Return only the verified original Engine object to the trusted caller."""
        if self.container_id is None:
            raise _blocked("DOCKER_CREATE_UNCONFIRMED")
        status, data = await self.engine.request("GET", "/containers/" + self.container_id + "/json")
        if status != 200:
            raise _blocked("DOCKER_INSPECT_UNCONFIRMED")
        try:
            verify_inspect(self.spec, container_id=self.container_id, observed=data)
        except ValueError:
            raise _blocked("DOCKER_SPEC_MISMATCH") from None
        return data

    async def _inspect(self):
        return verify_inspect(self.spec, container_id=self.container_id, observed=await self.inspect_raw())

    async def _current(self):
        expiry = await asyncio.wait_for(self.authority_window(), 2)
        now = time.monotonic_ns()
        if type(expiry) is not int or expiry <= now + 1_000_000_000:
            raise _blocked("DOCKER_LEASE_UNCONFIRMED")
        return now, min(expiry, now + 4_000_000_000)

    async def _send_heartbeat(self, sequence):
        issued, expires = await self._current()
        scope = {**self.spec["scope"], "spec_sha256": self.spec["spec_sha256"]}
        signed = {"scope": scope, "kind": "HEARTBEAT", "sequence": sequence,
                  "issued_mono_ns": issued, "lease_until_mono_ns": expires}
        mac = hmac.new(self._key, json.dumps(signed, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        frame = {key: value for key, value in signed.items() if key != "scope"}
        frame["mac"] = mac
        self._writer.write(json.dumps(frame, separators=(",", ":")).encode() + b"\n")
        await asyncio.wait_for(self._writer.drain(), 2)

    async def _heartbeats(self):
        sequence = 1
        try:
            while True:
                await asyncio.sleep(1)
                sequence += 1
                await self._send_heartbeat(sequence)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Closing the original attach channel causes the guard to stop.
            self._writer.close()
            if not self._output_ended:
                self._output_failure("DOCKER_LEASE_UNCONFIRMED")

    def _output_failure(self, code):
        if not self.stdout.at_eof() and self.stdout.exception() is None:
            self.stdout.set_exception(_blocked(code))

    async def _read_output(self, reader):
        total = 0
        in_frame = False
        try:
            while True:
                header = await reader.readexactly(8)
                in_frame = True
                size = int.from_bytes(header[4:], "big")
                if header[:4] != b"\x01\x00\x00\x00" or size > 65536 or total + size > 2 * 1024 * 1024:
                    raise ValueError
                self.stdout.feed_data(await reader.readexactly(size))
                total += size
                in_frame = False
        except asyncio.IncompleteReadError as error:
            if error.partial or in_frame:
                self._output_failure("DOCKER_OUTPUT_UNCONFIRMED")
            else:
                self.stdout.feed_eof()
        except (OSError, ValueError):
            self._output_failure("DOCKER_OUTPUT_UNCONFIRMED")
        finally:
            self._output_ended = True
            if self._heartbeat is not None:
                self._heartbeat.cancel()
            if self._writer is not None:
                self._writer.close()
            self.stdout.feed_eof()

    async def _wait(self):
        try:
            while True:
                observed = await self._inspect()
                if observed["status"] == "exited" and not observed["running"] and observed["pid"] == 0:
                    self.returncode = observed["exit_code"]
                    return self.returncode
                if observed["status"] != "running" or not observed["running"] or observed["pid"] <= 0:
                    raise _blocked("DOCKER_STATE_UNCONFIRMED")
                await asyncio.sleep(0.2)
        except Exception:
            self._writer.close()
            self._output_failure("DOCKER_STATE_UNCONFIRMED")
            raise

    async def start(self, config: dict):
        if self._used:
            raise _blocked("DOCKER_ORIGINAL_OPERATION_QUERY_ONLY")
        self._used = True  # even transport failure must never create again
        if sys.platform != "linux":
            raise _blocked("DOCKER_SHARED_CLOCK_UNAVAILABLE")
        try:
            if not hmac.compare_digest(self.spec["scope"]["clock_sha256"], clock_domain_digest()):
                raise ValueError
        except (ValueError, KeyError):
            raise _blocked("DOCKER_SHARED_CLOCK_UNAVAILABLE") from None
        if not isinstance(config, dict) or config.get("native_delegation") is not None:
            raise _blocked("DOCKER_DELEGATION_UNSUPPORTED")
        frame = json.dumps({"kind": "INIT", "key": base64.b64encode(self._key).decode(), "config": config},
                           separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        if len(frame) > _MAX_FRAME:
            raise _blocked("DOCKER_CONTROL_FRAME_INVALID")
        await self._current()
        verify_envelope(self.spec, await self.observe_envelope())
        status, result = await self.engine.request("POST", "/containers/create?name=" + self.spec["container_name"], create_body(self.spec))
        if status != 201 or not isinstance(result.get("Id"), str) or _ID.fullmatch(result["Id"]) is None:
            raise _blocked("DOCKER_CREATE_UNCONFIRMED")
        self.container_id = result["Id"]
        raw_inspect = await self.inspect_raw()
        observed = verify_inspect(self.spec, container_id=self.container_id, observed=raw_inspect)
        if observed["status"] != "created" or observed["running"] or observed["pid"] != 0:
            raise _blocked("DOCKER_CREATE_UNCONFIRMED")
        await self.bind_id(self.container_id, raw_inspect)
        await self._current()
        verify_envelope(self.spec, await self.observe_envelope())
        reader, self._writer = await self.engine.attach(self.container_id)
        try:
            await self.prepare_start(self.container_id, await self.inspect_raw())
            await self._current()
            status, _ = await self.engine.request("POST", "/containers/" + self.container_id + "/start")
            if status != 204:
                raise _blocked("DOCKER_START_UNCONFIRMED")
            self._writer.write(frame)
            await asyncio.wait_for(self._writer.drain(), 2)
            await self._send_heartbeat(1)
            observed = await self._inspect()
            if observed["status"] != "running" or not observed["running"] or observed["pid"] <= 0:
                raise _blocked("DOCKER_START_UNCONFIRMED")
            self._pump = asyncio.create_task(self._read_output(reader))
            self._heartbeat = asyncio.create_task(self._heartbeats())
            self._waiter = asyncio.create_task(self._wait())
            return self
        except BaseException:
            self._writer.close()
            raise

    async def wait(self):
        if self._waiter is None:
            raise _blocked("DOCKER_START_UNCONFIRMED")
        return await self._waiter

    async def stop(self):
        if self._stop_observation is not None:
            return self._stop_observation
        if self.container_id is None:
            raise _blocked("DOCKER_CREATE_UNCONFIRMED")
        if self._writer is not None:
            self._writer.close()
        if self._heartbeat is not None:
            self._heartbeat.cancel()
            await asyncio.gather(self._heartbeat, return_exceptions=True)
        deadline = time.monotonic() + _STOP_TIMEOUT
        while True:
            observed = await self._inspect()
            if observed["status"] == "exited" and not observed["running"] and observed["pid"] == 0:
                break
            if (observed["status"] != "running" or not observed["running"] or observed["pid"] <= 0
                    or time.monotonic() >= deadline):
                raise _blocked("DOCKER_STOP_UNCONFIRMED")
            await asyncio.sleep(min(0.2, max(0, deadline - time.monotonic())))
        self.returncode = observed["exit_code"]
        # Preserve already emitted output before teardown; EOF has a short bound.
        if self._pump is not None and not self._pump.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._pump), 3)
            except TimeoutError:
                self._pump.cancel()
                self._output_failure("DOCKER_OUTPUT_UNCONFIRMED")
        if self._waiter is not None and not self._waiter.done():
            self._waiter.cancel()
        await asyncio.gather(*(task for task in (self._pump, self._waiter) if task is not None), return_exceptions=True)
        self._stop_observation = {"local_processes_stopped": True, "runtime_started": True,
                                  "isolation": "docker-private-pid-namespace", "engine": observed}
        return self._stop_observation
