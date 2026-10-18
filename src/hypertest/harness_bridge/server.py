"""UDS host supervisor with an operational journal, separate from Canonical State.

The signed execution grant is minted by the trusted Worker only after checking
its database claim. The Bridge also fences claims/epochs locally and stops on
grant expiry. Management grants target historical calls; they cannot execute.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import signal
import time
from pathlib import Path
from typing import Any

from hypertest.harness_bridge.protocol import (
    MAX_MESSAGE,
    PROFILE,
    PROTOCOL,
    TOOLS,
    TRANSPORT,
    BridgeError,
    ExecutionContext,
    canonical,
    context_from,
    identifier,
    verify,
)
from hypertest.harness_bridge.provider import PersistentCodex, process_identity

_TERMINAL = frozenset({"COMPLETED", "FAILED", "INTERRUPTED", "OUTCOME_UNKNOWN"})
_MANAGEMENT = frozenset({"capabilities", "get_call", "restore_session", "interrupt", "close", "recover"})
_EXECUTION = frozenset({"create_session", "execute", "resume", "get_call", "renew", "respond_tool"})


def _identity(context: ExecutionContext) -> dict[str, Any]:
    return {key: getattr(context, key) for key in (
        "run_id", "binding_id", "logical_worker_id", "session_id", "workspace_id", "harness_host_id",
    )}


def _claim(context: ExecutionContext) -> str:
    return hashlib.sha256(context.claim_token.encode()).hexdigest()


class BridgeServer:
    def __init__(self, *, socket_path: Path, tool_socket_path: Path, state_dir: Path,
                 workspace_root: Path, host_id: str, execution_key: bytes, management_key: bytes,
                 provider: PersistentCodex | Any | None = None, max_concurrent: int = 2) -> None:
        if len(execution_key) < 32 or len(management_key) < 32 or execution_key == management_key:
            raise ValueError("separate Bridge keys of at least 32 bytes are required")
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self.socket_path, self.tool_socket_path = socket_path, tool_socket_path
        self.state_dir = state_dir.absolute()
        self.workspace_root = workspace_root.absolute()
        if self.workspace_root.is_symlink() or self.workspace_root.resolve() != self.workspace_root:
            raise ValueError("workspace root must be canonical and not a symlink")
        self.host_id = identifier(host_id)
        self.execution_key, self.management_key = execution_key, management_key
        self.provider = provider or PersistentCodex()
        self.max_concurrent = max_concurrent
        self.sessions: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.tool_waiters: dict[tuple[str, str], asyncio.Future] = {}
        self.relay_tokens: dict[str, str] = {}
        self._tool_schemas: dict[str, list[dict[str, Any]]] = {}
        self.nonces: dict[str, float] = {}
        self.lock = asyncio.Lock()
        self.listeners: list[asyncio.AbstractServer] = []
        self.watchdog_task: asyncio.Task | None = None
        self._load()

    def _load(self) -> None:
        self.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.state_dir.is_symlink() or self.state_dir.resolve() != self.state_dir:
            raise ValueError("journal directory must not be a symlink")
        os.chmod(self.state_dir, 0o700)
        for kind, collection in (("session", self.sessions), ("call", self.calls)):
            for path in self.state_dir.glob(f"{kind}-*.json"):
                if path.is_symlink():
                    raise ValueError("journal entries must not be symlinks")
                record = json.loads(path.read_text())
                identifier(record["id"])
                collection[record["id"]] = record
        for call in self.calls.values():
            if call["status"] == "RUNNING":
                call["status"] = "OUTCOME_UNKNOWN"
                call["error_code"] = "BRIDGE_RESTARTED"
                call["stopped"] = False
                session = self.sessions[call["identity"]["session_id"]]
                session["recovery_required"] = True
                self._save("call", call)
                self._save("session", session)

    def _save(self, kind: str, record: dict[str, Any]) -> None:
        path = self.state_dir / f"{kind}-{identifier(record['id'])}.json"
        temporary = path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(canonical(record))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        descriptor = os.open(self.state_dir, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def workspace(self, workspace_id: str) -> Path:
        # The signed context only accepts a UUID directory ID, never a caller path.
        from hypertest.harness_bridge.protocol import WORKSPACE
        if not isinstance(workspace_id, str) or not WORKSPACE.fullmatch(workspace_id):
            raise BridgeError("WORKSPACE_UNSAFE")
        container = self.workspace_root / workspace_id
        path = container / "repo"
        if container.is_symlink() or path.is_symlink() or path.resolve() != path or not path.is_dir():
            raise BridgeError("WORKSPACE_UNAVAILABLE")
        return path

    async def start(self) -> None:
        if isinstance(self.provider, PersistentCodex):
            await self.provider.validate_capabilities()
        for path, handler in ((self.socket_path, self.handle), (self.tool_socket_path, self.handle_relay)):
            path.parent.mkdir(parents=True, mode=0o770, exist_ok=True)
            if path.exists():
                if not path.is_socket():
                    raise ValueError("refusing to replace a non-socket Bridge path")
                # Do not silently take over an already live Bridge.
                try:
                    _, writer = await asyncio.open_unix_connection(str(path))
                except (ConnectionRefusedError, FileNotFoundError):
                    path.unlink(missing_ok=True)
                else:
                    writer.close()
                    await writer.wait_closed()
                    raise RuntimeError("Bridge socket is already active")
            listener = await asyncio.start_unix_server(handler, str(path), limit=MAX_MESSAGE)
            os.chmod(path, 0o660)
            self.listeners.append(listener)
        self.watchdog_task = asyncio.create_task(self.watchdog())

    async def shutdown(self) -> None:
        for listener in self.listeners:
            listener.close()
            await listener.wait_closed()
        if self.watchdog_task:
            self.watchdog_task.cancel()
            await asyncio.gather(self.watchdog_task, return_exceptions=True)
        for call_id in list(self.tasks):
            await self.stop(call_id, "BRIDGE_SHUTDOWN")
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
        for path in (self.socket_path, self.tool_socket_path):
            path.unlink(missing_ok=True)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(10):
                line = await reader.readline()
            if len(line) > MAX_MESSAGE:
                raise BridgeError("REQUEST_TOO_LARGE")
            request = json.loads(line)
            management = request.get("authority") == "management"
            request = verify(request, self.management_key if management else self.execution_key)
            operation = request.get("operation")
            if operation not in (_MANAGEMENT if management else _EXECUTION):
                raise BridgeError("AUTHORIZATION_REJECTED")
            nonce = identifier(request.get("nonce"))
            async with self.lock:
                self.nonces = {key: deadline for key, deadline in self.nonces.items() if deadline > time.time()}
                if nonce in self.nonces or len(self.nonces) > 10_000:
                    raise BridgeError("AUTHORIZATION_REPLAY")
                self.nonces[nonce] = time.time() + 60
                # Long process interruption is kept outside this short registry lock.
                if operation in {"interrupt", "close"}:
                    deferred = self.validate_management(operation, request["payload"])
                else:
                    result = self.dispatch(operation, request["payload"], management=management)
                    deferred = None
            if deferred is not None:
                result = await self.manage(operation, deferred)
            response = {"ok": True, "result": result}
        except BridgeError as exc:
            response = {"ok": False, "error": exc.code}
        except (ValueError, KeyError, TypeError, OSError, TimeoutError):
            response = {"ok": False, "error": "INVALID_REQUEST"}
        try:
            writer.write(canonical(response) + b"\n")
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    def checked_context(self, payload: dict[str, Any], *, execution: bool) -> ExecutionContext:
        context = context_from(payload["context"], execution=execution)
        if context.harness_host_id != self.host_id:
            raise BridgeError("HOST_MISMATCH")
        return context

    def session(self, context: ExecutionContext, *, current: bool = True) -> dict[str, Any]:
        session = self.sessions.get(context.session_id)
        if session is None or session["identity"] != _identity(context):
            raise BridgeError("SESSION_UNAVAILABLE")
        if current and session["epoch"] != context.binding_epoch:
            raise BridgeError("STALE_BINDING")
        return session

    def call(self, context: ExecutionContext, call_id: str) -> dict[str, Any]:
        call = self.calls.get(identifier(call_id))
        if not call or call["identity"] != _identity(context) or call["epoch"] != context.binding_epoch or call["job_id"] != context.job_id:
            raise BridgeError("CALL_NOT_FOUND")
        return call

    def authorize_call(self, context: ExecutionContext, call: dict[str, Any]) -> None:
        session = self.session(context)
        if session["closed"] or session["recovery_required"]:
            raise BridgeError("SESSION_UNAVAILABLE")
        if call["claim_hash"] != _claim(context) or call["job_id"] != context.job_id:
            raise BridgeError("STALE_CLAIM")
        if call["grant_expires_at"] <= time.time():
            raise BridgeError("AUTHORIZATION_EXPIRED")

    def dispatch(self, operation: str, payload: dict[str, Any], *, management: bool) -> dict[str, Any]:
        if operation == "capabilities":
            return {"transport": TRANSPORT, "protocol": PROTOCOL, "profile": PROFILE,
                    "host_id": self.host_id, "provider": "codex",
                    "provider_version": getattr(self.provider, "version", None), "persistent_session": True,
                    "domain_tools": sorted(TOOLS), "management_recovery": True, "native_shell": False, "native_filesystem": False,
                    "max_concurrent": self.max_concurrent}
        context = self.checked_context(payload, execution=not management)
        if operation == "create_session":
            self.workspace(context.workspace_id)
            existing = self.sessions.get(context.session_id)
            if existing:
                existing = self.session(context)
                if existing["closed"] or existing["recovery_required"]:
                    raise BridgeError("SESSION_UNAVAILABLE")
                return self.session_view(existing)
            if context.binding_epoch != 1:
                raise BridgeError("STALE_BINDING")
            if any(s["identity"]["run_id"] == context.run_id
                   or s["identity"]["binding_id"] == context.binding_id
                   or s["identity"]["workspace_id"] == context.workspace_id
                   or s["identity"]["logical_worker_id"] == context.logical_worker_id
                   for s in self.sessions.values()):
                raise BridgeError("BINDING_CONFLICT")
            record = {"id": context.session_id, "identity": _identity(context),
                      "epoch": context.binding_epoch, "closed": False, "recovery_required": False,
                      "provider_session_id": None, "started": False, "active_call": None,
                      "claims": [], "revoked_claims": [], "created_at": time.time()}
            self.sessions[context.session_id] = record
            self._save("session", record)
            return self.session_view(record)
        if operation == "restore_session":
            session = self.session(context)
            self.workspace(context.workspace_id)
            reference = session["provider_session_id"]
            if session["closed"] or not reference or not self.provider.session_exists(reference):
                raise BridgeError("SESSION_UNAVAILABLE")
            return self.session_view(session)
        if operation in {"execute", "resume"}:
            return self.start_call(context, payload, resume=operation == "resume")
        call = self.call(context, payload["call_id"])
        if operation == "recover":
            session = self.session(context, current=False)
            # An ACK may be lost after fenced recovery. Reconcile the same transition.
            if (session["epoch"] == payload["new_epoch"] == context.binding_epoch + 1
                    and call["stopped"] and not session["closed"]
                    and not session["recovery_required"]):
                return self.session_view(session)
            if session["epoch"] != context.binding_epoch:
                raise BridgeError("STALE_BINDING")
            if (not call["stopped"]
                    or call["claim_hash"] not in session.get("revoked_claims", [])
                    or session["active_call"] or payload["new_epoch"] != context.binding_epoch + 1
                    or session["closed"] or not session["provider_session_id"]
                    or not self.provider.session_exists(session["provider_session_id"])):
                raise BridgeError("RECOVERY_REJECTED")
            self.workspace(context.workspace_id)
            session.update(epoch=payload["new_epoch"], recovery_required=False)
            self._save("session", session)
            return self.session_view(session)
        if not management:
            self.authorize_call(context, call)
        if operation == "get_call":
            cursor = payload.get("cursor", 0)
            if not isinstance(cursor, int) or cursor < 0:
                raise BridgeError("INVALID_CURSOR")
            return self.call_view(call, cursor)
        if operation == "renew":
            if call["status"] != "RUNNING":
                raise BridgeError("CALL_FINISHED")
            call["grant_expires_at"] = context.expires_at
            self._save("call", call)
            return {"expires_at": call["grant_expires_at"]}
        if operation == "respond_tool":
            tool_id = identifier(payload["tool_call_id"])
            tool = call["tools"].get(tool_id)
            if not tool or call["status"] != "RUNNING":
                raise BridgeError("TOOL_NOT_PENDING")
            result = payload["result"]
            if not isinstance(result, dict) or len(canonical(result)) > 2_000_000:
                raise BridgeError("INVALID_TOOL_RESULT")
            digest = hashlib.sha256(canonical(result)).hexdigest()
            if tool["status"] == "COMPLETED":
                if tool["result_hash"] != digest:
                    raise BridgeError("IDEMPOTENCY_CONFLICT")
                return {"accepted": True}
            tool.update(status="COMPLETED", result=result, result_hash=digest)
            self._save("call", call)
            waiter = self.tool_waiters.get((call["id"], tool_id))
            if waiter is not None and not waiter.done():
                waiter.set_result(result)
            return {"accepted": True}
        raise BridgeError("OPERATION_UNSUPPORTED")

    def start_call(self, context: ExecutionContext, payload: dict[str, Any], *, resume: bool) -> dict[str, Any]:
        session = self.session(context)
        call_id = identifier(payload["call_id"])
        if payload.get("idempotency_key") != call_id:
            raise BridgeError("INVALID_IDEMPOTENCY_KEY")
        contract = payload["contract"]
        if not isinstance(contract, dict) or set(contract) != {"prompt", "tools", "timeout_seconds"}:
            raise BridgeError("INVALID_CONTRACT")
        if (not isinstance(contract["prompt"], str) or len(contract["prompt"]) > 500_000
                or not isinstance(contract["timeout_seconds"], int)
                or not 1 <= contract["timeout_seconds"] <= 7200):
            raise BridgeError("INVALID_CONTRACT")
        tools = contract["tools"]
        if not isinstance(tools, list) or not tools or len(tools) > len(TOOLS):
            raise BridgeError("INVALID_TOOLS")
        names = set()
        for tool in tools:
            if (not isinstance(tool, dict) or tool.get("name") not in TOOLS
                    or tool["name"] in names or not isinstance(tool.get("inputSchema"), dict)
                    or tool["inputSchema"].get("type") != "object"
                    or set(tool) - {"name", "description", "inputSchema"}):
                raise BridgeError("INVALID_TOOLS")
            names.add(tool["name"])
        digest = hashlib.sha256(canonical({"identity": _identity(context), "epoch": context.binding_epoch,
                                          "job_id": context.job_id, "claim_hash": _claim(context),
                                          "contract": contract, "resume": resume})).hexdigest()
        if call_id in self.calls:
            existing = self.call(context, call_id)
            if existing["input_hash"] != digest:
                raise BridgeError("IDEMPOTENCY_CONFLICT")
            return self.call_view(existing)
        if session["closed"] or session["recovery_required"]:
            raise BridgeError("SESSION_UNAVAILABLE")
        if session["active_call"]:
            raise BridgeError("SESSION_BUSY")
        if len(self.tasks) >= self.max_concurrent:
            raise BridgeError("HOST_CAPACITY_EXCEEDED")
        workspace = self.workspace(context.workspace_id)
        native = session["provider_session_id"]
        if resume:
            if not native or not self.provider.session_exists(native):
                raise BridgeError("SESSION_UNAVAILABLE")
        elif session["started"]:
            raise BridgeError("SESSION_ALREADY_STARTED")
        claim_hash = _claim(context)
        # A completed old owner cannot reclaim a session after a new claim ran.
        claims = session["claims"]
        if claim_hash in session.get("revoked_claims", []):
            raise BridgeError("STALE_CLAIM")
        if claims and claims[-1] != claim_hash and claim_hash in claims:
            raise BridgeError("STALE_CLAIM")
        if not claims or claims[-1] != claim_hash:
            claims.append(claim_hash)
        record = {"id": call_id, "identity": _identity(context), "epoch": context.binding_epoch,
                  "job_id": context.job_id, "claim_hash": claim_hash, "input_hash": digest,
                  "grant_expires_at": context.expires_at, "deadline": time.time() + contract["timeout_seconds"],
                  "status": "RUNNING", "stopped": False, "events": [], "sequence": 0,
                  "tools": {}, "provider_session_id": native, "pid": None, "process_identity": None,
                  "created_at": time.time(), "finished_at": None}
        session.update(started=True, active_call=call_id)
        self.calls[call_id] = record
        # Durable registration precedes any provider side effect.
        self._save("call", record)
        self._save("session", session)
        token = secrets.token_urlsafe(32)
        self.relay_tokens[call_id] = token
        self._tool_schemas[call_id] = tools
        self.tasks[call_id] = asyncio.create_task(self.run_call(record, workspace, contract, token))
        return self.call_view(record)

    def emit(self, call: dict[str, Any], event: dict[str, Any]) -> None:
        call["sequence"] += 1
        call["events"].append({"sequence": call["sequence"], **event})
        call["events"] = call["events"][-256:]
        self._save("call", call)

    async def run_call(self, call: dict[str, Any], workspace: Path,
                       contract: dict[str, Any], token: str) -> None:
        session = self.sessions[call["identity"]["session_id"]]

        def started(pid: int, identity: str | None) -> None:
            call.update(pid=pid, process_identity=identity)
            self._save("call", call)

        try:
            async for event in self.provider.run(
                call_id=call["id"], workspace=workspace, native_session=session["provider_session_id"],
                contract=contract, relay_socket=str(self.tool_socket_path), relay_token=token, started=started,
            ):
                if call["status"] != "RUNNING":
                    continue
                if event["type"] == "SESSION_STARTED":
                    reference = event["payload"]["provider_session_id"]
                    if session["provider_session_id"] and reference != session["provider_session_id"]:
                        raise BridgeError("PROVIDER_SESSION_CHANGED")
                    session["provider_session_id"] = call["provider_session_id"] = reference
                    self._save("session", session)
                self.emit(call, event)
            if call["status"] == "RUNNING":
                call["status"] = "COMPLETED"
        except asyncio.CancelledError:
            if call["status"] == "RUNNING":
                call.update(status="OUTCOME_UNKNOWN", error_code="CALL_CANCELLED")
                session["recovery_required"] = True
            raise
        except Exception as exc:
            if call["status"] == "RUNNING":
                call.update(status="FAILED", error_code=exc.code if isinstance(exc, BridgeError) else "PROVIDER_ERROR")
            self.emit(call, {"type": "ERROR", "payload": {"error_code": call.get("error_code", "PROVIDER_ERROR")}})
        finally:
            call["stopped"] = await self.provider.interrupt(call["id"])
            if call["stopped"] and not call.get("finished_at"):
                call["finished_at"] = time.time()
            if session["active_call"] == call["id"]:
                session["active_call"] = None
            self.relay_tokens.pop(call["id"], None)
            self._tool_schemas.pop(call["id"], None)
            for (cid, _), waiter in self.tool_waiters.items():
                if cid == call["id"] and not waiter.done():
                    waiter.set_exception(BridgeError("CALL_FINISHED"))
            self._save("call", call)
            self._save("session", session)
            self.tasks.pop(call["id"], None)

    def session_view(self, session: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": session["id"], "provider_session_id": session["provider_session_id"],
                "binding_epoch": session["epoch"], "closed": session["closed"],
                "recovery_required": session["recovery_required"], "active_call_id": session["active_call"]}

    def call_view(self, call: dict[str, Any], cursor: int = 0) -> dict[str, Any]:
        finished_at = call.get("finished_at")
        return {"call_id": call["id"], "status": call["status"], "stopped": call["stopped"],
                "created_at": call["created_at"], "finished_at": finished_at,
                "elapsed_seconds": max(0.0, (finished_at or time.time()) - call["created_at"]),
                "binding_epoch": call["epoch"], "provider_session_id": call["provider_session_id"],
                "error_code": call.get("error_code"), "cursor": call["sequence"],
                "events": [event for event in call["events"] if event["sequence"] > cursor],
                "pending_tools": [{"tool_call_id": key, "name": item["name"], "arguments": item["arguments"]}
                                  for key, item in call["tools"].items() if item["status"] == "PENDING"]}

    def validate_management(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        context = self.checked_context(payload, execution=False)
        session = self.session(context, current=False)
        if operation == "close" and (not payload.get("terminal") or session["epoch"] != context.binding_epoch):
            raise BridgeError("CLOSE_REJECTED")
        call_id = payload.get("call_id")
        if call_id:
            self.call(context, call_id)
        elif session["started"]:
            raise BridgeError("CALL_TARGET_REQUIRED")
        if operation == "interrupt" and not call_id:
            raise BridgeError("CALL_TARGET_REQUIRED")
        # Closing a historical generation must never kill current work.
        if operation == "close" and session["active_call"] not in {None, call_id}:
            raise BridgeError("CALL_TARGET_MISMATCH")
        return {"context": context, "session": session, "call_id": call_id}

    async def manage(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        session, call_id = data["session"], data["call_id"]
        if operation == "close":
            # Persist revocation first so no concurrent execute can get through.
            session["closed"] = True
            self._save("session", session)
        stopped = True
        if call_id:
            stopped = await self.stop(call_id, "INTERRUPTED")
        return {"accepted": True, "stopped": stopped, "closed": session["closed"]}

    async def stop(self, call_id: str, reason: str) -> bool:
        call = self.calls[call_id]
        session = self.sessions[call["identity"]["session_id"]]
        self.relay_tokens.pop(call_id, None)
        if call["claim_hash"] not in session.setdefault("revoked_claims", []):
            session["revoked_claims"].append(call["claim_hash"])
        if call["status"] == "RUNNING":
            unknown = reason != "INTERRUPTED"
            call.update(status="OUTCOME_UNKNOWN" if unknown else "INTERRUPTED", error_code=reason)
            if unknown:
                session["recovery_required"] = True
            self._save("call", call)
            self._save("session", session)
        if call_id in self.tasks:
            stopped = await self.provider.interrupt(call_id)
            task = self.tasks.get(call_id)
            if task and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        elif not call["stopped"]:
            # On restart, stop only the exact recorded Linux process generation.
            pid, identity = call.get("pid"), call.get("process_identity")
            stopped = False
            if pid and identity:
                live = process_identity(pid)
                if live is None or live != identity:
                    stopped = True
                else:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    for _ in range(50):
                        if process_identity(pid) != identity:
                            stopped = True
                            break
                        await asyncio.sleep(0.1)
        else:
            stopped = True
        call["stopped"] = stopped
        if stopped and not call.get("finished_at"):
            call["finished_at"] = time.time()
        if stopped and session["active_call"] == call_id:
            session["active_call"] = None
        self._save("call", call)
        self._save("session", session)
        return stopped

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            for call_id, call in list(self.calls.items()):
                if call["status"] == "RUNNING" and min(call["deadline"], call["grant_expires_at"]) <= time.time():
                    await self.stop(call_id, "EXECUTION_GRANT_EXPIRED")

    async def handle_relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(10):
                line = await reader.readline()
            if len(line) > MAX_MESSAGE:
                raise BridgeError("REQUEST_TOO_LARGE")
            request = json.loads(line)
            call_id = identifier(request["call_id"])
            expected = self.relay_tokens.get(call_id)
            if not expected or not hmac.compare_digest(expected, str(request.get("token", ""))):
                raise BridgeError("TOOL_AUTHORIZATION_REJECTED")
            call = self.calls[call_id]
            session = self.sessions[call["identity"]["session_id"]]
            if (call["status"] != "RUNNING" or call["grant_expires_at"] <= time.time()
                    or session["closed"] or session["epoch"] != call["epoch"]):
                raise BridgeError("TOOL_AUTHORIZATION_REJECTED")
            # Schemas are kept in memory only while their signed call is alive.
            tools = self._tool_schemas[call_id]
            if request["operation"] == "list":
                result = {"tools": tools}
            elif request["operation"] == "call":
                payload = request["payload"]
                name = payload.get("name")
                if name not in {item["name"] for item in tools} or not isinstance(payload.get("arguments"), dict):
                    raise BridgeError("TOOL_NOT_ALLOWED")
                tool_id = identifier(payload["tool_call_id"])
                if tool_id in call["tools"]:
                    raise BridgeError("TOOL_DUPLICATE")
                if any(item["status"] == "PENDING" for item in call["tools"].values()):
                    raise BridgeError("TOOL_BUSY")
                if len(call["tools"]) >= 256:
                    raise BridgeError("TOOL_BUDGET_EXHAUSTED")
                call["tools"][tool_id] = {"name": name, "arguments": payload["arguments"], "status": "PENDING"}
                self._save("call", call)
                waiter = asyncio.get_running_loop().create_future()
                self.tool_waiters[(call_id, tool_id)] = waiter
                try:
                    async with asyncio.timeout(max(1, call["deadline"] - time.time())):
                        result = await waiter
                finally:
                    self.tool_waiters.pop((call_id, tool_id), None)
            else:
                raise BridgeError("TOOL_OPERATION_REJECTED")
            response = {"ok": True, "result": result}
        except BridgeError as exc:
            response = {"ok": False, "error": exc.code}
        except (ValueError, KeyError, TypeError, OSError, TimeoutError):
            response = {"ok": False, "error": "TOOL_REQUEST_FAILED"}
        try:
            writer.write(canonical(response) + b"\n")
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
