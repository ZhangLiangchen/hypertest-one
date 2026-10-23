"""Single-operator admission and independently revocable device/project scopes."""
import hashlib
import hmac
from datetime import datetime
from uuid import UUID

from fastapi import Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.config import get_settings
from hypertest.domain.connector import HarnessDeviceGrant, HarnessNode, NodeProjectCapability
from hypertest.domain.models import Project
from hypertest.harness_bridge.protocol import BridgeError


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def require_operator(x_hypertest_operator_key: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if not settings.connector_operator_key:
        raise HTTPException(503, 'Connector operator key is not configured')
    if not x_hypertest_operator_key or not hmac.compare_digest(x_hypertest_operator_key, settings.connector_operator_key):
        raise HTTPException(401, 'Operator authorization required')
    return settings.connector_operator_identity


async def authenticate_device(db: AsyncSession, token: str, node_id: UUID | None = None,
                              *, allow_revoked: bool = False) -> tuple[HarnessNode, HarnessDeviceGrant]:
    if not token or len(token) > 512:
        raise BridgeError('DEVICE_AUTHORIZATION_REJECTED')
    grant = await db.scalar(select(HarnessDeviceGrant).where(HarnessDeviceGrant.token_hash == token_hash(token)).execution_options(populate_existing=True))
    if grant is None or (node_id is not None and grant.node_id != node_id):
        raise BridgeError('DEVICE_AUTHORIZATION_REJECTED')
    node = await db.get(HarnessNode, grant.node_id,populate_existing=True)
    if node is None:
        raise BridgeError('DEVICE_AUTHORIZATION_REJECTED')
    now = await db.scalar(select(func.clock_timestamp()))
    if not allow_revoked and (node.registration_status != 'ACTIVE' or grant.status != 'ACTIVE'
                             or not grant.not_before <= now < grant.expires_at):
        raise BridgeError('DEVICE_AUTHORIZATION_REVOKED')
    # A known revoked/expired identity may reconnect only for exact cleanup/query.
    return node, grant


async def require_capability(db: AsyncSession, node_id: UUID, project_id: UUID,
                             capability: str) -> NodeProjectCapability:
    # New dispatch/upload acceptance and final delivery share this admission
    # boundary. Cleanup and original receipt queries use their management paths.
    project = await db.scalar(select(Project).where(Project.id == project_id)
                              .with_for_update(read=True).execution_options(populate_existing=True))
    if project is None or project.deleted_at is not None:
        raise BridgeError('PROJECT_CAPABILITY_REJECTED')
    scope = await db.scalar(select(NodeProjectCapability).where(
        NodeProjectCapability.node_id == node_id, NodeProjectCapability.project_id == project_id,
        NodeProjectCapability.capability == capability, NodeProjectCapability.status == 'ACTIVE').execution_options(populate_existing=True))
    node = await db.get(HarnessNode, node_id,populate_existing=True)
    if scope is None or node is None or node.registration_status != 'ACTIVE':
        raise BridgeError('PROJECT_CAPABILITY_REJECTED')
    return scope


async def validate_issue_request(db: AsyncSession, node_id: UUID, payload: dict, *, create: bool, now) -> None:
    """Only the immutable approved executor delegation can reach the local adapter."""
    from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
    from hypertest.domain.harness import GitLabIssueOperation
    from hypertest.domain.issue_executor import GitLabIssueOperationExecutor
    from hypertest.domain.jobs import DurableJob, JobStatus
    try:
        operation_id=UUID(payload['operation_id'])
        deadline=datetime.fromisoformat(payload['expires_at'])
    except (KeyError,ValueError,TypeError) as exc:
        raise BridgeError('ISSUE_DELEGATION_REJECTED') from exc
    executor=await db.scalar(select(GitLabIssueOperationExecutor).where(GitLabIssueOperationExecutor.operation_id==operation_id))
    operation=await db.get(GitLabIssueOperation,operation_id)
    if (not executor or not operation or executor.executor_mode!='LOCAL_CONNECTOR' or executor.executor_node_id!=node_id
        or {k:v for k,v in payload.items() if k not in {'expires_at','delegation_sha256'}}!=executor.delegation
        or payload.get('delegation_sha256')!=executor.delegation_sha256
        or deadline.tzinfo is None or not now<deadline or (deadline-now).total_seconds()>120):
        raise BridgeError('ISSUE_DELEGATION_REJECTED')
    if create:
        binding=await db.get(RunExecutionBinding,operation.binding_id)
        job=await db.get(DurableJob,operation.durable_job_id)
        scope=await require_capability(db,node_id,UUID(payload['project_id']),'issue_executor')
        device=await db.get(HarnessDeviceGrant,executor.device_grant_id)
        constraints=scope.constraints
        if (scope.id!=executor.capability_id or not device or device.status!='ACTIVE' or device.expires_at<=now
            or device.node_id!=node_id or device.not_before>now or not job.lease_token
            or operation.status!='PENDING' or binding.status!=BindingStatus.ACTIVE
            or binding.binding_epoch!=payload['binding_epoch'] or job.status!=JobStatus.RUNNING
            or not job.lease_expires_at or deadline>job.lease_expires_at or deadline>device.expires_at
            or constraints.get('integration_id')!=payload['integration_id']
            or constraints.get('base_url')!=payload['base_url']
            or constraints.get('gitlab_project_id')!=payload['gitlab_project_id']
            or payload['assignee_id'] not in constraints.get('assignee_ids',[])):
            raise BridgeError('ISSUE_DELEGATION_REJECTED')


async def validate_workspace_request(db: AsyncSession, node_id: UUID, payload: dict, *, create: bool) -> None:
    from hypertest.domain.harness_selection import RunHarnessSelection
    from hypertest.domain.models import SourceSnapshot, TestRun
    from hypertest.domain.source_transfer import SourceBundleTransfer
    try:
        context=payload['context']
        run_id=UUID(payload['run_id'])
        transfer_id=UUID(payload['transfer_id'])
        require_workspace=(str(run_id)==context['run_id']
            and UUID(payload['workspace_id']).hex==UUID(context['workspace_id']).hex
            and payload['create'] is create)
    except (KeyError,ValueError,TypeError) as exc:
        raise BridgeError('WORKSPACE_SCOPE_REJECTED') from exc
    selected=await db.get(RunHarnessSelection,run_id,populate_existing=True)
    run=await db.get(TestRun,run_id,populate_existing=True)
    source=await db.get(SourceSnapshot,run.source_snapshot_id) if run else None
    transfer=await db.get(SourceBundleTransfer,transfer_id,populate_existing=True)
    if (not require_workspace or not selected or not source or not transfer or transfer.status!='ACCEPTED'
        or selected.node_id!=node_id or selected.source_bundle_transfer_id!=transfer_id or transfer.node_id!=node_id
        or transfer.project_id!=run.project_id or payload.get('project_id')!=str(run.project_id)
        or transfer.origin!=source.repository_url or transfer.commit_sha!=source.commit_sha
        or payload.get('origin')!=transfer.origin or payload.get('commit_sha')!=transfer.commit_sha
        or payload.get('bundle_sha256')!=transfer.bundle_sha256 or payload.get('root_tree')!=transfer.root_tree):
        raise BridgeError('WORKSPACE_SCOPE_REJECTED')
    if create:
        scope=await require_capability(db,node_id,run.project_id,'source_acquisition')
        if (scope.id!=transfer.source_capability_id or scope.policy_version!=transfer.policy_version
            or transfer.origin not in scope.constraints.get('allowed_origins',[])):
            raise BridgeError('SOURCE_ACQUISITION_SCOPE_REJECTED')
