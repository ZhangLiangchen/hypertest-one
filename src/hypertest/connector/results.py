"""Allowlisted projections at the device boundary; provider transcripts never persist."""
from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from hypertest.connector.protocol import ERROR_CODE, TRANSPORT
from hypertest.harness_bridge.protocol import PROFILE, PROTOCOL, TOOLS, BridgeError, canonical
from hypertest.harness_bridge.protocol import TRANSPORT as BRIDGE_TRANSPORT

CALL_KEYS={'call_id','status','stopped','created_at','finished_at','elapsed_seconds','binding_epoch',
           'provider_session_id','error_code','cursor','events','pending_tools'}
SESSION_KEYS={'session_id','provider_session_id','binding_epoch','closed','recovery_required','active_call_id'}
CAPABILITY_KEYS={'transport','protocol','profile','host_id','provider','provider_version','persistent_session',
    'domain_tools','management_recovery','native_shell','native_filesystem','max_concurrent','connector_transport',
    'local_authorization','source_acquisition','issue_executor','source_symlinks','source_lfs','source_submodules'}
PROVIDER_ACTIVITIES={'SIGNAL_RECEIVED','TURN_STARTED','TURN_COMPLETED','MODEL_ACTIVITY','TOOL_STARTED',
                     'TOOL_COMPLETED','FILE_ACTIVITY','ERROR'}


def require(condition: Any) -> None:
    if not condition:
        raise BridgeError('INVALID_CONNECTOR_RESULT')


def identity(value,*,nullable=False):
    if nullable and value is None:
        return
    require(isinstance(value,str) and 0<len(value)<=512 and all(not c.isspace() and ord(c)>=32 for c in value))


def number(value,*,minimum=0,maximum=1e12):
    require(type(value) in {float,int} and math.isfinite(value) and minimum<=value<=maximum)


def capabilities(result: dict) -> dict:
    require(not set(result)-CAPABILITY_KEYS)
    require(result.get('transport')==BRIDGE_TRANSPORT and result.get('protocol')==PROTOCOL and result.get('profile')==PROFILE)
    require(result.get('persistent_session') is True and result.get('management_recovery') is True
            and result.get('native_shell') is False and result.get('native_filesystem') is False)
    identity(result.get('host_id'))
    identity(result.get('provider'))
    if result.get('provider_version') is not None:
        require(isinstance(result['provider_version'],str) and len(result['provider_version'])<=256)
    require(isinstance(result.get('domain_tools'),list) and set(result['domain_tools'])<=TOOLS)
    require(type(result.get('max_concurrent')) is int and 1<=result['max_concurrent']<=128)
    if 'connector_transport' in result:
        require(result['connector_transport']==TRANSPORT)
    for key in {'local_authorization','source_acquisition','issue_executor','source_symlinks','source_lfs','source_submodules'}&result.keys():
        require(type(result[key]) is bool)
    return result


def normalize_result(operation: str, payload: dict, result: dict, *, management: bool = False) -> dict:
    """Reject unknown wire fields before storing even an operational response.

    Management authority comes from the server's persisted request, never from
    device result fields. Its get_call projection is only a status snapshot for
    exact historical reconciliation; it cannot replay activities or tools.
    """
    require(isinstance(result,dict) and len(canonical(result))<=4_000_000)
    if operation=='capabilities':
        return capabilities(result)
    context=payload.get('context',{})
    if operation in {'create_session','restore_session','recover'}:
        require(set(result)==SESSION_KEYS and result['session_id']==context.get('session_id'))
        require(type(result['binding_epoch']) is int and result['binding_epoch']>=1)
        if operation!='restore_session':
            require(result['binding_epoch']==payload.get('new_epoch',context.get('binding_epoch')))
        identity(result['provider_session_id'],nullable=True)
        identity(result['active_call_id'],nullable=True)
        require(all(type(result[key]) is bool for key in {'closed','recovery_required'}))
    elif operation in {'execute','resume','get_call'}:
        require(set(result)==CALL_KEYS and result['call_id']==payload.get('call_id'))
        require(result['binding_epoch']==context.get('binding_epoch'))
        require(result['status'] in {'RUNNING','COMPLETED','FAILED','INTERRUPTED','OUTCOME_UNKNOWN'})
        require(type(result['stopped']) is bool and type(result['cursor']) is int and result['cursor']>=0)
        identity(result['provider_session_id'],nullable=True)
        require(result['error_code'] is None or isinstance(result['error_code'],str) and ERROR_CODE.fullmatch(result['error_code']))
        number(result['created_at'])
        number(result['elapsed_seconds'],maximum=86400)
        if result['finished_at'] is not None:
            number(result['finished_at'],minimum=result['created_at'])
            require(result['stopped'])
        require(isinstance(result['events'],list) and len(result['events'])<=256)
        previous=payload.get('cursor',0)
        snapshot = management and operation == 'get_call'
        for index,event in enumerate(result['events']):
            require(isinstance(event,dict) and set(event)=={'sequence','type','payload'})
            require(type(event['sequence']) is int and previous<event['sequence']<=result['cursor'])
            # A retained suffix may begin after cursor only in a management
            # snapshot. Polling execution still fails on every cursor gap, and
            # gaps inside even the retained management suffix remain invalid.
            if event['sequence']!=previous+1 and not (snapshot and index==0):
                raise BridgeError('EVENT_CURSOR_GAP')
            previous=event['sequence']
            event_payload=event['payload']
            require(isinstance(event_payload,dict))
            if event['type']=='SESSION_STARTED':
                require(set(event_payload)=={'provider_session_id'})
                identity(event_payload['provider_session_id'])
            elif event['type']=='ACTIVITY':
                require(set(event_payload)=={'activity_kind'} and event_payload['activity_kind'] in PROVIDER_ACTIVITIES)
            elif event['type']=='TURN_FINISHED':
                require(set(event_payload)=={'return_code'} and type(event_payload['return_code']) is int and -255<=event_payload['return_code']<=255)
            elif event['type']=='ERROR':
                require(set(event_payload)=={'error_code'} and isinstance(event_payload['error_code'],str) and ERROR_CODE.fullmatch(event_payload['error_code']))
            else:
                raise BridgeError('INVALID_CONNECTOR_RESULT')
        require(isinstance(result['pending_tools'],list) and len(result['pending_tools'])<=1)
        for tool in result['pending_tools']:
            require(isinstance(tool,dict) and set(tool)=={'tool_call_id','name','arguments'} and tool['name'] in TOOLS)
            identity(tool['tool_call_id'])
            require(isinstance(tool['arguments'],dict))
            # Admission belongs to HarnessTools on the owning Worker. Invalid
            # business arguments must reach its typed rejection so the Agent can
            # correct them; they must not make read-only call reconciliation fail.
            require(len(canonical(tool['arguments']))<=3_500_000)
    elif operation=='renew':
        require(set(result)=={'expires_at'})
        number(result['expires_at'])
        require(result['expires_at']<=context.get('expires_at',0)+.001)
    elif operation=='respond_tool':
        require(result=={'accepted':True})
    elif operation in {'interrupt','close'}:
        require(set(result)=={'accepted','stopped','closed'} and all(type(v) is bool for v in result.values()))
    elif operation=='install_workspace':
        require(set(result)=={'workspace_id','installed'} and result['installed'] is True
                and UUID(result['workspace_id']).hex==UUID(payload['workspace_id']).hex)
    elif operation in {'prepare_source','source_prepare'}:
        from hypertest.api.source_transfer_schemas import SourceTransferRead
        require(set(result)==set(SourceTransferRead.model_fields))
        parsed=SourceTransferRead.model_validate(result)
        require(str(parsed.id)==payload['transfer_id'] and str(parsed.node_id)==payload['node_id']
            and str(parsed.project_id)==payload['project_id'] and parsed.origin==payload['origin']
            and parsed.commit_sha==payload['commit_sha'])
    elif operation in {'issue_create','issue_query'}:
        require(set(result)=={'operation_id','delegation_sha256','status','issue'}
            and result['operation_id']==payload['operation_id'] and result['delegation_sha256']==payload['delegation_sha256']
            and result['status'] in {'SUCCEEDED','UNKNOWN','REJECTED'})
        issue=result['issue']
        if issue is not None:
            require(isinstance(issue,dict) and set(issue)=={'iid','project_id','description','web_url','assignees'})
            require(type(issue['iid']) is int and issue['iid']>0 and issue['project_id']==payload['gitlab_project_id'])
            require(isinstance(issue['description'],str) and len(issue['description'])<=48000
                and payload['correlation'] in issue['description'])
            require(isinstance(issue['web_url'],str) and len(issue['web_url'])<=2048)
            require(issue['assignees']==[{'id':payload['assignee_id']}])
    else:
        raise BridgeError('INVALID_CONNECTOR_RESULT')
    if management and operation == 'get_call':
        return {**result,'events':[],'pending_tools':[]}
    return result
