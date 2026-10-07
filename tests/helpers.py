from sqlalchemy import select

from app.db import SessionLocal
from app.models import Certificate, Job


def job_body(**overrides) -> dict:
    body = {
        "event_name": "Python Bootcamp 2026",
        "issuer_name": "Deetag Academy",
        "issue_date": "2026-10-01",
        "recipients": [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Ravi Kumar", "email": "ravi@example.com"},
        ],
    }
    body.update(overrides)
    return body


def recipients(count: int) -> list[dict]:
    return [{"name": f"Recipient {i}", "email": f"recipient{i}@example.com"} for i in range(count)]


def get_job(job_id: str) -> Job:
    with SessionLocal() as session:
        return session.get(Job, job_id)


def get_rows(job_id: str) -> list[Certificate]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(Certificate)
                .where(Certificate.job_id == job_id)
                .order_by(Certificate.row_index)
            )
        )
