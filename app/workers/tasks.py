"""Background processing of a generation job.

``process_job`` is handed to FastAPI's ``BackgroundTasks`` after the response
has been sent, so a request carrying five hundred recipients returns in
milliseconds instead of blocking until every PDF is on disk.

Why ``BackgroundTasks`` and not Celery: see "Design decisions" in the README.
The function deliberately takes only a job id and opens its own session, so
moving it onto a Celery/RQ/Dramatiq worker later is a decorator away — nothing
about its body assumes it runs in the web process.
"""

import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.enums import CertificateStatus, JobStatus
from app.models import Certificate, Job
from app.services.certificate_service import generate_certificate, mark_certificate_failed
from app.services.job_service import refresh_job_counters
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

#: How often, in certificates, the job's counters are republished while it runs.
#: Progress has to be committed *during* the loop, not only at the end —
#: otherwise a client polling the status endpoint sees 0% for the whole job and
#: then 100%, which defeats the point of having a progress endpoint. Every row
#: would be correct too, but costs two COUNT queries and a commit per
#: certificate; ten is a reasonable middle.
PROGRESS_UPDATE_EVERY = 10


def process_job(job_id: str) -> None:
    """Generate every pending certificate in a job.

    Each certificate is rendered and committed independently. A failure is
    recorded against its own row and the loop continues, so one bad recipient
    cannot stop the batch — the requirement this whole design is built around.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("process_job called for unknown job %s", job_id)
            return

        logger.info("Processing job %s (%s recipients)", job.id, job.total_count)
        job.status = JobStatus.PROCESSING.value
        db.commit()

        storage = get_storage()
        pending = list(
            db.scalars(
                select(Certificate)
                .where(
                    Certificate.job_id == job.id,
                    Certificate.status == CertificateStatus.PENDING.value,
                )
                .order_by(Certificate.sequence)
            )
        )

        for position, certificate in enumerate(pending, start=1):
            try:
                generate_certificate(db, job, certificate, storage=storage)
            except Exception as exc:  # noqa: BLE001 - isolate every failure
                mark_certificate_failed(db, certificate, exc)

            # Publish progress periodically so the status endpoint advances
            # while the job runs rather than jumping from 0% to 100%.
            if position % PROGRESS_UPDATE_EVERY == 0:
                job = refresh_job_counters(db, job)

        job = refresh_job_counters(db, job)
        logger.info(
            "Job %s finished: status=%s generated=%s failed=%s",
            job.id,
            job.status,
            job.generated_count,
            job.failed_count,
        )
    except Exception:  # noqa: BLE001 - never let a worker crash silently
        logger.exception("Unexpected error while processing job %s", job_id)
        _mark_job_failed(db, job_id)
    finally:
        db.close()


def _mark_job_failed(db, job_id: str) -> None:
    """Last-resort status update if the worker itself blew up."""
    try:
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None and not job.is_terminal:
            job.status = JobStatus.FAILED.value
            db.commit()
    except Exception:  # pragma: no cover - the database is already unhappy
        logger.exception("Could not mark job %s as failed", job_id)
