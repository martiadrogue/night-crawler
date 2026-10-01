"""Dataset CSV exports on the local filesystem."""

import asyncio
import os
from pathlib import Path

from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)

RAW_DIR = "raw"
VALIDATED_DIR = "validated"


class LocalDatasetExportStorage(AbstractDatasetExportStorage):
    """Writes `<base_dir>/raw/<file_stem>.csv`.

    A validated CSV moves to `<base_dir>/validated/` under the same
    name; both stages stay flat, one file per run and no subfolders.
    """

    def __init__(self, base_dir: str) -> None:
        """Export under `base_dir`, created on the first save."""
        self._base_dir = Path(base_dir)

    async def save(self, file_stem: str, csv_content: str) -> str:
        """Write the CSV under raw, off the event loop; return its path.

        Raises:
            ExternalServiceException: the file could not be written.
        """
        path = self._path(RAW_DIR, file_stem)
        try:
            await asyncio.to_thread(_write, path, csv_content)
        except OSError as error:
            raise ExternalServiceException(
                f"Could not export the dataset CSV to {path}: {error}"
            ) from error
        return str(path)

    async def move_to_validated(self, file_stem: str) -> str:
        """Move the raw CSV to validated; return its new path.

        Raises:
            ExternalServiceException: there is no raw CSV, or it could
                not be moved.
        """
        source = self._path(RAW_DIR, file_stem)
        target = self._path(VALIDATED_DIR, file_stem)
        try:
            await asyncio.to_thread(_move, source, target)
        except OSError as error:
            raise ExternalServiceException(
                f"Could not move the dataset CSV to {target}: {error}"
            ) from error
        return str(target)

    def _path(self, stage: str, file_stem: str) -> Path:
        """Return where a run's CSV lives at `stage`."""
        return self._base_dir / stage / f"{file_stem}.csv"


def _write(path: Path, csv_content: str) -> None:
    """Create the stage's folder if needed and write the file.

    `newline=""` keeps the CSV's own CRLF line endings as they are.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(csv_content)


def _move(source: Path, target: Path) -> None:
    """Move a file, creating the target's folder if needed."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
