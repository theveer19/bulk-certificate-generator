"""SQLAlchemy ORM models.

The schema is deliberately two tables rather than one:

``jobs``
    One row per bulk request.

``certificates``
    One row per recipient in that request.

Storing a row per recipient is what makes per-recipient status tracking and
partial failure possible: a failed render marks its own row ``FAILED`` with a
reason and leaves every other row untouched.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import CertificateStatus, FailureReason, JobStatus

# Re-exported so callers can do ``from app.models import JobStatus``.
__all__ = [
    "Certificate",
    "CertificateStatus",
    "FailureReason",
    "Job",
    "JobStatus",
]


def _new_id() -> str:
    """Primary keys are UUID4 strings.

    Stored as ``String(36)`` rather than a native UUID column so the same
    models run unchanged on SQLite and PostgreSQL.
    """
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=JobStatus.PENDING.value, index=True
    )

    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Certificate.sequence",
    )

    @property
    def processed_count(self) -> int:
        return self.generated_count + self.failed_count

    @property
    def progress_percent(self) -> float:
        """Share of recipients that reached a terminal state, 0-100."""
        if self.total_count == 0:
            return 100.0
        return round(self.processed_count / self.total_count * 100, 2)

    @property
    def is_terminal(self) -> bool:
        return self.status in JobStatus.terminal()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Job id={self.id} status={self.status} total={self.total_count}>"


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        # The sequence number is assigned from the position in the request, so
        # it must be unique within a job and is how we map a result back to the
        # row the client sent.
        UniqueConstraint("job_id", "sequence", name="uq_certificate_job_sequence"),
        Index("ix_certificates_job_status", "job_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    certificate_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    course_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CertificateStatus.PENDING.value, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship(back_populates="certificates")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Certificate number={self.certificate_number} "
            f"recipient={self.recipient_name!r} status={self.status}>"
        )
