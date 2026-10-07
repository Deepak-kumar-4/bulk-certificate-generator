import pytest

from app.db import SessionLocal
from app.models import Job, JobStatus
from app.services import processor, renderer
from tests.helpers import job_body, recipients


@pytest.fixture
def no_background(monkeypatch):
    """Stop the POST from processing the job, so we can observe it before and during work."""
    monkeypatch.setattr(processor, "process_job", lambda job_id: None)


def submit(client, people) -> str:
    response = client.post("/api/jobs/", json=job_body(recipients=people))
    assert response.status_code == 202
    return response.json()["id"]


def status_of(client, job_id: str) -> dict:
    response = client.get(f"/api/jobs/{job_id}/")
    assert response.status_code == 200
    return response.json()


def process_first(job_id: str, count: int) -> None:
    """Run the real per-certificate step for the first `count` pending rows only."""
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        job.status = JobStatus.PROCESSING
        session.commit()
        for certificate_id in processor._pending_certificate_ids(session, job_id)[:count]:
            processor._generate_one(session, job, certificate_id)


def test_status_while_pending(client, no_background):
    people = [*recipients(3), {"name": "", "email": "bad"}]
    job_id = submit(client, people)

    data = status_of(client, job_id)

    assert data["id"] == job_id
    assert data["event_name"] == "Python Bootcamp 2026"
    assert data["status"] == "PENDING"
    assert data["total_count"] == 4
    assert data["succeeded_count"] == 0
    assert data["failed_count"] == 1
    assert data["pending_count"] == 3
    assert data["progress_percent"] == 25.0
    assert data["created_at"] is not None
    assert data["started_at"] is None
    assert data["finished_at"] is None


def test_status_part_way_through(client, no_background):
    job_id = submit(client, recipients(4))

    process_first(job_id, 2)
    data = status_of(client, job_id)

    assert data["status"] == "PROCESSING"
    assert (data["succeeded_count"], data["failed_count"], data["pending_count"]) == (2, 0, 2)
    assert data["progress_percent"] == 50.0
    assert data["finished_at"] is None


def test_progress_percent_is_rounded(client, no_background):
    job_id = submit(client, recipients(3))

    process_first(job_id, 1)

    assert status_of(client, job_id)["progress_percent"] == 33.3


def test_status_when_finished_completed(client):
    job_id = submit(client, recipients(3))

    data = status_of(client, job_id)

    assert data["status"] == "COMPLETED"
    assert (data["succeeded_count"], data["failed_count"], data["pending_count"]) == (3, 0, 0)
    assert data["progress_percent"] == 100.0
    assert data["started_at"] is not None
    assert data["finished_at"] is not None


def test_status_when_finished_with_errors(client):
    job_id = submit(client, [*recipients(2), {"name": "No Email"}])

    data = status_of(client, job_id)

    assert data["status"] == "COMPLETED_WITH_ERRORS"
    assert (data["succeeded_count"], data["failed_count"]) == (2, 1)
    assert data["progress_percent"] == 100.0


def test_status_when_nothing_succeeded(client, monkeypatch):
    def broken_render(**kwargs):
        raise RuntimeError("template broken")

    monkeypatch.setattr(renderer, "render", broken_render)
    job_id = submit(client, recipients(2))

    data = status_of(client, job_id)

    assert data["status"] == "FAILED"
    assert (data["succeeded_count"], data["failed_count"]) == (0, 2)


def test_unknown_job_is_404(client):
    response = client.get("/api/jobs/does-not-exist/")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "JOB_NOT_FOUND", "message": "No job with id does-not-exist"}
    }


def test_certificate_list_shows_every_row_in_order(client):
    people = [
        {"name": "Asha Rao", "email": "asha@example.com"},
        {"name": "", "email": "not-an-email"},
    ]
    job_id = submit(client, people)

    response = client.get(f"/api/jobs/{job_id}/certificates/")

    assert response.status_code == 200
    data = response.json()
    assert (data["job_id"], data["total"], data["limit"], data["offset"]) == (job_id, 2, 100, 0)
    generated, invalid = data["items"]
    assert generated["row_index"] == 0
    assert generated["recipient_name"] == "Asha Rao"
    assert generated["status"] == "GENERATED"
    assert generated["certificate_number"].startswith("CERT-2026-")
    assert generated["download_url"] == f"/api/certificates/{generated['id']}/download"
    assert invalid == {
        "id": invalid["id"],
        "row_index": 1,
        "recipient_name": "",
        "recipient_email": "not-an-email",
        "certificate_number": None,
        "status": "INVALID",
        "error": "name is required; email is not valid",
        "download_url": None,
    }


def test_certificate_list_pagination(client):
    job_id = submit(client, recipients(5))

    data = client.get(f"/api/jobs/{job_id}/certificates/?limit=2&offset=2").json()

    assert data["total"] == 5
    assert (data["limit"], data["offset"]) == (2, 2)
    assert [item["row_index"] for item in data["items"]] == [2, 3]

    last_page = client.get(f"/api/jobs/{job_id}/certificates/?limit=2&offset=4").json()
    assert [item["row_index"] for item in last_page["items"]] == [4]


def test_certificate_list_filter_by_status(client, monkeypatch):
    real_render = renderer.render

    def flaky_render(**kwargs):
        if kwargs["recipient_name"] == "Recipient 1":
            raise RuntimeError("simulated failure")
        return real_render(**kwargs)

    monkeypatch.setattr(renderer, "render", flaky_render)
    job_id = submit(client, [*recipients(3), {"name": "Bad", "email": "bad"}])

    failed = client.get(f"/api/jobs/{job_id}/certificates/?status=FAILED").json()
    invalid = client.get(f"/api/jobs/{job_id}/certificates/?status=INVALID").json()
    generated = client.get(f"/api/jobs/{job_id}/certificates/?status=GENERATED").json()

    assert failed["total"] == 1
    assert failed["items"][0]["error"] == "simulated failure"
    assert failed["items"][0]["download_url"] is None
    assert invalid["total"] == 1
    assert invalid["items"][0]["row_index"] == 3
    assert generated["total"] == 2


@pytest.mark.parametrize("query", ["status=DONE", "limit=0", "limit=1001", "offset=-1"], ids=str)
def test_certificate_list_rejects_bad_query(client, query):
    job_id = submit(client, recipients(1))

    response = client.get(f"/api/jobs/{job_id}/certificates/?{query}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_certificate_list_unknown_job_is_404(client):
    response = client.get("/api/jobs/does-not-exist/certificates/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"
