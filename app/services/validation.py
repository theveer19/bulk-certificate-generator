"""Per-recipient business validation.

This module is pure Python with no database or framework imports, which keeps
it trivially unit-testable and means the rules can be reused by a CSV importer
or a CLI without dragging FastAPI along.

Its job is to split a submitted list of recipients into those we will try to
generate certificates for and those we will not, *without* failing the batch.
"""

import re
from dataclasses import dataclass, field

from app.enums import FailureReason
from app.schemas import RecipientIn

MAX_NAME_LENGTH = 200
MAX_EMAIL_LENGTH = 254
MAX_COURSE_NAME_LENGTH = 200

# A pragmatic email check: one "@", a non-empty local part, and a dotted
# domain. Full RFC 5322 compliance is not attempted on purpose — the regex is
# isolated in this one function, so swapping in the `email-validator` package
# is a one-line change if stricter checking is ever needed.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")

# Reject control characters outright; they corrupt the rendered PDF text.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class AcceptedRecipient:
    """A recipient that passed validation, with cleaned-up values."""

    index: int
    name: str
    email: str | None = None
    course_name: str | None = None


@dataclass
class RejectedRecipient:
    """A recipient that failed validation and will never be rendered."""

    index: int
    name: str | None
    reason: FailureReason
    errors: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return "; ".join(self.errors)


def _clean(value: str | None) -> str | None:
    """Trim whitespace and strip control characters; empty becomes None."""
    if value is None:
        return None
    cleaned = _CONTROL_CHARS_RE.sub("", value).strip()
    return cleaned or None


def _duplicate_key(name: str, email: str | None) -> str:
    """Identity used for duplicate detection within a single request."""
    return f"{name.casefold()}|{(email or '').casefold()}"


def validate_recipient(
    recipient: RecipientIn, index: int
) -> tuple[AcceptedRecipient | None, RejectedRecipient | None]:
    """Validate one recipient in isolation.

    Returns ``(accepted, None)`` or ``(None, rejected)``.
    """
    errors: list[str] = []

    name = _clean(recipient.name)
    email = _clean(recipient.email)
    course_name = _clean(recipient.course_name)

    if name is None:
        errors.append("name is required and cannot be blank")
    elif len(name) > MAX_NAME_LENGTH:
        errors.append(f"name exceeds {MAX_NAME_LENGTH} characters")

    if email is not None:
        if len(email) > MAX_EMAIL_LENGTH:
            errors.append(f"email exceeds {MAX_EMAIL_LENGTH} characters")
        elif not _EMAIL_RE.match(email):
            errors.append(f"email {email!r} is not a valid address")

    if course_name is not None and len(course_name) > MAX_COURSE_NAME_LENGTH:
        errors.append(f"course_name exceeds {MAX_COURSE_NAME_LENGTH} characters")

    if errors:
        return None, RejectedRecipient(
            index=index,
            name=name,
            reason=FailureReason.VALIDATION_ERROR,
            errors=errors,
        )

    assert name is not None  # narrowed by the checks above
    return (
        AcceptedRecipient(index=index, name=name, email=email, course_name=course_name),
        None,
    )


def validate_recipients(
    recipients: list[RecipientIn],
) -> tuple[list[AcceptedRecipient], list[RejectedRecipient]]:
    """Validate a whole batch, including cross-row duplicate detection.

    Duplicates are matched case-insensitively on (name, email). The first
    occurrence is accepted; later ones are rejected as ``DUPLICATE_RECIPIENT``,
    so a client that accidentally submits the same CSV twice does not get two
    certificates for the same person.
    """
    accepted: list[AcceptedRecipient] = []
    rejected: list[RejectedRecipient] = []
    seen: dict[str, int] = {}

    for index, recipient in enumerate(recipients):
        ok, bad = validate_recipient(recipient, index)
        if bad is not None:
            rejected.append(bad)
            continue

        assert ok is not None
        key = _duplicate_key(ok.name, ok.email)
        if key in seen:
            rejected.append(
                RejectedRecipient(
                    index=index,
                    name=ok.name,
                    reason=FailureReason.DUPLICATE_RECIPIENT,
                    errors=[
                        f"duplicate of recipient at index {seen[key]} "
                        f"(same name and email)"
                    ],
                )
            )
            continue

        seen[key] = index
        accepted.append(ok)

    return accepted, rejected
