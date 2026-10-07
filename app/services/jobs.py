from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow
from app.schemas import JobCreate
from app.services.validation import validate_recipients


def create_job(session: Session, payload: JobCreate) -> Job:
    """Persist a job and one certificate row per submitted recipient, valid or not.

    Invalid rows are stored as INVALID with the reason and counted as failed straight away.
    If no row is valid the job is FAILED immediately and there is nothing to process.
    """
    results = validate_recipients(payload.recipients)
    invalid_count = sum(1 for result in results if not result.is_valid)

    job = Job(
        event_name=payload.event_name,
        issuer_name=payload.issuer_name,
        issue_date=payload.issue_date,
        status=JobStatus.PENDING,
        total_count=len(results),
        failed_count=invalid_count,
    )
    if invalid_count == len(results):
        job.status = JobStatus.FAILED
        job.finished_at = utcnow()
    session.add(job)
    session.flush()

    session.add_all(
        Certificate(
            job_id=job.id,
            row_index=index,
            recipient_name=result.name,
            recipient_email=result.email,
            status=CertificateStatus.PENDING if result.is_valid else CertificateStatus.INVALID,
            error=result.error,
        )
        for index, result in enumerate(results)
    )
    session.commit()
    return job


def get_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"No job with id {job_id}", code="JOB_NOT_FOUND")
    return job


def progress_percent(job: Job) -> float:
    if job.total_count == 0:
        return 100.0
    done = job.succeeded_count + job.failed_count
    return round(done * 100 / job.total_count, 1)


def list_certificates(
    session: Session,
    job_id: str,
    status: CertificateStatus | None,
    limit: int,
    offset: int,
) -> tuple[int, list[Certificate]]:
    """One page of a job's certificates in submission order, plus the total matching count."""
    conditions = [Certificate.job_id == job_id]
    if status is not None:
        conditions.append(Certificate.status == status)

    total = session.scalar(select(func.count()).select_from(Certificate).where(*conditions))
    items = session.scalars(
        select(Certificate)
        .where(*conditions)
        .order_by(Certificate.row_index)
        .limit(limit)
        .offset(offset)
    ).all()
    return total, list(items)
