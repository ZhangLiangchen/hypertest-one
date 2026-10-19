"""Outbound-only local Connector using the existing persistent Bridge supervisor."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from hypertest.agent.bridge import BridgeClient
from hypertest.connector.protocol import (
    BRIDGE_MANAGEMENT,
    INTEGRATION,
    MAX_MESSAGE,
    MAX_TTL_SECONDS,
    OPERATIONS,
    TRANSPORT,
    digest,
    hello,
)
from hypertest.harness_bridge.protocol import BridgeError, canonical
from hypertest.harness_bridge.server import BridgeServer

Handler = Callable[[dict, dict], Awaitable[dict]]
LOG = logging.getLogger(__name__)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url,code,'Connector redirects are disabled',headers,fp)


class _StrictConnect(connect):
    def process_redirect(self, exc):
        # Device credentials are scoped to the configured entry point only.
        return exc


def checked_url(url: str, *, allow_insecure_loopback: bool = False) -> str:
    parsed=urlsplit(url)
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError('Connector URL must not contain authentication, query or fragment')
    if parsed.scheme!='https' and not (allow_insecure_loopback and parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost','::1'}):
        raise ValueError('HTTPS is required; insecure loopback is an explicit development option')
    return url.rstrip('/')


class ConnectorDaemon:
    def __init__(self, *, api_url: str, node_id: str, device_token: str, server: BridgeServer,
                 ca_file: str | None = None, allow_insecure_loopback: bool = False,
                 source_adapter=None, issue_adapter=None) -> None:
        self.api_url=checked_url(api_url,allow_insecure_loopback=allow_insecure_loopback)
        self.node_id,self.device_token,self.server=node_id,device_token,server
        self.ssl_context=ssl.create_default_context(cafile=ca_file)
        self.bridge=BridgeClient(str(server.socket_path),server.execution_key,server.management_key,timeout=15)
        self.handlers: dict[str,Handler]={}
        self.source_adapter,self.issue_adapter=source_adapter,issue_adapter
        self._deadlines: dict[str,float]={}
        self._revoked=False
        self._inflight: dict[str,asyncio.Task]={}
        self._send_lock=asyncio.Lock()
        if source_adapter is not None:
            self.register_handler('prepare_source',self.prepare_source)
            self.register_handler('install_workspace',self.install_workspace)
        if issue_adapter is not None:
            self.register_handler('issue_create',self.issue_create)
            self.register_handler('issue_query',self.issue_query)

    def register_handler(self, operation: str, handler: Handler) -> None:
        if operation not in INTEGRATION:
            raise ValueError('Only typed integration handlers can be registered')
        self.handlers[operation]=handler

    def register_workspace(self, run_id: str, path: Path) -> None:
        # Bridge only consumes its opaque workspace_id/repo layout, never an arbitrary path.
        canonical_path=path.absolute()
        if canonical_path.resolve()!=canonical_path or not canonical_path.is_relative_to(self.server.workspace_root):
            raise BridgeError('WORKSPACE_UNSAFE')

    def http_json(self, method: str, path: str, payload=None, *, raw=None, headers=None) -> dict:
        body=raw if raw is not None else canonical(payload) if payload is not None else None
        req=urllib.request.Request(self.api_url+path,data=body,method=method,
            headers={'Authorization':'Bearer '+self.device_token,'Content-Type':'application/json',**(headers or {})})
        opener=urllib.request.build_opener(_NoRedirect(),urllib.request.HTTPSHandler(context=self.ssl_context))
        with opener.open(req,timeout=120) as response:
            content=response.read(MAX_MESSAGE)
            return json.loads(content)

    async def prepare_source(self,payload,envelope):
        prepared=await asyncio.to_thread(self.source_adapter.prepare,payload,
            deadline=time.monotonic()+min(MAX_TTL_SECONDS,envelope['expires_at']-time.time()))
        transfer_id=payload['transfer_id']
        authorization=await asyncio.to_thread(self.http_json,'POST',f'/source-transfers/{transfer_id}/authorize-upload',prepared.receipt)
        result=await asyncio.to_thread(self.http_json,'PUT',f'/source-transfers/{transfer_id}/content',raw=prepared.bundle_path.read_bytes(),
            headers={'X-Source-Upload-Token':authorization['upload_token']})
        return result

    async def install_workspace(self,payload,envelope):
        path=await asyncio.to_thread(self.source_adapter.install_workspace,payload)
        self.register_workspace(payload['run_id'],path)
        return {'workspace_id':payload['workspace_id'],'installed':True}

    async def issue_create(self,payload,envelope):
        return await self.issue_adapter.create(payload,envelope)

    async def issue_query(self,payload,envelope):
        return await self.issue_adapter.query(payload,envelope)

    async def dispatch(self,envelope: dict) -> dict:
        if (envelope.get('type')!='request' or envelope.get('transport')!=TRANSPORT
            or envelope.get('node_id')!=self.node_id or envelope.get('operation') not in OPERATIONS
            or not isinstance(envelope.get('payload'),dict) or len(canonical(envelope))>MAX_MESSAGE
            or envelope.get('input_sha256')!=digest(envelope['payload'])):
            raise BridgeError('INVALID_REQUEST')
        remaining=envelope.get('expires_at',0)-time.time()
        if not 0<remaining<=MAX_TTL_SECONDS+1:
            raise BridgeError('AUTHORIZATION_EXPIRED')
        operation,payload=envelope['operation'],envelope['payload']
        management=envelope.get('authority')=='management'
        if self._revoked and not management:
            raise BridgeError('DEVICE_AUTHORIZATION_REVOKED')
        if management and operation not in BRIDGE_MANAGEMENT | {'issue_query','install_workspace'}:
            raise BridgeError('AUTHORIZATION_REJECTED')
        if operation=='install_workspace':
            if type(payload.get('create')) is not bool or management is payload['create']:
                raise BridgeError('WORKSPACE_SCOPE_REJECTED')
            context=payload.get('context') or {}
            if context.get('run_id')!=payload.get('run_id') or context.get('workspace_id')!=payload.get('workspace_id'):
                raise BridgeError('WORKSPACE_SCOPE_REJECTED')
            if context.get('harness_host_id')!=self.server.host_id:
                raise BridgeError('HOST_MISMATCH')
            if not management and not 0<context.get('expires_at',0)-time.time()<=MAX_TTL_SECONDS:
                raise BridgeError('AUTHORIZATION_EXPIRED')
        if operation in INTEGRATION:
            handler=self.handlers.get(operation)
            if handler is None:
                raise BridgeError('CAPABILITY_UNSUPPORTED')
            return await handler(payload,envelope)
        if operation!='capabilities':
            context=payload.get('context') or {}
            if context.get('harness_host_id')!=self.server.host_id:
                raise BridgeError('HOST_MISMATCH')
            if not management:
                ttl=min(context.get('expires_at',0),envelope['expires_at'])-time.time()
                if not 0<ttl<=MAX_TTL_SECONDS:
                    raise BridgeError('AUTHORIZATION_EXPIRED')
                if operation in {'create_session','execute','resume'}:
                    self.server.workspace(context.get('workspace_id'))
                if operation in {'execute','resume','renew'}:
                    self._deadlines[payload['call_id']]=asyncio.get_running_loop().time()+ttl
        result=await self.bridge.request(operation,payload,management=management)
        if operation=='capabilities':
            result.update({'connector_transport':TRANSPORT,'local_authorization':True,
                'source_acquisition':'prepare_source' in self.handlers,'issue_executor':'issue_create' in self.handlers})
        return result

    async def handle(self,websocket,envelope):
        try:
            result=await self.dispatch(envelope)
            response={'type':'response','request_id':envelope['request_id'],'ok':True,'result':result}
        except BridgeError as exc:
            response={'type':'response','request_id':envelope.get('request_id'),'ok':False,'error':exc.code}
        except Exception:
            # Never send exception messages: CLI/HTTP errors can contain credentials.
            LOG.exception('Local typed connector operation failed',exc_info=False)
            response={'type':'response','request_id':envelope.get('request_id'),'ok':False,'error':'CONNECTOR_OPERATION_FAILED'}
        async with self._send_lock:
            try:
                await websocket.send(canonical(response).decode())
            except ConnectionClosed:
                pass

    async def watchdog(self):
        while True:
            await asyncio.sleep(.2)
            now=asyncio.get_running_loop().time()
            for call_id,deadline in list(self._deadlines.items()):
                call=self.server.calls.get(call_id)
                if call and call['status']=='RUNNING' and now>=deadline:
                    await self.server.stop(call_id,'CONNECTOR_GRANT_EXPIRED')
                if now>=deadline:
                    self._deadlines.pop(call_id,None)

    async def revoke(self):
        self._revoked=True
        for call_id,call in list(self.server.calls.items()):
            if call['status']=='RUNNING':
                await self.server.stop(call_id,'CONNECTOR_DEVICE_REVOKED')

    async def connected(self,websocket):
        capabilities=await self.bridge.capabilities()
        capabilities.update({'source_acquisition':self.source_adapter is not None,'issue_executor':self.issue_adapter is not None,
            'source_symlinks':False,'source_lfs':False,'source_submodules':False})
        await websocket.send(canonical(hello(self.node_id,capabilities)).decode())
        async with asyncio.timeout(10):
            ack=json.loads(await websocket.recv())
        if ack.get('type')!='hello_ack' or ack.get('transport')!=TRANSPORT:
            raise BridgeError('CAPABILITY_UNSUPPORTED')
        async def heartbeat():
            while True:
                await asyncio.sleep(5)
                async with self._send_lock:
                    await websocket.send(canonical({'type':'heartbeat'}).decode())
        pulse=asyncio.create_task(heartbeat())
        try:
            async for raw in websocket:
                envelope=json.loads(raw)
                if envelope.get('type')=='grants_revoked':
                    for call_id in envelope.get('call_ids',[]):
                        call=self.server.calls.get(call_id)
                        if call and call['status']=='RUNNING':
                            await self.server.stop(call_id,'CONNECTOR_GRANT_REVOKED')
                    continue
                if envelope.get('type')=='revoked':
                    await self.revoke()
                    continue
                if envelope.get('type')!='request':
                    raise BridgeError('INVALID_REQUEST')
                request_id=envelope.get('request_id')
                # SENT messages are not resent by platform. Duplicate IDs are rejected locally.
                if request_id in self._inflight or len(self._inflight)>=32:
                    raise BridgeError('CONNECTOR_QUEUE_FULL')
                task=asyncio.create_task(self.handle(websocket,envelope))
                self._inflight[request_id]=task
                task.add_done_callback(lambda _task,key=request_id:self._inflight.pop(key,None))
        finally:
            pulse.cancel()
            await asyncio.gather(pulse,return_exceptions=True)

    async def run(self,stopping: asyncio.Event):
        await self.server.start()
        watchdog=asyncio.create_task(self.watchdog())
        stop_waiter=asyncio.create_task(stopping.wait())
        ws_url=self.api_url.replace('https://','wss://',1).replace('http://','ws://',1)+'/harness-connectors/ws'
        try:
            while not stopping.is_set():
                try:
                    async with _StrictConnect(ws_url,additional_headers={'Authorization':'Bearer '+self.device_token},
                        ssl=self.ssl_context if ws_url.startswith('wss:') else None,max_size=MAX_MESSAGE,
                        max_queue=32,open_timeout=15,close_timeout=5) as websocket:
                        connection=asyncio.create_task(self.connected(websocket))
                        done,_=await asyncio.wait({connection,stop_waiter},return_when=asyncio.FIRST_COMPLETED)
                        if stop_waiter in done:
                            connection.cancel()
                        await asyncio.gather(connection,return_exceptions=True)
                except (OSError,ConnectionClosed,InvalidHandshake,BridgeError,ValueError,TimeoutError):
                    LOG.info('Connector channel unavailable; calls retain only their existing TTL')
                if not stopping.is_set():
                    await asyncio.wait({stop_waiter},timeout=2)
        finally:
            watchdog.cancel()
            stop_waiter.cancel()
            await asyncio.gather(watchdog,stop_waiter,return_exceptions=True)
            await self.server.shutdown()
            if self._inflight:
                await asyncio.gather(*list(self._inflight.values()),return_exceptions=True)


def private_key(path: Path) -> bytes:
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('Connector keys must be private regular files')
        return path.read_bytes().strip()
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    key=secrets.token_hex(32).encode()
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(key)
    return key
