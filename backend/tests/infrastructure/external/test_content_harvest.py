from datetime import datetime

import pytest
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.rules.selector_tree import flatten_harvest
from night_crawler.infrastructure.external.content_harvest import (
    ResponseSnapshot,
    harvest_response,
)

NOW = datetime(2026, 1, 1)
PAGE = """
<html><head><title>Venues</title></head><body>
  <div class="venue"><h2>Casa Pepe</h2><a href="/v/1">more</a></div>
  <div class="venue"><h2>Bar Nou</h2><a href="/v/2">more</a></div>
  <button id="consent">Accept all</button>
</body></html>
"""
HEADERS = [
    ("Content-Type", "text/html"),
    ("Set-Cookie", "session_id=abc123; Path=/"),
    ("Set-Cookie", "lang=ca; Path=/"),
    ("Set-Cookie", "theme=dark"),
    ("X-Next", "not-a-cookie"),
]


def _snapshot(
    body=PAGE,
    content_type="text/html",
    url="https://example.com/v?page=3",
    placeholders=None,
):
    return ResponseSnapshot(
        body=body,
        content_type=content_type,
        headers=HEADERS,
        url=url,
        placeholders=placeholders or {},
    )


def _selector(selector_id, path, selector_type="value", **overrides):
    return MessageSelector(
        id=selector_id,
        message_template_id="template-1",
        parent_selector_id=overrides.pop("parent", None),
        path=path,
        type=selector_type,
        target=overrides.pop("target", "__text"),
        created_at=NOW,
        updated_at=NOW,
        title=overrides.pop("title", None),
        source=overrides.pop("source", "content"),
    )


async def _harvest(selectors, **snapshot):
    return flatten_harvest(await harvest_response(_snapshot(**snapshot), selectors))


@pytest.mark.anyio
async def test_css_and_xpath_paths_read_the_same_page():
    harvested = await _harvest(
        [
            _selector("venue", "div.venue", "iterator"),
            _selector("name", "h2", parent="venue", title="name"),
            _selector("url", "./a", parent="venue", target="href", title="url"),
            _selector("title", "//title", title="page_title"),
            _selector("found", "#consent", "boolean", title="has_consent"),
        ]
    )

    assert ["Casa Pepe", "Bar Nou"] == harvested["name[]"]
    assert ["/v/1", "/v/2"] == harvested["url[]"]
    assert "Venues" == harvested["page_title"]
    assert True is harvested["has_consent"]


@pytest.mark.anyio
async def test_one_row_per_iterator_match():
    harvest = await harvest_response(
        _snapshot(),
        [
            _selector("venue", "div.venue", "iterator"),
            _selector("name", "h2", parent="venue", title="name"),
            _selector("title", "title", title="page_title"),
        ],
    )

    assert [
        {"page_title": "Venues", "name": "Casa Pepe"},
        {"page_title": "Venues", "name": "Bar Nou"},
    ] == harvest.rows
    assert frozenset({"name"}) == harvest.array_titles


@pytest.mark.anyio
async def test_headers_and_url_are_read_with_the_regex_capture_group():
    harvested = await _harvest(
        [
            _selector(
                "sid", r"^set-cookie: session_id=([^;]+)", source="headers", title="sid"
            ),
            _selector("page", r"page=(\d+)", source="url", title="page"),
            _selector("host", r"https://[^/]+", source="url", title="origin"),
        ]
    )

    assert "abc123" == harvested["sid"]
    assert "3" == harvested["page"]
    assert "https://example.com" == harvested["origin"]


@pytest.mark.anyio
async def test_a_context_selector_reads_the_runs_placeholder_value():
    harvest = await harvest_response(
        _snapshot(placeholders={"place_id": "p1", "empty": ""}),
        [
            _selector("venue", "div.venue", "iterator"),
            _selector("name", "h2", parent="venue", title="name"),
            _selector("id", "place_id", source="context", title="item_id"),
            _selector("has", "empty", "boolean", source="context", title="has_empty"),
            _selector("none", "missing", source="context", title="missing"),
        ],
    )

    assert [
        {"item_id": "p1", "has_empty": False, "name": "Casa Pepe"},
        {"item_id": "p1", "has_empty": False, "name": "Bar Nou"},
    ] == harvest.rows


@pytest.mark.anyio
async def test_a_headers_iterator_gives_its_children_each_match():
    harvested = await _harvest(
        [
            _selector("cookies", r"^set-cookie: ([^;]+)", "iterator", source="headers"),
            _selector("name", r"^([^=]+)=", parent="cookies", title="cookie_name"),
            _selector("value", r"=(.*)$", parent="cookies", title="cookie_value"),
        ]
    )

    assert ["session_id", "lang", "theme"] == harvested["cookie_name[]"]
    assert ["abc123", "ca", "dark"] == harvested["cookie_value[]"]


@pytest.mark.anyio
async def test_without_a_browser_a_click_reads_its_children_once_as_a_list():
    harvested = await _harvest(
        [
            _selector("consent", "#consent", "click"),
            _selector("label", "#consent", parent="consent", title="label"),
        ]
    )

    assert {"label[]": ["Accept all"]} == harvested


@pytest.mark.anyio
async def test_json_leaves_keep_their_native_values():
    body = (
        '{"places": [{"id": "p1", "types": ["bar", "cafe"]},'
        ' {"id": "p2", "types": ["restaurant"]}], "nextPageToken": "t"}'
    )
    harvested = await _harvest(
        [
            _selector("places", "places", "iterator"),
            _selector("id", "id", parent="places", title="place_id"),
            _selector("types", "types", parent="places", title="categories"),
            _selector("token", "nextPageToken", title="next_page_token"),
        ],
        body=body,
        content_type="application/json; charset=utf-8",
    )

    assert ["p1", "p2"] == harvested["place_id[]"]
    assert [["bar", "cafe"], ["restaurant"]] == harvested["categories[]"]
    assert "t" == harvested["next_page_token"]


@pytest.mark.anyio
async def test_a_body_claiming_json_must_parse():
    with pytest.raises(ExternalServiceException):
        await harvest_response(
            _snapshot(body="<html>", content_type="application/json"), []
        )
