"""The port for keeping a copy of each execution's dataset CSV."""

from abc import ABC, abstractmethod


class AbstractDatasetExportStorage(ABC):
    """Stores exported dataset CSVs, one file per Crawler Execution.

    A CSV is written as raw first; only a run that succeeded and whose
    rows passed validation has it moved to validated.
    """

    @abstractmethod
    async def save(self, file_stem: str, csv_content: str) -> str:
        """Store an execution's CSV as raw and return where it went.

        A second save under the same name replaces the first.

        Args:
            file_stem: The file's name without `.csv`, from
                `export_file_stem`.
            csv_content: The full CSV text.

        Raises:
            ExternalServiceException: the CSV could not be stored.
        """

    @abstractmethod
    async def move_to_validated(self, file_stem: str) -> str:
        """Move an execution's raw CSV to validated; return where it is.

        Raises:
            ExternalServiceException: there is no raw CSV, or it could
                not be moved.
        """
