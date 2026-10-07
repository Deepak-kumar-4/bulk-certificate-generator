from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import JobCreate, JobCreated
from app.services.jobs import create_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

SessionDep = Annotated[Session, Depends(get_session)]


def job_url(job_id: str) -> str:
    return f"/api/jobs/{job_id}/"


@router.post("/", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
def submit_job(payload: JobCreate, response: Response, session: SessionDep) -> JobCreated:
    """Accept a bulk request. Returns immediately; certificates are generated in the background."""
    job = create_job(session, payload)
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
