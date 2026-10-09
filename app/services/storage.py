"""Certificate file storage.

Access to generated files goes through this small interface rather than
scattering ``open()`` calls across the services. Swapping local disk for S3 or
Azure Blob means implementing ``Storage`` once and changing a single line in
``get_storage()`` — nothing else in the application knows where files live.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from app.config import get_settings


class Storage(ABC):
    """Where generated certificates are kept."""

    @abstractmethod
    def path_for(self, job_id: str, certificate_id: str) -> Path:
        """Absolute path of the PDF for one certificate."""

    @abstractmethod
    def prepare_job(self, job_id: str) -> Path:
        """Create (if needed) and return the directory for a job's files."""

    @abstractmethod
    def exists(self, path: str | Path) -> bool:
        """Whether a previously stored file is still present."""


class LocalFileStorage(Storage):
    """Stores PDFs on the local filesystem.

    Layout::

        <storage_dir>/<job_id>/<certificate_id>.pdf

    Files are namespaced by job so a job's output can be listed, zipped or
    deleted as a unit without touching other jobs.
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def prepare_job(self, job_id: str) -> Path:
        job_dir = self.base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def path_for(self, job_id: str, certificate_id: str) -> Path:
        return self.base_dir / job_id / f"{certificate_id}.pdf"

    def exists(self, path: str | Path) -> bool:
        return Path(path).is_file()

    def job_dir(self, job_id: str) -> Path:
        return self.base_dir / job_id


def get_storage() -> Storage:
    """Return the configured storage backend."""
    return LocalFileStorage(get_settings().storage_dir)
