"""Required test area 2: input validation.

Two layers are exercised here:

* structural problems with the request itself must be rejected with 422;
* a bad recipient inside an otherwise valid batch must *not* fail the batch.
"""

import pytest

from app.enums import CertificateStatus, FailureReason
from app.models import Job
from app.schemas import RecipientIn
from app.services.validation import validate_recipient, validate_recipients
from tests.conftest import API, create_job, make_payload


# --------------------------------------------------------------------------- #
# Request-level (structural) validation → 422, nothing persisted
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"title": "Workshop"}, id="recipients-missing"),
        pytest.param({"title": "Workshop", "recipients": []}, id="recipients-empty"),
        pytest.param(
            {"title": "Workshop", "recipients": "Aarav"}, id="recipients-not-a-list"
        ),
        pytest.param(
            {"title": "", "recipients": [{"name": "Aarav"}]}, id="title-blank"
        ),
        pytest.param({"recipients": [{"name": "Aarav"}]}, id="title-missing"),
        pytest.param(
            {
                "title": "Workshop",
                "issue_date": "not-a-date",
                "recipients": [{"name": "Aarav"}],
            },
            id="issue-date-malformed",
        ),
    ],
)
def test_structurally_invalid_requests_are_rejected(client, db, payload):
    response = client.post(f"{API}/jobs", json=payload)

    assert response.status_code == 422
    # Nothing was written.
    assert db.query(Job).count() == 0


def test_batch_larger_than_the_configured_limit_is_rejected(client):
    from app.config import get_settings

    limit = get_settings().max_recipients_per_job
    payload = make_payload([f"Recipient {i}" for i in range(limit + 1)])

    response = client.post(f"{API}/jobs", json=payload)

    assert response.status_code == 422
    assert str(limit) in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Recipient-level validation → the batch survives
# --------------------------------------------------------------------------- #


def test_a_blank_name_does_not_fail_the_batch(client, db):
    body = create_job(
        client,
        [{"name": "Aarav Sharma"}, {"name": "   "}, {"name": "Diya Patel"}],
    )

    assert body["accepted"] == 2
    assert body["rejected"] == 1
    rejected = body["rejected_recipients"][0]
    assert rejected["index"] == 1
    assert rejected["reason"] == FailureReason.VALIDATION_ERROR.value
    assert "name is required" in rejected["errors"][0]

    # The two good recipients still have certificates.
    job = db.get(Job, body["job_id"])
    generated = [c for c in job.certificates if c.status == CertificateStatus.GENERATED.value]
    assert {c.recipient_name for c in generated} == {"Aarav Sharma", "Diya Patel"}


def test_a_malformed_email_rejects_only_that_recipient(client):
    body = create_job(
        client,
        [
            {"name": "Aarav Sharma", "email": "aarav@example.com"},
            {"name": "Diya Patel", "email": "diya-at-example"},
        ],
    )

    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert "not a valid address" in body["rejected_recipients"][0]["errors"][0]


def test_duplicate_recipients_are_rejected_after_the_first(client):
    body = create_job(
        client,
        [
            {"name": "Aarav Sharma", "email": "aarav@example.com"},
            {"name": "aarav sharma", "email": "AARAV@EXAMPLE.COM"},
        ],
    )

    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert body["rejected_recipients"][0]["reason"] == FailureReason.DUPLICATE_RECIPIENT.value


def test_rejected_recipients_are_recorded_against_the_job(client, db):
    """Failures must be visible on the job, not only in the creation response."""
    body = create_job(client, [{"name": "Aarav Sharma"}, {"name": ""}])

    job = db.get(Job, body["job_id"])
    assert job.total_count == 2
    assert job.generated_count == 1
    assert job.failed_count == 1

    failed = [c for c in job.certificates if c.status == CertificateStatus.FAILED.value]
    assert failed[0].failure_reason == FailureReason.VALIDATION_ERROR.value
    assert failed[0].error_message


def test_email_is_optional(client):
    body = create_job(client, [{"name": "Aarav Sharma"}])
    assert body["accepted"] == 1


# --------------------------------------------------------------------------- #
# The validator in isolation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "email,valid",
    [
        ("aarav@example.com", True),
        ("aarav.sharma+tag@sub.example.co.in", True),
        ("aarav@example", False),
        ("aarav example@test.com", False),
        ("@example.com", False),
        ("aarav@@example.com", False),
    ],
)
def test_email_rules(email, valid):
    accepted, rejected = validate_recipient(RecipientIn(name="Aarav", email=email), 0)
    assert (accepted is not None) is valid
    assert (rejected is not None) is not valid


def test_whitespace_and_control_characters_are_cleaned():
    accepted, _ = validate_recipient(
        RecipientIn(name="  Aarav\x00 Sharma  ", email="  aarav@example.com "), 0
    )
    assert accepted is not None
    assert accepted.name == "Aarav Sharma"
    assert accepted.email == "aarav@example.com"


def test_overlong_name_is_rejected():
    _, rejected = validate_recipient(RecipientIn(name="x" * 500), 0)
    assert rejected is not None
    assert "exceeds" in rejected.message


def test_validate_recipients_preserves_submitted_indexes():
    recipients = [
        RecipientIn(name="Aarav"),
        RecipientIn(name=""),
        RecipientIn(name="Diya"),
    ]
    accepted, rejected = validate_recipients(recipients)

    assert [a.index for a in accepted] == [0, 2]
    assert [r.index for r in rejected] == [1]
