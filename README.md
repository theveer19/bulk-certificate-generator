# Bulk Certificate Generator

A backend API that accepts one request containing many recipients, generates a
PDF certificate for each of them from a predefined template, tracks the outcome
per recipient, and lets the client retrieve the results.

Built with **FastAPI**, **SQLAlchemy 2.0** and **ReportLab**. It runs against
SQLite with no setup at all, and against PostgreSQL via Docker Compose.

---

## Contents

- [Quick start](#quick-start)
- [Running the tests](#running-the-tests)
- [Using the API](#using-the-api)
- [How it works](#how-it-works)
- [Design decisions](#design-decisions)
- [Known limitations](#known-limitations)
- [What I learned](#what-i-learned)
- [Future scope](#future-scope)
- [Project structure](#project-structure)

---

## Quick start

Requires Python 3.11 or newer. No database server, compiler or system library
is needed for the default setup.

```bash
git clone <your-repo-url>
cd bulk-certificate-generator

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://localhost:8000/docs> for the interactive API documentation. The
service creates its SQLite database and storage directory on first start.

### Optional configuration

Every setting has a working default. Copy `.env.example` to `.env` to change
the organisation and signatory printed on the certificate, point at
PostgreSQL, or move the storage directory.

### With Docker (PostgreSQL)

```bash
docker compose up --build
```

This starts PostgreSQL and the API together, proving the same code runs on
both databases. The API is on <http://localhost:8000>.

---

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite uses a throwaway SQLite database and a temporary storage directory,
so it never touches local data. It covers all six required areas:

| File | Covers |
|---|---|
| `tests/test_job_creation.py` | Creating a generation job |
| `tests/test_validation.py` | Input validation, both layers |
| `tests/test_certificate_generation.py` | Certificate generation and the renderer |
| `tests/test_job_status.py` | Job status and progress |
| `tests/test_failure_isolation.py` | Handling an individual certificate failure |
| `tests/test_certificate_retrieval.py` | Retrieving generated certificates |

---

## Using the API

All endpoints are prefixed with `/api/v1`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/jobs` | Submit a bulk generation request |
| `GET` | `/jobs` | List jobs |
| `GET` | `/jobs/{job_id}` | Job status and progress |
| `GET` | `/jobs/{job_id}/certificates` | Paginated per-recipient results |
| `GET` | `/jobs/{job_id}/download` | All generated certificates as a ZIP |
| `GET` | `/certificates/{id}` | One certificate record |
| `GET` | `/certificates/{id}/download` | One certificate as PDF |
| `GET` | `/health` | Service and database health |

### 1. Submit a generation request

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @samples/sample_request.json
```

Request body:

```json
{
  "title": "Advanced Python Workshop 2026",
  "issue_date": "2026-10-09",
  "recipients": [
    { "name": "Aarav Sharma", "email": "aarav@example.com" },
    { "name": "Diya Patel",  "email": "diya@example.com",
      "course_name": "Advanced Python Workshop 2026 (Honours)" },
    { "name": "   " }
  ]
}
```

`title` is printed as the course name. `issue_date` defaults to today.
`email` and `course_name` are optional per recipient; `course_name` overrides
the job title for that one certificate.

Response — **202 Accepted**, because the job exists but the certificates do not
yet:

```json
{
  "job_id": "4f1c2e8a-9b3d-4c77-8a51-0d2f6b7e1a44",
  "status": "PENDING",
  "total_recipients": 3,
  "accepted": 2,
  "rejected": 1,
  "rejected_recipients": [
    {
      "index": 2,
      "name": null,
      "reason": "VALIDATION_ERROR",
      "errors": ["name is required and cannot be blank"]
    }
  ],
  "status_url": "/api/v1/jobs/4f1c2e8a-9b3d-4c77-8a51-0d2f6b7e1a44",
  "certificates_url": "/api/v1/jobs/4f1c2e8a-9b3d-4c77-8a51-0d2f6b7e1a44/certificates"
}
```

Note that the one invalid recipient did **not** fail the request. It is
reported back with its position in the submitted array and recorded against
the job.

### 2. Check progress

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}
```

```json
{
  "id": "4f1c2e8a-9b3d-4c77-8a51-0d2f6b7e1a44",
  "title": "Advanced Python Workshop 2026",
  "issue_date": "2026-10-09",
  "status": "COMPLETED_WITH_ERRORS",
  "total_count": 3,
  "generated_count": 2,
  "failed_count": 1,
  "progress_percent": 100.0,
  "created_at": "2026-10-09T08:14:22Z",
  "completed_at": "2026-10-09T08:14:23Z",
  "failed_sample": [
    {
      "sequence": 3,
      "certificate_number": "CERT-4F1C2E8A-0003",
      "recipient_name": "(missing name)",
      "status": "FAILED",
      "failure_reason": "VALIDATION_ERROR",
      "error_message": "name is required and cannot be blank",
      "download_url": null
    }
  ],
  "certificates_url": "/api/v1/jobs/.../certificates",
  "download_all_url": "/api/v1/jobs/.../download"
}
```

Job statuses:

| Status | Meaning |
|---|---|
| `PENDING` | Accepted, not started |
| `PROCESSING` | Generation under way |
| `COMPLETED` | Every recipient succeeded |
| `COMPLETED_WITH_ERRORS` | Some succeeded, some failed |
| `FAILED` | No recipient could be generated |

### 3. Inspect per-recipient results

```bash
# everything, paginated
curl "http://localhost:8000/api/v1/jobs/{job_id}/certificates?limit=50&offset=0"

# just the failures
curl "http://localhost:8000/api/v1/jobs/{job_id}/certificates?status=FAILED"
```

### 4. Retrieve the certificates

```bash
# one certificate
curl -OJ http://localhost:8000/api/v1/certificates/{certificate_id}/download

# the whole job as a ZIP
curl -OJ http://localhost:8000/api/v1/jobs/{job_id}/download
```

Downloading a certificate that failed or is still pending returns **409**, not
404 — the record exists, the file does not. A client polling for completion can
act on that difference.

### Trying the bulk path

```bash
python scripts/make_bulk_request.py 500 > samples/bulk_500.json
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" -d @samples/bulk_500.json
```

The response comes back immediately; the 500 PDFs appear under
`storage/certificates/{job_id}/` as the background worker writes them.

---

## How it works

```
POST /api/v1/jobs
      │
      ├─ 1. Structural validation (Pydantic) ──── bad request ──→ 422, nothing saved
      │
      ├─ 2. Per-recipient validation ─── invalid rows recorded as FAILED
      │
      ├─ 3. Persist: 1 job row + 1 certificate row per recipient
      │
      ├─ 4. Queue process_job(job_id) as a background task
      │
      └─ 5. Return 202 with the job id            (request ends here)

Background worker
      │
      for each PENDING certificate:
      │     ├─ render the PDF  ──→ success: status GENERATED, commit
      │     ├─ any exception   ──→ status FAILED + reason, commit, CONTINUE
      │     └─ every 10 certificates: republish the job counters
      │
      └─ recompute job counters and final status from the rows
```

The database schema is two tables:

```
jobs                               certificates
────────────────────────           ──────────────────────────────
id            (uuid)      1 ───┐   id                 (uuid)
title                          └─n job_id             (fk)
issue_date                         sequence           (position in request)
status                             certificate_number (printed on the PDF)
total_count                        recipient_name / email / course_name
generated_count                    status
failed_count                       failure_reason / error_message
created_at / completed_at          file_path / file_size / generated_at
```

A row per recipient is what makes everything else possible: per-recipient
status, partial failure, pagination, and counters that are *derived* from the
rows rather than incremented in memory.

---

## Design decisions

### Background processing over a synchronous response

A single request may carry hundreds of recipients. Rendering them inline would
hold the connection open for the whole batch, risk a gateway timeout, and give
the client no way to see progress. So `POST /jobs` persists the work, returns
**202 Accepted**, and generates in the background while the client polls.

**Why FastAPI `BackgroundTasks` and not Celery.** At the scale this service
targets — jobs up to the configured 1000-recipient ceiling, roughly 2 ms per
certificate — in-process background execution is sufficient and keeps the
project to a single runnable component, which matters for a reviewer cloning
the repo. The trade-off is explicit: tasks live in the web process, so a
restart mid-job leaves certificates in `PENDING`, and the work does not spread
across machines.

`process_job` was written to make that migration trivial. It takes only a job
id, opens its own session, and assumes nothing about its caller — moving it to
Celery means adding a decorator and swapping `background_tasks.add_task` for
`.delay()`. Nothing else changes. The recovery story for interrupted jobs is a
start-up sweep that re-queues any job left in `PENDING`/`PROCESSING`, which is
listed under future scope.

### Two layers of validation

The assignment asks for invalid data to be handled appropriately *and* for one
failure not to block the rest. Those pull in opposite directions if all
validation happens in one place, because Pydantic rejects the whole request
body on the first bad field.

So the request model is deliberately permissive about recipient fields, and
business rules live in `app/services/validation.py`:

- **422, nothing persisted** — the request is not a usable batch at all:
  `recipients` missing, empty, or not a list; `title` blank; malformed
  `issue_date`; more recipients than the configured ceiling.
- **Accepted, that row marked `FAILED`** — one recipient is bad: blank name,
  overlong name, malformed email, or a duplicate of an earlier row.

The client gets back the index of every rejected row, so it can map failures
onto the array it sent.

### Failure isolation by commit boundary

Each certificate is committed on its own as it is rendered. A failure rolls
back only its own transaction, writes a `FAILED` row with the reason, and the
loop moves to the next recipient. This is structural rather than a `try`/`except`
bolted on: there is no shared transaction that a late failure could undo.

Job counters are then recomputed with `COUNT` queries over the certificate
rows rather than incremented in memory, so they cannot drift out of sync with
reality if a job is ever retried or processed concurrently.

### Progress is published during the run, not only at the end

Counters are committed every ten certificates as well as at the end. This was
a bug I found by watching a real job rather than by reading the code: the
first version recomputed counters only after the loop finished, so a polling
client saw `0%` for the entire job and then `100%` — a progress endpoint that
reported no progress. Updating after every single certificate would also be
correct but costs two `COUNT` queries and a commit per PDF; ten is the
compromise, and `PROGRESS_UPDATE_EVERY` makes it tunable.

### ReportLab over an HTML-to-PDF engine

The obvious alternative was a Jinja2 HTML template rendered by WeasyPrint,
which gives nicer styling control. It was rejected because WeasyPrint needs
GTK/Pango/Cairo system libraries — a genuinely painful install on Windows and
a heavier Docker image. ReportLab is pure Python, installs from a wheel
everywhere, and renders identically on every platform, so `pip install -r
requirements.txt` is all a reviewer needs.

The cost is that the template is drawn in code rather than styled in CSS. For
a single predefined template that is an acceptable trade; if the service ever
needed multiple designs or user-supplied templates, HTML templating would
become the better choice.

### SQLite by default, PostgreSQL supported

The default `DATABASE_URL` is a local SQLite file so the project runs
immediately after a clone. Nothing in the code is SQLite-specific: ids are
`String(36)` rather than a native UUID type, and `docker compose up` runs the
identical code against PostgreSQL 16.

### Synchronous SQLAlchemy

PDF rendering is CPU-bound work that happens in a worker thread. Synchronous
sessions are much simpler to reason about there, and FastAPI runs `def`
endpoints in a threadpool, so the event loop is never blocked. Async SQLAlchemy
would add complexity without a benefit at this scale.

### Schema creation instead of migrations

The schema is created from the model metadata at start-up. For a two-table
service this keeps setup to one command. A production deployment would use
Alembic; adding it is `alembic init` plus one autogenerated revision, and the
hook is already isolated in `init_db()`.

---

## Known limitations

These are deliberate, scoped choices rather than oversights.

1. **Interrupted jobs are not resumed.** A restart mid-job leaves certificates
   in `PENDING`. The fix is a start-up sweep (see future scope).
2. **Non-Latin scripts need a font.** The built-in Type 1 fonts cover Latin-1.
   A name in Devanagari is detected and reported as a generation failure with
   a clear message rather than being rendered as blank boxes on a certificate
   handed to a real person. Setting `CERTIFICATE_FONT_PATH` to a suitable
   TrueType font lifts the limit; no font binary is committed to the repo for
   licensing reasons.
3. **The ZIP download is built in memory.** Fine at the 1000-recipient
   ceiling, but it should stream from disk for larger jobs.
4. **No authentication.** Out of scope for the assignment; in production these
   endpoints would sit behind API-key or JWT auth, and download URLs would be
   signed and expiring rather than guessable by id.

---

## What I learned

- **Where validation lives changes the API's behaviour.** My first instinct
  was to put every rule in the Pydantic model. That would have made a single
  blank name reject a 500-recipient batch — the exact opposite of the
  requirement. Splitting structural from per-row validation was the decision
  that shaped the rest of the design.
- **Partial failure is a schema problem before it is an exception-handling
  problem.** Once each recipient had its own row and its own commit, "one
  failure must not block the others" stopped needing careful `try`/`except`
  placement and became a property of the design.
- **Derived counters beat incremented ones.** Counting the rows is a little
  more work per job but removes a whole class of drift bugs.
- **A green test suite is not the same as a working service.** All 64 tests
  passed while the progress endpoint was still reporting 0% for the whole run,
  because every test either waited for the job to finish or called the counter
  refresh by hand. The bug only showed up when I polled a job that was still
  running. I added a test that reads the counters from a separate session
  mid-render, which is what the original suite was missing.
- **Dependency choices are UX for the reviewer.** Choosing ReportLab over
  WeasyPrint meant the difference between `pip install` working first time on
  Windows and a GTK troubleshooting session.

---

## Future scope

- **Celery or RQ workers** for horizontal scaling, with retry/backoff on
  transient failures.
- **Start-up recovery sweep** that re-queues jobs left `PENDING` or
  `PROCESSING` by a restart, making the worker crash-safe.
- **Retry endpoint** — `POST /jobs/{id}/retry` to re-attempt only the failed
  certificates in a job.
- **Object storage** (S3/Azure Blob) behind the existing `Storage` interface,
  with pre-signed, expiring download URLs.
- **Email delivery** of each certificate to its recipient, which is why
  `recipient_email` is already captured and validated.
- **Webhook on completion** so clients need not poll.
- **Multiple templates** and a template-selection field, which is the point at
  which HTML-based rendering becomes worth revisiting.
- **CSV/XLSX upload** as an alternative to a JSON body, matching how the
  recipient list usually arrives in practice.
- **Authentication and per-tenant isolation.**

---

## Project structure

```
bulk-certificate-generator/
├── app/
│   ├── main.py                      FastAPI app, routers, lifespan
│   ├── config.py                    Environment-driven settings
│   ├── database.py                  Engine, session factory, Base
│   ├── enums.py                     Status and failure enums
│   ├── models.py                    Job and Certificate ORM models
│   ├── schemas.py                   Request/response models
│   ├── api/
│   │   ├── serializers.py           ORM → response conversion
│   │   └── routes/
│   │       ├── jobs.py              Create, poll, list, ZIP download
│   │       ├── certificates.py      Record and PDF download
│   │       └── health.py            Health check
│   ├── services/
│   │   ├── validation.py            Per-recipient business rules
│   │   ├── job_service.py           Job creation, queries, counters
│   │   ├── certificate_service.py   Generate or fail one certificate
│   │   ├── pdf_renderer.py          The certificate template
│   │   └── storage.py               Storage interface + local backend
│   └── workers/
│       └── tasks.py                 Background job processing
├── tests/                           Six test modules + fixtures
├── samples/                         Example request payloads
├── scripts/make_bulk_request.py     Generate a large payload
├── Dockerfile / docker-compose.yml
├── requirements.txt / requirements-dev.txt
└── .env.example
```
