"""Worker-side Bridge-compatible client using the PostgreSQL connector mailbox."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from hypertest.agent.bridge import BridgeClient
from hypertest.connector.mailbox import expire_requests
from hypertest.connector.protocol import (
    BRIDGE_MANAGEMENT,
    INTEGRATION,
    MAX_MESSAGE,
    MAX_QUEUE,
    MAX_TTL_SECONDS,
    OPERATIONS,
    claim_identity,
    digest,
)
from hypertest.connector.security import (
    require_capability,
    validate_issue_request,
    validate_workspace_request,
)
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.connector import (
    ConnectorRequest,
    HarnessDeviceGrant,
    HarnessDispatchGrant,
    HarnessNode,
    RunHarnessPlacement,
)
from hypertest.domain.jobs import DurableJob, JobStatus
from hypertest.domain.models import AgentSessionRecord, TestRun
from hypertest.harness_bridge.protocol import BridgeError, canonical


class RemoteBridgeClient(BridgeClient):
    def __init__(self, node_id: UUID | str, session_factory=None, *, project_id: UUID | str | None = None, timeout: float = 20) -> None:
        if session_factory is None:
            from hypertest.db.session import AsyncSessionLocal
            session_factory = AsyncSessionLocal
        self.node_id = UUID(str(node_id))
        self.project_id = UUID(str(project_id)) if project_id else None
        self.session_factory = session_factory
        self.timeout = timeout

    async def request(self, operation: str, payload: dict[str, Any] | None = None,
                      *, management: bool = False) -> dict[str, Any]:
        if operation not in OPERATIONS or (management and operation not in BRIDGE_MANAGEMENT | {'issue_query','install_workspace'}):
            raise BridgeError('CAPABILITY_UNSUPPORTED')
        payload = dict(payload or {})
        if len(canonical(payload)) > MAX_MESSAGE - 4096:
            raise BridgeError('REQUEST_TOO_LARGE')
        async with self.session_factory() as db:
            now = await db.scalar(select(func.clock_timestamp()))
            node = await db.get(HarnessNode, self.node_id,with_for_update=True)
            if node is None:
                raise BridgeError('NODE_UNAVAILABLE')
            grant = await db.scalar(select(HarnessDeviceGrant).where(
                HarnessDeviceGrant.node_id == self.node_id, HarnessDeviceGrant.status == 'ACTIVE',
                HarnessDeviceGrant.not_before <= now, HarnessDeviceGrant.expires_at > now)
                .order_by(HarnessDeviceGrant.created_at.desc()).limit(1))
            if not management and (node.registration_status != 'ACTIVE' or grant is None):
                raise BridgeError('DEVICE_AUTHORIZATION_REVOKED')
            if not management and (node.presence!='ONLINE' or not node.last_seen_at or now-node.last_seen_at>timedelta(seconds=15)):
                raise BridgeError('NODE_OFFLINE')
            await expire_requests(db,self.node_id,now=now,connection_generation=node.connection_generation)
            pending = await db.scalar(select(func.count()).select_from(ConnectorRequest).where(
                ConnectorRequest.node_id == self.node_id, ConnectorRequest.status.in_(['QUEUED','SENT'])))
            if pending >= MAX_QUEUE:
                raise BridgeError('CONNECTOR_QUEUE_FULL')
            dispatch = None
            expires_at = now + timedelta(seconds=min(MAX_TTL_SECONDS, max(self.timeout, 10)))
            authority = 'management' if management else 'execution'
            if operation=='install_workspace':
                create=payload.get('create')
                if type(create) is not bool or management is create:
                    raise BridgeError('WORKSPACE_SCOPE_REJECTED')
                context=dict(payload.get('context') or {})
                binding,placement,job,agent,run=await self._scope(db,context,execution=create,now=now,operation=operation)
                await validate_workspace_request(db,self.node_id,payload,create=create)
                context['claim_token']=claim_identity(str(self.node_id),context['claim_token'])
                authority='execution' if create else 'management'
                if create:
                    scope=await require_capability(db,self.node_id,run.project_id,'harness')
                    expires_at=min(expires_at,job.lease_expires_at,datetime.fromtimestamp(context['expires_at'],UTC),grant.expires_at)
                    if expires_at<=now:
                        raise BridgeError('AUTHORIZATION_EXPIRED')
                    context['expires_at']=expires_at.timestamp()
                    dispatch=HarnessDispatchGrant(node_id=self.node_id,project_id=run.project_id,placement_id=placement.id,
                        binding_id=binding.id,session_id=agent.id,job_id=job.id,device_grant_id=grant.id,capability_id=scope.id,
                        workspace_id=context['workspace_id'],claim_identity=context['claim_token'],binding_epoch=context['binding_epoch'],
                        call_id=context['session_id'],operation=operation,not_before=now,expires_at=expires_at)
                    db.add(dispatch)
                    await db.flush()
                payload['context']=context
            elif operation in INTEGRATION:
                authority = 'management' if management else 'integration'
                payload['project_id'] = payload.get('project_id') or payload.get('hypertest_project_id')
                if not payload.get('project_id') or str(payload.get('node_id',self.node_id)) != str(self.node_id):
                    raise BridgeError('INVALID_INTEGRATION_SCOPE')
                if operation=='issue_create':
                    prior=await db.scalar(select(ConnectorRequest.id).where(ConnectorRequest.operation=='issue_create',
                        ConnectorRequest.payload['operation_id'].astext==payload.get('operation_id')))
                    if prior:
                        raise BridgeError('OUTCOME_UNKNOWN','Issue create already has a consumed delivery identity; query the original operation')
                if operation in {'issue_create','issue_query'}:
                    await validate_issue_request(db,self.node_id,payload,create=operation=='issue_create',now=now)
                    expires_at=min(expires_at,datetime.fromisoformat(payload['expires_at']))
                capability = 'source_acquisition' if operation in {'prepare_source','source_prepare','install_workspace'} else 'issue_executor'
                if not management:
                    await require_capability(db,self.node_id,UUID(payload['project_id']),capability)
                payload['node_id'] = str(self.node_id)
            elif operation == 'capabilities':
                if self.project_id:
                    await require_capability(db,self.node_id,self.project_id,'harness')
            else:
                context = dict(payload.get('context') or {})
                binding, placement, job, agent, run = await self._scope(db, context, execution=not management, now=now,operation=operation)
                context['claim_token'] = claim_identity(str(self.node_id), context['claim_token'])
                if not management:
                    scope = await require_capability(db,self.node_id,run.project_id,'harness')
                    expires_at = min(expires_at,job.lease_expires_at,datetime.fromtimestamp(context['expires_at'],UTC),grant.expires_at)
                    if expires_at <= now:
                        raise BridgeError('AUTHORIZATION_EXPIRED')
                    context['expires_at'] = expires_at.timestamp()
                    dispatch = HarnessDispatchGrant(node_id=self.node_id, project_id=run.project_id,
                        placement_id=placement.id,binding_id=binding.id,session_id=agent.id,job_id=job.id,
                        device_grant_id=grant.id,capability_id=scope.id,workspace_id=context['workspace_id'],
                        claim_identity=context['claim_token'],binding_epoch=context['binding_epoch'],
                        call_id=payload.get('call_id') or context['session_id'],operation=operation,
                        not_before=now,expires_at=expires_at)
                    db.add(dispatch)
                    await db.flush()
                payload['context'] = context
            row = ConnectorRequest(node_id=self.node_id,operation=operation,authority=authority,
                payload=payload,input_sha256=digest(payload),expires_at=expires_at,
                dispatch_grant_id=dispatch.id if dispatch else None,
                connection_generation=node.connection_generation if not management else None)
            db.add(row)
            await db.commit()
            request_id = row.id
        deadline = asyncio.get_running_loop().time() + self.timeout
        while asyncio.get_running_loop().time() < deadline:
            async with self.session_factory() as db:
                row = await db.get(ConnectorRequest, request_id)
                if row.status == 'SUCCEEDED':
                    return row.result or {}
                if row.status == 'FAILED':
                    raise BridgeError(row.error_code or 'CONNECTOR_ERROR')
                if row.status == 'UNKNOWN':
                    raise BridgeError('OUTCOME_UNKNOWN','Connector delivery uncertain; query original call before retry')
            await asyncio.sleep(0.1)
        async with self.session_factory() as db:
            row = await db.get(ConnectorRequest,request_id,with_for_update=True)
            if row.status in {'QUEUED','SENT'}:
                row.status,row.error_code,row.finished_at = 'UNKNOWN','RESPONSE_UNAVAILABLE',datetime.now(UTC)
                await db.commit()
        raise BridgeError('OUTCOME_UNKNOWN','Connector response unavailable; reconcile original call before retry')

    async def _scope(self, db, context: dict, *, execution: bool, now,operation: str):
        try:
            run = await db.get(TestRun,UUID(context['run_id']))
            binding = await db.get(RunExecutionBinding,UUID(context['binding_id']))
            job = await db.get(DurableJob,UUID(context['job_id']))
            agent = await db.get(AgentSessionRecord,UUID(context['session_id']))
        except (ValueError,TypeError,KeyError) as exc:
            raise BridgeError('INVALID_CONTEXT') from exc
        placement = await db.scalar(select(RunHarnessPlacement).where(RunHarnessPlacement.binding_id == binding.id)) if binding else None
        node = await db.get(HarnessNode,self.node_id)
        if (not all((run,binding,job,agent,placement)) or placement.node_id != self.node_id
            or placement.mode != 'LOCAL_CONNECTOR' or binding.test_run_id != run.id
            or placement.test_run_id != run.id or job.test_run_id != run.id
            or binding.primary_agent_session_id != agent.id or binding.harness_host_id != node.node_key
            or context['harness_host_id'] != node.node_key or context['workspace_id'] != UUID(binding.workspace_id).hex
            or context['logical_worker_id'] != str(binding.logical_worker_id)):
            raise BridgeError('CONTEXT_SCOPE_REJECTED')
        if execution and (binding.binding_epoch != context['binding_epoch']
            or binding.status not in {BindingStatus.RESERVED,BindingStatus.ACTIVE}
            or job.status != JobStatus.RUNNING or not job.lease_token
            or str(job.lease_token) != context['claim_token'] or not job.lease_expires_at or job.lease_expires_at <= now):
            raise BridgeError('STALE_CLAIM')
        if not execution and not 1 <= int(context['binding_epoch']) <= binding.binding_epoch:
            # A lost recover ACK may leave the local handle one generation ahead.
            # Only a read-only restore can inspect that pending explicit transition.
            if not (operation=='restore_session' and binding.status==BindingStatus.RECOVERY_REQUIRED
                    and int(context['binding_epoch'])==binding.binding_epoch+1):
                raise BridgeError('STALE_BINDING')
        return binding,placement,job,agent,run
