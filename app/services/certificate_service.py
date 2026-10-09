"""Generation of a single certificate.

Isolated from the worker loop so the "generate one certificate" unit can be
tested, retried or called from a different runner without change.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import CertificateStatus, FailureReason
from app.models import Certificate, Job
from app.services.pdf_renderer import render_certificate
from app.services.storage import Storage, get_storage

logger = logging.getLogger(__name__)


def generate_certificate(
    db: Session,
    job: Job,
    certificate: Certificate,
    storage: Storage | None = None,
) -> Certificate:
    """Render one certificate and commit its result.

    The commit happens per certificate — that is what keeps one failure from
    rolling back the successes that came before it in the same job.

    Raises:
        CertificateRenderError: propagated so the caller can record the failure.
    """
    settings = get_settings()
    storage = storage or get_storage()

    storage.prepare_job(job.id)
    output_path = storage.path_for(job.id, certificate.id)

    size = render_certificate(
        recipient_name=certificate.recipient_name,
        # Per-recipient course name wins; otherwise the job title is used.
        course_name=certificate.course_name or job.title,
        issue_date=job.issue_date,
        certificate_number=certificate.certificate_number,
        organization_name=settings.organization_name,
        signatory_name=settings.signatory_name,
        signatory_title=settings.signatory_title,
        output_path=output_path,
    )

    certificate.status = CertificateStatus.GENERATED.value
    certificate.file_path = str(output_path)
    certificate.file_size = size
    certificate.generated_at = datetime.now(timezone.utc)
    certificate.failure_reason = None
    certificate.error_message = None
    db.commit()

    return certificate


def mark_certificate_failed(
    db: Session, certificate: Certificate, error: Exception
) -> Certificate:
    """Record a generation failure against a single certificate.

    Any pending transaction is rolled back first: the failing render may have
    left the session dirty, and we must still be able to write the failure.
    """
    db.rollback()

    fresh = db.get(Certificate, certificate.id)
    if fresh is None:  # pragma: no cover - the row was deleted mid-flight
        return certificate

    # Anything reaching this point failed while rendering or writing the file;
    # bad input was already filtered out at validation time.
    fresh.status = CertificateStatus.FAILED.value
    fresh.failure_reason = FailureReason.GENERATION_ERROR.value
    # Truncated: the message is shown through the API, not a place for a
    # full traceback. The traceback goes to the application log.
    fresh.error_message = str(error)[:1000] or error.__class__.__name__
    fresh.file_path = None
    fresh.file_size = None
    db.commit()

    logger.exception(
        "Certificate %s failed to generate", fresh.certificate_number, exc_info=error
    )
    return fresh
