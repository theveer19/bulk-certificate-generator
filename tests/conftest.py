"""Shared pytest fixtures.

The environment is configured *before* the application is imported, so the
tests get their own throwaway SQLite database and storage directory and can
never touch a developer's real data.
"""

import os
import shutil
import tempfile
from pathlib import Path

# --- configure the app before importing it -------------------------------- #
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="bulk-certificates-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_ROOT / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_TMP_ROOT / "certificates")
os.environ["ORGANIZATION_NAME"] = "Test Organisation"
os.environ["SIGNATORY_NAME"] = "Test Signatory"
os.environ["SIGNATORY_TITLE"] = "Programme Director"
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

API = get_settings().api_prefix


@pytest.fixture(scope="session")
def client():
    """A TestClient with the application lifespan running.

    Note: Starlette's TestClient executes background tasks before returning
    from the request, so a POST to /jobs comes back with generation already
    finished. That makes these tests deterministic without any sleeping or
    polling.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state():
    """Give every test an empty database and empty storage directory."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    storage_dir = get_settings().storage_dir
    if storage_dir.exists():
        shutil.rmtree(storage_dir, ignore_errors=True)
    storage_dir.mkdir(parents=True, exist_ok=True)

    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def make_payload(recipients, title="Advanced Python Workshop 2026", issue_date="2026-10-09"):
    """Build a job creation payload from a list of names or recipient dicts."""
    normalised = [
        {"name": r} if isinstance(r, str) else r for r in recipients
    ]
    return {"title": title, "issue_date": issue_date, "recipients": normalised}


def create_job(client, recipients, **kwargs):
    """POST a job and return the parsed response body."""
    response = client.post(f"{API}/jobs", json=make_payload(recipients, **kwargs))
    assert response.status_code == 202, response.text
    return response.json()
