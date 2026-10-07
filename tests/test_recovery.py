from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import create_app
from app.models import Job, JobStatus
from app.services import processor, renderer
from tests.helpers import get_job, get_rows, job_body, recipients


def count_renders(monkeypatch) -> list[str]:
    calls: list[str] = []
    real_render = renderer.render

    def counting_render(**kwargs):
        calls.append(kwargs["recipient_name"])
        return real_render(**kwargs)

    monkeypatch.setattr(renderer, "render", counting_render)
    return calls


def snapshot(job_id: str) -> list[tuple]:
    return [
        (row.id, row.status, row.certificate_number, row.file_path, row.generated_at)
        for row in get_rows(job_id)
    ]


def test_rerunning_a_finished_job_regenerates_nothing(client, monkeypatch):
    people = [*recipients(3), {"name": "", "email": "bad"}]
    job_id = client.post("/api/jobs/", json=job_body(recipients=people)).json()["id"]
    before_rows = snapshot(job_id)
    before_job = get_job(job_id)
    calls = count_renders(monkeypatch)

    processor.process_job(job_id)

    assert calls == []
    assert snapshot(job_id) == before_rows
    after_job = get_job(job_id)
    assert after_job.status == before_job.status == "COMPLETED_WITH_ERRORS"
    assert (after_job.succeeded_count, after_job.failed_count) == (3, 1)
    assert after_job.finished_at == before_job.finished_at


def test_resuming_an_interrupted_job_only_generates_what_is_left(client, monkeypatch):
    monkeypatch.setattr(processor, "process_job", lambda job_id: None)
    job_id = client.post("/api/jobs/", json=job_body(recipients=recipients(4))).json()["id"]
    monkeypatch.undo()

    # Simulate a crash after two certificates: PROCESSING, two rows done, two still PENDING.
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        job.status = JobStatus.PROCESSING
        session.commit()
        for certificate_id in processor._pending_certificate_ids(session, job_id)[:2]:
            processor._generate_one(session, job, certificate_id)
    done_before = snapshot(job_id)[:2]
    calls = count_renders(monkeypatch)

    processor.process_job(job_id)

    assert calls == ["Recipient 2", "Recipient 3"]
    assert snapshot(job_id)[:2] == done_before
    job = get_job(job_id)
    assert job.status == "COMPLETED"
    assert (job.succeeded_count, job.failed_count) == (4, 0)


def post_job(client, people) -> str:
    return client.post("/api/jobs/", json=job_body(recipients=people)).json()["id"]


def test_startup_resumes_pending_and_processing_jobs(settings_env, monkeypatch):
    monkeypatch.setattr(processor, "process_job", lambda job_id: None)
    with TestClient(create_app()) as first_run:
        pending_id = post_job(first_run, recipients(2))
        processing_id = post_job(first_run, recipients(3))
        failed_id = post_job(first_run, [{"name": "", "email": "bad"}])
        with SessionLocal() as session:
            session.get(Job, processing_id).status = JobStatus.PROCESSING
            session.commit()
    monkeypatch.undo()

    # "Restart" the server against the same database and storage.
    app = create_app()
    with TestClient(app) as second_run:
        app.state.recovery_thread.join(timeout=30)
        assert not app.state.recovery_thread.is_alive()

        for job_id, total in ((pending_id, 2), (processing_id, 3)):
            data = second_run.get(f"/api/jobs/{job_id}/").json()
            assert data["status"] == "COMPLETED"
            assert data["succeeded_count"] == total
        assert second_run.get(f"/api/jobs/{failed_id}/").json()["status"] == "FAILED"


def test_startup_with_nothing_to_resume_starts_no_thread(settings_env):
    app = create_app()
    with TestClient(app):
        assert app.state.recovery_thread is None
