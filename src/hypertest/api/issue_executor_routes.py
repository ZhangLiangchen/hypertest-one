"""Operator-only reconciliation of the exact original local Issue operation."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.gitlab import _view, reconcile_managed_issue
from hypertest.application.services import ConflictError
from hypertest.connector.security import require_operator
from hypertest.db.session import get_db
from hypertest.domain.harness import GitLabIssueOperation
from hypertest.domain.issue_executor import GitLabIssueOperationExecutor

router = APIRouter()


@router.get("/gitlab-issue-operations/{operation_id}", dependencies=[Depends(require_operator)])
async def get_issue_operation(operation_id: UUID, db: AsyncSession = Depends(get_db)):
    operation = await db.get(GitLabIssueOperation, operation_id)
    if operation is None:
        raise HTTPException(404, "Issue operation not found")
    executor = await db.scalar(select(GitLabIssueOperationExecutor).where(
        GitLabIssueOperationExecutor.operation_id == operation_id))
    return {**_view(operation), "executor_mode": executor.executor_mode if executor else "SERVER_HOST",
        "executor_node_id": str(executor.executor_node_id) if executor and executor.executor_node_id else None,
        "integration_id": executor.integration_id if executor else None}


@router.post("/gitlab-issue-operations/{operation_id}/reconcile")
async def reconcile_issue_operation(operation_id: UUID, operator: str = Depends(require_operator),
                                    db: AsyncSession = Depends(get_db)):
    try:
        return await reconcile_managed_issue(db, operation_id, actor=operator)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
