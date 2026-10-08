import json

from night_crawler.domain.ports.browser_agent_recorder import (
    AgentFinalResult,
    AgentRecording,
    AgentRequest,
    AgentStep,
    FilteredRecording,
    KeptRequest,
)
from night_crawler.domain.rules.recording_filter import (
    filter_recording,
    summarize_filtered_recording,
)

SITE = "https://shows.example"
TRACKERS = ("google-analytics.com", "doubleclick.net")
SHOWS = [{"item_id": "show-101", "name": "Comedy night"}]


def _request(path, step=0, *, resource_type="xhr", status=200, body=None, **fields):
    url = path if path.startswith("http") else f"{SITE}{path}"
    return AgentRequest(
        step_index=step,
        url=url,
        method=fields.pop("method", "GET"),
        resource_type=resource_type,
        status=status,
        response_body=body,
        **fields,
    )


def _page(path="/", step=0, body="<html>shows</html>", **fields):
    return _request(path, step, resource_type="document", body=body, **fields)


def _step(index, action="navigate", target=None, is_success=True):
    return AgentStep(
        index=index,
        action=action,
        url=SITE,
        is_success=is_success,
        target_xpath=target,
        error=None if is_success else "Element not found",
    )


def _recording(*requests, steps=None, data=SHOWS, is_success=True):
    step_count = 1 + max((request.step_index for request in requests), default=0)
    return AgentRecording(
        steps=tuple(steps or (_step(i) for i in range(step_count))),
        requests=requests,
        final_result=AgentFinalResult(data=data, is_success=is_success),
    )


def _urls(filtered: FilteredRecording) -> list[str]:
    return [kept.request.url for kept in filtered.requests]


def _kept(filtered: FilteredRecording, url: str) -> KeptRequest:
    [kept] = [kept for kept in filtered.requests if url == kept.request.url]
    return kept


def _shows_json(**extra) -> str:
    return json.dumps({"shows": SHOWS, **extra})


# --- hard drops ---------------------------------------------------------------
def test_failures_assets_trackers_and_preflights_are_dropped():
    # Each later request carries the data too, so it would be the seed
    # (the latest carrier) if it were not dropped.
    filtered = filter_recording(
        _recording(
            _page("/search", body=f"<li>{SHOWS[0]['name']} show-101</li>"),
            _request("/api/shows", status=500, body=_shows_json()),
            _request("/api/shows?retry", failure="net::ERR_CONNECTION_RESET"),
            _request("/api/shows?aborted", status=None, body=_shows_json()),
            _request("/logo.png", resource_type="image", body=_shows_json()),
            _request("/app.js", resource_type="script", body=_shows_json()),
            _request(
                "https://www.google-analytics.com/collect?show=show-101",
                body=_shows_json(),
            ),
            _request("/api/shows", method="OPTIONS", body=_shows_json()),
            _request("/moved", resource_type="document", status=302),
        ),
        TRACKERS,
    )

    assert [f"{SITE}/search"] == _urls(filtered)
    assert ("carries final data",) == filtered.requests[0].reasons
    assert ("Comedy night", "show-101") == filtered.requests[0].values


def test_exact_duplicates_keep_the_last():
    filtered = filter_recording(
        _recording(
            _page(),
            _request("/api/shows", 0, body=_shows_json()),
            _request("/api/shows", 1, body=_shows_json()),
        ),
        TRACKERS,
    )

    assert [1] == [
        kept.request.step_index
        for kept in filtered.requests
        if "carries final data" in kept.reasons
    ]


# --- failed attempts ----------------------------------------------------------
def test_requests_of_a_failed_step_are_dropped():
    filtered = filter_recording(
        _recording(
            _page("/search", 0, body="<li>Comedy night</li><b>show-101</b>"),
            _request("/api/broken", 1, body=_shows_json()),
            steps=(_step(0), _step(1, "click", "html/body/a", is_success=False)),
        ),
        TRACKERS,
    )

    assert [f"{SITE}/search"] == _urls(filtered)


def test_a_retried_click_keeps_only_its_last_attempt():
    button = "html/body/main/button[2]"
    filtered = filter_recording(
        _recording(
            _page("/search", 0),
            _request("/api/more?try=1", 1, body='{"name": "Late laughs"}'),
            _request("/api/more?try=2", 2, body=_shows_json()),
            steps=(_step(0), _step(1, "click", button), _step(2, "click", button)),
            data=[*SHOWS, {"item_id": "show-202", "name": "Late laughs"}],
        ),
        TRACKERS,
    )

    assert f"{SITE}/api/more?try=1" not in _urls(filtered)
    assert f"{SITE}/api/more?try=2" in _urls(filtered)


# --- lineage ------------------------------------------------------------------
def test_lineage_keeps_the_token_request_feeding_the_data_request():
    filtered = filter_recording(
        _recording(
            _page("/search", 0, body="<html>search</html>"),
            _request("/api/unrelated", 0, body='{"weather": "sunny"}'),
            _request("/api/token", 1, method="POST", body='{"token": "tok-98765"}'),
            _request(
                "/api/shows?token=tok-98765",
                1,
                body=_shows_json(),
                request_headers={"Referer": f"{SITE}/search"},
            ),
        ),
        TRACKERS,
    )

    assert [
        f"{SITE}/search",
        f"{SITE}/api/token",
        f"{SITE}/api/shows?token=tok-98765",
    ] == _urls(filtered)
    token = _kept(filtered, f"{SITE}/api/token")
    assert (f"feeds {SITE}/api/shows?token=tok-98765",) == token.reasons
    assert ("tok-98765",) == token.values
    page = _kept(filtered, f"{SITE}/search")
    assert (f"loads the page for {SITE}/api/token",) == page.reasons


def test_lineage_follows_values_through_several_hops():
    filtered = filter_recording(
        _recording(
            _page("/", 0, body='<a href="/list?city=bcn-0042">Barcelona</a>'),
            _request("/list?city=bcn-0042", 1, body='{"cursor": "c-777-next"}'),
            _request(
                "/api/shows",
                2,
                method="POST",
                post_body='{"cursor": "c-777-next"}',
                body=_shows_json(),
            ),
        ),
        TRACKERS,
    )

    assert [f"{SITE}/", f"{SITE}/list?city=bcn-0042", f"{SITE}/api/shows"] == (
        _urls(filtered)
    )
    assert (f"feeds {SITE}/list?city=bcn-0042",) == _kept(filtered, f"{SITE}/").reasons


def test_lineage_keeps_the_document_that_set_a_cookie_the_data_request_sends():
    filtered = filter_recording(
        _recording(
            _page("/", 0, response_headers={"Set-Cookie": "sid=<redacted>"}),
            _page("/about", 0, response_headers={"Set-Cookie": "theme=<redacted>"}),
            _request(
                "/api/shows",
                1,
                body=_shows_json(),
                request_headers={"Cookie": "sid=<redacted>"},
            ),
        ),
        TRACKERS,
    )

    assert [f"{SITE}/", f"{SITE}/api/shows"] == _urls(filtered)
    assert ("sets cookie sid",) == _kept(filtered, f"{SITE}/").reasons
    assert ("sid",) == _kept(filtered, f"{SITE}/").values


def test_values_shorter_than_three_characters_never_link():
    filtered = filter_recording(
        _recording(
            _page("/", 0, body="<html>ok 42</html>"),
            _request("/api/count", 0, body='{"n": 42, "id": "7"}'),
            _request("/api/shows?id=7&n=42", 1, body=_shows_json()),
        ),
        TRACKERS,
    )

    assert f"{SITE}/api/count" not in _urls(filtered)
    assert [] == _urls(
        filter_recording(
            _recording(_page("/", body="<p>ok 42</p>"), data=[{"a": "ok", "b": 42}]),
            TRACKERS,
        )
    )


def test_json_escaped_and_url_encoded_values_match():
    name = 'Café "Le Bar"/Gràcia'
    escaped = json.dumps({"name": name})
    filtered = filter_recording(
        _recording(
            _page("/", 0, body='{"next": "page two/2"}'),
            _request("/api/shows?cursor=page%20two%2F2", 1, body=escaped),
            data=[{"name": name}],
        ),
        TRACKERS,
    )

    assert ("carries final data",) == _kept(
        filtered, f"{SITE}/api/shows?cursor=page%20two%2F2"
    ).reasons
    assert ("page two/2",) == _kept(filtered, f"{SITE}/").values

    linked = filter_recording(
        _recording(
            _page("/", body='<a href="/s?q=Late%20laughs">x</a>'), data=["Late laughs"]
        ),
        TRACKERS,
    )
    assert [f"{SITE}/"] == _urls(linked)


def test_numbers_match_as_text():
    filtered = filter_recording(
        _recording(
            _page("/", body="<td>Rating 4.75</td><td>1234</td>"),
            data=[{"rating": 4.75, "votes": 1234}],
        ),
        TRACKERS,
    )

    assert ("1234", "4.75") == filtered.requests[0].values


def test_an_empty_chain_is_reported_as_no_requests():
    filtered = filter_recording(
        _recording(_page("/", body="<html>nothing here</html>")), TRACKERS
    )

    assert () == filtered.requests
    assert SHOWS == filtered.final_result.data


# --- summary ------------------------------------------------------------------
def test_the_summary_keeps_url_method_status_and_reasons_capped():
    filtered = filter_recording(
        _recording(_page("/" + "x" * 3000, body="Comedy night show-101")), TRACKERS
    )

    [summary] = summarize_filtered_recording(filtered, max_entries=5, max_url_chars=40)
    assert (40, "GET", 200, ("carries final data",)) == (
        len(summary.url),
        summary.method,
        summary.status,
        summary.reasons,
    )
    assert () == summarize_filtered_recording(filtered, max_entries=0, max_url_chars=40)
