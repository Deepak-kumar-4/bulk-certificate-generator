from app.services import processor, renderer, storage
from tests.helpers import get_job, get_rows, job_body, recipients


def submit(client, people) -> str:
    response = client.post("/api/jobs/", json=job_body(recipients=people))
    assert response.status_code == 202
    return response.json()["id"]


def test_valid_job_generates_every_certificate(client, settings_env):
    job_id = submit(client, recipients(3))

    job = get_job(job_id)
    assert job.status == "COMPLETED"
    assert (job.succeeded_count, job.failed_count) == (3, 0)
    assert job.started_at is not None and job.finished_at is not None

    rows = get_rows(job_id)
    assert all(row.status == "GENERATED" for row in rows)
    assert len({row.certificate_number for row in rows}) == 3
    for row in rows:
        assert row.certificate_number.startswith("CERT-2026-")
        assert row.file_path == f"{job_id}/{row.id}.pdf"
        path = settings_env.storage_dir / row.file_path
        assert path.read_bytes().startswith(b"%PDF")


def test_one_render_failure_does_not_stop_the_others(client, monkeypatch):
    real_render = renderer.render

    def flaky_render(**kwargs):
        if kwargs["recipient_name"] == "Recipient 2":
            raise RuntimeError("simulated renderer crash")
        return real_render(**kwargs)

    monkeypatch.setattr(renderer, "render", flaky_render)

    job_id = submit(client, recipients(5))

    rows = get_rows(job_id)
    assert [row.status for row in rows] == [
        "GENERATED",
        "GENERATED",
        "FAILED",
        "GENERATED",
        "GENERATED",
    ]
    failed = rows[2]
    assert failed.error == "simulated renderer crash"
    assert failed.certificate_number is None
    assert failed.file_path is None

    job = get_job(job_id)
    assert job.status == "COMPLETED_WITH_ERRORS"
    assert (job.succeeded_count, job.failed_count) == (4, 1)


def test_storage_failure_is_isolated_too(client, monkeypatch):
    real_save = storage.save_certificate
    calls = []

    def failing_save(job_id, certificate_id, data):
        calls.append(certificate_id)
        if len(calls) == 1:
            raise OSError("disk full")
        return real_save(job_id, certificate_id, data)

    monkeypatch.setattr(storage, "save_certificate", failing_save)

    job_id = submit(client, recipients(3))

    assert [row.status for row in get_rows(job_id)] == ["FAILED", "GENERATED", "GENERATED"]
    assert get_rows(job_id)[0].error == "disk full"


def test_real_render_error_marks_row_failed(client):
    people = [
        {"name": "Asha Rao", "email": "asha@example.com"},
        {"name": "W" * 100, "email": "wide@example.com"},
    ]

    job_id = submit(client, people)

    rows = get_rows(job_id)
    assert rows[0].status == "GENERATED"
    assert rows[1].status == "FAILED"
    assert "too long to fit" in rows[1].error
    assert get_job(job_id).status == "COMPLETED_WITH_ERRORS"


def test_every_render_failing_marks_job_failed(client, monkeypatch):
    def broken_render(**kwargs):
        raise RuntimeError("template broken")

    monkeypatch.setattr(renderer, "render", broken_render)

    job_id = submit(client, recipients(2))

    job = get_job(job_id)
    assert job.status == "FAILED"
    assert (job.succeeded_count, job.failed_count) == (0, 2)
    assert all(row.error == "template broken" for row in get_rows(job_id))


def test_invalid_rows_count_as_failed_in_final_status(client):
    people = [{"name": "Asha", "email": "asha@example.com"}, {"name": "", "email": "x"}]

    job_id = submit(client, people)

    job = get_job(job_id)
    assert job.status == "COMPLETED_WITH_ERRORS"
    assert (job.succeeded_count, job.failed_count) == (1, 1)
    assert [row.status for row in get_rows(job_id)] == ["GENERATED", "INVALID"]


def test_crash_outside_the_per_certificate_loop_fails_the_job(client, monkeypatch):
    monkeypatch.setattr(processor, "process_job", lambda job_id: None)
    job_id = submit(client, recipients(2))
    monkeypatch.undo()

    def explode(session, job_id):
        raise RuntimeError("database went away")

    monkeypatch.setattr(processor, "_pending_certificate_ids", explode)
    processor.process_job(job_id)

    job = get_job(job_id)
    assert job.status == "FAILED"
    assert job.failed_count == 2
    assert job.finished_at is not None
    assert all(row.error == "job aborted: database went away" for row in get_rows(job_id))


def test_file_path_is_built_from_ids_not_user_input(client, settings_env):
    people = [{"name": "../../etc/passwd", "email": "evil@example.com"}]

    job_id = submit(client, people)

    row = get_rows(job_id)[0]
    assert row.status == "GENERATED"
    assert row.file_path == f"{job_id}/{row.id}.pdf"
    stored = (settings_env.storage_dir / row.file_path).resolve()
    assert stored.is_relative_to(settings_env.storage_dir.resolve())
