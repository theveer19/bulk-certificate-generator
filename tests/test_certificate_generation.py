"""Required test area 3: certificate generation."""

from datetime import date
from pathlib import Path

import pytest

from app.enums import CertificateStatus
from app.models import Job
from app.services.pdf_renderer import CertificateRenderError, render_certificate
from tests.conftest import create_job

PDF_MAGIC = b"%PDF-"


def test_a_pdf_is_written_for_every_valid_recipient(client, db):
    body = create_job(client, ["Aarav Sharma", "Diya Patel", "Rohan Verma"])

    certificates = db.get(Job, body["job_id"]).certificates
    assert len(certificates) == 3

    for certificate in certificates:
        assert certificate.status == CertificateStatus.GENERATED.value
        assert certificate.file_path
        path = Path(certificate.file_path)
        assert path.is_file()
        assert path.read_bytes().startswith(PDF_MAGIC)
        assert certificate.file_size == path.stat().st_size > 0
        assert certificate.generated_at is not None


def test_files_are_namespaced_by_job(client, db):
    first = create_job(client, ["Aarav Sharma"])
    second = create_job(client, ["Diya Patel"])

    path_one = Path(db.get(Job, first["job_id"]).certificates[0].file_path)
    path_two = Path(db.get(Job, second["job_id"]).certificates[0].file_path)

    assert path_one.parent.name == first["job_id"]
    assert path_two.parent.name == second["job_id"]
    assert path_one != path_two


def test_renderer_produces_a_valid_pdf(tmp_path):
    output = tmp_path / "certificate.pdf"

    size = render_certificate(
        recipient_name="Aarav Sharma",
        course_name="Advanced Python Workshop 2026",
        issue_date=date(2026, 10, 9),
        certificate_number="CERT-ABCD1234-0001",
        organization_name="Test Organisation",
        signatory_name="Test Signatory",
        signatory_title="Programme Director",
        output_path=output,
    )

    assert size > 0
    assert output.read_bytes().startswith(PDF_MAGIC)


@pytest.mark.parametrize(
    "recipient_name,course_name",
    [
        pytest.param("Li", "AI", id="very-short"),
        pytest.param(
            "Lakshmi Venkataraman Subramanian Iyer Krishnamurthy",
            "Full Stack Web Development with FastAPI, PostgreSQL and Modern "
            "Deployment Practices - Cohort 7",
            id="very-long",
        ),
        pytest.param("Zoë Müller-Çelik", "Café Operations", id="accented-latin"),
        pytest.param("O'Brien-Smith (Jr.)", "C++ & Rust", id="punctuation"),
    ],
)
def test_renderer_handles_awkward_but_valid_content(tmp_path, recipient_name, course_name):
    """Long names shrink to fit and long titles wrap rather than overflowing."""
    output = tmp_path / "certificate.pdf"

    render_certificate(
        recipient_name=recipient_name,
        course_name=course_name,
        issue_date=date(2026, 10, 9),
        certificate_number="CERT-ABCD1234-0001",
        organization_name="Test Organisation",
        signatory_name="Test Signatory",
        signatory_title="Programme Director",
        output_path=output,
    )

    assert output.read_bytes().startswith(PDF_MAGIC)


def test_renderer_rejects_an_empty_name(tmp_path):
    with pytest.raises(CertificateRenderError):
        render_certificate(
            recipient_name="   ",
            course_name="Workshop",
            issue_date=date(2026, 10, 9),
            certificate_number="CERT-ABCD1234-0001",
            organization_name="Test Organisation",
            signatory_name="Test Signatory",
            signatory_title="Programme Director",
            output_path=tmp_path / "certificate.pdf",
        )


def test_renderer_reports_unsupported_scripts_instead_of_rendering_blanks(tmp_path):
    """A known limitation, surfaced as a clear error rather than a broken PDF.

    The built-in Type 1 fonts cover Latin-1 only. Rendering a Devanagari name
    with them would produce empty boxes on a certificate that is handed to a
    real person, so it is reported as a failure instead. Setting
    CERTIFICATE_FONT_PATH to a suitable TrueType font lifts the limit.
    """
    with pytest.raises(CertificateRenderError) as error:
        render_certificate(
            recipient_name="आरव शर्मा",
            course_name="Workshop",
            issue_date=date(2026, 10, 9),
            certificate_number="CERT-ABCD1234-0001",
            organization_name="Test Organisation",
            signatory_name="Test Signatory",
            signatory_title="Programme Director",
            output_path=tmp_path / "certificate.pdf",
        )

    assert "CERTIFICATE_FONT_PATH" in str(error.value)
