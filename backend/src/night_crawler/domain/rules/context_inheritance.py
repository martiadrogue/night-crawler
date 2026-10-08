"""Which Context keys a new run inherits from the previous one.

Values selectors harvest never carry over: every run starts without
them, so a selector that misses can't silently reuse the last run's
values (DOMAIN_MODEL §4.10). Seeded and user-set keys still carry over.
"""

from collections.abc import Iterable
from typing import Any

from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.rules.selector_tree import ITERATOR_KEY_SUFFIX


def harvested_keys(
    selectors: Iterable[MessageSelector], fields: Iterable[str]
) -> frozenset[str]:
    """Return the Context keys a version's selectors write.

    Both forms of each title, `name` and `name[]`, since nesting decides
    which one a selector writes. Titles of the Crawler's fields feed the
    dataset, never the Context, so they are left out.
    """
    field_names = set(fields)
    titles = {
        selector.title
        for selector in selectors
        if selector.title and selector.title not in field_names
    }
    return frozenset(
        key for title in titles for key in (title, f"{title}{ITERATOR_KEY_SUFFIX}")
    )


def drop_harvested(context: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    """Return the Context without the harvested `keys`."""
    return {key: value for key, value in context.items() if key not in keys}
