"""Which recorded requests led to the data a browser agent extracted.

A recording holds everything the agent's browser did: assets,
trackers, failed tries, and the few requests that produced the data.
Instructions are written from those few only (DOMAIN_MODEL §4.16):

1. Noise is dropped: failures, preflights, empty redirects, assets,
   ignored (analytics/ads) hosts, and exact duplicates (the last kept).
2. Failed attempts are dropped: the requests of a failed step, and of
   every repetition of an action on one target but the last.
3. Lineage runs backwards from the final data. The latest page or API
   response carrying each extracted value is kept; then, until nothing
   changes, the latest earlier response holding a value a kept request
   uses (a token, an id, a cursor, a link), or setting a cookie it
   sends. A chain that starts on an API call gets the page it ran on.

Values match as text of 3 characters or more, raw, JSON-escaped,
URL-encoded, or HTML-escaped, so short values never link by chance.
"""

import html
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus, unquote, urlsplit

from night_crawler.domain.ports.browser_agent_recorder import (
    REDACTED_VALUE,
    AgentRecording,
    AgentRequest,
    AgentStep,
    FilteredRecording,
    FilteredRequestSummary,
    KeptRequest,
)

MIN_VALUE_LENGTH = 3
"""Shorter values (`7`, `ok`) appear everywhere and prove nothing."""

DATA_RESOURCE_TYPES = frozenset({"document", "xhr", "fetch"})
"""Responses that can carry the extracted data: pages and API calls."""

PAGE_RESOURCE_TYPE = "document"

NOISE_RESOURCE_TYPES = frozenset(
    {"image", "font", "stylesheet", "script", "media", "websocket", "manifest", "ping"}
)

STANDARD_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "accept-language",
        "cache-control",
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "dnt",
        "host",
        "origin",
        "pragma",
        "priority",
        "referer",
        "upgrade-insecure-requests",
        "user-agent",
    }
)
"""Headers every browser sends; their values never carry lineage."""

LONG_PATH_SEGMENT = 16
"""A path segment this long is an id or token even without a digit."""

CARRIES_FINAL_DATA = "carries final data"


@dataclass
class _Kept:
    """Why one request is kept, as lineage grows."""

    reasons: list[str] = field(default_factory=list)
    values: set[str] = field(default_factory=set)

    def add(self, reason: str, value: str) -> None:
        """Add a reason (once) and the value behind it."""
        if reason not in self.reasons:
            self.reasons.append(reason)
        self.values.add(value)


def filter_recording(
    recording: AgentRecording, ignored_hosts: Iterable[str]
) -> FilteredRecording:
    """Return the requests that led to the recording's final data.

    Args:
        recording: What the browser agent did.
        ignored_hosts: Analytics and ads hosts; their subdomains are
            ignored too.

    Returns:
        The chain in time order, each request with why it was kept;
        empty when no response carries the final data.
    """
    candidates = _drop_failed_attempts(
        recording.steps, _drop_noise(recording.requests, tuple(ignored_hosts))
    )
    kept = _seed(candidates, _final_values(recording.final_result.data))
    if kept:
        _grow(candidates, kept)
        _add_page(candidates, kept)
    return FilteredRecording(
        requests=tuple(
            KeptRequest(
                request=candidates[position],
                reasons=tuple(kept[position].reasons),
                values=tuple(sorted(kept[position].values)),
            )
            for position in sorted(kept)
        ),
        final_result=recording.final_result,
    )


def summarize_filtered_recording(
    filtered: FilteredRecording, max_entries: int, max_url_chars: int
) -> tuple[FilteredRequestSummary, ...]:
    """Return what is stored of the chain: URLs, statuses, reasons."""
    return tuple(
        FilteredRequestSummary(
            url=kept.request.url[:max_url_chars],
            method=kept.request.method,
            status=kept.request.status,
            reasons=kept.reasons,
        )
        for kept in filtered.requests[:max_entries]
    )


def _drop_noise(
    requests: Iterable[AgentRequest], ignored_hosts: tuple[str, ...]
) -> dict[int, AgentRequest]:
    """Return the requests worth tracing, by recorded position.

    Of exact duplicates (method, URL, body), the last one stays.
    """
    survivors = {
        position: request
        for position, request in enumerate(requests)
        if not _is_noise(request, ignored_hosts)
    }
    seen: set[tuple[str, str, str | None]] = set()
    for position in sorted(survivors, reverse=True):
        request = survivors[position]
        identity = (request.method, request.url, request.post_body)
        if identity in seen:
            del survivors[position]
        seen.add(identity)
    return survivors


def _is_noise(request: AgentRequest, ignored_hosts: tuple[str, ...]) -> bool:
    """Tell whether a request could not have led to the data."""
    return (
        _has_failed(request)
        or "OPTIONS" == request.method.upper()
        or request.resource_type in NOISE_RESOURCE_TYPES
        or _is_ignored_host(request.url, ignored_hosts)
    )


def _has_failed(request: AgentRequest) -> bool:
    """Tell whether a request failed, or redirected with no body."""
    status = request.status
    if None is status or None is not request.failure:
        return True
    if 400 <= status:
        return True
    return 300 <= status and not request.response_body


def _is_ignored_host(url: str, ignored_hosts: tuple[str, ...]) -> bool:
    """Tell whether `url`'s host is an ignored one or under one."""
    host = (urlsplit(url).hostname or "").lower()
    return any(
        host == ignored or host.endswith(f".{ignored}") for ignored in ignored_hosts
    )


def _drop_failed_attempts(
    steps: Iterable[AgentStep], candidates: dict[int, AgentRequest]
) -> dict[int, AgentRequest]:
    """Drop requests of failed steps and of superseded repetitions.

    A step repeating the step before it (same action on the same
    target) supersedes it: only the last attempt is the one that
    worked.
    """
    dropped_steps = _dropped_steps(list(steps))
    return {
        position: request
        for position, request in candidates.items()
        if request.step_index not in dropped_steps
    }


def _dropped_steps(steps: list[AgentStep]) -> set[int]:
    """Return the failed steps, and repetitions a later step redid."""
    failed = {step.index for step in steps if not step.is_success}
    superseded = {
        previous.index for previous, step in pairwise(steps) if _repeats(previous, step)
    }
    return failed | superseded


def _repeats(previous: AgentStep, step: AgentStep) -> bool:
    """Tell whether `step` redoes `previous`'s action on its target."""
    return (
        None is not step.target_xpath
        and step.target_xpath == previous.target_xpath
        and step.action == previous.action
    )


def _seed(candidates: dict[int, AgentRequest], values: set[str]) -> dict[int, _Kept]:
    """Keep, per final value, the latest page or API call with it."""
    kept: dict[int, _Kept] = {}
    carriers = {
        position: request
        for position, request in candidates.items()
        if request.resource_type in DATA_RESOURCE_TYPES
    }
    for value in values:
        forms = _forms(value)
        carrier = _latest(
            carriers, lambda other, forms=forms: _contains(other.response_body, forms)
        )
        if None is not carrier:
            kept.setdefault(carrier, _Kept()).add(CARRIES_FINAL_DATA, value)
    return kept


def _grow(candidates: dict[int, AgentRequest], kept: dict[int, _Kept]) -> None:
    """Keep the earlier requests kept ones need, until none is new."""
    traced: set[int] = set()
    while untraced := sorted(set(kept) - traced):
        for position in untraced:
            traced.add(position)
            _keep_feeders(candidates, kept, position)
            _keep_cookie_setters(candidates, kept, position)


def _keep_feeders(
    candidates: dict[int, AgentRequest], kept: dict[int, _Kept], position: int
) -> None:
    """Keep the latest earlier response holding each value it uses."""
    request = candidates[position]
    for value in _used_values(request):
        forms = _forms(value)
        feeder = _latest_before(
            candidates,
            position,
            lambda other, forms=forms: _contains(_offered_text(other), forms),
        )
        if None is not feeder:
            kept.setdefault(feeder, _Kept()).add(f"feeds {request.url}", value)


def _keep_cookie_setters(
    candidates: dict[int, AgentRequest], kept: dict[int, _Kept], position: int
) -> None:
    """Keep the latest earlier response setting each cookie it sends."""
    for name in _cookie_names(
        _header(candidates[position].request_headers, "cookie"), "; "
    ):
        setter = _latest_before(
            candidates,
            position,
            lambda other, name=name: name in _set_cookie_names(other),
        )
        if None is not setter:
            kept.setdefault(setter, _Kept()).add(f"sets cookie {name}", name)


def _add_page(candidates: dict[int, AgentRequest], kept: dict[int, _Kept]) -> None:
    """Start a chain that begins on an API call at its page."""
    first = min(kept)
    if PAGE_RESOURCE_TYPE == candidates[first].resource_type:
        return
    page = _latest_before(
        candidates, first, lambda other: PAGE_RESOURCE_TYPE == other.resource_type
    )
    if None is not page:
        url = candidates[first].url
        kept.setdefault(page, _Kept()).add(f"loads the page for {url}", url)


def _latest_before(
    candidates: dict[int, AgentRequest],
    position: int,
    matches: Callable[[AgentRequest], bool],
) -> int | None:
    """Return the latest position before `position` that `matches`."""
    earlier = {p: request for p, request in candidates.items() if p < position}
    return _latest(earlier, matches)


def _latest(
    candidates: dict[int, AgentRequest], matches: Callable[[AgentRequest], bool]
) -> int | None:
    """Return the latest position whose request `matches`, if any."""
    return max(
        (p for p, request in candidates.items() if matches(request)), default=None
    )


def _final_values(data: Any) -> set[str]:
    """Return the extracted data's scalar values worth tracing."""
    return {value for value in _scalars(data) if _is_traceable(value)}


def _used_values(request: AgentRequest) -> set[str]:
    """Return the values a request sends that another may have given.

    Its URL itself (a followed link), query values, id-like path
    segments, body values, and non-standard header values.
    """
    values = {
        *_url_values(request.url),
        *_body_values(request.post_body),
        *_header_values(request.request_headers),
    }
    return {value for value in values if _is_traceable(value)}


def _url_values(url: str) -> Iterator[str]:
    """Yield a URL, its id-like path and segments, and query values."""
    parts = urlsplit(url)
    yield url
    yield from (value for _name, value in parse_qsl(parts.query))
    path_and_query = f"{parts.path}?{parts.query}" if parts.query else parts.path
    if _has_digit(path_and_query):
        yield path_and_query
    yield from _id_like_segments(parts.path)


def _id_like_segments(path: str) -> Iterator[str]:
    """Yield the path segments that look like ids or tokens."""
    for segment in (unquote(part) for part in path.split("/")):
        if _has_digit(segment) or LONG_PATH_SEGMENT <= len(segment):
            yield segment


def _has_digit(text: str) -> bool:
    """Tell whether `text` has a digit, as ids and tokens mostly do."""
    return any(character.isdigit() for character in text)


def _body_values(body: str | None) -> Iterator[str]:
    """Yield a request body's values: JSON scalars, else form values."""
    if not body:
        return
    try:
        yield from _scalars(json.loads(body))
    except json.JSONDecodeError:
        yield from (value for _name, value in parse_qsl(body))


def _header_values(headers: dict[str, str]) -> Iterator[str]:
    """Yield the values of non-standard, unredacted request headers."""
    for name, value in headers.items():
        lowered = name.lower()
        if lowered in STANDARD_REQUEST_HEADERS or lowered.startswith("sec-"):
            continue
        if REDACTED_VALUE not in value:
            yield value


def _scalars(data: Any) -> Iterator[str]:
    """Yield every scalar in `data` as text, but booleans and nulls."""
    if isinstance(data, dict):
        data = list(data.values())
    if isinstance(data, list):
        for value in data:
            yield from _scalars(value)
        return
    text = _scalar_text(data)
    if None is not text:
        yield text


def _scalar_text(value: Any) -> str | None:
    """Return a scalar as text (`5.0` as `5`), or `None` for flags."""
    if isinstance(value, bool) or None is value:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _is_traceable(value: str) -> bool:
    """Tell whether a value is long enough to prove a link."""
    return MIN_VALUE_LENGTH <= len(value)


def _forms(value: str) -> set[str]:
    """Return how a value may appear in a response."""
    return {
        value,
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
        json.dumps(value)[1:-1].replace("/", "\\/"),
        quote(value, safe=""),
        quote_plus(value, safe=""),
        html.escape(value),
    }


def _contains(text: str | None, forms: set[str]) -> bool:
    """Tell whether `text` holds any of the forms."""
    return bool(text) and any(form in text for form in forms)


def _offered_text(request: AgentRequest) -> str:
    """Return what a response gives later requests: body and headers."""
    headers = "\n".join(
        value
        for value in request.response_headers.values()
        if REDACTED_VALUE not in value
    )
    return f"{request.response_body or ''}\n{headers}"


def _header(headers: dict[str, str], name: str) -> str:
    """Return a header's value, its name matched in any case."""
    return next((v for k, v in headers.items() if name == k.lower()), "")


def _set_cookie_names(request: AgentRequest) -> set[str]:
    """Return the names of the cookies a response sets."""
    return set(_cookie_names(_header(request.response_headers, "set-cookie"), "\n"))


def _cookie_names(header: str, separator: str) -> list[str]:
    """Return the cookie names in a `Cookie` or `Set-Cookie` value."""
    return [
        part.split("=", 1)[0].strip()
        for part in header.split(separator)
        if "=" in part and part.split("=", 1)[0].strip()
    ]
