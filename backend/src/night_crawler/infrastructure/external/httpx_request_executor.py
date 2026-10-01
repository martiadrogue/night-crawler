"""httpx implementation of the request executor (`none` mode)."""

import logging

import httpx
from night_crawler.domain.exceptions import RequestFailedException
from night_crawler.domain.model.entities import MessageAidProxy
from night_crawler.domain.model.value_objects import SessionState
from night_crawler.domain.ports.request_executor import (
    AbstractRequestExecutor,
    DispatchRequest,
    DispatchResult,
)
from night_crawler.domain.rules.host_session import (
    build_request_headers,
    resolve_request_host,
    shareable_headers,
)
from night_crawler.domain.rules.response_status import is_success_status
from night_crawler.infrastructure.external.content_harvest import (
    ResponseSnapshot,
    harvest_response,
)

logger = logging.getLogger(__name__)


class HttpxRequestExecutor(AbstractRequestExecutor):
    """Sends requests over httpx, pooling one client per host and proxy.

    Shared cookies travel in the `Cookie` header; cookies every response
    sets (redirects included) are captured for the next request. Only
    headers the template or the session supplied are shared back, never
    httpx's own defaults, so its generic User-Agent never reaches a
    browser.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Start with no clients; `transport` replaces the network."""
        self._transport = transport
        self._clients: dict[tuple[str | None, str | None], httpx.AsyncClient] = {}

    async def execute(self, request: DispatchRequest) -> DispatchResult:
        """Send the request and harvest the response body.

        Raises:
            RequestFailedException: the request failed or timed out,
                or the status is 400 or above.
        """
        rendered = request.rendered
        headers = build_request_headers(rendered.headers, request.session)
        client = self._client_for(rendered.url, request.proxy)
        client.cookies.clear()
        try:
            response = await client.request(
                rendered.action,
                rendered.url,
                content=rendered.body,
                headers=headers,
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException as exception:
            raise RequestFailedException(
                f"Request timed out: {exception}", failure_code="timeout"
            ) from exception
        except httpx.HTTPError as exception:
            raise RequestFailedException(f"Request failed: {exception}") from exception
        if not is_success_status(response.status_code, request.success_codes):
            logger.warning(
                "Request failed: url=%s, status=%s", rendered.url, response.status_code
            )
            raise RequestFailedException(
                f"Request failed: {response.status_code} {response.reason_phrase}",
                failure_code=str(response.status_code),
            )
        return DispatchResult(
            harvest=await harvest_response(
                ResponseSnapshot(
                    body=response.text,
                    content_type=response.headers.get("content-type", ""),
                    headers=response.headers.multi_items(),
                    url=str(response.url),
                    placeholders=rendered.placeholder_values,
                ),
                request.selectors,
            ),
            status_code=response.status_code,
            session=SessionState(
                cookies=_response_cookies(response), headers=shareable_headers(headers)
            ),
        )

    def _client_for(self, url: str, proxy: MessageAidProxy | None) -> httpx.AsyncClient:
        """Return the pooled client for a host and proxy.

        A proxy is fixed when a client is built, so each needs its own.
        The jar is cleared before every request: cookies only travel
        through the shared session, never by accident.
        """
        key = (resolve_request_host(url), None if None is proxy else proxy.id)
        client = self._clients.get(key)
        if None is client:
            client = httpx.AsyncClient(
                transport=self._transport,
                proxy=_to_httpx_proxy(proxy),
                follow_redirects=True,
            )
            self._clients[key] = client
        return client

    async def aclose(self) -> None:
        """Close every pooled client."""
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            await client.aclose()


def _response_cookies(response: httpx.Response) -> dict[str, str]:
    """Return the cookies set along the redirect chain; last wins."""
    cookies: dict[str, str] = {}
    for step in [*response.history, response]:
        cookies.update(dict(step.cookies))
    return cookies


def _to_httpx_proxy(proxy: MessageAidProxy | None) -> httpx.Proxy | None:
    """Convert a pooled proxy to an `httpx.Proxy` with credentials."""
    if None is proxy:
        return None
    return httpx.Proxy(
        proxy.url,
        auth=(proxy.user, proxy.password) if None is not proxy.user else None,
        headers=proxy.headers,
    )
