import pytest
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.infrastructure.storage.local_dataset_export_storage import (
    LocalDatasetExportStorage,
)


@pytest.mark.anyio
async def test_a_csv_is_written_under_raw_first(tmp_path):
    storage = LocalDatasetExportStorage(str(tmp_path / "csv"))

    path = await storage.save("crawler-1_run-1_20261001T114123Z", "item_id\r\np1\r\n")

    assert str(tmp_path / "csv/raw/crawler-1_run-1_20261001T114123Z.csv") == path
    assert (
        b"item_id\r\np1\r\n"
        == (tmp_path / "csv/raw/crawler-1_run-1_20261001T114123Z.csv").read_bytes()
    )
    assert ["crawler-1_run-1_20261001T114123Z.csv"] == [
        entry.name for entry in (tmp_path / "csv/raw").iterdir()
    ]


@pytest.mark.anyio
async def test_a_validated_csv_moves_from_raw_to_validated(tmp_path):
    storage = LocalDatasetExportStorage(str(tmp_path / "csv"))
    await storage.save("crawler-1_run-1_20261001T114123Z", "item_id\r\np1\r\n")

    path = await storage.move_to_validated("crawler-1_run-1_20261001T114123Z")

    assert str(tmp_path / "csv/validated/crawler-1_run-1_20261001T114123Z.csv") == path
    assert (
        b"item_id\r\np1\r\n"
        == (
            tmp_path / "csv/validated/crawler-1_run-1_20261001T114123Z.csv"
        ).read_bytes()
    )
    assert [] == list((tmp_path / "csv/raw").iterdir())


@pytest.mark.anyio
async def test_moving_a_csv_never_written_is_an_external_error(tmp_path):
    storage = LocalDatasetExportStorage(str(tmp_path / "csv"))

    with pytest.raises(ExternalServiceException):
        await storage.move_to_validated("missing")


@pytest.mark.anyio
async def test_an_unwritable_directory_is_an_external_error(tmp_path):
    blocker = tmp_path / "csv"
    blocker.write_text("a file where the directory should be")
    storage = LocalDatasetExportStorage(str(blocker))

    with pytest.raises(ExternalServiceException):
        await storage.save("crawler-1_run-1_20261001T114123Z", "item_id\r\n")
