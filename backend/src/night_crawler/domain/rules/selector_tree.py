"""Context key naming, and routing harvests to Context or dataset."""

import json
from typing import Any

from night_crawler.domain.model.value_objects import Harvest

ITERATOR_KEY_SUFFIX = "[]"


def resolve_context_key(title: str, has_iterator_ancestor: bool) -> str:
    """Return `title[]` under an iterator, else `title`."""
    return f"{title}{ITERATOR_KEY_SUFFIX}" if has_iterator_ancestor else title


def bare_field_name(key: str) -> str:
    """Return `key` without its `[]` iterator suffix."""
    return key.removesuffix(ITERATOR_KEY_SUFFIX)


def split_harvest_by_fields(
    harvested: dict[str, Any], fields: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a harvest into (Context items, dataset items).

    An entry whose bare name is one of the Crawler's fields feeds the
    dataset and never the Context (DOMAIN_MODEL §5.4).
    """
    context_items: dict[str, Any] = {}
    dataset_items: dict[str, Any] = {}
    for key, value in harvested.items():
        target = dataset_items if bare_field_name(key) in fields else context_items
        target[key] = value
    return context_items, dataset_items


def flatten_harvest(harvest: Harvest) -> dict[str, Any]:
    """Return a harvest as Context values.

    A title read inside an iterator or click becomes a `title[]` list
    with one entry per row; any other title is a scalar from the first
    row.
    """
    titles = dict.fromkeys(title for row in harvest.rows for title in row)
    return {
        resolve_context_key(title, title in harvest.array_titles): _title_value(
            harvest, title
        )
        for title in titles
    }


def _title_value(harvest: Harvest, title: str) -> Any:
    """Return a title's list across rows, or its first-row scalar."""
    if title in harvest.array_titles:
        return [row.get(title) for row in harvest.rows]
    return harvest.rows[0].get(title)


def merge_context_value(
    existing: Any, incoming: Any, is_iterator: bool, is_first_harvest: bool
) -> Any:
    """Combine a new harvest with the value already in the Context.

    A miss (`None`, or an empty list) never erases a value. The first
    harvest of a key in a run replaces what the run inherited from the
    previous one; later harvests extend lists, so a fan-out's harvests
    all end up in one list. A list holds each value once
    (`append_unique`).
    """
    if incoming in (None, []):
        return existing
    if not is_iterator:
        return incoming
    return append_unique([] if is_first_harvest else existing or [], incoming)


def append_unique(existing: list[Any], incoming: list[Any]) -> list[Any]:
    """Return `existing` with the `incoming` values it lacks appended.

    Values compare as the Context stores them (`to_primitive`), types
    included: `1`, `"1"`, and `True` stay apart. A repeat is skipped,
    so each value keeps its first position.
    """
    seen = {_stored_identity(value) for value in existing}
    merged = list(existing)
    for value in incoming:
        identity = _stored_identity(value)
        if identity not in seen:
            seen.add(identity)
            merged.append(value)
    return merged


def to_primitive(value: Any) -> Any:
    """Return `value` as a primitive; objects and lists become JSON."""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return value


def _stored_identity(value: Any) -> tuple[type, Any]:
    """Return what makes two values one entry once stored."""
    primitive = to_primitive(value)
    return type(primitive), primitive
