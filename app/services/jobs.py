from sqlalchemy.orm import Session

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
