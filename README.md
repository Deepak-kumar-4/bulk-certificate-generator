# Bulk Certificate Generator API

A FastAPI backend that takes **one request containing many recipients** and generates a PDF
certificate for each valid recipient from a single fixed template. Clients get an immediate
`202 Accepted`, then track progress, see exactly which recipients succeeded or failed and why,
and download certificates one at a time or as a zip.

**Sample output:** [docs/sample-certificate.pdf](docs/sample-certificate.pdf), produced by the
renderer in this repo.

- [Features](#features)
- [Quick start](#quick-start)
- [Running the tests](#running-the-tests)
- [Using the API](#using-the-api)
- [API reference](#api-reference)
- [Design decisions](#design-decisions)
- [Assumptions and limits](#assumptions-and-limits)
- [Future scope](#future-scope)

## Features

- `POST /api/jobs/` accepts up to 5,000 recipients and returns `202` immediately.
- Generation runs in the background. Progress is visible per certificate.
- Validation happens at two levels. A malformed request is rejected with `422`. A bad
  recipient only invalidates its own row.
- Failures are isolated: one certificate that fails to render never stops the others.
- One result row per submitted recipient, so clients can map results back by `row_index`.
- Single-PDF and whole-job zip downloads.
- Jobs cut off by a server restart resume on startup without regenerating finished certificates.
- Interactive OpenAPI docs at `/docs`.

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 on SQLite, ReportLab, pytest, ruff, Docker,
GitHub Actions.

## Quick start

### Option A: pip

Requires Python 3.12.

```bash
git clone https://github.com/Deepak-kumar-4/bulk-certificate-generator.git
cd bulk-certificate-generator

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

uvicorn app.main:app --reload
```

The API is now on <http://localhost:8000>, with interactive docs at
<http://localhost:8000/docs>. Check it with:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### Option B: Docker

```bash
docker build -t bulk-certificate-generator .
docker run --rm -p 8000:8000 -v certdata:/data bulk-certificate-generator
```

The image keeps the SQLite database and generated PDFs in `/data`. Mount a volume there, as
above, so they survive container restarts.

### Configuration

Settings come from environment variables or a local `.env` file:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | SQLAlchemy URL. Any SQLAlchemy-supported database works. |
| `STORAGE_DIR` | `storage` | Directory where generated PDFs are written |
| `MAX_RECIPIENTS` | `5000` | Maximum recipients per request |

## Running the tests

```bash
pytest                    # full test suite
ruff check .              # lint
ruff format --check .     # formatting
```

Each test gets its own temporary SQLite database and storage directory, so tests do not depend
on each other or on local state. CI (`.github/workflows/ci.yml`) runs the same three commands
on every push and pull request.

| Area | File |
|---|---|
| Creating a job, request-level `422`s | `tests/test_create_job.py` |
| Recipient-level validation rules | `tests/test_validation.py` |
| PDF rendering (text, long names, accents) | `tests/test_renderer.py` |
| Status counts and progress at each stage, certificate list | `tests/test_job_status.py` |
| One failure does not affect the others | `tests/test_failure_isolation.py` |
| Single and zip downloads, `404`/`409` cases | `tests/test_download.py` |
| Re-running and resuming jobs, startup recovery | `tests/test_recovery.py` |

## Using the API

These examples assume the server is running on `localhost:8000`. They use `curl` from a
POSIX shell (Linux, macOS, Git Bash or WSL).

### 1. Submit a generation request

[`examples/job.json`](examples/job.json) contains a real request body with two valid
recipients (one with an accented name) and two invalid ones:

```json
{
  "event_name": "Python Bootcamp 2026",
  "issuer_name": "Deetag Academy",
  "issue_date": "2026-10-01",
  "recipients": [
    { "name": "Asha Rao", "email": "asha@example.com" },
    { "name": "José Núñez", "email": "jose@example.com" },
    { "name": "", "email": "not-an-email" },
    { "name": "Asha R.", "email": "ASHA@example.com" }
  ]
}
```

```bash
curl -i -X POST http://localhost:8000/api/jobs/ \
  -H "Content-Type: application/json" \
  -d @examples/job.json
```

```http
HTTP/1.1 202 Accepted
location: /api/jobs/7ba4370b-c66b-4fb8-962e-d776f181d7a0/

{"id":"7ba4370b-c66b-4fb8-962e-d776f181d7a0","status":"PENDING","total_count":4,
 "accepted_count":2,"invalid_count":2,
 "status_url":"/api/jobs/7ba4370b-c66b-4fb8-962e-d776f181d7a0/"}
```

You can also send the body inline:

```bash
curl -X POST http://localhost:8000/api/jobs/ \
  -H "Content-Type: application/json" \
  -d '{"event_name": "Python Bootcamp 2026", "issuer_name": "Deetag Academy",
       "issue_date": "2026-10-01",
       "recipients": [{"name": "Asha Rao", "email": "asha@example.com"}]}'
```

> On Windows, curl may not send non-ASCII characters typed on the command line as UTF-8.
> Use the `-d @file.json` form for names with accents.

Save the job id from the response for the next steps:

```bash
JOB_ID=7ba4370b-c66b-4fb8-962e-d776f181d7a0
```

### 2. Check status and progress

```bash
curl http://localhost:8000/api/jobs/$JOB_ID/
```

```json
{
  "id": "7ba4370b-c66b-4fb8-962e-d776f181d7a0",
  "event_name": "Python Bootcamp 2026",
  "status": "COMPLETED_WITH_ERRORS",
  "total_count": 4,
  "succeeded_count": 2,
  "failed_count": 2,
  "pending_count": 0,
  "progress_percent": 100.0,
  "created_at": "2026-10-07T08:15:45.425526Z",
  "started_at": "2026-10-07T08:15:45.446615Z",
  "finished_at": "2026-10-07T08:15:45.497043Z"
}
```

Poll this URL until `finished_at` is set. A large job shows `PROCESSING` with a rising
`progress_percent`.

### 3. See per-recipient results

```bash
curl "http://localhost:8000/api/jobs/$JOB_ID/certificates/?limit=10&offset=0"
```

```json
{
  "job_id": "7ba4370b-...", "total": 4, "limit": 10, "offset": 0,
  "items": [
    {"id": "14e9efd5-...", "row_index": 0, "recipient_name": "Asha Rao",
     "recipient_email": "asha@example.com", "certificate_number": "CERT-2026-4D88F700E393",
     "status": "GENERATED", "error": null,
     "download_url": "/api/certificates/14e9efd5-.../download"},
    {"id": "9f941f85-...", "row_index": 2, "recipient_name": "", "recipient_email": "not-an-email",
     "certificate_number": null, "status": "INVALID",
     "error": "name is required; email is not valid", "download_url": null},
    {"id": "d070160c-...", "row_index": 3, "recipient_name": "Asha R.",
     "recipient_email": "ASHA@example.com", "certificate_number": null, "status": "INVALID",
     "error": "duplicate email in request", "download_url": null}
  ]
}
```

(Shortened: the row for José Núñez is left out.)

Find out what went wrong by filtering on status:

```bash
curl "http://localhost:8000/api/jobs/$JOB_ID/certificates/?status=INVALID"   # rejected by validation
curl "http://localhost:8000/api/jobs/$JOB_ID/certificates/?status=FAILED"    # valid, but generation failed
```

### 4. Download certificates

A single PDF. Use the `id` or `download_url` of a `GENERATED` row:

```bash
CERT_ID=14e9efd5-a359-4f59-925b-6e745a423110
curl -OJ http://localhost:8000/api/certificates/$CERT_ID/download
# saves Asha-Rao-CERT-2026-4D88F700E393.pdf
```

Every generated certificate of a finished job, as one zip:

```bash
curl -OJ http://localhost:8000/api/jobs/$JOB_ID/download
# saves certificates-<job id>.zip containing
#   Asha-Rao-CERT-2026-4D88F700E393.pdf
#   Jose-Nunez-CERT-2026-F1D73899C471.pdf
```

(`-O` saves to a file. `-J` uses the filename from the server's `Content-Disposition` header.)

### Errors

Every error has the same shape:

```bash
curl http://localhost:8000/api/jobs/does-not-exist/
# {"error":{"code":"JOB_NOT_FOUND","message":"No job with id does-not-exist"}}
```

## API reference

| Method and path | Success | Errors |
|---|---|---|
| `POST /api/jobs/` | `202` + `Location` header | `422 VALIDATION_ERROR` |
| `GET /api/jobs/{id}/` | `200` status and counts | `404 JOB_NOT_FOUND` |
| `GET /api/jobs/{id}/certificates/?status=&limit=&offset=` | `200` page of rows | `404 JOB_NOT_FOUND`, `422` for a bad query |
| `GET /api/certificates/{id}/download` | `200 application/pdf` | `404 CERTIFICATE_NOT_FOUND`, `409 CERTIFICATE_NOT_GENERATED` |
| `GET /api/jobs/{id}/download` | `200 application/zip` | `404 JOB_NOT_FOUND`, `409 JOB_NOT_FINISHED`, `409 NO_CERTIFICATES` |
| `GET /health` | `{"status": "ok"}` | |

**Job status:** `PENDING` → `PROCESSING` → `COMPLETED` (every row generated),
`COMPLETED_WITH_ERRORS` (some generated, some not) or `FAILED` (none generated).

**Certificate status:** `PENDING`, `GENERATED`, `INVALID` (rejected by validation and never
attempted) or `FAILED` (valid input, but generation raised an error).

**Counts:** `failed_count` includes both `INVALID` and `FAILED` rows.
`pending_count = total_count - succeeded_count - failed_count`.
`progress_percent` is the share of rows that are finished, rounded to one decimal place.

`limit` defaults to 100, with a maximum of 1000. Rows are always ordered by `row_index`, which
is the recipient's position in the submitted list.

## Design decisions

### Background processing with `BackgroundTasks`

| Option | Good | Bad |
|---|---|---|
| Synchronous, in the request | Simplest | 5,000 PDFs means a request that hangs for a long time and can time out; no progress |
| **`BackgroundTasks` (chosen)** | Instant `202`, real progress tracking, no extra services to install | Runs inside the web process: work is lost if the server restarts mid-job, and it does not scale across machines |
| Celery + Redis | Durable, retries, scales out | Two more services for a reviewer to run; overkill for this scope |

The create route only validates, writes the job and certificate rows, schedules
`process_job(job_id)` and returns `202`. `process_job`
([app/services/processor.py](app/services/processor.py)) takes **only a job id**, opens its
own database session and reads everything it needs from the database. Moving to Celery or
another queue therefore means changing the one line that schedules it in
[app/api/jobs.py](app/api/jobs.py), not the function itself. It is a plain `def`, so FastAPI
runs it in a threadpool and the event loop is not blocked.

The weakness, a restart losing in-flight work, is handled by **restart recovery**: on startup
the app finds jobs still `PENDING` or `PROCESSING` and resumes them on a background thread.
This is safe because `process_job` only picks up certificates that are still `PENDING`.
Finished certificates are never regenerated, and running it on a finished job does nothing.
This was tested by killing the server partway through a 1,500-recipient job: after the
restart it resumed from where it stopped and finished with 1,500 unique certificates.

### Two-level validation: a bad row does not reject the request

- **Request level** (`422`, nothing saved): `event_name` or `issuer_name` missing or blank,
  a bad `issue_date`, or `recipients` missing, empty, not a list or longer than
  `MAX_RECIPIENTS`. These make the whole job meaningless, so it is rejected.
- **Recipient level** (job accepted, row saved as `INVALID` with a reason):
  - `name` is required, trimmed, 1–100 characters.
  - `email` is required, must be a valid format (checked with `email-validator`) and is
    lowercased.
  - A later duplicate of an email gets `"duplicate email in request"`.
  - All of a row's problems are collected and joined with `"; "`.

In a bulk upload, one typo in row 3,812 should not throw away the other 4,999 rows. So
recipients are typed loosely (`list[Any]`, not a strict Pydantic model) and each one is
validated by [app/services/validation.py](app/services/validation.py). If every recipient
is invalid, the job is still created and immediately `FAILED`, and the reasons are available
through the certificates list.

### Per-certificate commit and error isolation

The generation loop wraps **each certificate** in its own `try/except` and commits after each
one (`_generate_one` in [processor.py](app/services/processor.py)):

- If rendering or saving fails, the session is rolled back, any partly written file is
  removed, the row is marked `FAILED` with the error message, and the loop continues.
- Committing after every certificate makes progress visible to `GET /api/jobs/{id}/` while the
  job runs, and means a crash loses at most the certificate in progress.
- If the loop itself crashes (for example, the database goes away), a top-level handler marks
  the job `FAILED` and marks the rows it never reached as `FAILED` too, with
  `"job aborted: ..."`, so the counts still add up.

### One row per recipient, including invalid ones

Every submitted recipient gets a `certificates` row with its `row_index`. The client gets a
complete result for every input. Nothing is silently dropped, and the client can map results
back to its own list by position. Valid rows store the cleaned values (trimmed name,
lowercased email) that appear on the certificate. Invalid rows store the values as received,
so the client can see what was rejected.

### ReportLab instead of HTML-to-PDF

ReportLab is pure Python and installs with pip on any OS. HTML-to-PDF tools such as
WeasyPrint need system libraries (Pango, Cairo) that are hard to install, especially on
Windows, and headless Chrome is a heavy dependency. With one fixed template, drawing on a
canvas is simple, fast (about 55–60 certificates per second on a laptop) and needs no
external files apart from the font. The renderer
([app/services/renderer.py](app/services/renderer.py)) returns bytes and does not touch the
disk or the database, so it is unit tested directly.

- **Font:** DejaVu Sans is bundled in `app/assets/fonts` (see its license file there).
  ReportLab's built-in fonts cannot draw accented or non-Latin characters.
- **Long text:** names, the event name and the issuer name shrink one point at a time until
  they fit the page width. If text does not fit even at the minimum size (10pt for names),
  the renderer raises an error and the row becomes `FAILED` with a clear message.
- **Unsupported characters:** if the text contains a character the font has no glyph for
  (for example, Chinese characters), the renderer raises an error instead of printing empty
  boxes, and the row becomes `FAILED`.

### SQLite now, Postgres by configuration

SQLite needs no setup for whoever runs the project. The schema is plain SQLAlchemy 2.0 and
the URL comes from `DATABASE_URL`, so moving to Postgres is a configuration change plus
installing a driver such as `psycopg`. The SQLite engine is created with
`check_same_thread=False`, because the background task runs on a different thread from the
request. Timestamps are stored as UTC and returned as timezone-aware ISO 8601 strings.

### Storage and safety

- Files are stored at `STORAGE_DIR/{job_id}/{certificate_id}.pdf`. Paths are built only from
  generated ids, never from names or emails, so user input cannot influence a file path.
  Resolved paths are also checked to stay inside `STORAGE_DIR`.
- Files are written to a temporary name and then renamed, so a crash never leaves a
  half-written PDF.
- The download filename is an ASCII-safe version of the recipient's name plus the
  certificate number, for example `Jose-Nunez-CERT-2026-F1D73899C471.pdf`. Characters that
  could change the `Content-Disposition` header or the path are stripped.
- The job zip is built in a temporary file on disk and streamed, rather than held in memory.
  The temporary file is deleted after it has been sent.
- `MAX_RECIPIENTS` limits the memory and disk one request can use.

### Smaller choices

- **Certificate numbers** look like `CERT-2026-4D88F700E393`: the issue year plus 12 random
  hex characters (48 bits). A shorter random part would make duplicate numbers likely once
  there are tens of thousands of certificates. The column has a unique constraint as a
  final safeguard. Numbers are assigned only when a certificate is generated.
- **Duplicate emails:** only a valid row claims an email. If the first row with an email is
  invalid for another reason (such as a blank name), a later valid row with the same email
  is accepted.
- **Validation error details:** the `error` object always has `code` and `message`. A `422`
  also includes a `details` list of `{field, message}` items, so a client can show which
  field is wrong.
- **`409` codes:** the zip endpoint returns `JOB_NOT_FINISHED` while the job is `PENDING` or
  `PROCESSING`, and `NO_CERTIFICATES` when the job finished with nothing generated.
- **Missing file:** if a `GENERATED` certificate's file has been deleted from storage, the
  download returns `500 CERTIFICATE_FILE_MISSING` rather than pretending the certificate
  does not exist.
- **Trailing slashes** follow the routes as listed: job routes end in `/`, download routes do
  not. FastAPI redirects the other form.

## Assumptions and limits

- **Run a single worker process.** Background work and startup recovery run inside the web
  process. With several uvicorn or gunicorn workers, each one would try to resume the same
  unfinished jobs on startup. Scaling out needs a real queue (see future scope).
- **No complex text shaping.** ReportLab does not shape text, so scripts such as Devanagari,
  Tamil or Arabic will not render correctly even when the font has the glyphs. CJK
  characters are not in DejaVu Sans and are rejected with a clear `FAILED` reason.
- **Speed:** with about 55–60 certificates per second, a full 5,000-recipient job takes
  roughly a minute and a half. The `POST` itself, which validates and inserts every row,
  takes a couple of seconds at the maximum size.
- **SQLite and concurrency:** SQLite allows one writer at a time. That is fine for a single
  process with commits after each certificate, but not for heavy concurrent use. Use
  Postgres for that.
- **Storage is local disk.** It is fine for one machine but not shared between instances.
- **No authentication.** Anyone who can reach the API can create jobs and download any
  certificate whose id they know. Ids are random UUIDs, but they are not a security
  boundary.
- **The issue date is taken as given.** Past and future dates are both accepted.

## Future scope

- **Celery/Redis (or another queue) worker:** durable jobs, retries and horizontal scaling.
  Only the line that schedules `process_job` changes.
- **Retry endpoint for failed rows:** set `FAILED` rows back to `PENDING`, adjust the counts
  and schedule `process_job` again.
- **CSV upload:** a route that parses rows into the same recipient list and calls the same
  job-creation service.
- **Emailing certificates** to recipients once they are generated.
- **Public verification:** a URL or QR code on the PDF, using the certificate number, that
  confirms a certificate is genuine.
- **Object storage** such as S3 for the PDFs, with pre-signed download URLs.
- **Authentication and per-client job ownership.**
- **More templates:** a `template` field on the job that selects the render function.

## Project layout

```
app/
  main.py              app factory, routers, error handlers, startup recovery
  config.py            settings (DATABASE_URL, STORAGE_DIR, MAX_RECIPIENTS)
  db.py                engine, session factory, session dependency
  models.py            Job and Certificate tables, status enums
  schemas.py           request and response models
  errors.py            domain errors and the {"error": {...}} response shape
  api/jobs.py          job routes (create, status, list, zip)
  api/certificates.py  single certificate download
  services/
    jobs.py            job creation, queries, download preparation
    validation.py      recipient validation (pure functions)
    renderer.py        recipient data -> PDF bytes (no DB, no HTTP)
    processor.py       process_job(job_id): the generation loop
    storage.py         file paths, saving, filenames, zip building
  assets/fonts/        DejaVu Sans and its license
tests/                 pytest suite
examples/job.json      sample request body
docs/                  sample generated certificate
```
