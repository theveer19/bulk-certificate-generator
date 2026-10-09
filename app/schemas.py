"""Pydantic request and response models.

Validation is intentionally split across two layers:

1. *Structural* validation lives here. A payload that is not a usable bulk
   request at all — ``recipients`` missing, not a list, empty, or a recipient
   that is not an object — is rejected with HTTP 422 and nothing is persisted.

2. *Per-recipient business* validation lives in ``app/services/validation.py``.
   A blank name or a malformed email inside an otherwise valid payload must not
   fail the whole request, so those rows are accepted into the job and recorded
   as ``FAILED`` with a reason.

This is why the recipient fields below are permissive: if ``name`` were
declared ``str = Field(min_length=1)`` here, one blank name among five hundred
good rows would 422 the entire batch, which is exactly the behaviour the
assignment asks us to avoid.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class RecipientIn(BaseModel):
    """One recipient as supplied by the client.

    Every field is optional at this layer on purpose — see the module docstring.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    email: str | None = None
    course_name: str | None = Field(
        default=None,
        description="Per-recipient course/achievement. Falls back to the job title.",
    )


class JobCreateRequest(BaseModel):
    """A bulk certificate generation request."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "title": "Advanced Python Workshop 2026",
                "issue_date": "2026-10-09",
                "recipients": [
                    {"name": "Aarav Sharma", "email": "aarav@example.com"},
                    {
                        "name": "Diya Patel",
                        "email": "diya@example.com",
                        "course_name": "Advanced Python Workshop 2026 (Honours)",
                    },
                ],
            }
        },
    )

    title: str = Field(min_length=1, max_length=200, description="Printed as the course name.")
    issue_date: date | None = Field(
        default=None, description="Defaults to today if omitted."
    )
    recipients: list[RecipientIn] = Field(
        min_length=1, description="At least one recipient. Upper bound is configurable."
    )


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #


class RejectedRecipientOut(BaseModel):
    """A recipient that failed validation, reported back on job creation."""

    index: int = Field(description="Zero-based position in the submitted recipients array.")
    name: str | None = None
    reason: str
    errors: list[str]


class JobCreateResponse(BaseModel):
    """Returned with HTTP 202 — the job is queued, not finished."""

    job_id: str
    status: str
    total_recipients: int
    accepted: int
    rejected: int
    rejected_recipients: list[RejectedRecipientOut] = []
    status_url: str
    certificates_url: str


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    certificate_number: str
    recipient_name: str
    recipient_email: str | None = None
    course_name: str | None = None
    status: str
    failure_reason: str | None = None
    error_message: str | None = None
    file_size: int | None = None
    generated_at: datetime | None = None
    download_url: str | None = None


class JobSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    issue_date: date
    status: str
    total_count: int
    generated_count: int
    failed_count: int
    progress_percent: float
    created_at: datetime
    completed_at: datetime | None = None


class JobDetailOut(JobSummaryOut):
    """Job status with a sample of failures.

    The full per-recipient list is paginated under
    ``GET /api/v1/jobs/{job_id}/certificates`` rather than inlined here, so the
    status endpoint stays cheap to poll even for a thousand-recipient job.
    """

    failed_sample: list[CertificateOut] = []
    certificates_url: str
    download_all_url: str


class PaginatedCertificatesOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CertificateOut]


class PaginatedJobsOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[JobSummaryOut]


class ErrorOut(BaseModel):
    detail: str
