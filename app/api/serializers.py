"""Converters from ORM objects to response models.

Kept apart from the route handlers so the "what does a certificate look like
over the wire" decision lives in exactly one place.
"""

from app.config import get_settings
from app.enums import CertificateStatus
from app.models import Certificate, Job
from app.schemas import CertificateOut, JobDetailOut, JobSummaryOut


def certificate_download_url(certificate: Certificate) -> str | None:
    """Download link, or None when there is no file to download yet."""
    if certificate.status != CertificateStatus.GENERATED.value:
        return None
    prefix = get_settings().api_prefix
    return f"{prefix}/certificates/{certificate.id}/download"


def to_certificate_out(certificate: Certificate) -> CertificateOut:
    return CertificateOut(
        id=certificate.id,
        sequence=certificate.sequence,
        certificate_number=certificate.certificate_number,
        recipient_name=certificate.recipient_name,
        recipient_email=certificate.recipient_email,
        course_name=certificate.course_name,
        status=certificate.status,
        failure_reason=certificate.failure_reason,
        error_message=certificate.error_message,
        file_size=certificate.file_size,
        generated_at=certificate.generated_at,
        download_url=certificate_download_url(certificate),
    )


def to_job_summary(job: Job) -> JobSummaryOut:
    return JobSummaryOut(
        id=job.id,
        title=job.title,
        issue_date=job.issue_date,
        status=job.status,
        total_count=job.total_count,
        generated_count=job.generated_count,
        failed_count=job.failed_count,
        progress_percent=job.progress_percent,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def to_job_detail(job: Job, failed_sample: list[Certificate]) -> JobDetailOut:
    prefix = get_settings().api_prefix
    return JobDetailOut(
        **to_job_summary(job).model_dump(),
        failed_sample=[to_certificate_out(c) for c in failed_sample],
        certificates_url=f"{prefix}/jobs/{job.id}/certificates",
        download_all_url=f"{prefix}/jobs/{job.id}/download",
    )
