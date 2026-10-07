from sqlalchemy.orm import Session

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate


def create_job(session: Session, payload: JobCreate) -> Job:
    """Persist a job and one certificate row per submitted recipient."""
    job = Job(
        event_name=payload.event_name,
        issuer_name=payload.issuer_name,
        issue_date=payload.issue_date,
        status=JobStatus.PENDING,
        total_count=len(payload.recipients),
    )
    session.add(job)
    session.flush()

    for index, raw in enumerate(payload.recipients):
        raw = raw if isinstance(raw, dict) else {}
        session.add(
            Certificate(
                job_id=job.id,
                row_index=index,
                recipient_name=raw.get("name"),
                recipient_email=raw.get("email"),
                status=CertificateStatus.PENDING,
            )
        )

    session.commit()
    return job
