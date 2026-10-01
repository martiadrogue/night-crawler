"""Validation of a Crawler's fields against its target dataset.

A Crawler lists which of the Dataset's fields an execution downloads,
in CSV order. Types, patterns, and which fields are required or unique
belong to the Dataset (DOMAIN_MODEL DM-17).
"""

from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.rules.dataset_definition import (
    list_field_names,
    list_required_field_names,
)


def validate_crawler_fields(dataset: Dataset, fields: list[str]) -> list[str]:
    """Return every problem with `fields` for `dataset`, in order.

    Each must be one of the Dataset's fields, listed once, and every
    field the Dataset requires must be there.

    Returns:
        Human-readable errors; empty when the fields are valid.
    """
    return [
        *_find_unknown_fields(dataset, fields),
        *_find_duplicate_fields(fields),
        *_find_missing_fields(dataset, fields),
    ]


def _find_unknown_fields(dataset: Dataset, fields: list[str]) -> list[str]:
    """Report fields the dataset doesn't define."""
    known = list_field_names(dataset)
    return [
        f"Field '{name}' is not a '{dataset.name}' field."
        for name in fields
        if name not in known
    ]


def _find_duplicate_fields(fields: list[str]) -> list[str]:
    """Report fields listed more than once, once each."""
    return [
        f"Field '{name}' is listed more than once."
        for name in dict.fromkeys(fields)
        if fields.count(name) > 1
    ]


def _find_missing_fields(dataset: Dataset, fields: list[str]) -> list[str]:
    """Report required fields the Crawler leaves out."""
    return [
        f"Required field '{name}' is missing."
        for name in list_required_field_names(dataset)
        if name not in fields
    ]
