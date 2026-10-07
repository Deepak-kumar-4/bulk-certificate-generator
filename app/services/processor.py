"""The generation loop.

process_job() takes only a job id and opens its own database session, so it can be run by
FastAPI BackgroundTasks today and by a task queue (Celery, RQ, ...) later without changes.
It only touches certificates that are still PENDING, so running it again on the same job
(for example after a restart) never regenerates finished certificates.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow
from app.services import renderer, storage

logger = logging.getLogger(__name__)

FINISHED_STATUSES = {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED}


def make_certificate_number(job: Job) -> str:
    return f"CERT-{job.issue_date.year}-{uuid.uuid4().hex[:12].upper()}"


def describe_error(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


def final_status(job: Job) -> JobStatus:
    if job.succeeded_count == job.total_count:
        return JobStatus.COMPLETED
    if job.succeeded_count == 0:
        return JobStatus.FAILED
    return JobStatus.COMPLETED_WITH_ERRORS


def _pending_certificate_ids(session: Session, job_id: str) -> list[str]:
    return list(
        session.scalars(
            select(Certificate.id)
            .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.PENDING)
            .order_by(Certificate.row_index)
        )
    )


def _generate_one(session: Session, job: Job, certificate_id: str) -> None:
    """Generate one certificate. Any error is contained here and recorded on that row only."""
    cert = session.get(Certificate, certificate_id)
    saved_path: str | None = None
    try:
        number = make_certificate_number(job)
        pdf = renderer.render(
            recipient_name=cert.recipient_name,
            event_name=job.event_name,
            issuer_name=job.issuer_name,
            issue_date=job.issue_date,
            certificate_number=number,
        )
        saved_path = storage.save_certificate(job.id, cert.id, pdf)
        cert.status = CertificateStatus.GENERATED
        cert.certificate_number = number
        cert.file_path = saved_path
        cert.generated_at = utcnow()
        job.succeeded_count += 1
        session.commit()  # per certificate: progress is visible and a crash loses nothing
    except Exception as exc:
        session.rollback()
        if saved_path is not None:
            storage.delete_file(saved_path)
        logger.warning("Certificate %s of job %s failed: %s", certificate_id, job.id, exc)
        cert = session.get(Certificate, certificate_id)
        cert.status = CertificateStatus.FAILED
        cert.error = describe_error(exc)
        job.failed_count += 1
        session.commit()


def _run(session: Session, job_id: str) -> None:
    job = session.get(Job, job_id)
    if job is None:
        logger.warning("process_job: job %s not found", job_id)
        return
    if job.status in FINISHED_STATUSES:
        return

    job.status = JobStatus.PROCESSING
    job.started_at = job.started_at or utcnow()
    session.commit()

    for certificate_id in _pending_certificate_ids(session, job_id):
        _generate_one(session, job, certificate_id)

    job.status = final_status(job)
    job.finished_at = utcnow()
    session.commit()


def _abort(session: Session, job_id: str, exc: Exception) -> None:
    """The loop itself crashed: fail the job and any rows it never reached."""
    session.rollback()
    job = session.get(Job, job_id)
    if job is None:
        return
    remaining = session.scalars(
        select(Certificate).where(
            Certificate.job_id == job_id, Certificate.status == CertificateStatus.PENDING
        )
    ).all()
    for cert in remaining:
        cert.status = CertificateStatus.FAILED
        cert.error = f"job aborted: {describe_error(exc)}"
    job.failed_count += len(remaining)
    job.status = JobStatus.FAILED
    job.finished_at = utcnow()
    session.commit()


def process_job(job_id: str) -> None:
    """Generate every PENDING certificate of a job. Safe to call more than once."""
    with SessionLocal() as session:
        try:
            _run(session, job_id)
        except Exception as exc:
            logger.exception("process_job crashed for job %s", job_id)
            _abort(session, job_id, exc)
