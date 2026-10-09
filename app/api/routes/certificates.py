"""Certificate endpoints: inspect or download one generated certificate."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.serializers import to_certificate_out
from app.database import get_db
from app.enums import CertificateStatus
from app.models import Certificate
from app.schemas import CertificateOut

router = APIRouter(prefix="/certificates", tags=["certificates"])


def _get_certificate(db: Session, certificate_id: str) -> Certificate:
    certificate = db.get(Certificate, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail=f"Certificate {certificate_id} not found")
    return certificate


@router.get(
    "/{certificate_id}",
    response_model=CertificateOut,
    summary="Get one certificate's record",
    responses={404: {"description": "No such certificate"}},
)
def get_certificate(certificate_id: str, db: Session = Depends(get_db)) -> CertificateOut:
    return to_certificate_out(_get_certificate(db, certificate_id))


@router.get(
    "/{certificate_id}/download",
    summary="Download a generated certificate as PDF",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}}},
        404: {"description": "No such certificate, or its file is missing"},
        409: {"description": "The certificate is not generated (still pending, or failed)"},
    },
)
def download_certificate(certificate_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Stream one certificate PDF.

    Status codes are deliberately distinct: **409** means "this certificate
    exists but has no file" (still pending, or it failed), while **404** means
    the record or the file itself is gone. A client polling for completion can
    act on the difference.
    """
    certificate = _get_certificate(db, certificate_id)

    if certificate.status != CertificateStatus.GENERATED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Certificate {certificate.certificate_number} is {certificate.status}"
                + (f": {certificate.error_message}" if certificate.error_message else "")
            ),
        )

    if not certificate.file_path or not Path(certificate.file_path).is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"The file for certificate {certificate.certificate_number} is missing "
                f"from storage"
            ),
        )

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in certificate.recipient_name
    ).strip("_")
    return FileResponse(
        path=certificate.file_path,
        media_type="application/pdf",
        filename=f"{certificate.certificate_number}_{safe_name or 'certificate'}.pdf",
    )
