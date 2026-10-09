"""Required test area 1: creating a generation job."""

from app.enums import CertificateStatus, JobStatus
from app.models import Job
from tests.conftest import API, create_job


def test_create_job_returns_202_and_job_id(client):
    body = create_job(client, ["Aarav Sharma", "Diya Patel", "Rohan Verma"])

    assert body["job_id"]
    assert body["total_recipients"] == 3
    assert body["accepted"] == 3
    assert body["rejected"] == 0
    assert body["rejected_recipients"] == []
    assert body["status_url"].endswith(body["job_id"])


def test_create_job_persists_one_row_per_recipient(client, db):
    body = create_job(client, ["Aarav Sharma", "Diya Patel"])

    job = db.get(Job, body["job_id"])
    assert job is not None
    assert job.title == "Advanced Python Workshop 2026"
    assert job.issue_date.isoformat() == "2026-10-09"
    assert len(job.certificates) == 2

    # Sequence mirrors the order the client submitted.
    assert [c.sequence for c in job.certificates] == [1, 2]
    assert [c.recipient_name for c in job.certificates] == ["Aarav Sharma", "Diya Patel"]


def test_certificate_numbers_are_unique_and_traceable(client, db):
    body = create_job(client, ["Aarav Sharma", "Diya Patel", "Rohan Verma"])
    job_id = body["job_id"]

    numbers = [c.certificate_number for c in db.get(Job, job_id).certificates]
    assert len(set(numbers)) == 3
    # Every number carries the job prefix, so a printed PDF maps back to its job.
    assert all(n.startswith(f"CERT-{job_id[:8].upper()}-") for n in numbers)


def test_single_request_handles_a_large_batch(client, db):
    """The API is built around one request carrying many recipients."""
    names = [f"Recipient {i:03d}" for i in range(120)]
    body = create_job(client, names)

    assert body["accepted"] == 120
    job = db.get(Job, body["job_id"])
    assert job.total_count == 120
    assert job.generated_count == 120
    assert job.status == JobStatus.COMPLETED.value


def test_issue_date_defaults_to_today_when_omitted(client, db):
    from datetime import date

    response = client.post(
        f"{API}/jobs",
        json={"title": "Workshop", "recipients": [{"name": "Aarav Sharma"}]},
    )
    assert response.status_code == 202

    job = db.get(Job, response.json()["job_id"])
    assert job.issue_date == date.today()


def test_per_recipient_course_name_overrides_job_title(client, db):
    body = create_job(
        client,
        [
            {"name": "Aarav Sharma"},
            {"name": "Diya Patel", "course_name": "Advanced Python (Honours)"},
        ],
    )

    certificates = db.get(Job, body["job_id"]).certificates
    assert certificates[0].course_name is None  # falls back to the job title
    assert certificates[1].course_name == "Advanced Python (Honours)"


def test_job_listing_includes_the_new_job(client):
    body = create_job(client, ["Aarav Sharma"])

    listing = client.get(f"{API}/jobs").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == body["job_id"]


def test_all_certificates_start_from_a_known_state(client, db):
    """No certificate is ever left in PENDING once the worker has run."""
    body = create_job(client, ["Aarav Sharma", "Diya Patel"])

    statuses = {c.status for c in db.get(Job, body["job_id"]).certificates}
    assert CertificateStatus.PENDING.value not in statuses


def test_unknown_job_returns_404(client):
    assert client.get(f"{API}/jobs/does-not-exist").status_code == 404
