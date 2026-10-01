"""Context key naming, and routing harvests to Context or dataset."""

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
    all end up in one list.
    """
    if incoming in (None, []):
        return existing
    if is_first_harvest or not is_iterator:
        return incoming
    return (existing or []) + incoming
