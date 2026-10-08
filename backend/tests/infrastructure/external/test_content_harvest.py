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


@pytest.mark.anyio
async def test_format_epoch_turns_unix_seconds_into_a_date():
    body = '{"events": [{"start": 1791484200, "label": "1791484200"}]}'
    harvested = await _harvest(
        [
            _selector("events", "events", "iterator"),
            _selector(
                "utc",
                "format_epoch(start, '%Y-%m-%d %H:%M:%S', 'UTC')",
                parent="events",
                title="utc",
            ),
            _selector(
                "madrid",
                "format_epoch(start, '%Y-%m-%d %H:%M:%S', 'Europe/Madrid')",
                parent="events",
                title="madrid",
            ),
            _selector(
                "text",
                "format_epoch(label, '%d/%m/%Y', 'UTC')",
                parent="events",
                title="text",
            ),
        ],
        body=body,
        content_type="application/json",
    )

    assert ["2026-10-08 18:30:00"] == harvested["utc[]"]
    assert ["2026-10-08 20:30:00"] == harvested["madrid[]"]
    assert ["08/10/2026"] == harvested["text[]"]


@pytest.mark.anyio
async def test_format_epoch_leaves_a_value_it_cannot_read_empty():
    body = '{"start": "soon", "missing": null, "when": 1791491400}'
    harvested = await _harvest(
        [
            _selector("a", "format_epoch(start, '%Y', 'UTC')", title="not_a_number"),
            _selector("b", "format_epoch(missing, '%Y', 'UTC')", title="null"),
            _selector("c", "format_epoch(when, '%Y', 'Mars/Olympus')", title="bad_tz"),
        ],
        body=body,
        content_type="application/json",
    )

    assert None is harvested.get("not_a_number")
    assert None is harvested.get("null")
    assert None is harvested.get("bad_tz")


@pytest.mark.anyio
async def test_json_ld_in_an_html_script_is_read_with_jmespath():
    page = """
<html><head>
<script type="application/ld+json">{"@type": "Product", "name": "Show"}</script>
<script type="application/ld+json">
[{"@type": "ComedyEvent", "startDate": "2026-10-08T19:30:00+02:00",
  "location": {"name": "Teatre Coliseum"}},
 {"@type": "ComedyEvent", "startDate": "2026-10-09T19:00:00+02:00",
  "location": {"name": "Teatre Coliseum"}}]
</script>
<script>var notJson = 1;</script>
</head><body><h1>Show</h1></body></html>
"""
    harvested = await _harvest(
        [
            _selector(
                "scripts",
                "//script[@type='application/ld+json'][contains(., 'ComedyEvent')]",
                "iterator",
            ),
            _selector(
                "events", "[?\"@type\" == 'ComedyEvent']", "iterator", parent="scripts"
            ),
            _selector("start", "startDate", parent="events", title="start"),
            _selector("venue", "location.name", parent="events", title="venue"),
        ],
        body=page,
    )

    assert [
        "2026-10-08T19:30:00+02:00",
        "2026-10-09T19:00:00+02:00",
    ] == harvested["start[]"]
    assert ["Teatre Coliseum", "Teatre Coliseum"] == harvested["venue[]"]


@pytest.mark.anyio
async def test_format_iso_turns_iso_text_into_a_date_in_a_timezone():
    body = (
        '{"offset": "2026-10-08T19:30:00+02:00", "utc": "2026-10-08T17:30:00Z",'
        ' "naive": "2026-10-08T19:30:00", "bad": "soon"}'
    )
    madrid = "'%Y-%m-%d %H:%M:%S', 'Europe/Madrid'"
    harvested = await _harvest(
        [
            _selector("a", f"format_iso(offset, {madrid})", title="offset"),
            _selector("b", f"format_iso(utc, {madrid})", title="utc"),
            _selector("c", f"format_iso(naive, {madrid})", title="naive"),
            _selector("d", f"format_iso(bad, {madrid})", title="bad"),
            _selector("e", f"format_iso(missing, {madrid})", title="missing"),
        ],
        body=body,
        content_type="application/json",
    )

    assert "2026-10-08 19:30:00" == harvested["offset"]
    assert "2026-10-08 19:30:00" == harvested["utc"]
    assert "2026-10-08 19:30:00" == harvested["naive"]
    assert None is harvested.get("bad")
    assert None is harvested.get("missing")


@pytest.mark.anyio
async def test_placeholder_reads_the_runs_value_inside_jmespath():
    harvested = await _harvest(
        [
            _selector("events", "events", "iterator"),
            _selector(
                "url",
                "join('', ['https://example.com', placeholder('show_path'), '#', at])",
                parent="events",
                title="source_url",
            ),
            _selector("none", "placeholder('missing')", title="missing"),
        ],
        body='{"events": [{"at": "2026-10-08"}, {"at": "2026-10-09"}]}',
        content_type="application/json",
        placeholders={"show_path": "/entradas/show_e1/"},
    )

    assert [
        "https://example.com/entradas/show_e1/#2026-10-08",
        "https://example.com/entradas/show_e1/#2026-10-09",
    ] == harvested["source_url[]"]
    assert None is harvested.get("missing")


@pytest.mark.anyio
async def test_an_xpath_string_result_is_harvested_as_plain_text():
    harvested = await _harvest(
        [
            _selector("venues", "div.venue", "iterator"),
            _selector("link", "(string(.//a/@href))", parent="venues", title="link"),
        ]
    )

    assert ["/v/1", "/v/2"] == harvested["link[]"]
    assert all(str is type(link) for link in harvested["link[]"])
