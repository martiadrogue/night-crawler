"""Validation of a run's dataset rows against its Dataset's fields.

Row checks: a required field is empty (the row is dropped), a unique
field repeats an earlier row's value (the later row is dropped), and a
value isn't of its field's type or doesn't match its pattern (kept, but
the dataset is invalid). Dataset check: none of the Crawler's fields
may be empty in every row (DOMAIN_MODEL §5.4).
"""

import json
import re
from collections import Counter
from dataclasses import replace
from typing import Any

from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.model.value_objects import DatasetField, DatasetValidation

EMPTY_VALUES: tuple[Any, ...] = (None, "", [], {})
"""Values that count as missing."""

_INTEGER_TEXT = re.compile(r"^-?\d+$")
_FLOAT_TEXT = re.compile(r"^-?\d+(\.\d+)?$")
_BOOLEAN_TEXT = ("true", "false")


def validate_dataset_rows(
    rows: list[dict[str, Any]], fields: list[str], dataset: Dataset
) -> tuple[list[dict[str, Any]], DatasetValidation]:
    """Return the rows to keep, and what validating them found.

    Args:
        rows: The run's rows, one dict per CSV row.
        fields: The Crawler's fields: the CSV columns.
        dataset: The Dataset whose field rules apply.
    """
    rules = _rules_for(dataset, fields)
    complete = [row for row in rows if _has_required(row, rules)]
    kept = _drop_duplicates(complete, rules)
    report = DatasetValidation(
        rows_checked=len(rows),
        rows_dropped_missing_required=len(rows) - len(complete),
        rows_dropped_duplicate=len(complete) - len(kept),
        type_mismatches=_count_mismatches(kept, rules, _is_of_type),
        pattern_mismatches=_count_mismatches(kept, rules, _matches_pattern),
        empty_columns=_empty_columns(kept, fields),
    )
    return kept, _with_verdict(report)


def is_empty(value: Any) -> bool:
    """Tell whether a value counts as missing."""
    return any(value == empty and type(value) is type(empty) for empty in EMPTY_VALUES)


def _rules_for(dataset: Dataset, fields: list[str]) -> dict[str, DatasetField]:
    """Return the Dataset's rules for the Crawler's fields, by name."""
    return {field.name: field for field in dataset.fields if field.name in fields}


def _has_required(row: dict[str, Any], rules: dict[str, DatasetField]) -> bool:
    """Tell whether every required field of the row has a value."""
    return not any(
        rule.is_required and is_empty(row.get(name)) for name, rule in rules.items()
    )


def _drop_duplicates(
    rows: list[dict[str, Any]], rules: dict[str, DatasetField]
) -> list[dict[str, Any]]:
    """Return the rows without later repeats of a unique value."""
    seen = _unique_fields(rules)
    kept = []
    for row in rows:
        if not _repeats_a_unique_value(row, seen):
            _remember_unique_values(row, seen)
            kept.append(row)
    return kept


def _unique_fields(rules: dict[str, DatasetField]) -> dict[str, set[str]]:
    """Return an empty set of seen values per unique field."""
    return {name: set() for name, rule in rules.items() if rule.is_unique}


def _repeats_a_unique_value(row: dict[str, Any], seen: dict[str, set[str]]) -> bool:
    """Tell whether a unique field of the row repeats a seen value."""
    return any(
        not is_empty(row.get(name)) and _as_text(row.get(name)) in values
        for name, values in seen.items()
    )


def _remember_unique_values(row: dict[str, Any], seen: dict[str, set[str]]) -> None:
    """Record the row's unique values, so a later repeat is dropped."""
    for name, values in seen.items():
        if not is_empty(row.get(name)):
            values.add(_as_text(row.get(name)))


def _count_mismatches(
    rows: list[dict[str, Any]], rules: dict[str, DatasetField], is_valid
) -> dict[str, int]:
    """Count, per field, the non-empty values `is_valid` rejects."""
    counts = Counter(
        name
        for row in rows
        for name, rule in rules.items()
        if not is_empty(row.get(name)) and not is_valid(row.get(name), rule)
    )
    return dict(counts)


def _is_integer(value: Any) -> bool:
    """Tell whether a value is a whole number, or text reading so."""
    return isinstance(value, int) or _is_text_like(value, _INTEGER_TEXT)


def _is_float(value: Any) -> bool:
    """Tell whether a value is a number, or text reading as one."""
    return isinstance(value, int | float) or _is_text_like(value, _FLOAT_TEXT)


def _is_boolean_text(value: Any) -> bool:
    """Tell whether a value is the text `true` or `false`, any case."""
    return isinstance(value, str) and value.lower() in _BOOLEAN_TEXT


def _accepts_anything(value: Any) -> bool:
    """Tell that a `string` field takes any value, objects included."""
    return True


_TYPE_CHECKS = {
    "integer": _is_integer,
    "float": _is_float,
    "boolean": _is_boolean_text,
}
"""How a non-boolean value is checked, per field type."""


def _is_of_type(value: Any, rule: DatasetField) -> bool:
    """Tell whether a value is of the field's type.

    Text from an HTML page counts when it reads as that type (`"9.8"`
    for a float). A real boolean only fits a `boolean` or `string`
    field, even though Python counts it as an integer.
    """
    if isinstance(value, bool):
        return rule.type in ("boolean", "string")
    return _TYPE_CHECKS.get(rule.type, _accepts_anything)(value)


def _is_text_like(value: Any, pattern: re.Pattern[str]) -> bool:
    """Tell whether a value is text matching `pattern`."""
    return isinstance(value, str) and bool(pattern.match(value.strip()))


def _matches_pattern(value: Any, rule: DatasetField) -> bool:
    """Tell whether the field has no pattern or the value matches it."""
    return None is rule.pattern or bool(re.search(rule.pattern, _as_text(value)))


def _as_text(value: Any) -> str:
    """Return a value as text: objects and lists as JSON."""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if None is value else str(value)


def _empty_columns(rows: list[dict[str, Any]], fields: list[str]) -> tuple[str, ...]:
    """Return the fields with no value in any row, in order."""
    return tuple(
        name for name in fields if all(is_empty(row.get(name)) for row in rows)
    )


def _with_verdict(report: DatasetValidation) -> DatasetValidation:
    """Return the report with `is_valid` set from its findings."""
    is_valid = not (
        report.rows_dropped_missing_required
        or report.type_mismatches
        or report.pattern_mismatches
        or report.empty_columns
    )
    return replace(report, is_valid=is_valid)
