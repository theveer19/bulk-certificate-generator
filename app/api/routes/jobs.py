"""Job endpoints: create a bulk request, poll it, download its output."""

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.enums import CertificateStatus
from app.api.serializers import to_certificate_out, to_job_detail, to_job_summary
from app.schemas import (
    JobCreateRequest,
    JobCreateResponse,
    JobDetailOut,
    PaginatedCertificatesOut,
    PaginatedJobsOut,
    RejectedRecipientOut,
)
from app.services import job_service
from app.workers.tasks import process_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a bulk certificate generation request",
    response_description="The job was accepted and queued for generation.",
)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobCreateResponse:
    """Accept a batch of recipients and queue them for generation.

    Returns **202 Accepted**, not 201: the job exists, but the certificates do
    not yet. Poll ``status_url`` to follow progress.

    Recipients that fail validation do not fail the request — they are
    reported in ``rejected_recipients`` and recorded against the job.
    """
    settings = get_settings()
    if len(payload.recipients) > settings.max_recipients_per_job:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"A single job accepts at most {settings.max_recipients_per_job} "
                f"recipients; received {len(payload.recipients)}. Split the batch."
            ),
        )

    job, accepted, rejected = job_service.create_job(db, payload)

    # Runs after the response is sent.
    background_tasks.add_task(process_job, job.id)

    prefix = settings.api_prefix
    return JobCreateResponse(
        job_id=job.id,
        status=job.status,
        total_recipients=job.total_count,
        accepted=len(accepted),
        rejected=len(rejected),
        rejected_recipients=[
            RejectedRecipientOut(
                index=r.index, name=r.name, reason=r.reason.value, errors=r.errors
            )
            for r in rejected
        ],
        status_url=f"{prefix}/jobs/{job.id}",
        certificates_url=f"{prefix}/jobs/{job.id}/certificates",
    )


@router.get("", response_model=PaginatedJobsOut, summary="List jobs")
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedJobsOut:
    total, jobs = job_service.list_jobs(db, limit=limit, offset=offset)
    return PaginatedJobsOut(
        total=total, limit=limit, offset=offset, items=[to_job_summary(j) for j in jobs]
    )


@router.get(
    "/{job_id}",
    response_model=JobDetailOut,
    summary="Check job status and progress",
    responses={404: {"description": "No such job"}},
)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    """Status, counters and progress for one job.

    A sample of failures is inlined; the complete per-recipient list is
    paginated under ``/jobs/{job_id}/certificates`` so this endpoint stays
    cheap to poll.
    """
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return to_job_detail(job, job_service.failed_certificates(db, job.id))


@router.get(
    "/{job_id}/certificates",
    response_model=PaginatedCertificatesOut,
    summary="List the certificates in a job",
    responses={404: {"description": "No such job"}},
)
def list_job_certificates(
    job_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    certificate_status: CertificateStatus | None = Query(
        None,
        alias="status",
        description="Filter by certificate status, e.g. FAILED.",
    ),
    db: Session = Depends(get_db),
) -> PaginatedCertificatesOut:
    if job_service.get_job(db, job_id) is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    total, items = job_service.list_certificates(
        db,
        job_id,
        limit=limit,
        offset=offset,
        status=certificate_status.value if certificate_status else None,
    )
    return PaginatedCertificatesOut(
        total=total,
        limit=limit,
        offset=offset,
        items=[to_certificate_out(c) for c in items],
    )


@router.get(
    "/{job_id}/download",
    summary="Download every generated certificate in the job as a ZIP",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"application/zip": {}}},
        404: {"description": "No such job, or nothing generated yet"},
    },
)
def download_job_archive(job_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    """Bundle a job's PDFs into one ZIP.

    The archive is built in memory, which is fine at the configured batch
    ceiling. For much larger jobs this should stream from disk or be produced
    once and cached — noted in the README's future scope.
    """
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    _, certificates = job_service.list_certificates(
        db, job_id, limit=10_000, offset=0, status=CertificateStatus.GENERATED.value
    )
    if not certificates:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} has no generated certificates to download",
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for certificate in certificates:
            if not certificate.file_path or not Path(certificate.file_path).is_file():
                continue
            safe_name = "".join(
                ch if ch.isalnum() or ch in "-_ " else "_" for ch in certificate.recipient_name
            ).strip()
            archive.write(
                certificate.file_path,
                arcname=f"{certificate.certificate_number}_{safe_name or 'recipient'}.pdf",
            )
    buffer.seek(0)

    filename = f"certificates_{job.id[:8]}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
