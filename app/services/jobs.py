from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError, ConflictError, NotFoundError
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow
from app.schemas import JobCreate
from app.services import storage
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


def get_certificate(session: Session, certificate_id: str) -> Certificate:
    cert = session.get(Certificate, certificate_id)
    if cert is None:
        raise NotFoundError(
            f"No certificate with id {certificate_id}", code="CERTIFICATE_NOT_FOUND"
        )
    return cert


def _stored_file(cert: Certificate) -> Path:
    path = storage.resolve(cert.file_path)
    if not path.is_file():
        raise AppError(
            f"The file for certificate {cert.id} is missing from storage",
            code="CERTIFICATE_FILE_MISSING",
            status_code=500,
        )
    return path


def certificate_file(session: Session, certificate_id: str) -> tuple[Path, str]:
    """Path and download filename of a generated certificate."""
    cert = get_certificate(session, certificate_id)
    if cert.status != CertificateStatus.GENERATED:
        raise ConflictError(
            f"Certificate {cert.id} is {cert.status}, not GENERATED; there is no file to download",
            code="CERTIFICATE_NOT_GENERATED",
        )
    filename = storage.download_filename(cert.recipient_name, cert.certificate_number)
    return _stored_file(cert), filename


def job_zip(session: Session, job_id: str) -> tuple[Path, str]:
    """Build a temporary zip of every generated certificate in a finished job."""
    job = get_job(session, job_id)
    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise ConflictError(
            f"Job {job.id} is still {job.status}; try again when it has finished",
            code="JOB_NOT_FINISHED",
        )
    generated = session.scalars(
        select(Certificate)
        .where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.GENERATED)
        .order_by(Certificate.row_index)
    ).all()
    if not generated:
        raise ConflictError(
            f"Job {job.id} has no generated certificates to download", code="NO_CERTIFICATES"
        )
    for cert in generated:
        _stored_file(cert)

    entries = [
        (cert.file_path, storage.download_filename(cert.recipient_name, cert.certificate_number))
        for cert in generated
    ]
    return storage.build_zip(entries), f"certificates-{job.id}.zip"
