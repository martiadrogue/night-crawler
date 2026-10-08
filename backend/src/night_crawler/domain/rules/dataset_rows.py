"""Turning harvest rows into dataset CSV rows."""

import csv
import io
import json
from typing import Any

from night_crawler.domain.model.value_objects import Harvest
from night_crawler.domain.rules.dataset_validation import is_empty


def project_rows(harvest: Harvest, fields: list[str]) -> list[dict[str, Any]]:
    """Return one response's dataset rows, keeping only `fields`.

    Call it only for a template that feeds the dataset. Every harvest
    row with at least one of `fields` is one dataset row; a field not
    harvested is `None`. A row with none of them carries no data (a
    page with nothing to harvest, e.g. a show with no dates) and is
    left out. Rows are validated, and some dropped, once the run ends
    (DOMAIN_MODEL §5.4).
    """
    projected = [{field: row.get(field) for field in fields} for row in harvest.rows]
    return [row for row in projected if any(not is_empty(v) for v in row.values())]


def build_csv(fields: list[str], rows: list[dict[str, Any]]) -> str:
    """Return the CSV text: a header, then one line per row.

    `None` is an empty cell; objects and lists are JSON-encoded.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([_cell(row.get(field)) for field in fields])
    return buffer.getvalue()


def _cell(value: Any) -> str:
    """Return one CSV cell."""
    if None is value:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
