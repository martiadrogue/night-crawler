from night_crawler.domain.model.value_objects import SessionState
from night_crawler.domain.rules.host_session import (
    build_request_headers,
    merge_session,
    resolve_request_host,
    shareable_headers,
)


def test_hosts_are_exact_and_lower_case():
    assert "www.google.com" == resolve_request_host("https://WWW.Google.com/maps")
    assert None is resolve_request_host("not a url")


def test_merging_keeps_older_values_and_lets_newer_ones_win():
    existing = SessionState(cookies={"a": "1", "b": "1"}, headers={"user-agent": "UA1"})
    captured = SessionState(cookies={"b": "2"}, headers={"accept-language": "en"})

    merged = merge_session(existing, captured)

    assert {"a": "1", "b": "2"} == merged.cookies
    assert {"user-agent": "UA1", "accept-language": "en"} == merged.headers


def test_merging_into_nothing_returns_the_capture():
    captured = SessionState(cookies={"a": "1"}, headers={})

    assert captured == merge_session(None, captured)


def test_shared_headers_fill_gaps_and_template_headers_win():
    session = SessionState(
        cookies={"sid": "abc", "lang": "ca"},
        headers={"user-agent": "Chrome/140", "x-token": "shared"},
    )

    headers = build_request_headers({"X-Token": "own", "Cookie": "lang=en"}, session)

    assert "own" == headers["X-Token"]
    assert "Chrome/140" == headers["user-agent"]
    assert "x-token" not in headers
    assert "sid=abc; lang=en" == headers["Cookie"]


def test_without_a_session_the_template_headers_are_sent_as_is():
    assert {"Accept": "text/html"} == build_request_headers(
        {"Accept": "text/html"}, None
    )


def test_request_specific_headers_are_never_shared():
    assert {"user-agent": "UA", "accept-language": "en"} == shareable_headers(
        {
            "User-Agent": "UA",
            "Accept-Language": "en",
            "Host": "example.com",
            "Content-Length": "10",
            "Content-Type": "application/json",
            "Cookie": "a=1",
            ":authority": "example.com",
        }
    )
