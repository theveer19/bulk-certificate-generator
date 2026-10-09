"""Database engine, session factory and declarative base.

The project uses synchronous SQLAlchemy 2.0. Synchronous sessions were chosen
deliberately: certificate rendering is CPU/IO bound work that runs in a worker
thread, and a synchronous session is far simpler to reason about there than an
async one. FastAPI runs ``def`` endpoints in a threadpool, so this does not
block the event loop.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")

# ``check_same_thread=False`` is required because the background worker runs in
# a different thread from the request that created the job.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    # Keep attributes readable after commit so services can return ORM objects
    # straight to the serialisation layer.
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables.

    The assignment scope is a single service with a two-table schema, so the
    schema is created from the model metadata at start-up. A production
    deployment would replace this with Alembic migrations — see the
    "Design decisions" section of the README.
    """
    from app import models  # noqa: F401  — registers models on Base.metadata

    Base.metadata.create_all(bind=engine)
