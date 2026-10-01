"""One request in a headless browser, shared by both browser engines.

Playwright and Patchright have the same API; each executor passes its
own library in as a `BrowserEngine`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from night_crawler.domain.exceptions import RequestFailedException
from night_crawler.domain.model.entities import MessageAidProxy, MessageSelector
from night_crawler.domain.model.value_objects import Harvest, SessionState
from night_crawler.domain.ports.request_executor import DispatchRequest, DispatchResult
from night_crawler.domain.rules.host_session import (
    build_request_headers,
    find_header,
    merge_cookies,
    resolve_request_host,
    shareable_headers,
)
from night_crawler.domain.rules.response_status import is_success_status
from night_crawler.domain.rules.selector_paths import is_xpath
from night_crawler.infrastructure.external.content_harvest import (
    PageInteractor,
    ResponseSnapshot,
    harvest_response,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "user-agent"


@dataclass(frozen=True)
class BrowserEngine:
    """A Playwright-compatible library: its entry point and errors."""

    start: Callable[[], Any]
    error_type: type[Exception]
    timeout_error_type: type[Exception]


class BrowserExecution:
    """Reuse browser resources for one crawler execution."""

    def __init__(self, engine: BrowserEngine) -> None:
        """Create an empty execution-scoped browser pool."""
        self._engine = engine
        self._manager: Any = None
        self._library: Any = None
        self._browsers: dict[str | None, Any] = {}
        self._contexts: dict[
            tuple[str | None, str | None], tuple[Any, Any, str | None]
        ] = {}

    async def execute(self, request: DispatchRequest) -> DispatchResult:
        """Run one request inside this execution's browser pool.

        Raises:
            RequestFailedException: the browser failed or timed out.
        """
        try:
            return await self._dispatch(request)
        except self._engine.timeout_error_type as exception:
            raise RequestFailedException(
                f"Render timed out: {exception}", failure_code="timeout"
            ) from exception
        except self._engine.error_type as exception:
            raise RequestFailedException(f"Render failed: {exception}") from exception

    async def aclose(self) -> None:
        """Close contexts, browsers, and the engine manager."""
        try:
            for context, _page, _user_agent in self._contexts.values():
                await context.close()
            for browser in self._browsers.values():
                await browser.close()
        finally:
            if None is not self._library:
                await self._library.stop()
            self._contexts.clear()
            self._browsers.clear()
            self._manager = None
            self._library = None

    async def _dispatch(self, request: DispatchRequest) -> DispatchResult:
        """Seed a page, send one request, and capture its session."""
        rendered = request.rendered
        headers = build_request_headers(
            rendered.headers, _without_cookies(request.session)
        )
        browser = await self._get_browser(request.proxy)
        context, page, should_close_context = await self._get_context(
            browser, request, headers
        )
        try:
            await _prepare_context(context, request, headers)
            timeout_ms = request.timeout_seconds * 1000
            harvest, status, sent = await _send_browser_request(
                page, request, timeout_ms
            )
            user_agent = await page.evaluate("() => navigator.userAgent")
            browser_cookies = await context.cookies(rendered.url)
        finally:
            if should_close_context:
                await context.close()
        return DispatchResult(
            harvest=harvest,
            status_code=status,
            session=SessionState(
                cookies={cookie["name"]: cookie["value"] for cookie in browser_cookies},
                headers={**shareable_headers(sent), _USER_AGENT: user_agent},
            ),
        )

    async def _get_browser(self, proxy: MessageAidProxy | None) -> Any:
        """Return the proxy browser, launching if needed."""
        proxy_id = None if None is proxy else proxy.id
        browser = self._browsers.get(proxy_id)
        if None is browser:
            if None is self._manager:
                self._manager = self._engine.start()
                self._library = await self._manager.start()
            browser = await self._library.chromium.launch(
                proxy=_to_browser_proxy(proxy)
            )
            self._browsers[proxy_id] = browser
        return browser

    async def _get_context(
        self,
        browser: Any,
        request: DispatchRequest,
        headers: dict[str, str],
    ) -> tuple[Any, Any, bool]:
        """Reuse a shared host context or create an isolated one."""
        key = _shared_context_key(request)
        requested_user_agent = find_header(headers, _USER_AGENT)
        current = (
            await self._get_reusable_context(key, requested_user_agent)
            if None is not key
            else None
        )
        if None is not current:
            return current[0], current[1], False

        context = await browser.new_context(
            user_agent=requested_user_agent,
            extra_http_headers=_extra_headers(headers),
        )
        page = await context.new_page()
        user_agent = await page.evaluate("() => navigator.userAgent")
        if None is key:
            return context, page, True
        self._contexts[key] = (context, page, user_agent)
        return context, page, False

    async def _get_reusable_context(
        self,
        key: tuple[str | None, str],
        requested_user_agent: str | None,
    ) -> tuple[Any, Any, str | None] | None:
        """Reuse a host context while the User-Agent matches."""
        current = self._contexts.get(key)
        if None is current:
            return None
        if None is requested_user_agent or requested_user_agent == current[2]:
            return current
        await current[0].close()
        del self._contexts[key]
        return None


def _shared_context_key(
    request: DispatchRequest,
) -> tuple[str | None, str] | None:
    """Return the reusable proxy/host key, or `None` when isolated."""
    if not request.is_host_session_sharing_enabled:
        return None
    host = resolve_request_host(request.rendered.url)
    if None is host:
        return None
    proxy_id = None if None is request.proxy else request.proxy.id
    return proxy_id, host


async def _prepare_context(
    context: Any, request: DispatchRequest, headers: dict[str, str]
) -> None:
    """Apply this request's headers and cookies to its context."""
    await context.set_extra_http_headers(_extra_headers(headers))
    cookies = _requested_cookies(request)
    if cookies:
        await context.add_cookies(
            [
                {"name": name, "value": value, "url": request.rendered.url}
                for name, value in cookies.items()
            ]
        )


async def _send_browser_request(
    page: Any, request: DispatchRequest, timeout_ms: float
) -> tuple[Harvest, int | None, dict[str, str]]:
    """Send and harvest one request on `page`."""
    if "GET" == request.rendered.action.upper():
        return await _load(page, request, timeout_ms)
    return await _fetch(page, request, timeout_ms)


async def _load(
    page: Any, request: DispatchRequest, timeout_ms: float
) -> tuple[Harvest, int | None, dict[str, str]]:
    """Navigate and harvest the live page, clicking as selectors say.

    Returns:
        The harvest, the status, and the headers the navigation sent.
    """
    response = await page.goto(request.rendered.url, timeout=timeout_ms)
    status, headers, sent = await _response_metadata(response)
    _raise_for_status(request.rendered.url, status, request.success_codes)
    body, content_type, interactor = await _response_content(page, response, timeout_ms)
    harvest = await harvest_response(
        ResponseSnapshot(
            body=body,
            content_type=content_type,
            headers=[(header["name"], header["value"]) for header in headers],
            url=page.url,
            placeholders=request.rendered.placeholder_values,
        ),
        request.selectors,
        interactor,
    )
    return harvest, status, sent


async def _response_metadata(
    response: Any,
) -> tuple[int | None, list[dict[str, str]], dict[str, str]]:
    """Return response status and headers, or empty values."""
    if None is response:
        return None, [], {}
    return (
        response.status,
        await response.headers_array(),
        await response.request.all_headers(),
    )


async def _response_content(
    page: Any, response: Any, timeout_ms: float
) -> tuple[str, str, PageInteractor | None]:
    """Return raw JSON content or a live HTML page for harvesting."""
    if None is response:
        return await page.content(), "text/html", _LivePage(page, timeout_ms)
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        return await response.text(), content_type, None
    return await page.content(), "text/html", _LivePage(page, timeout_ms)


async def _fetch(
    page: Any, request: DispatchRequest, timeout_ms: float
) -> tuple[Harvest, int | None, dict[str, str]]:
    """Send a non-GET request through the context and harvest its body.

    A browser can only navigate with GET. The context's request API
    shares its cookies and extra headers, and stores cookies it sets.
    There is no page to click on.

    Returns:
        The harvest, the status, and the headers the request sent.
    """
    rendered = request.rendered
    response = await page.request.fetch(
        rendered.url, method=rendered.action, data=rendered.body, timeout=timeout_ms
    )
    _raise_for_status(rendered.url, response.status, request.success_codes)
    harvest = await harvest_response(
        ResponseSnapshot(
            body=await response.text(),
            content_type=response.headers.get("content-type", ""),
            headers=[(h["name"], h["value"]) for h in response.headers_array],
            url=response.url,
            placeholders=rendered.placeholder_values,
        ),
        request.selectors,
    )
    sent = build_request_headers(rendered.headers, request.session)
    return harvest, response.status, sent


class _LivePage(PageInteractor):
    """Clicks and selects on a Playwright-compatible page."""

    def __init__(self, page: Any, timeout_ms: float) -> None:
        """Act on `page`, waiting at most `timeout_ms` per action."""
        self._page = page
        self._timeout_ms = timeout_ms

    async def count(self, path: str) -> int:
        """Return how many elements `path` matches right now."""
        return await self._page.locator(_locator(path)).count()

    async def act(self, selector: MessageSelector, index: int) -> None:
        """Act on the `index`-th match, then let the page settle."""
        match = self._page.locator(_locator(selector.path)).nth(index)
        if "click" == selector.type:
            await match.click(timeout=self._timeout_ms)
        else:
            await match.select_option(value=selector.target, timeout=self._timeout_ms)
        await self._page.wait_for_load_state(timeout=self._timeout_ms)

    async def snapshot(self) -> str:
        """Return the page's current HTML."""
        return await self._page.content()


def _locator(path: str) -> str:
    """Return a Playwright locator for an XPath or CSS path."""
    return f"xpath={path}" if is_xpath(path) else path


def _raise_for_status(
    url: str, status: int | None, success_codes: tuple[str, ...] | None
) -> None:
    """Reject a status that isn't a success; same-document has none.

    Raises:
        RequestFailedException: `status` isn't in `success_codes`, or is
            400 or above without them.
    """
    if None is not status and not is_success_status(status, success_codes):
        logger.warning("Render failed: url=%s, status=%s", url, status)
        raise RequestFailedException(
            f"Render failed: status {status}", failure_code=str(status)
        )


def _without_cookies(session: SessionState | None) -> SessionState | None:
    """Return the session minus cookies: browsers take them natively."""
    return None if None is session else SessionState(headers=session.headers)


def _requested_cookies(request: DispatchRequest) -> dict[str, str]:
    """Return the shared cookies plus any the template sets itself."""
    shared = {} if None is request.session else request.session.cookies
    return merge_cookies(shared, request.rendered.headers)


def _extra_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return the headers a context sends on every request.

    User-Agent is set on the context itself, cookies through its jar.
    """
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in (_USER_AGENT, "cookie")
    }


def _to_browser_proxy(proxy: MessageAidProxy | None) -> dict[str, str] | None:
    """Convert a pooled proxy to Playwright's proxy settings."""
    if None is proxy:
        return None
    settings = {"server": proxy.url, "password": proxy.password}
    if None is not proxy.user:
        settings["username"] = proxy.user
    return settings
