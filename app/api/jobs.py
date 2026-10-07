from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.db import get_session
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import CertificateOut, CertificatePage, JobCreate, JobCreated, JobStatusOut
from app.services import jobs as job_service
from app.services import processor

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

SessionDep = Annotated[Session, Depends(get_session)]


def job_url(job_id: str) -> str:
    return f"/api/jobs/{job_id}/"


def certificate_download_url(cert: Certificate) -> str | None:
    if cert.status != CertificateStatus.GENERATED:
        return None
    return f"/api/certificates/{cert.id}/download"


def job_status_out(job: Job) -> JobStatusOut:
    return JobStatusOut(
        id=job.id,
        event_name=job.event_name,
        status=job.status,
        total_count=job.total_count,
        succeeded_count=job.succeeded_count,
        failed_count=job.failed_count,
        pending_count=job.pending_count,
        progress_percent=job_service.progress_percent(job),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def certificate_out(cert: Certificate) -> CertificateOut:
    return CertificateOut(
        id=cert.id,
        row_index=cert.row_index,
        recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email,
        certificate_number=cert.certificate_number,
        status=cert.status,
        error=cert.error,
        download_url=certificate_download_url(cert),
    )


@router.post("/", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
def submit_job(
    payload: JobCreate,
    response: Response,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> JobCreated:
    """Accept a bulk request. Returns immediately; certificates are generated in the background."""
    job = job_service.create_job(session, payload)
    if job.status == JobStatus.PENDING:
        # The only line that decides *how* the work runs. Swap for a task queue to scale out.
        background_tasks.add_task(processor.process_job, job.id)

    url = job_url(job.id)
    response.headers["Location"] = url
    return JobCreated(
        id=job.id,
        status=job.status,
        total_count=job.total_count,
        accepted_count=job.total_count - job.failed_count,
        invalid_count=job.failed_count,
        status_url=url,
    )


@router.get("/{job_id}/", response_model=JobStatusOut)
def get_job_status(job_id: str, session: SessionDep) -> JobStatusOut:
    """Current status, counts and progress of a job."""
    return job_status_out(job_service.get_job(session, job_id))


@router.get("/{job_id}/certificates/", response_model=CertificatePage)
def list_job_certificates(
    job_id: str,
    session: SessionDep,
    status: Annotated[
        CertificateStatus | None,
        Query(description="Only rows with this status, e.g. FAILED or INVALID"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CertificatePage:
    """Per-recipient results in submission order. Filter by status to find what went wrong."""
    job = job_service.get_job(session, job_id)
    total, items = job_service.list_certificates(session, job.id, status, limit, offset)
    return CertificatePage(
        job_id=job.id,
        total=total,
        limit=limit,
        offset=offset,
        items=[certificate_out(cert) for cert in items],
    )


@router.get(
    "/{job_id}/download",
    response_class=FileResponse,
    responses={200: {"content": {"application/zip": {}}, "description": "Zip of all PDFs"}},
)
def download_job(job_id: str, session: SessionDep) -> FileResponse:
    """Download every generated certificate of a finished job as one zip."""
    path, filename = job_service.job_zip(session, job_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
