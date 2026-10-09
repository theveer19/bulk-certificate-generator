"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes import certificates, health, jobs
from app.config import get_settings
from app.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and the storage directory before serving traffic."""
    init_db()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    logging.getLogger(__name__).info(
        "%s ready | database=%s | storage=%s",
        settings.app_name,
        settings.database_url.split("://", 1)[0],
        settings.storage_dir,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Generate certificates in bulk from a single request.\n\n"
        "Submit many recipients to `POST /api/v1/jobs`, which returns **202 Accepted** "
        "immediately and generates the PDFs in the background. Poll "
        "`GET /api/v1/jobs/{job_id}` for progress, then download individual "
        "certificates or the whole job as a ZIP.\n\n"
        "Invalid recipients and failed renders are recorded per recipient, so one bad "
        "row never stops the rest of the batch."
    ),
    lifespan=lifespan,
    debug=settings.debug,
)

app.include_router(health.router)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(certificates.router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send browsers straight to the interactive API documentation."""
    return RedirectResponse(url="/docs")
