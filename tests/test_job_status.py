"""Required test area 4: job status and progress."""

from datetime import date

from app.enums import CertificateStatus, JobStatus
from app.models import Job
from app.schemas import JobCreateRequest
from app.services import job_service
from tests.conftest import API, create_job


def test_status_endpoint_reports_completion(client):
    body = create_job(client, ["Aarav Sharma", "Diya Patel"])

    status_body = client.get(f"{API}/jobs/{body['job_id']}").json()

    assert status_body["status"] == JobStatus.COMPLETED.value
    assert status_body["total_count"] == 2
    assert status_body["generated_count"] == 2
    assert status_body["failed_count"] == 0
    assert status_body["progress_percent"] == 100.0
    assert status_body["completed_at"] is not None
    assert status_body["failed_sample"] == []


def test_status_is_completed_with_errors_when_some_recipients_fail(client):
    body = create_job(client, [{"name": "Aarav Sharma"}, {"name": ""}])

    status_body = client.get(f"{API}/jobs/{body['job_id']}").json()

    assert status_body["status"] == JobStatus.COMPLETED_WITH_ERRORS.value
    assert status_body["generated_count"] == 1
    assert status_body["failed_count"] == 1
    assert status_body["progress_percent"] == 100.0


def test_status_is_failed_when_no_recipient_could_be_generated(client):
    body = create_job(client, [{"name": ""}, {"name": "   "}])

    status_body = client.get(f"{API}/jobs/{body['job_id']}").json()

    assert status_body["status"] == JobStatus.FAILED.value
    assert status_body["generated_count"] == 0
    assert status_body["failed_count"] == 2


def test_status_response_samples_the_failures(client):
    body = create_job(
        client,
        [{"name": "Aarav Sharma"}, {"name": ""}, {"name": "Diya Patel", "email": "bad"}],
    )

    status_body = client.get(f"{API}/jobs/{body['job_id']}").json()

    assert len(status_body["failed_sample"]) == 2
    for failure in status_body["failed_sample"]:
        assert failure["status"] == CertificateStatus.FAILED.value
        assert failure["error_message"]
        assert failure["download_url"] is None

    # The full list lives behind its own paginated endpoint.
    assert status_body["certificates_url"].endswith(f"/jobs/{body['job_id']}/certificates")


def test_progress_is_partial_while_a_job_is_still_running(client, db):
    """Counters are derived from the rows, so mid-flight progress is accurate."""
    job, _, _ = job_service.create_job(
        db,
        JobCreateRequest.model_validate(
            {
                "title": "Workshop",
                "recipients": [{"name": f"Recipient {i}"} for i in range(4)],
            }
        ),
    )
    assert job.status == JobStatus.PENDING.value

    # Simulate the worker having finished one of the four.
    first = job.certificates[0]
    first.status = CertificateStatus.GENERATED.value
    db.commit()

    job = job_service.refresh_job_counters(db, job)

    assert job.status == JobStatus.PROCESSING.value
    assert job.progress_percent == 25.0
    assert job.completed_at is None


def test_progress_is_published_to_other_readers_while_the_job_runs(client, monkeypatch):
    """Progress must be visible *during* the job, not only once it finishes.

    The renderer is wrapped so that, just before each certificate is drawn, a
    separate database session reads the job's committed counters — exactly
    what a client polling ``GET /jobs/{id}`` would see at that moment.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.services import certificate_service
    from app.workers import tasks

    # Publish after every certificate so a small test job shows the effect.
    monkeypatch.setattr(tasks, "PROGRESS_UPDATE_EVERY", 1)

    observed: list[int] = []
    real_render = certificate_service.render_certificate

    def recording_render(**kwargs):
        session = SessionLocal()
        try:
            job = session.scalars(select(Job)).first()
            if job is not None:
                observed.append(job.generated_count)
        finally:
            session.close()
        return real_render(**kwargs)

    monkeypatch.setattr(certificate_service, "render_certificate", recording_render)

    create_job(client, ["Aarav Sharma", "Diya Patel", "Rohan Verma", "Ananya Iyer"])

    assert len(observed) == 4
    assert observed[0] == 0  # nothing finished before the first render
    assert observed == sorted(observed)  # never goes backwards
    assert observed[-1] >= 2  # progress was visible while the job was running


def test_progress_of_an_empty_job_does_not_divide_by_zero():
    job = Job(
        title="Empty",
        issue_date=date(2026, 10, 9),
        total_count=0,
        generated_count=0,
        failed_count=0,
    )
    assert job.progress_percent == 100.0


def test_status_for_an_unknown_job_is_404(client):
    response = client.get(f"{API}/jobs/11111111-2222-3333-4444-555555555555")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
