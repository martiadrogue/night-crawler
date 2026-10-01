"""Turning harvest rows into dataset CSV rows."""

import csv
import io
import json
from typing import Any

from night_crawler.domain.model.value_objects import Harvest


def project_rows(harvest: Harvest, fields: list[str]) -> list[dict[str, Any]]:
    """Return one response's dataset rows, keeping only `fields`.

    Call it only for a template that feeds the dataset. Every harvest
    row is one dataset row; a field not harvested is `None`. Rows are
    validated, and some dropped, once the run ends (DOMAIN_MODEL §5.4).
    """
    return [{field: row.get(field) for field in fields} for row in harvest.rows]


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
