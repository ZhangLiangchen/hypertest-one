"""Actual local Bridge/Connector lifecycle; provider is an explicit boundary fixture."""
import asyncio
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from test_harness_bridge import BoundaryProvider, context, contract, until_call

from hypertest.connector.daemon import ConnectorDaemon, checked_url
from hypertest.connector.protocol import TRANSPORT, claim_identity, digest
from hypertest.harness_bridge.protocol import BridgeError
from hypertest.harness_bridge.server import BridgeServer


@pytest.fixture
async def local_connector():
    with tempfile.TemporaryDirectory(prefix='htc-',dir='/tmp') as tmp:
        root=Path(tmp).resolve()
        provider=BoundaryProvider()
        server=BridgeServer(socket_path=root/'c.sock',tool_socket_path=root/'t.sock',state_dir=root/'journal',
            workspace_root=root/'workspaces',host_id='host-test',execution_key=b'e'*32,management_key=b'm'*32,provider=provider)
        daemon=ConnectorDaemon(api_url='https://localhost/api/v1',node_id=str(uuid4()),device_token='private-device-token',server=server)
        await server.start()
        watchdog=asyncio.create_task(daemon.watchdog())
        try:
            yield daemon,server,provider
        finally:
            watchdog.cancel()
            await asyncio.gather(watchdog,return_exceptions=True)
            await server.shutdown()


def envelope(daemon,operation,payload,*,management=False,ttl=20):
    return {'type':'request','transport':TRANSPORT,'node_id':daemon.node_id,'request_id':str(uuid4()),
        'operation':operation,'authority':'management' if management else 'execution','payload':payload,
        'input_sha256':digest(payload),'expires_at':time.time()+ttl}


async def test_connector_reuses_bridge_native_session_and_queries_without_replay(local_connector):
    daemon,server,provider=local_connector
    ctx=context(server)
    await daemon.dispatch(envelope(daemon,'create_session',{'context':ctx.to_dict()}))
    await daemon.dispatch(envelope(daemon,'execute',{'context':ctx.to_dict(),'contract':contract(),'call_id':'one','idempotency_key':'one'}))
    first=await until_call(daemon.bridge,ctx,'one',lambda c:c['stopped'])
    for _ in range(2):
        found=await daemon.dispatch(envelope(daemon,'get_call',{'context':ctx.to_dict(),'call_id':'one','cursor':0},management=True))
        assert found['provider_session_id']==first['provider_session_id']
    assert len(provider.invocations)==1
    await daemon.dispatch(envelope(daemon,'resume',{'context':ctx.to_dict(),'contract':contract(),'call_id':'two','idempotency_key':'two'}))
    second=await until_call(daemon.bridge,ctx,'two',lambda c:c['stopped'])
    assert second['provider_session_id']==first['provider_session_id']


async def test_connector_monotonic_expiry_stops_call_without_reconnect_replay(local_connector):
    daemon,server,provider=local_connector
    ctx=context(server,expires_at=time.time()+1)
    await daemon.dispatch(envelope(daemon,'create_session',{'context':ctx.to_dict()}))
    await daemon.dispatch(envelope(daemon,'execute',{'context':ctx.to_dict(),'contract':contract('wait'),'call_id':'offline','idempotency_key':'offline'}))
    await until_call(daemon.bridge,ctx,'offline',lambda c:bool(c['provider_session_id']))
    stopped=await until_call(daemon.bridge,ctx,'offline',lambda c:c['stopped'])
    assert stopped['status'] in {'INTERRUPTED','OUTCOME_UNKNOWN'}
    assert len(provider.invocations)==1
    with pytest.raises(BridgeError,match='AUTHORIZATION_EXPIRED'):
        await daemon.dispatch(envelope(daemon,'renew',{'context':ctx.to_dict(),'call_id':'offline'}))


async def test_revoked_device_keeps_exact_cleanup_but_rejects_execution(local_connector):
    daemon,server,provider=local_connector
    ctx=context(server)
    await daemon.dispatch(envelope(daemon,'create_session',{'context':ctx.to_dict()}))
    await daemon.dispatch(envelope(daemon,'execute',{'context':ctx.to_dict(),'contract':contract('wait'),'call_id':'revoked','idempotency_key':'revoked'}))
    await until_call(daemon.bridge,ctx,'revoked',lambda c:bool(c['provider_session_id']))
    await daemon.revoke()
    management=replace(ctx,claim_token='management',expires_at=0)
    found=await daemon.dispatch(envelope(daemon,'get_call',{'context':management.to_dict(),'call_id':'revoked'},management=True))
    assert found['stopped']
    with pytest.raises(BridgeError,match='DEVICE_AUTHORIZATION_REVOKED'):
        await daemon.dispatch(envelope(daemon,'resume',{'context':ctx.to_dict(),'contract':contract(),'call_id':'bad','idempotency_key':'bad'}))
    assert len(provider.invocations)==1


async def test_envelope_is_typed_scoped_and_does_not_create_unprepared_workspace(local_connector):
    daemon,server,_=local_connector
    ctx=context(server)
    (server.workspace_root/ctx.workspace_id/'repo').rmdir()
    with pytest.raises(BridgeError,match='WORKSPACE_UNAVAILABLE'):
        await daemon.dispatch(envelope(daemon,'create_session',{'context':ctx.to_dict()}))
    with pytest.raises(BridgeError,match='INVALID_REQUEST'):
        await daemon.dispatch(envelope(daemon,'shell',{'command':'whoami'}))
    with pytest.raises(BridgeError,match='AUTHORIZATION_REJECTED'):
        await daemon.dispatch(envelope(daemon,'resume',{},management=True))
    wrong=envelope(daemon,'capabilities',{},management=True)
    wrong['node_id']=str(uuid4())
    with pytest.raises(BridgeError,match='INVALID_REQUEST'):
        await daemon.dispatch(wrong)


def test_device_claim_is_stable_scoped_and_hides_lease_secret():
    token=str(uuid4())
    first=claim_identity('node-1',token)
    assert first==claim_identity('node-1',token)
    assert first!=claim_identity('node-2',token) and token not in first and len(first)==64
    with pytest.raises(ValueError,match='HTTPS'):
        checked_url('http://example.com/api/v1')
    with pytest.raises(ValueError):
        checked_url('https://user:secret@example.com')
    assert checked_url('http://127.0.0.1',allow_insecure_loopback=True)=='http://127.0.0.1'


async def test_connector_wire_results_reject_transcripts_but_preserve_business_rejections(local_connector):
    from copy import deepcopy

    from hypertest.connector.results import normalize_result
    daemon,server,_=local_connector
    ctx=context(server)
    session=await daemon.dispatch(envelope(daemon,'create_session',{'context':ctx.to_dict()}))
    assert normalize_result('create_session',{'context':ctx.to_dict()},session)==session
    await daemon.dispatch(envelope(daemon,'execute',{'context':ctx.to_dict(),'contract':contract(),'call_id':'typed','idempotency_key':'typed'}))
    result=await until_call(daemon.bridge,ctx,'typed',lambda c:c['stopped'])
    request={'context':ctx.to_dict(),'call_id':'typed','cursor':0}
    assert normalize_result('get_call',request,result)==result
    for bad in [{**result,'reasoning':'private provider transcript'},
                {**result,'events':[{'sequence':1,'type':'ACTIVITY','payload':{'activity_kind':'MODEL_ACTIVITY','text':'private'}}]},
                {**result,'pending_tools':[{'tool_call_id':'tool-1','name':'unregistered_tool','arguments':{}}]}]:
        with pytest.raises(BridgeError):
            normalize_result('get_call',request,bad)
    # A provider can submit an invalid business value. The owning Worker must
    # return a typed rejection; management call queries must stay available.
    invalid_business={**result,'pending_tools':[{'tool_call_id':'bad-business','name':'get_state',
        'arguments':{'resource':'nonexistent-resource'}}]}
    assert normalize_result('get_call',request,invalid_business)==invalid_business
    from hypertest.application.harness_tools import TOOL_MODELS
    with pytest.raises(ValueError):
        TOOL_MODELS['get_state'][0].model_validate(invalid_business['pending_tools'][0]['arguments'])
    bad=deepcopy(result)
    bad['events'][0]['sequence']=3
    bad['cursor']=max(3,bad['cursor'])
    with pytest.raises(BridgeError,match='EVENT_CURSOR_GAP'):
        normalize_result('get_call',request,bad)
    capabilities=await daemon.bridge.capabilities()
    with pytest.raises(BridgeError):
        normalize_result('capabilities',{},dict(capabilities,raw_stdout='provider transcript'))
