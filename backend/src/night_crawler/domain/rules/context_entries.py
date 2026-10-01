"""The Context as stored: primitive entries, one per list element.

In memory a run's Context maps each key to a value, or to a list for a
`name[]` key. Stored, a key without `[]` is one entry, and a `name[]`
key is one entry per element with its `position`.
"""

import json
from typing import Any

from night_crawler.domain.rules.selector_tree import ITERATOR_KEY_SUFFIX

Entry = tuple[str, int | None, Any]
"""(key, position or `None` for a scalar key, primitive value)."""


def to_primitive(value: Any) -> Any:
    """Return `value` as a primitive; objects and lists become JSON."""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return value


def context_to_entries(context: dict[str, Any]) -> list[Entry]:
    """Return the entries to store for a Context."""
    entries: list[Entry] = []
    for key, value in context.items():
        if key.endswith(ITERATOR_KEY_SUFFIX):
            entries.extend(
                (key, position, to_primitive(item))
                for position, item in enumerate(value)
            )
        else:
            entries.append((key, None, to_primitive(value)))
    return entries


def entries_to_context(entries: list[Entry]) -> dict[str, Any]:
    """Rebuild a Context from its entries, lists in position order."""
    context: dict[str, Any] = {}
    for key, position, value in sorted(entries, key=_by_key_and_position):
        if None is position:
            context[key] = value
        else:
            context.setdefault(key, []).append(value)
    return context


def _by_key_and_position(entry: Entry) -> tuple[str, int]:
    """Sort key: scalars before list elements, elements by position."""
    key, position, _value = entry
    return key, -1 if None is position else position
