"""Host-only public HTTPS broker. Canonical SENT always precedes the one send."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Protocol

from .errors import CloudBlocked
from .http_operations import (
    WIRE_LIMIT,
    HttpOriginals,
    project_response,
    response_document,
    uuid_text,
    validate_request,
)
from .http_profile import HttpProfile, blocked, canonical_bytes, digest, exact
from .http_transport import HttpsTransport


class HttpAuthority(Protocol):
    async def prepare_start(self, key: str, resource_key: str) -> dict: ...
    async def admit_send(self, operation_id: str) -> None: ...
    async def get_operation(self, operation_id: str) -> dict: ...
    async def get_operation_by_key(self, key: str) -> dict: ...
    async def record_response(self, operation_id: str, response: dict) -> dict: ...
    async def validate_output(self, body: bytes) -> None: ...
    async def remote_closed(self) -> bool: ...


class HttpBroker:
    def __init__(self, socket_path: Path, *, profile: HttpProfile, authority: HttpAuthority,
                 private_root: Path, deadline: int, transport=None):
        if type(deadline) is not int or deadline < 1:
            raise blocked("HTTPS_DEADLINE_INVALID")
        self.socket_path, self.profile, self.authority = socket_path, profile, authority
        self.private_root, self.deadline = private_root, deadline
        self.transport = transport or HttpsTransport()
        self.originals = HttpOriginals(private_root)
        self.server = None
        self.closed = self._closing = False
        self._lock = asyncio.Lock()
        self._handlers, self._inflight = set(), set()
        self._operations = {}
        self._admission_unknown = set()
        self._authority_closed = False

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.close()

    async def start(self):
        if (self.socket_path.absolute() != self.socket_path
                or self.socket_path.parent.resolve() != self.socket_path.parent
                or os.path.lexists(self.socket_path)):
            raise blocked("HTTPS_SOCKET_UNSAFE")
        self.server = await asyncio.start_unix_server(self._handle, path=self.socket_path, limit=8193)
        os.chmod(self.socket_path, 0o600)
        return self

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self._handlers.add(task)
        result = {"status": "REFUSED", "code": "HTTPS_REQUEST_UNAVAILABLE"}
        verb = None
        try:
            async with asyncio.timeout(25):
                raw = await reader.readline()
                if len(raw) > 8192 or not raw.endswith(b"\n"):
                    raise blocked()
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise blocked()
                verb = payload.get("verb")
                if verb == "INVOKE":
                    exact(payload, {"verb", "key", "resource_key"})
                    result = await self.invoke(payload["key"], payload["resource_key"])
                elif verb == "QUERY":
                    if set(payload) == {"verb", "operation_id"}:
                        result = await self.query(payload["operation_id"])
                    elif set(payload) == {"verb", "key"}:
                        result = await self.query(key=payload["key"])
                    else:
                        raise blocked()
                else:
                    raise blocked()
        except (Exception, asyncio.CancelledError):
            if verb == "QUERY":
                result = {"status": "UNKNOWN", "code": "HTTPS_ORIGINAL_QUERY_UNAVAILABLE"}
        finally:
            try:
                encoded = canonical_bytes(result) + b"\n"
                if len(encoded) > WIRE_LIMIT:
                    encoded = canonical_bytes({"status": "UNKNOWN", "code": "HTTPS_RESPONSE_LIMIT"}) + b"\n"
                writer.write(encoded)
                await asyncio.wait_for(writer.drain(), 1)
            except (OSError, TimeoutError):
                pass
            writer.close()
            self._handlers.discard(task)

    def _record(self, record):
        if not isinstance(record, dict):
            raise blocked("HTTPS_AUTHORITY_INVALID")
        request = validate_request(record.get("request"), self.profile)
        if (record.get("id") != request["operation_id"] or record.get("request_digest") != digest(request)
                or request["hard_deadline"] > self.deadline
                or record.get("state") not in {"SENT", "UNKNOWN", "OBSERVED"}
                or type(record.get("allow_send", False)) is not bool
                or (record.get("allow_send") and record["state"] != "SENT")):
            raise blocked("HTTPS_AUTHORITY_INVALID")
        existing = self._operations.setdefault(record["id"], {"request": request, "response": None})
        if existing["request"] != request:
            raise blocked("HTTPS_ORIGINAL_TARGET_CHANGED")
        return request

    @staticmethod
    def _metadata(response):
        return {key: value for key, value in response.items() if key != "body_base64"}

    async def _unknown(self, operation_id, reason="TRANSPORT_UNKNOWN"):
        item = self._operations[operation_id]
        if item["response"] and item["response"]["state"] == "OBSERVED":
            # A delivery error cannot rewrite an accepted external observation.
            return {"status": "UNKNOWN", "code": "HTTPS_RESPONSE_NOT_DELIVERED"}
        response = response_document(item["request"], reason=reason)
        item["response"] = response
        try:
            async with asyncio.timeout(2):
                await self.authority.record_response(operation_id, response)
        except (Exception, asyncio.CancelledError):
            pass
        return {"status": "UNKNOWN", "response": response}

    async def invoke(self, key, resource_key):
        if (not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", key) is None
                or self.closed or self._closing):
            raise blocked("HTTPS_REQUEST_UNAVAILABLE")
        resource = self.profile.resource(resource_key)
        async with self._lock:
            if self.closed or self._closing or time.time() >= self.deadline:
                raise blocked("HTTPS_REQUEST_UNAVAILABLE")
            self._admission_unknown.add(key)
            try:
                async with asyncio.timeout(5):
                    record = await self.authority.prepare_start(key, resource_key)
                request = self._record(record)
            except (Exception, asyncio.CancelledError):
                # Admission may have committed SENT before losing its reply.
                # Never issue a second prepare/start as a recovery mechanism.
                return {"status": "UNKNOWN", "code": "HTTPS_ADMISSION_UNKNOWN", "operation_key": key}
            self._admission_unknown.discard(key)
            if record.get("allow_send") is not True:
                return await self.query(record["id"])
            operation_id = record["id"]
            self._inflight.add(operation_id)
            reason = "TRANSPORT_UNKNOWN"
            try:
                timeout = min(resource.timeout_seconds, request["hard_deadline"] - time.time(),
                              self.deadline - time.time())
                if timeout <= 0:
                    return await self._unknown(operation_id)

                async def before_send():
                    nonlocal reason
                    reason = "AUTHORITY_LOST"
                    await self.authority.admit_send(operation_id)
                    if self._closing or self.closed:
                        raise blocked("HTTPS_REQUEST_UNAVAILABLE")
                    reason = "TRANSPORT_UNKNOWN"

                exchange = await self.transport.send(self.profile, resource, timeout=timeout, before_send=before_send)
                reason = "OUTPUT_REJECTED"
                await self.authority.validate_output(exchange.body)
                response = response_document(request, state="OBSERVED", http_status=exchange.status,
                    body=exchange.body, reason="REDIRECT_REFUSED" if 300 <= exchange.status <= 399 else "RESPONSE_OBSERVED")
                # Preserve approved originals before the DB ACK can be lost.
                # The private directory is outside the Agent namespace; no
                # response body is released until fenced DB acceptance succeeds.
                self.originals.save(request, response)
                reason = "AUTHORITY_LOST"
                async with asyncio.timeout(5):
                    accepted = await self.authority.record_response(operation_id, response)
                self._record(accepted)
                if accepted.get("state") != "OBSERVED" or accepted.get("response") != self._metadata(response):
                    return await self._unknown(operation_id, "AUTHORITY_LOST")
                self._operations[operation_id]["response"] = response
                return {"status": "OBSERVED", "response": response}
            except asyncio.CancelledError:
                await self._unknown(operation_id, reason)
                raise
            except Exception as error:
                if isinstance(error, CloudBlocked) and error.code == "HTTPS_OUTPUT_LIMIT":
                    reason = "OUTPUT_LIMIT"
                return await self._unknown(operation_id, reason)
            finally:
                self._inflight.discard(operation_id)

    async def query(self, operation_id=None, *, key=None):
        if (operation_id is None) == (key is None):
            raise blocked("HTTPS_QUERY_IDENTITY_REQUIRED")
        async with asyncio.timeout(5):
            if key is not None:
                if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", key) is None:
                    raise blocked("HTTPS_QUERY_IDENTITY_REQUIRED")
                record = await self.authority.get_operation_by_key(key)
            else:
                uuid_text(operation_id)
                record = await self.authority.get_operation(operation_id)
        request = self._record(record)
        operation_id = record["id"]
        if record["state"] == "OBSERVED":
            try:
                response = self.originals.get(request)
                if record.get("response") != self._metadata(response):
                    raise blocked("HTTPS_ORIGINAL_MISMATCH")
                await self.authority.validate_output(base64.b64decode(response["body_base64"], validate=True))
                self._operations[operation_id]["response"] = response
                original_key = key or record.get("operation_key")
                self._admission_unknown.discard(original_key)
                return {"status": "OBSERVED", "response": response}
            except Exception:
                self._operations[operation_id]["response"] = None
                return {"status": "UNKNOWN", "code": "HTTPS_ORIGINAL_UNAVAILABLE"}
        response = record.get("response")
        if response is not None:
            response = project_response({**response, "body_base64": ""}, request)
        else:
            response = response_document(request)
        self._operations[operation_id]["response"] = response
        return {"status": "UNKNOWN", "response": response}

    def observation(self):
        pending = [key for key, item in self._operations.items()
                   if not item["response"] or item["response"]["state"] != "OBSERVED"]
        return {"closed": self.closed, "pending_operations": sorted(pending),
            "pending_keys": sorted(self._admission_unknown),
            "remote_closed": self._authority_closed and not pending and not self._admission_unknown and not self._inflight,
            "inflight": len(self._inflight),
            "operations": [self._metadata(item["response"]) for item in self._operations.values() if item["response"]]}

    @property
    def drained(self):
        return self.closed and not self._handlers and self.observation()["remote_closed"]

    async def close(self):
        if self.closed:
            return self.observation()
        self._closing = True
        if self.server:
            self.server.close()
        # Python 3.13 wait_closed also waits for active stream connections.
        # Cancel and close their handlers before waiting for the listener.
        handlers = tuple(self._handlers)
        for handler in handlers:
            handler.cancel()
        if handlers:
            try:
                await asyncio.wait_for(asyncio.gather(*handlers, return_exceptions=True), 3)
            except TimeoutError:
                pass
        if self.server:
            try:
                await asyncio.wait_for(self.server.wait_closed(), 2)
            except TimeoutError:
                pass
        try:
            # One bound covers *all* reconciliation reads, rather than allowing
            # up to max_operations independent five-second shutdown waits.
            async with asyncio.timeout(6):
                for operation_id, item in tuple(self._operations.items()):
                    if not item["response"] or item["response"]["state"] != "OBSERVED":
                        try:
                            await self.query(operation_id)  # Local/DB reads only; no HTTPS.
                        except Exception:
                            pass
                self._authority_closed = await self.authority.remote_closed() is True
        except (Exception, asyncio.CancelledError):
            self._authority_closed = False
        self.closed = True
        if self.server is not None:
            try:
                info = self.socket_path.lstat()
                if stat.S_ISSOCK(info.st_mode):
                    self.socket_path.unlink()
            except FileNotFoundError:
                pass
        return self.observation()
