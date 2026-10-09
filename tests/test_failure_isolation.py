"""Required test area 5: a single certificate failure must not stop the job.

This is the core resilience requirement, so it is tested against a *renderer*
failure (an unexpected crash deep in generation) rather than a validation
failure, which is already filtered out earlier.
"""

import pytest

from app.enums import CertificateStatus, FailureReason, JobStatus
from app.models import Job
from app.services import certificate_service
from app.services.pdf_renderer import CertificateRenderError
from tests.conftest import API, create_job

GOOD_BEFORE = "Aarav Sharma"
POISON = "Diya Patel"
GOOD_AFTER = "Rohan Verma"


@pytest.fixture
def renderer_fails_for_one_recipient(monkeypatch):
    """Make the renderer blow up for exactly one recipient."""
    real_render = certificate_service.render_certificate

    def flaky_render(**kwargs):
        if kwargs.get("recipient_name") == POISON:
            raise CertificateRenderError("simulated renderer failure")
        return real_render(**kwargs)

    monkeypatch.setattr(certificate_service, "render_certificate", flaky_render)
    return flaky_render


def test_one_failure_does_not_block_the_rest_of_the_job(
    client, db, renderer_fails_for_one_recipient
):
    body = create_job(client, [GOOD_BEFORE, POISON, GOOD_AFTER])

    certificates = {c.recipient_name: c for c in db.get(Job, body["job_id"]).certificates}

    # The recipient after the failure still got a certificate — proof the loop
    # continued rather than aborting.
    assert certificates[GOOD_BEFORE].status == CertificateStatus.GENERATED.value
    assert certificates[GOOD_AFTER].status == CertificateStatus.GENERATED.value
    assert certificates[GOOD_BEFORE].file_path
    assert certificates[GOOD_AFTER].file_path


def test_the_failed_certificate_records_why(client, db, renderer_fails_for_one_recipient):
    body = create_job(client, [GOOD_BEFORE, POISON, GOOD_AFTER])

    failed = next(
        c
        for c in db.get(Job, body["job_id"]).certificates
        if c.recipient_name == POISON
    )

    assert failed.status == CertificateStatus.FAILED.value
    assert failed.failure_reason == FailureReason.GENERATION_ERROR.value
    assert "simulated renderer failure" in failed.error_message
    assert failed.file_path is None
    assert failed.file_size is None


def test_job_totals_reflect_the_mixed_outcome(
    client, db, renderer_fails_for_one_recipient
):
    body = create_job(client, [GOOD_BEFORE, POISON, GOOD_AFTER])

    job = db.get(Job, body["job_id"])
    assert job.status == JobStatus.COMPLETED_WITH_ERRORS.value
    assert job.total_count == 3
    assert job.generated_count == 2
    assert job.failed_count == 1
    assert job.progress_percent == 100.0


def test_failures_are_identifiable_through_the_api(
    client, renderer_fails_for_one_recipient
):
    """The status response must be enough to tell successes from failures."""
    body = create_job(client, [GOOD_BEFORE, POISON, GOOD_AFTER])
    job_id = body["job_id"]

    failures = client.get(
        f"{API}/jobs/{job_id}/certificates", params={"status": "FAILED"}
    ).json()
    successes = client.get(
        f"{API}/jobs/{job_id}/certificates", params={"status": "GENERATED"}
    ).json()

    assert failures["total"] == 1
    assert failures["items"][0]["recipient_name"] == POISON
    assert failures["items"][0]["error_message"]
    assert successes["total"] == 2


def test_an_unexpected_exception_type_is_also_contained(client, db, monkeypatch):
    """Not only CertificateRenderError — any exception must be isolated."""
    real_render = certificate_service.render_certificate

    def exploding_render(**kwargs):
        if kwargs.get("recipient_name") == POISON:
            raise ValueError("something unexpected went wrong")
        return real_render(**kwargs)

    monkeypatch.setattr(certificate_service, "render_certificate", exploding_render)

    body = create_job(client, [GOOD_BEFORE, POISON, GOOD_AFTER])

    job = db.get(Job, body["job_id"])
    assert job.status == JobStatus.COMPLETED_WITH_ERRORS.value
    assert job.generated_count == 2
    failed = next(c for c in job.certificates if c.recipient_name == POISON)
    assert "something unexpected" in failed.error_message


def test_every_recipient_failing_marks_the_whole_job_failed(client, db, monkeypatch):
    def always_fails(**kwargs):
        raise CertificateRenderError("storage unavailable")

    monkeypatch.setattr(certificate_service, "render_certificate", always_fails)

    body = create_job(client, [GOOD_BEFORE, POISON, GOOD_AFTER])

    job = db.get(Job, body["job_id"])
    assert job.status == JobStatus.FAILED.value
    assert job.generated_count == 0
    assert job.failed_count == 3
