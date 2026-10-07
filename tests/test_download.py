import io
import zipfile

import pytest
from pypdf import PdfReader

from app.db import SessionLocal
from app.models import Job, JobStatus
from app.services import processor, renderer, storage
from tests.helpers import get_rows, job_body, recipients


def submit(client, people) -> str:
    response = client.post("/api/jobs/", json=job_body(recipients=people))
    assert response.status_code == 202
    return response.json()["id"]


def test_download_single_certificate(client):
    job_id = submit(client, [{"name": "José Núñez", "email": "jose@example.com"}])
    row = get_rows(job_id)[0]

    response = client.get(f"/api/certificates/{row.id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f'filename="Jose-Nunez-{row.certificate_number}.pdf"' in disposition
    assert response.content.startswith(b"%PDF")
    text = PdfReader(io.BytesIO(response.content)).pages[0].extract_text()
    assert "José Núñez" in text
    assert row.certificate_number in text


def test_download_via_url_from_certificate_list(client):
    job_id = submit(client, recipients(1))
    item = client.get(f"/api/jobs/{job_id}/certificates/").json()["items"][0]

    response = client.get(item["download_url"])

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_download_unknown_certificate_is_404(client):
    response = client.get("/api/certificates/does-not-exist/download")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CERTIFICATE_NOT_FOUND"


def test_download_invalid_certificate_is_409(client):
    job_id = submit(client, [*recipients(1), {"name": "", "email": "bad"}])
    invalid = get_rows(job_id)[1]

    response = client.get(f"/api/certificates/{invalid.id}/download")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CERTIFICATE_NOT_GENERATED"


def test_download_pending_certificate_is_409(client, monkeypatch):
    monkeypatch.setattr(processor, "process_job", lambda job_id: None)
    job_id = submit(client, recipients(1))

    response = client.get(f"/api/certificates/{get_rows(job_id)[0].id}/download")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CERTIFICATE_NOT_GENERATED"


def test_download_with_missing_file_reports_it(client):
    job_id = submit(client, recipients(1))
    row = get_rows(job_id)[0]
    storage.delete_file(row.file_path)

    response = client.get(f"/api/certificates/{row.id}/download")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CERTIFICATE_FILE_MISSING"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Asha Rao", "Asha-Rao-CERT-1.pdf"),
        ("../../etc/passwd", "etc-passwd-CERT-1.pdf"),
        ('Evil"; filename="x.exe', "Evil-filename-x-exe-CERT-1.pdf"),
        ("田中太郎", "certificate-CERT-1.pdf"),
        (None, "certificate-CERT-1.pdf"),
    ],
)
def test_download_filename_is_sanitised(name, expected):
    assert storage.download_filename(name, "CERT-1") == expected


def test_zip_contains_exactly_the_generated_certificates(client, monkeypatch):
    real_render = renderer.render

    def flaky_render(**kwargs):
        if kwargs["recipient_name"] == "Recipient 1":
            raise RuntimeError("simulated failure")
        return real_render(**kwargs)

    monkeypatch.setattr(renderer, "render", flaky_render)
    job_id = submit(client, [*recipients(3), {"name": "", "email": "bad"}])
    generated = [row for row in get_rows(job_id) if row.status == "GENERATED"]
    assert len(generated) == 2

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f'filename="certificates-{job_id}.zip"' in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert sorted(names) == sorted(
            f"Recipient-{row.row_index}-{row.certificate_number}.pdf" for row in generated
        )
        for name in names:
            assert archive.read(name).startswith(b"%PDF")


def test_zip_temp_file_is_removed_after_sending(client, monkeypatch):
    built = []
    real_build = storage.build_zip

    def tracking_build(entries):
        path = real_build(entries)
        built.append(path)
        return path

    monkeypatch.setattr(storage, "build_zip", tracking_build)
    job_id = submit(client, recipients(2))

    assert client.get(f"/api/jobs/{job_id}/download").status_code == 200
    assert len(built) == 1
    assert not built[0].exists()


@pytest.mark.parametrize("state", [JobStatus.PENDING, JobStatus.PROCESSING])
def test_zip_while_job_is_unfinished_is_409(client, monkeypatch, state):
    monkeypatch.setattr(processor, "process_job", lambda job_id: None)
    job_id = submit(client, recipients(2))
    with SessionLocal() as session:
        session.get(Job, job_id).status = state
        session.commit()

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_FINISHED"


def test_zip_with_nothing_generated_is_409(client):
    job_id = submit(client, [{"name": "", "email": "bad"}])

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_CERTIFICATES"


def test_zip_unknown_job_is_404(client):
    response = client.get("/api/jobs/does-not-exist/download")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"
