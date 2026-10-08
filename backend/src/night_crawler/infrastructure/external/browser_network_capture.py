"""The network traffic of a browser agent's browser, from CDP events.

Browser Use drives Chromium over the Chrome DevTools Protocol, so its
`Network` events are what the browser sent and received. They arrive
as plain dicts, one request split across several events keyed by
`requestId`; this module joins them into `AgentRequest`s.
"""

import asyncio
import base64
import bisect
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from night_crawler.domain.ports.browser_agent_recorder import (
    REDACTED_VALUE,
    AgentRequest,
)

logger = logging.getLogger(__name__)

BodyFetcher = Callable[[str, str | None], Awaitable[dict[str, Any]]]
"""Calls CDP's `Network.getResponseBody(requestId)` on a session."""

BODY_RESOURCE_TYPES = frozenset({"document", "xhr", "fetch"})
"""Resource types whose response bodies are kept: pages and API data."""

REDACTED_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "x-goog-api-key"}
)
"""Headers whose values are secrets; only their names are kept."""

COOKIE_SEPARATORS = {"cookie": ";", "set-cookie": "\n"}
"""Cookie headers keep each cookie's name, never its value: lineage
traces who set a cookie by name (DOMAIN_MODEL §4.16)."""


@dataclass
class _PendingRequest:
    """One request being assembled from its CDP events."""

    wall_time: float
    url: str
    method: str
    resource_type: str | None
    request_headers: dict[str, str]
    post_body: str | None
    session_id: str | None
    status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: str | None = None
    is_response_body_truncated: bool = False
    failure: str | None = None


class BrowserNetworkCapture:
    """Collects one browser's requests while an agent drives it.

    The `on_*` methods are CDP event handlers. Bodies are fetched in
    the background once a response finishes loading, since CDP drops
    them soon after; `wait_for_bodies` waits for those fetches.
    """

    def __init__(self, fetch_body: BodyFetcher, response_body_max_bytes: int) -> None:
        """Keep how to fetch bodies and how much of each to keep."""
        self._fetch_body = fetch_body
        self._response_body_max_bytes = response_body_max_bytes
        self._requests: list[_PendingRequest] = []
        self._in_flight: dict[str, _PendingRequest] = {}
        self._body_tasks: set[asyncio.Task] = set()

    def on_request_will_be_sent(
        self, params: dict[str, Any], session_id: str | None
    ) -> None:
        """Start a request; a redirect closes the hop before it."""
        request_id = params["requestId"]
        redirect_response = params.get("redirectResponse")
        if redirect_response and request_id in self._in_flight:
            _set_response(self._in_flight[request_id], redirect_response)
        request = params["request"]
        pending = _PendingRequest(
            wall_time=params.get("wallTime", 0.0),
            url=request["url"],
            method=request["method"],
            resource_type=_lower(params.get("type")),
            request_headers=_redact(request.get("headers", {})),
            post_body=request.get("postData"),
            session_id=session_id,
        )
        self._requests.append(pending)
        self._in_flight[request_id] = pending

    def on_response_received(
        self, params: dict[str, Any], session_id: str | None
    ) -> None:
        """Record a request's status and headers."""
        pending = self._in_flight.get(params["requestId"])
        if None is not pending:
            _set_response(pending, params["response"])

    def on_loading_finished(
        self, params: dict[str, Any], session_id: str | None
    ) -> None:
        """Fetch the body of a finished page or API call."""
        request_id = params["requestId"]
        pending = self._in_flight.pop(request_id, None)
        if None is pending or pending.resource_type not in BODY_RESOURCE_TYPES:
            return
        task = asyncio.get_running_loop().create_task(
            self._read_body(pending, request_id)
        )
        self._body_tasks.add(task)
        task.add_done_callback(self._body_tasks.discard)

    def on_loading_failed(self, params: dict[str, Any], session_id: str | None) -> None:
        """Record why a request failed; it has no status."""
        pending = self._in_flight.pop(params["requestId"], None)
        if None is pending:
            return
        pending.status = None
        if params.get("canceled"):
            pending.failure = "aborted"
        else:
            pending.failure = params.get("errorText") or "failed"

    async def wait_for_bodies(self, timeout_seconds: float) -> None:
        """Wait for pending body fetches; give up on the slow ones."""
        if not self._body_tasks:
            return
        _done, pending = await asyncio.wait(
            set(self._body_tasks), timeout=timeout_seconds
        )
        for task in pending:
            task.cancel()

    def get_requests(
        self, step_start_times: Sequence[float]
    ) -> tuple[AgentRequest, ...]:
        """Return every request so far, tied to the step it was made in.

        A request belongs to the last step started before it; requests
        before the first step (the browser starting up) belong to it.

        Args:
            step_start_times: When each step started, in order, as
                epoch seconds like CDP's `wallTime`.
        """
        return tuple(
            _to_request(pending, _step_index(step_start_times, pending.wall_time))
            for pending in self._requests
        )

    async def _read_body(self, pending: _PendingRequest, request_id: str) -> None:
        """Fetch a body and keep it, cut at the set size.

        A body CDP no longer holds (a page that navigated away, an
        evicted resource) is missing data, not a failure: it stays
        `None`.
        """
        try:
            response = await self._fetch_body(request_id, pending.session_id)
        except RuntimeError as error:
            logger.debug("Response body unavailable: url=%s, %s", pending.url, error)
            return
        body = _decode(response)
        cut = body[: self._response_body_max_bytes]
        pending.response_body = cut.decode("utf-8", errors="ignore")
        pending.is_response_body_truncated = len(cut) < len(body)


def _set_response(pending: _PendingRequest, response: dict[str, Any]) -> None:
    """Copy a CDP response's status and headers onto a request."""
    pending.status = response.get("status")
    pending.response_headers = _redact(response.get("headers", {}))


def _redact(headers: dict[str, Any]) -> dict[str, str]:
    """Return headers as text, secret values replaced by name."""
    return {
        name: _redact_value(name.lower(), str(value)) for name, value in headers.items()
    }


def _redact_value(name: str, value: str) -> str:
    """Return a header's value, or `<redacted>` where it is secret.

    `Cookie: a=1; b=2` reads `a=<redacted>; b=<redacted>`, and each
    `Set-Cookie` line (CDP joins them with newlines) `name=<redacted>`,
    its attributes dropped.
    """
    if name in REDACTED_HEADERS:
        return REDACTED_VALUE
    separator = COOKIE_SEPARATORS.get(name)
    if None is separator:
        return value
    return _redact_cookies(value, separator)


def _redact_cookies(value: str, separator: str) -> str:
    """Return a cookie header's cookies as `name=<redacted>`."""
    names = [
        part.split("=", 1)[0].strip() for part in value.split(separator) if "=" in part
    ]
    joiner = "; " if ";" == separator else separator
    return joiner.join(f"{cookie}={REDACTED_VALUE}" for cookie in names)


def _decode(response: dict[str, Any]) -> bytes:
    """Return a `Network.getResponseBody` result's body as bytes."""
    body = response.get("body") or ""
    if response.get("base64Encoded"):
        return base64.b64decode(body)
    return body.encode()


def _lower(text: str | None) -> str | None:
    """Return `text` lower-cased, keeping `None`."""
    return None if None is text else text.lower()


def _step_index(step_start_times: Sequence[float], wall_time: float) -> int:
    """Return the index of the last step started by `wall_time`."""
    return max(bisect.bisect_right(step_start_times, wall_time) - 1, 0)


def _to_request(pending: _PendingRequest, step_index: int) -> AgentRequest:
    """Freeze an assembled request into its value object."""
    return AgentRequest(
        step_index=step_index,
        url=pending.url,
        method=pending.method,
        resource_type=pending.resource_type,
        request_headers=pending.request_headers,
        post_body=pending.post_body,
        status=pending.status,
        response_headers=pending.response_headers,
        response_body=pending.response_body,
        is_response_body_truncated=pending.is_response_body_truncated,
        failure=pending.failure,
    )
