from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job
from tests.helpers import get_job, get_rows, job_body


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

    job = get_job(job_id)
    assert job is not None
    assert job.event_name == "Python Bootcamp 2026"
    assert job.issuer_name == "Deetag Academy"
    assert job.total_count == 2

    rows = get_rows(job_id)
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


def test_bad_rows_are_accepted_and_marked_invalid(client):
    recipients = [
        {"name": "Asha Rao", "email": "asha@example.com"},
        {"name": "", "email": "blank-name@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        {"name": "Asha Duplicate", "email": "ASHA@example.com"},
    ]

    response = client.post("/api/jobs/", json=job_body(recipients=recipients))

    assert response.status_code == 202
    data = response.json()
    assert (data["total_count"], data["accepted_count"], data["invalid_count"]) == (4, 1, 3)

    rows = get_rows(data["id"])
    assert rows[0].status != "INVALID"
    assert [(row.status, row.error) for row in rows[1:]] == [
        ("INVALID", "name is required"),
        ("INVALID", "email is not valid"),
        ("INVALID", "duplicate email in request"),
    ]


def test_all_rows_invalid_still_creates_a_failed_job(client):
    recipients = [{"name": "", "email": "not-an-email"}, {"name": "Ravi"}]

    response = client.post("/api/jobs/", json=job_body(recipients=recipients))

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "FAILED"
    assert (data["accepted_count"], data["invalid_count"]) == (0, 2)

    with SessionLocal() as session:
        job = session.get(Job, data["id"])
        assert job.status == "FAILED"
        assert job.failed_count == 2
        assert job.finished_at is not None
    assert [row.error for row in get_rows(data["id"])] == [
        "name is required; email is not valid",
        "email is required",
    ]


def test_validation_error_message_is_readable(client):
    response = client.post("/api/jobs/", json=job_body(recipients=[]))

    assert response.json()["error"]["message"] == "recipients: must contain at least one recipient"


def test_malformed_json_uses_error_shape(client):
    response = client.post(
        "/api/jobs/", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
