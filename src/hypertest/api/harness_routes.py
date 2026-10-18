"""Read-only session/report views and queued trusted-worker recovery."""
import hashlib
import re
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.delivery_routes import _http_error
from hypertest.api.harness_schemas import BindingRecover, ReportRead, RunHarnessRead
from hypertest.application.bindings import get_run_binding
from hypertest.application.services import ConflictError, NotFoundError, get_test_run
from hypertest.db.session import get_db
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.harness import GitLabIssueOperation, RunHarnessState, RunReport
from hypertest.runner.artifacts import artifact_root

router = APIRouter()


def _issue_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == "https" and parsed.hostname and parsed.username is None and parsed.password is None
                and not parsed.query and not parsed.fragment and not any(character.isspace() for character in value)):
            return value
    except ValueError:
        pass
    return None


@router.get("/test-runs/{run_id}/harness", response_model=RunHarnessRead)
async def read_run_harness(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        binding = await get_run_binding(db, run_id)
        state = await db.get(RunHarnessState, binding.id) if binding else None
        reports = list(await db.scalars(select(RunReport).where(RunReport.test_run_id == run_id)
                                       .order_by(RunReport.created_at.desc(), RunReport.id.desc())))
        operations = list(await db.scalars(select(GitLabIssueOperation).where(GitLabIssueOperation.test_run_id == run_id)
                                          .order_by(GitLabIssueOperation.created_at.desc(), GitLabIssueOperation.id.desc())))
        issues = [{"id": item.id, "finding_id": item.finding_id, "status": item.status,
                   "issue_iid": item.issue_iid, "issue_url": _issue_url(item.issue_url),
                   "created_at": item.created_at, "updated_at": item.updated_at} for item in operations]
        return {"binding": binding, "state": state, "reports": reports, "issues": issues}
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.get("/test-runs/{run_id}/reports", response_model=list[ReportRead])
async def read_reports(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        return list(await db.scalars(select(RunReport).where(RunReport.test_run_id == run_id)
                                    .order_by(RunReport.created_at.desc(), RunReport.id.desc())))
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.get("/reports/{report_id}/content")
async def read_report_content(report_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(RunReport, report_id)
    if item is None:
        raise HTTPException(status_code=404, detail="report not found")
    try:
        if not re.fullmatch(r"[a-f0-9]{64}", item.content_sha256) or item.artifact_uri != f"sha256:{item.content_sha256}":
            raise ValueError("invalid content address")
        root = artifact_root()
        path = root / "sha256" / item.content_sha256[:2] / item.content_sha256
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("unsupported report artifact")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item.content_sha256:
            raise ValueError("report integrity check failed")
        content.decode("utf-8")
    except (OSError, ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=409, detail="report artifact unavailable or checksum mismatch") from exc
    return Response(content, media_type="text/plain", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.post("/bindings/{binding_id}/recover")
async def recover_binding(binding_id: UUID, payload: BindingRecover, db: AsyncSession = Depends(get_db)):
    try:
        binding = await db.get(RunExecutionBinding, binding_id)
        if binding is None:
            raise NotFoundError("run execution binding not found")
        if (binding.status is not BindingStatus.RECOVERY_REQUIRED or binding.binding_epoch != payload.expected_epoch
                or binding.row_version != payload.expected_row_version):
            raise ConflictError("binding recovery state changed; refresh before trying again")
        # Do not hold a DB snapshot/aggregate lock while the trusted Worker verifies
        # the host session, fences the old call and validates pinned workspace bytes.
        await db.commit()
        from hypertest.application.runtime_control import request_control

        return await request_control(db, "RECOVER_BINDING", {"binding_id": str(binding_id), **payload.model_dump()})
    except RuntimeError as exc:
        raise _http_error(exc) from exc
