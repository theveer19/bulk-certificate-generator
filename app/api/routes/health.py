"""Liveness/readiness endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health", summary="Service health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Report service and database health.

    The database round-trip is what makes this a readiness check rather than a
    "the process is running" check.
    """
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # noqa: BLE001 - report, never raise, from /health
        database = f"error: {exc}"

    return {
        "status": "ok" if database == "ok" else "degraded",
        "service": get_settings().app_name,
        "database": database,
    }
