from sqlalchemy import select

from app.db import SessionLocal
from app.models import Certificate, Job


def job_body(**overrides):
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


def test_create_job_returns_202_with_location(client):
    response = client.post("/api/jobs/", json=job_body())

    assert response.status_code == 202
    data = response.json()
    assert data["total_count"] == 2
    assert data["accepted_count"] == 2
    assert data["invalid_count"] == 0
    assert data["status_url"] == f"/api/jobs/{data['id']}/"
    assert response.headers["Location"] == data["status_url"]


def test_create_job_stores_job_and_one_row_per_recipient(client):
    response = client.post("/api/jobs/", json=job_body())
    job_id = response.json()["id"]

    with SessionLocal() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.event_name == "Python Bootcamp 2026"
        assert job.issuer_name == "Deetag Academy"
        assert job.total_count == 2
        rows = session.scalars(
            select(Certificate).where(Certificate.job_id == job_id).order_by(Certificate.row_index)
        ).all()
        assert [row.row_index for row in rows] == [0, 1]
        assert [row.recipient_email for row in rows] == ["asha@example.com", "ravi@example.com"]


def assert_rejected(response, field: str):
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any(detail["field"] == field for detail in error["details"])


def test_empty_recipients_is_rejected(client):
    assert_rejected(client.post("/api/jobs/", json=job_body(recipients=[])), "recipients")


def test_missing_recipients_is_rejected(client):
    body = job_body()
    del body["recipients"]
    assert_rejected(client.post("/api/jobs/", json=body), "recipients")


def test_recipients_not_a_list_is_rejected(client):
    assert_rejected(client.post("/api/jobs/", json=job_body(recipients="asha")), "recipients")


def test_recipients_over_the_cap_is_rejected(client, settings_env, monkeypatch):
    monkeypatch.setattr(settings_env, "max_recipients", 3)
    recipients = [{"name": f"User {i}", "email": f"user{i}@example.com"} for i in range(4)]

    response = client.post("/api/jobs/", json=job_body(recipients=recipients))

    assert_rejected(response, "recipients")
    assert "at most 3" in response.json()["error"]["message"]


def test_missing_event_name_is_rejected(client):
    body = job_body()
    del body["event_name"]
    assert_rejected(client.post("/api/jobs/", json=body), "event_name")


def test_blank_issuer_name_is_rejected(client):
    assert_rejected(client.post("/api/jobs/", json=job_body(issuer_name="   ")), "issuer_name")


def test_bad_date_is_rejected(client):
    assert_rejected(client.post("/api/jobs/", json=job_body(issue_date="2026-13-45")), "issue_date")


def test_rejected_request_saves_nothing(client):
    client.post("/api/jobs/", json=job_body(recipients=[]))

    with SessionLocal() as session:
        assert session.scalars(select(Job)).all() == []
