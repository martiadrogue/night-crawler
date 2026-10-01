"""How a run's exported dataset CSV is named."""

from night_crawler.domain.model.entities import CrawlerExecution

STARTED_AT_FORMAT = "%Y%m%dT%H%M%SZ"
"""Compact UTC timestamp: sortable, readable, safe in any file name."""


def export_file_stem(execution: CrawlerExecution) -> str:
    """Return the CSV's file name, without `.csv`.

    `<crawler_id>_<execution_id>_<started>`, e.g. `…_20261001T114123Z`:
    when the run started, or was created if it never started.
    """
    started = execution.started_at or execution.created_at
    return f"{execution.crawler_id}_{execution.id}_{started:{STARTED_AT_FORMAT}}"
