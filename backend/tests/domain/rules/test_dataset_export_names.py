from datetime import datetime

from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.rules.dataset_export_names import export_file_stem


def _execution(started_at):
    return CrawlerExecution(
        id="run-1",
        crawler_id="crawler-1",
        crawler_version_id="version-1",
        status="running",
        parsing_status="pending",
        queue="discovery",
        started_at=started_at,
        finished_at=None,
        created_at=datetime(2026, 10, 1, 11, 40, 0),
        updated_at=datetime(2026, 10, 1, 11, 40, 0),
    )


def test_the_name_ends_with_when_the_run_started():
    stem = export_file_stem(_execution(datetime(2026, 10, 1, 11, 41, 23, 456)))

    assert "crawler-1_run-1_20261001T114123Z" == stem


def test_a_run_that_never_started_uses_when_it_was_created():
    assert "crawler-1_run-1_20261001T114000Z" == export_file_stem(_execution(None))
