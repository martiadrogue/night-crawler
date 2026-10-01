"""When a template runs again: the placeholders it fills itself.

A template whose placeholder is the title of one of its own selectors
feeds itself. A single value (e.g. a page token) makes each fan-out
combination repeat while the value keeps changing; a list (e.g. links
under an iterator) makes the template run again for every element it
appends, once each (DOMAIN_MODEL §5.8).
"""

from dataclasses import dataclass
from typing import Any

from night_crawler.domain.model.entities import MessageSelector, MessageTemplate
from night_crawler.domain.rules.placeholders import extract_placeholders
from night_crawler.domain.rules.selector_tree import ITERATOR_KEY_SUFFIX
from night_crawler.domain.rules.template_ordering import template_texts

LOOP_SELECTOR_TYPES = ("iterator", "click", "select")
"""Selectors whose children harvest one value per match: lists."""


@dataclass(frozen=True)
class SelfFedPlaceholders:
    """A template's placeholders that its own selectors fill.

    Attributes:
        scalars: Filled by a selector outside any loop: one value per
            response, e.g. `next_page_token`.
        lists: Filled under an iterator or click: a `name[]` list the
            template fans out over and keeps extending.
    """

    scalars: frozenset[str] = frozenset()
    lists: frozenset[str] = frozenset()


def find_self_fed_placeholders(
    template: MessageTemplate, selectors: list[MessageSelector]
) -> SelfFedPlaceholders:
    """Return the template's placeholders its `selectors` harvest."""
    placeholders = extract_placeholders(template_texts(template))
    by_id = {selector.id: selector for selector in selectors}
    scalars, lists = set(), set()
    for selector in selectors:
        if selector.title in placeholders:
            is_list = _is_in_loop(selector, by_id)
            (lists if is_list else scalars).add(selector.title)
    return SelfFedPlaceholders(scalars=frozenset(scalars), lists=frozenset(lists))


def next_scalar_values(
    harvested: dict[str, Any], used: dict[str, set[Any]]
) -> dict[str, Any]:
    """Return the new values to repeat with; empty means stop.

    A value counts only when it was harvested, isn't empty, and hasn't
    been sent yet in this combination, so a token coming back unchanged
    (or alternating) ends the repeat.
    """
    return {
        name: value
        for name, value in harvested.items()
        if value not in (None, "") and value not in used.get(name, set())
    }


def unrun_list_elements(
    context: dict[str, Any], lists: frozenset[str], done: dict[str, list[Any]]
) -> dict[str, list[Any]]:
    """Return each self-fed list's elements that haven't run yet.

    Elements are compared by value, so one harvested twice runs once.
    """
    unrun = {
        name: _fresh_elements(
            context.get(f"{name}{ITERATOR_KEY_SUFFIX}", []), done.get(name, [])
        )
        for name in sorted(lists)
    }
    return {name: elements for name, elements in unrun.items() if elements}


def _fresh_elements(elements: list[Any], done: list[Any]) -> list[Any]:
    """Return `elements` not in `done`, each once, in order."""
    fresh: list[Any] = []
    for element in elements:
        if element not in done and element not in fresh:
            fresh.append(element)
    return fresh


def _is_in_loop(selector: MessageSelector, by_id: dict[str, MessageSelector]) -> bool:
    """Tell whether an ancestor iterates or acts on each match."""
    parent = by_id.get(selector.parent_selector_id or "")
    while None is not parent:
        if parent.type in LOOP_SELECTOR_TYPES:
            return True
        parent = by_id.get(parent.parent_selector_id or "")
    return False
