"""Worker-only broker for an exact, pre-authorized external action.

No model/Agent credentials, arbitrary URL, body or operation key are accepted.
The independently fenced ledger must issue each one-shot permission before the
next step; HTTP observation never constitutes a terminal business result.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from uuid import UUID, uuid4

from .action_body import validate_prepared_body
from .action_profile import validate_action_profile
from .action_transport import ActionTransport
from .errors import CloudBlocked
from .http_profile import canonical_bytes

_EMPTY_SHA = hashlib.sha256(b"").hexdigest()
_WIRE_LIMIT = 8192
_PREFLIGHT_CODES = frozenset({"CONTROLLED_ACTION_PREFLIGHT_CREDENTIAL_UNAVAILABLE",
    "CONTROLLED_ACTION_OBSERVER_DNS_REFUSED", "CONTROLLED_ACTION_PREFLIGHT_INSUFFICIENT_BALANCE",
    *("CONTROLLED_ACTION_PREFLIGHT_" + stage + "_UNAVAILABLE" for stage in
      ("OAUTH", "ADDRESS", "BALANCE", "ADAPTER", "VALIDATION", "AUTHORITY"))})
_OBSERVATION_CODES = frozenset("CONTROLLED_ACTION_OBSERVE_" + stage + "_UNAVAILABLE" for stage in
    ("ORIGINAL", "OAUTH", "ORDER_GET", "DETAIL_GET", "ADAPTER", "VALIDATION", "AUTHORITY"))


def _blocked(code="CONTROLLED_ACTION_UNAVAILABLE"):
    return CloudBlocked(code, "Controlled action requires original-operation reconciliation")


def _original_id(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError):
        raise _blocked() from None
    return value


class ActionOriginals:
    """Approved HTTP originals stay on the Worker-private volume only."""
    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_absolute() or self.root.resolve(strict=True) != self.root:
            raise _blocked()
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise _blocked()

    def save(self, identity_id: str, body: bytes, *, http_status: int, observed_at: int):
        _original_id(identity_id)
        if (not isinstance(body, bytes) or len(body) > 262144 or type(http_status) is not int
                or not 200 <= http_status <= 599 or type(observed_at) is not int or observed_at < 1):
            raise _blocked()
        original = canonical_bytes({"identity_id": identity_id, "http_status": http_status, "observed_at": observed_at,
            "body_base64": base64.b64encode(body).decode(), "body_sha256": hashlib.sha256(body).hexdigest()})
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            fd = os.open(identity_id + ".response", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
            try:
                view = memoryview(original)
                while view:
                    count = os.write(fd, view)
                    if count <= 0:
                        raise _blocked()
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory)
        except OSError:
            raise _blocked("CONTROLLED_ACTION_ORIGINAL_UNAVAILABLE") from None
        finally:
            os.close(directory)

    def load(self, identity_id: str):
        _original_id(identity_id)
        directory = descriptor = None
        try:
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            descriptor = os.open(identity_id + ".response", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) != 0o600 or not 0 < before.st_size <= 350000):
                raise ValueError
            chunks, remaining = [], before.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 65536))
                if not chunk:
                    raise ValueError
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError
            raw = b"".join(chunks)
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {"identity_id", "http_status", "observed_at", "body_base64", "body_sha256"}
                    or value["identity_id"] != identity_id or type(value["http_status"]) is not int
                    or not 200 <= value["http_status"] <= 599 or type(value["observed_at"]) is not int
                    or value["observed_at"] < 1 or canonical_bytes(value) != raw):
                raise ValueError
            body = base64.b64decode(value["body_base64"], validate=True)
            if len(body) > 262144 or hashlib.sha256(body).hexdigest() != value["body_sha256"]:
                raise ValueError
            return {"http_status": value["http_status"], "observed_at": value["observed_at"], "body": body,
                    "body_sha256": value["body_sha256"]}
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise _blocked("CONTROLLED_ACTION_ORIGINAL_UNAVAILABLE") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory is not None:
                os.close(directory)


class ActionBroker:
    """Serial one-shot execution; only an action key crosses the Agent socket.

    ``authority`` is the private DB authority; ``signer`` executes and checks
    the pinned native project adapter in its independently isolated boundary;
    ``credentials`` materializes the matching API key only for this host.
    None may be supplied by the Agent. Terminal observations are obtained
    only by the trusted authority using the frozen provider observer.
    """
    def __init__(self, socket_path: Path, *, task_id: str, profile: dict, authority, signer,
                 credentials, private_root: Path, deadline: int, validate_output, preflight, transport=None,
                 observer=None):
        _original_id(task_id)
        if type(deadline) is not int or deadline < 1 or not Path(socket_path).is_absolute():
            raise _blocked()
        self.socket_path, self.task_id = Path(socket_path), task_id
        self.profile = validate_action_profile(profile)
        self.authority, self.signer, self.credentials = authority, signer, credentials
        self.originals = ActionOriginals(private_root)
        self.deadline, self.validate_output, self.preflight = deadline, validate_output, preflight
        self.observer = observer
        self.transport = transport or ActionTransport()
        self.server = None
        self.closed = self._closing = False
        self._lock = asyncio.Lock()
        self._handlers = set()
        self._attempted = set()
        self._inflight = set()

    @staticmethod
    def operation_key(task_id: str, action_key: str) -> str:
        return "ca:" + hashlib.sha256((task_id + "\0" + action_key).encode()).hexdigest()

    def _action(self, action_key):
        rows = [item for item in self.profile["actions"] if item["action_key"] == action_key]
        if len(rows) != 1:
            raise _blocked()
        return rows[0]

    @staticmethod
    def _public(record):
        keys = ("identity_id", "action_key", "operation_key", "client_ref", "unique_ref", "state", "body_sha256")
        if not isinstance(record, dict) or any(key not in record for key in keys):
            raise _blocked()
        _original_id(record["identity_id"])
        if (record["state"] not in {"IDENTIFIED", "SENT"}
                or any(not isinstance(record[key], str) for key in keys if key not in {"body_sha256"})
                or record["body_sha256"] is not None and not isinstance(record["body_sha256"], str)):
            raise _blocked()
        observations = record.get("observations", [])
        if not isinstance(observations, list) or len(observations) > 64:
            raise _blocked()
        projected = []
        fields = {"state", "http_status", "body_sha256", "byte_count", "reason", "observed_at"}
        for item in observations:
            # The terminal record is returned only by OBSERVE, where the
            # authority revalidates its frozen provider projection. QUERY is
            # limited to the original identity and transport observations.
            if isinstance(item, dict) and item.get("state") == "BUSINESS_TERMINAL":
                continue
            if (not isinstance(item, dict) or set(item) != {"state", "observation"}
                    or item["state"] not in {"HTTP_OBSERVED", "UNKNOWN"}
                    or not isinstance(item["observation"], dict) or set(item["observation"]) != fields
                    or item["observation"]["state"] != item["state"]):
                raise _blocked()
            value = item["observation"]
            if (not isinstance(value["body_sha256"], str) or re.fullmatch(r"[a-f0-9]{64}", value["body_sha256"]) is None
                    or type(value["byte_count"]) is not int or not 0 <= value["byte_count"] <= 262144
                    or type(value["observed_at"]) is not int or value["observed_at"] < 1
                    or (value["state"] == "HTTP_OBSERVED" and (type(value["http_status"]) is not int
                        or not 200 <= value["http_status"] <= 599 or value["reason"] != "RESPONSE_OBSERVED"))
                    or (value["state"] == "UNKNOWN" and (value["http_status"] is not None
                        or value["byte_count"] != 0 or value["body_sha256"] != _EMPTY_SHA
                        or value["reason"] not in {"TRANSPORT_UNKNOWN", "AUTHORITY_LOST", "OUTPUT_REJECTED"}))):
                raise _blocked()
            projected.append({"state": item["state"], "observation": {key: value[key] for key in fields}})
        return {**{key: record[key] for key in keys}, "observations": projected}

    async def start(self):
        if (self.socket_path.resolve(strict=False) != self.socket_path
                or self.socket_path.parent.resolve(strict=True) != self.socket_path.parent
                or os.path.lexists(self.socket_path)):
            raise _blocked()
        self.server = await asyncio.start_unix_server(self._handle, path=self.socket_path, limit=_WIRE_LIMIT + 1)
        os.chmod(self.socket_path, 0o600)
        return self

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self._handlers.add(task)
        result = {"status": "UNKNOWN", "code": "CONTROLLED_ACTION_UNAVAILABLE"}
        try:
            # Keep all preflight/signing/transport inside the original task
            # deadline; a fixed 25s wrapper could interrupt a valid preflight.
            async with asyncio.timeout(min(120, max(0.001, self.deadline - time.time()))):
                raw = await reader.readline()
                if not raw.endswith(b"\n") or len(raw) > _WIRE_LIMIT:
                    raise _blocked()
                payload = json.loads(raw)
                if not isinstance(payload, dict) or set(payload) != {"verb", "action_key"}:
                    raise _blocked()
                if payload["verb"] == "INVOKE":
                    result = await self.invoke(payload["action_key"])
                elif payload["verb"] == "QUERY":
                    result = await self.query(payload["action_key"])
                elif payload["verb"] == "OBSERVE":
                    result = await self.observe(payload["action_key"])
                else:
                    raise _blocked()
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.write(canonical_bytes(result) + b"\n")
                await asyncio.wait_for(writer.drain(), 1)
            except (OSError, TimeoutError):
                pass
            writer.close()
            self._handlers.discard(task)

    async def query(self, action_key):
        self._action(action_key)
        key = self.operation_key(self.task_id, action_key)
        try:
            async with asyncio.timeout(5):
                record = await self.authority.get_by_key(key)
            return {"status": "ORIGINAL", "operation": self._public(record)}
        except (Exception, asyncio.CancelledError):
            return {"status": "UNKNOWN", "code": "CONTROLLED_ACTION_ORIGINAL_UNAVAILABLE", "operation_key": key}

    async def _unknown(self, identity_id, reason):
        try:
            async with asyncio.timeout(2):
                return await self.authority.record_observation(identity_id=identity_id, observation={"state": "UNKNOWN",
                    "http_status": None, "body_sha256": _EMPTY_SHA, "byte_count": 0, "reason": reason,
                    "observed_at": int(time.time())})
        except (Exception, asyncio.CancelledError):
            return None

    async def observe(self, action_key):
        self._action(action_key)
        key = self.operation_key(self.task_id, action_key)
        if self.closed or self._closing or self.observer is None:
            raise _blocked()
        async with self._lock:
            stage = "ORIGINAL"
            try:
                record = self._public(await self.authority.get_by_key(key))
                if record["action_key"] != action_key or record["operation_key"] != key or record["state"] != "SENT":
                    raise _blocked()
                stage = "AUTHORITY"
                result = await self.authority.observe_business_terminal(record["identity_id"], key,
                    observer=self.observer, signer=self.signer, validate_output=self.validate_output)
                projection = result["projection"]
                if not isinstance(projection, dict) or type(projection.get("business_terminal")) is not bool:
                    raise _blocked()
                stage = "VALIDATION"
                await self.validate_output({"controlled_action_observation": projection})
                return {"status": "BUSINESS_TERMINAL" if projection["business_terminal"] else "BUSINESS_PENDING",
                        "operation_key": key, "observation": projection}
            except (Exception, asyncio.CancelledError) as error:
                code = error.code if isinstance(error, CloudBlocked) and error.code in _OBSERVATION_CODES else (
                    "CONTROLLED_ACTION_OBSERVE_" + stage + "_UNAVAILABLE")
                return {"status": "UNKNOWN", "code": code, "operation_key": key}

    async def invoke(self, action_key):
        action = self._action(action_key)
        key = self.operation_key(self.task_id, action_key)
        if self.closed or self._closing:
            raise _blocked()
        async with self._lock:
            if self.closed or self._closing or time.time() >= self.deadline:
                raise _blocked()
            if action_key in self._attempted:
                return await self.query(action_key)
            try:
                # Project-specific, trusted live precondition (e.g. existing
                # source-address balance). No Agent self-report can grant it.
                if await self.preflight(action) is not True:
                    return {"status": "BLOCKED", "code": "CONTROLLED_ACTION_PREFLIGHT_UNAVAILABLE"}
            except (Exception, asyncio.CancelledError) as error:
                code = error.code if isinstance(error, CloudBlocked) and error.code in _PREFLIGHT_CODES else "CONTROLLED_ACTION_PREFLIGHT_UNAVAILABLE"
                return {"status": "BLOCKED", "code": code}
            self._attempted.add(action_key)
            try:
                client_ref, unique_ref = "ht_" + uuid4().hex, "ht_" + uuid4().hex
                async with asyncio.timeout(5):
                    identity = await self.authority.prepare_identity(action_key=action_key, operation_key=key,
                        client_ref=client_ref, unique_ref=unique_ref)
                original = self._public(identity)
                if (identity.get("allow_prepare") is not True or original["action_key"] != action_key
                        or original["operation_key"] != key or original["client_ref"] != client_ref
                        or original["unique_ref"] != unique_ref or original["state"] != "IDENTIFIED"):
                    return await self.query(action_key)
            except (Exception, asyncio.CancelledError):
                return {"status": "UNKNOWN", "code": "CONTROLLED_ACTION_IDENTITY_UNKNOWN", "operation_key": key}
            identity_id = original["identity_id"]
            sent = False
            reason = "TRANSPORT_UNKNOWN"
            try:
                body = await self.signer.prepare(action, client_ref, unique_ref, identity_id=identity_id)
                digest = validate_prepared_body(self.profile, action_key=action_key, client_ref=client_ref,
                                                unique_ref=unique_ref, body=body)["body_sha256"]
                if await self.signer.verify(action, body, identity_id=identity_id) is not True:
                    raise _blocked("CONTROLLED_ACTION_SIGNATURE_INVALID")
                api_key = await self.credentials.api_key(action, identity_id=identity_id)
                # Re-read the source immediately before recording SENT. The
                # following authority/DNS/POST remains subject to a race, which
                # must be reported rather than claimed to be a distributed lock.
                if await self.preflight(action) is not True:
                    raise _blocked("CONTROLLED_ACTION_PREFLIGHT_UNAVAILABLE")
                async with asyncio.timeout(5):
                    receipt = await self.authority.prepare_send(identity_id=identity_id, body_sha256=digest)
                if (receipt.get("allow_send") is not True or receipt.get("identity_id") != identity_id
                        or receipt.get("body_sha256") != digest or receipt.get("state") != "SENT"):
                    return await self.query(action_key)
                sent = True
                self._inflight.add(identity_id)
                remaining = min(15, self.deadline - time.time())
                if remaining <= 0:
                    raise _blocked()

                async def before_send(value):
                    nonlocal reason
                    reason = "AUTHORITY_LOST"
                    if self.closed or self._closing:
                        raise _blocked()
                    await self.authority.admit_send(identity_id=identity_id, body_sha256=value)
                    if self.closed or self._closing:
                        raise _blocked()
                    reason = "TRANSPORT_UNKNOWN"

                async def verify_signature(item, value):
                    return await self.signer.verify(item, value, identity_id=identity_id)

                result = await self.transport.send(profile=self.profile, action_key=action_key,
                    client_ref=client_ref, unique_ref=unique_ref, body=body, sent_body_sha256=digest,
                    api_key=api_key, timeout=remaining, verify_signature=verify_signature, before_send=before_send)
                reason = "OUTPUT_REJECTED"
                text = result.body.decode("utf-8")
                await self.validate_output({"controlled_action_response": text})
                observed_at = int(time.time())
                self.originals.save(identity_id, result.body, http_status=result.status, observed_at=observed_at)
                reason = "AUTHORITY_LOST"
                async with asyncio.timeout(5):
                    accepted = await self.authority.record_observation(identity_id=identity_id, observation={
                        "state": "HTTP_OBSERVED", "http_status": result.status,
                        "body_sha256": hashlib.sha256(result.body).hexdigest(), "byte_count": len(result.body),
                        "reason": "RESPONSE_OBSERVED", "observed_at": observed_at})
                return {"status": "HTTP_OBSERVED", "operation": self._public(accepted),
                        "business_terminal": False}
            except asyncio.CancelledError:
                if sent:
                    await asyncio.shield(self._unknown(identity_id, reason))
                raise
            except Exception:
                if sent:
                    await self._unknown(identity_id, reason)
                return {"status": "UNKNOWN", "operation_key": key, "identity_id": identity_id}
            finally:
                self._inflight.discard(identity_id)

    async def close(self):
        if self.closed:
            return
        self._closing = True
        if self.server is not None:
            self.server.close()
        handlers = tuple(self._handlers)
        for handler in handlers:
            handler.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        if self.server is not None:
            await self.server.wait_closed()
        self.closed = True
        try:
            if stat.S_ISSOCK(self.socket_path.lstat().st_mode):
                self.socket_path.unlink()
        except FileNotFoundError:
            pass

    async def drained(self):
        if not self.closed or self._handlers or self._inflight:
            return False
        try:
            return await self.authority.remote_closed() is True
        except Exception:
            return False
