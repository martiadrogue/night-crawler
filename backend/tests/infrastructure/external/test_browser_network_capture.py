import json
from pathlib import Path

import pytest
from night_crawler.infrastructure.external.browser_network_capture import (
    BrowserNetworkCapture,
)

FIXTURE = Path(__file__).parent / "fixtures" / "browser_use" / "cdp_events.json"

STEP_START_TIMES = [100.0, 101.0, 102.0]


async def _replay(response_body_max_bytes: int = 1024):
    """Feed the recorded CDP events to a capture; return it and fetches."""
    recorded = json.loads(FIXTURE.read_text())
    fetched: list[tuple[str, str | None]] = []

    async def fetch_body(request_id: str, session_id: str | None) -> dict:
        fetched.append((request_id, session_id))
        return recorded["bodies"][request_id]

    capture = BrowserNetworkCapture(fetch_body, response_body_max_bytes)
    handlers = {
        "Network.requestWillBeSent": capture.on_request_will_be_sent,
        "Network.responseReceived": capture.on_response_received,
        "Network.loadingFinished": capture.on_loading_finished,
        "Network.loadingFailed": capture.on_loading_failed,
    }
    for event in recorded["events"]:
        handlers[event["method"]](event["params"], event["session_id"])
    await capture.wait_for_bodies(1)
    return capture, fetched


@pytest.mark.anyio
async def test_each_request_is_tied_to_the_step_it_was_made_in():
    capture, _fetched = await _replay()

    requests = capture.get_requests(STEP_START_TIMES)

    assert [
        ("http://shows.example/start", 0),
        ("https://shows.example/search", 0),
        ("https://shows.example/api/list", 1),
        ("https://shows.example/logo.png", 1),
        ("https://tracker.example/t", 2),
        ("https://shows.example/app.js", 2),
    ] == [(request.url, request.step_index) for request in requests]
    assert ["document", "document", "xhr", "image", "fetch", "script"] == [
        request.resource_type for request in requests
    ]


@pytest.mark.anyio
async def test_requests_before_the_first_step_belong_to_it():
    capture, _fetched = await _replay()

    requests = capture.get_requests([500.0])

    assert {0} == {request.step_index for request in requests}


@pytest.mark.anyio
async def test_a_redirect_hop_is_its_own_request():
    capture, _fetched = await _replay()

    hop, landed, *_rest = capture.get_requests(STEP_START_TIMES)

    assert 301 == hop.status
    assert {"Location": "https://shows.example/search"} == hop.response_headers
    assert None is hop.response_body
    assert 200 == landed.status


@pytest.mark.anyio
async def test_failed_requests_have_no_status_and_say_why():
    capture, _fetched = await _replay()

    *_rest, unresolved, aborted = capture.get_requests(STEP_START_TIMES)

    assert (None, "net::ERR_NAME_NOT_RESOLVED") == (
        unresolved.status,
        unresolved.failure,
    )
    assert (None, "aborted") == (aborted.status, aborted.failure)


@pytest.mark.anyio
async def test_bodies_are_kept_for_documents_and_api_calls_only():
    capture, fetched = await _replay()

    _hop, document, api, image, *_rest = capture.get_requests(STEP_START_TIMES)

    assert [("r1", "S1"), ("r2", "S1")] == fetched
    assert document.response_body.startswith("<html><body><ul>")
    assert '{"shows": [{"id": "1", "name": "Comedy night"}]}' == api.response_body
    assert '{"page": 1}' == api.post_body
    assert "POST" == api.method
    assert None is image.response_body


@pytest.mark.anyio
async def test_bodies_are_cut_at_the_set_size():
    capture, _fetched = await _replay(response_body_max_bytes=20)

    _hop, document, api, *_rest = capture.get_requests(STEP_START_TIMES)

    assert "<html><body><ul><li " == document.response_body
    assert document.is_response_body_truncated
    assert 20 == len(api.response_body.encode())
    assert api.is_response_body_truncated


@pytest.mark.anyio
async def test_cookies_and_authorization_are_redacted_by_name():
    capture, _fetched = await _replay()

    hop, document, api, *_rest = capture.get_requests(STEP_START_TIMES)

    # Cookie names stay, so lineage can tell who set what; values never.
    assert {"User-Agent": "Chrome/140", "Cookie": "sid=<redacted>"} == (
        hop.request_headers
    )
    assert "sid=<redacted>" == document.response_headers["Set-Cookie"]
    assert "text/html" == document.response_headers["Content-Type"]
    assert "<redacted>" == api.request_headers["Authorization"]
    assert "<redacted>" == api.request_headers["X-Api-Key"]
    assert "secret-token" not in json.dumps(
        [request.request_headers for request in capture.get_requests([])]
    )
