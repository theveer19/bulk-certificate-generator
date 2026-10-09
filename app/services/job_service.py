"""Job creation and querying.

Everything the API layer needs to do with jobs lives here, so the routes stay
thin and the same logic can be driven from tests or a CLI.
"""

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import CertificateStatus, JobStatus
from app.models import Certificate, Job
from app.schemas import JobCreateRequest
from app.services.validation import (
    AcceptedRecipient,
    RejectedRecipient,
    validate_recipients,
)


def build_certificate_number(job_id: str, sequence: int) -> str:
    """Human-readable, unique identifier printed on the certificate.

    Derived from the job id and the recipient's position in the request, so a
    printed certificate can always be traced back to its database row.
    """
    return f"CERT-{job_id[:8].upper()}-{sequence:04d}"


def create_job(
    db: Session, payload: JobCreateRequest
) -> tuple[Job, list[AcceptedRecipient], list[RejectedRecipient]]:
    """Validate the payload and persist the job and all of its recipient rows.

    Invalid recipients are persisted too, as ``FAILED`` certificates carrying
    the reason. Keeping them in the same table means the job's totals always
    add up and a client can see exactly which of its rows were dropped and why,
    rather than having to diff the request against the result.
    """
    accepted, rejected = validate_recipients(payload.recipients)

    job = Job(
        title=payload.title.strip(),
        issue_date=payload.issue_date or date.today(),
        status=JobStatus.PENDING.value,
        total_count=len(payload.recipients),
        generated_count=0,
        failed_count=len(rejected),
    )
    db.add(job)
    # Flush (not commit) to obtain the generated job id for certificate numbers
    # while keeping the whole creation in one transaction.
    db.flush()

    for recipient in accepted:
        sequence = recipient.index + 1
        db.add(
            Certificate(
                job_id=job.id,
                sequence=sequence,
                certificate_number=build_certificate_number(job.id, sequence),
                recipient_name=recipient.name,
                recipient_email=recipient.email,
                course_name=recipient.course_name,
                status=CertificateStatus.PENDING.value,
            )
        )

    for bad in rejected:
        sequence = bad.index + 1
        db.add(
            Certificate(
                job_id=job.id,
                sequence=sequence,
                certificate_number=build_certificate_number(job.id, sequence),
                # Preserve whatever the client sent so the row is recognisable,
                # even when the name is what failed validation.
                recipient_name=(bad.name or "(missing name)")[:200],
                status=CertificateStatus.FAILED.value,
                failure_reason=bad.reason.value,
                error_message=bad.message,
            )
        )

    db.commit()
    db.refresh(job)
    return job, accepted, rejected


def get_job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)


def list_jobs(db: Session, limit: int, offset: int) -> tuple[int, list[Job]]:
    total = db.scalar(select(func.count()).select_from(Job)) or 0
    jobs = list(
        db.scalars(
            select(Job).order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset)
        )
    )
    return total, jobs


def list_certificates(
    db: Session,
    job_id: str,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[int, list[Certificate]]:
    """Paginated certificates for a job, optionally filtered by status."""
    filters = [Certificate.job_id == job_id]
    if status:
        filters.append(Certificate.status == status)

    total = db.scalar(select(func.count()).select_from(Certificate).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Certificate).where(*filters).order_by(Certificate.sequence).limit(limit).offset(offset)
        )
    )
    return total, items


def failed_certificates(db: Session, job_id: str, limit: int = 10) -> list[Certificate]:
    """A small sample of failures, inlined into the job status response."""
    return list(
        db.scalars(
            select(Certificate)
            .where(
                Certificate.job_id == job_id,
                Certificate.status == CertificateStatus.FAILED.value,
            )
            .order_by(Certificate.sequence)
            .limit(limit)
        )
    )


def refresh_job_counters(db: Session, job: Job) -> Job:
    """Recompute a job's counters and status from its certificate rows.

    Counters are derived from the rows rather than incremented in memory, so a
    retry or a concurrent worker can never drift them out of sync.
    """
    generated = (
        db.scalar(
            select(func.count())
            .select_from(Certificate)
            .where(
                Certificate.job_id == job.id,
                Certificate.status == CertificateStatus.GENERATED.value,
            )
        )
        or 0
    )
    failed = (
        db.scalar(
            select(func.count())
            .select_from(Certificate)
            .where(
                Certificate.job_id == job.id,
                Certificate.status == CertificateStatus.FAILED.value,
            )
        )
        or 0
    )

    job.generated_count = generated
    job.failed_count = failed

    if generated + failed < job.total_count:
        job.status = JobStatus.PROCESSING.value
        job.completed_at = None
    else:
        if failed == 0:
            job.status = JobStatus.COMPLETED.value
        elif generated == 0:
            job.status = JobStatus.FAILED.value
        else:
            job.status = JobStatus.COMPLETED_WITH_ERRORS.value
        job.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)
    return job
