"""Harvest one response with a selector tree.

What a selector reads depends on its `source` and the response:

- `content`, HTML: XPath or CSS (`domain/rules/selector_paths.py`).
- `content`, JSON: JMESPath.
- `headers`: a regex over each response header, written as one
  `name: value` line with the name lower-cased (so cookies are
  `set-cookie:` lines); a capture never runs into the next header.
- `url`: a regex over the final URL.
- `context`: the value of the placeholder named by the path in the
  template's run (e.g. the `place_id` a detail page fanned out over),
  for `value` and `boolean` selectors.

A regex's value is its first capture group, or the whole match without
one. Under a `headers`/`url` iterator, children apply their regex to the
iterated match. Shared by every engine; only browsers can act on a page.
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import jmespath
from lxml import etree
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.model.value_objects import Harvest
from night_crawler.domain.rules.selector_paths import is_xpath

_LEAF_TYPES = ("value", "boolean")
_ACTION_TYPES = ("click", "select")
_HTML, _JSON, _TEXT = "html", "json", "text"


@dataclass(frozen=True)
class ResponseSnapshot:
    """The parts of a response a selector can read."""

    body: str
    content_type: str
    headers: list[tuple[str, str]]
    url: str
    placeholders: dict[str, Any] = field(default_factory=dict)


class PageInteractor(ABC):
    """Acts on a live page; only the browser engines have one."""

    @abstractmethod
    async def count(self, path: str) -> int:
        """Return how many elements `path` matches right now."""

    @abstractmethod
    async def act(self, selector: MessageSelector, index: int) -> None:
        """Click, or select `selector.target` on, match `index`."""

    @abstractmethod
    async def snapshot(self) -> str:
        """Return the page's current HTML."""


@dataclass(frozen=True)
class _Scope:
    """A walk position: the node, how to read it, and the row so far."""

    node: Any
    kind: str
    row: dict[str, Any]
    is_in_loop: bool


@dataclass
class _HarvestWalk:
    """One harvest: the selector tree, the response, the bookkeeping."""

    children_by_parent: dict[str | None, list[MessageSelector]]
    root: Any
    root_kind: str
    header_lines: list[str]
    url: str
    placeholders: dict[str, Any]
    interactor: PageInteractor | None
    array_titles: set[str] = field(default_factory=set)

    async def harvest_level(
        self, scope: _Scope, selectors: list[MessageSelector]
    ) -> list[dict[str, Any]]:
        """Fold this level's leaves into a row, then loop.

        Leaves come first, so they read the page before any click.
        """
        rows = [self._fold_leaves(scope, selectors)]
        for selector in selectors:
            rows = await self._expand(scope, selector, rows)
        return rows

    def _fold_leaves(
        self, scope: _Scope, selectors: list[MessageSelector]
    ) -> dict[str, Any]:
        """Return the scope's row with every titled leaf folded in."""
        row = scope.row
        for selector in selectors:
            if selector.type in _LEAF_TYPES and selector.title:
                row = self._fold_leaf(scope, selector, row)
        return row

    def _fold_leaf(
        self, scope: _Scope, selector: MessageSelector, row: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge a leaf's value into `row`; a miss never overwrites."""
        value = self._leaf_value(scope, selector)
        if scope.is_in_loop:
            self.array_titles.add(selector.title)
        return row if None is value else {**row, selector.title: value}

    def _leaf_value(self, scope: _Scope, selector: MessageSelector) -> Any:
        """Return a bool for `boolean`, else the first match's value."""
        if "context" == selector.source:
            return _context_leaf_value(self.placeholders, selector)
        node, kind = self._target(scope, selector)
        if _JSON == kind:
            return _json_leaf_value(node, selector)
        matches = _read(node, kind, selector)
        if "boolean" == selector.type:
            return bool(matches)
        return matches[0] if matches else None

    def _target(self, scope: _Scope, selector: MessageSelector) -> tuple[Any, str]:
        """Return what `selector` reads, and how.

        Inside a `headers`/`url` iterator, the match; otherwise the
        headers or URL for those sources, else the scope's node.
        """
        if _TEXT == scope.kind:
            return scope.node, _TEXT
        if "headers" == selector.source:
            return self.header_lines, _TEXT
        if "url" == selector.source:
            return self.url, _TEXT
        return scope.node, scope.kind

    async def _expand(
        self, scope: _Scope, selector: MessageSelector, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Cross-join `rows` with an iterator's or action's own rows."""
        if "iterator" == selector.type:
            return await self._iterate(scope, selector, rows)
        if selector.type in _ACTION_TYPES:
            return await self._interact(scope, selector, rows)
        return rows

    async def _iterate(
        self, scope: _Scope, selector: MessageSelector, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Harvest the children once per match, scoped to that match."""
        node, kind = self._target(scope, selector)
        items = _items(node, kind, selector.path)
        children = self.children_by_parent.get(selector.id, [])
        result: list[dict[str, Any]] = []
        for row in rows or [{}]:
            for item in items:
                result += await self.harvest_level(
                    _Scope(item, kind, row, True), children
                )
        return result or rows

    async def _interact(
        self, scope: _Scope, selector: MessageSelector, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Act on each match, then harvest the children on the page.

        Without a live page (httpx), the children read the page once as
        fetched.
        """
        children = self.children_by_parent.get(selector.id, [])
        if None is self.interactor:
            return await self._harvest_rows(rows, children, None)
        result: list[dict[str, Any]] = []
        for index in range(await self.interactor.count(selector.path)):
            await self.interactor.act(selector, index)
            page = _parse_html(await self.interactor.snapshot())
            result += await self._harvest_rows(rows, children, page)
        return result or rows

    async def _harvest_rows(
        self,
        rows: list[dict[str, Any]],
        children: list[MessageSelector],
        page: Any,
    ) -> list[dict[str, Any]]:
        """Harvest `children` over a clicked page, once per row.

        `page` is `None` when nothing was clicked: the rows are kept as
        they are and the children read the root they already had. Either
        way the children sit under a click, so their titles are lists.
        """
        result: list[dict[str, Any]] = []
        for row in rows:
            scope = (
                _Scope(self.root, self.root_kind, row, True)
                if None is page
                else _Scope(page, _HTML, row, True)
            )
            result += await self.harvest_level(scope, children)
        return result


async def harvest_response(
    snapshot: ResponseSnapshot,
    selectors: list[MessageSelector],
    interactor: PageInteractor | None = None,
) -> Harvest:
    """Walk the selector tree over one response.

    Raises:
        ExternalServiceException: the body claims JSON but doesn't
            parse.
    """
    root, kind = _parse(snapshot.body, snapshot.content_type)
    children_by_parent: dict[str | None, list[MessageSelector]] = {}
    for selector in selectors:
        children_by_parent.setdefault(selector.parent_selector_id, []).append(selector)
    walk = _HarvestWalk(
        children_by_parent,
        root,
        kind,
        [f"{name.lower()}: {value}" for name, value in snapshot.headers],
        snapshot.url,
        snapshot.placeholders,
        interactor,
    )
    rows = await walk.harvest_level(
        _Scope(root, kind, {}, False), children_by_parent.get(None, [])
    )
    return Harvest(rows=rows, array_titles=frozenset(walk.array_titles))


def _parse(body: str, content_type: str) -> tuple[Any, str]:
    """Return the parsed body and how to read it.

    Raises:
        ExternalServiceException: the body claims JSON but doesn't
            parse.
    """
    if "json" not in content_type.lower():
        return _parse_html(body), _HTML
    try:
        return json.loads(body), _JSON
    except ValueError as exception:
        raise ExternalServiceException(
            f"Response claims JSON but did not parse: {exception}"
        ) from exception


def _parse_html(body: str) -> Any:
    """Return the lxml root of an HTML body, or `None` when empty."""
    return etree.HTML(body) if body.strip() else None


def _items(node: Any, kind: str, path: str) -> list[Any]:
    """Return what an iterator loops over, for each kind of node."""
    if _TEXT == kind:
        return _regex_matches(path, node)
    if _JSON == kind:
        return _json_items(node, path)
    return _html_nodes(node, path)


def _json_items(node: Any, path: str) -> list[Any]:
    """Return a JMESPath result as items: a list is split, else one."""
    result = None if None is node else jmespath.search(path, node)
    if None is result:
        return []
    return result if isinstance(result, list) else [result]


def _read(node: Any, kind: str, selector: MessageSelector) -> list[Any]:
    """Return a leaf's matches, read by its target (HTML) or regex."""
    if _TEXT == kind:
        return _regex_matches(selector.path, node)
    return [
        _read_html_node(match, selector.target)
        for match in _html_nodes(node, selector.path)
    ]


def _json_leaf_value(node: Any, selector: MessageSelector) -> Any:
    """Return the JMESPath result as is, lists and objects included."""
    result = None if None is node else jmespath.search(selector.path, node)
    if "boolean" == selector.type:
        return result not in (None, [], {}, "")
    return result


def _context_leaf_value(placeholders: dict[str, Any], selector: MessageSelector) -> Any:
    """Return the placeholder's value, or whether it has one."""
    value = placeholders.get(selector.path)
    if "boolean" == selector.type:
        return value not in (None, [], {}, "")
    return value


def _regex_matches(pattern: str, text: Any) -> list[str]:
    """Return each match's first capture group, or the whole match.

    Header lines are matched one by one, so a capture never runs into
    the next header. Matching is case-insensitive.
    """
    regex = re.compile(pattern, re.IGNORECASE)
    return [
        match.group(1) if regex.groups else match.group(0)
        for line in _as_lines(text)
        for match in regex.finditer(line)
    ]


def _as_lines(text: Any) -> list[str]:
    """Return a URL or item as one line, header lines as they are."""
    if isinstance(text, str):
        return [text]
    return text if isinstance(text, list) else []


def _html_nodes(node: Any, path: str) -> list[Any]:
    """Return XPath or CSS matches; a string result is one match."""
    if None is node:
        return []
    if not is_xpath(path):
        return node.cssselect(path)
    result = node.xpath(path)
    return result if isinstance(result, list) else [result]


def _read_html_node(node: Any, target: str) -> str:
    """Read a match: its text for `__text`, else the named attribute."""
    if isinstance(node, str):
        return node
    if "__text" == target:
        return "".join(node.itertext()).strip()
    return node.get(target) or ""
