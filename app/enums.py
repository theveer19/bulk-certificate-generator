"""Status enums shared by the ORM, the services and the API layer.

Kept free of SQLAlchemy and FastAPI imports so that pure business logic (for
example ``app/services/validation.py``) can use them without pulling in the
persistence layer.
"""

from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle of a bulk generation job."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    #: Every recipient was generated successfully.
    COMPLETED = "COMPLETED"
    #: Some recipients were generated, some failed.
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    #: No recipient could be generated at all.
    FAILED = "FAILED"

    @classmethod
    def terminal(cls) -> set[str]:
        return {cls.COMPLETED.value, cls.COMPLETED_WITH_ERRORS.value, cls.FAILED.value}


class CertificateStatus(str, Enum):
    """Lifecycle of a single certificate within a job."""

    PENDING = "PENDING"
    GENERATED = "GENERATED"
    FAILED = "FAILED"


class FailureReason(str, Enum):
    """Machine-readable failure categories.

    Exposed alongside the human-readable message so a client can tell
    "you sent bad data" apart from "our renderer broke".
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_RECIPIENT = "DUPLICATE_RECIPIENT"
    GENERATION_ERROR = "GENERATION_ERROR"
