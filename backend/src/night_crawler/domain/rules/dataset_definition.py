"""Validation of a Dataset's definition: its fields and item id."""

import re

from night_crawler.domain.model.constants import ITEM_ID_COLUMN, SCHEMA_FIELD_TYPES
from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.model.value_objects import DatasetField


def list_field_names(dataset: Dataset) -> list[str]:
    """Return the Dataset's field names, in CSV order."""
    return [field.name for field in dataset.fields]


def list_required_field_names(dataset: Dataset) -> list[str]:
    """Return the names of the fields every row must have."""
    return [field.name for field in dataset.fields if field.is_required]


def validate_dataset_definition(dataset: Dataset) -> list[str]:
    """Return every problem with `dataset`'s fields, in order.

    `item_id` must be a required, unique field: with the Crawler's
    Source it keys every record. Each field needs a name, a known type,
    and a pattern that compiles.

    Returns:
        Human-readable errors; empty when the definition is valid.
    """
    names = list_field_names(dataset)
    return [
        *_find_duplicate_names(names),
        *_check_item_id(dataset),
        *[error for field in dataset.fields for error in _check_field(field)],
    ]


def _find_duplicate_names(names: list[str]) -> list[str]:
    """Report field names listed more than once, once each."""
    return [
        f"Field '{name}' is listed more than once."
        for name in dict.fromkeys(names)
        if names.count(name) > 1
    ]


def _check_item_id(dataset: Dataset) -> list[str]:
    """Report an `item_id` that is missing, optional, or not unique."""
    item_ids = [field for field in dataset.fields if ITEM_ID_COLUMN == field.name]
    if not item_ids:
        return [f"Field '{ITEM_ID_COLUMN}' is missing."]
    return _check_item_id_rules(item_ids[0])


def _check_item_id_rules(item_id: DatasetField) -> list[str]:
    """Report each key rule `item_id` lacks: required, then unique."""
    rules = (("required", item_id.is_required), ("unique", item_id.is_unique))
    return [
        f"Field '{ITEM_ID_COLUMN}' must be {rule}."
        for rule, is_set in rules
        if not is_set
    ]


def _check_field(field: DatasetField) -> list[str]:
    """Report a blank name, an unknown type, or a broken pattern."""
    if not field.name.strip():
        return ["A field name can't be blank."]
    errors = []
    if field.type not in SCHEMA_FIELD_TYPES:
        errors.append(f"Field '{field.name}' has unknown type '{field.type}'.")
    if None is not field.pattern and not _is_valid_regex(field.pattern):
        errors.append(f"Field '{field.name}' has an invalid pattern.")
    return errors


def _is_valid_regex(pattern: str) -> bool:
    """Tell whether `pattern` compiles as a regex."""
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True
