from datetime import datetime

import httpx
import pytest
from night_crawler.domain.exceptions import RequestFailedException
from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.model.value_objects import RenderedRequest, SessionState
from night_crawler.domain.ports.request_executor import DispatchRequest
from night_crawler.domain.rules.selector_tree import flatten_harvest
from night_crawler.infrastructure.external.httpx_request_executor import (
    HttpxRequestExecutor,
)


def _selector(selector_id, path, source, title):
    return MessageSelector(
        id=selector_id,
        message_template_id="template-1",
        parent_selector_id=None,
        path=path,
        type="value",
        target="__text",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        title=title,
        source=source,
    )


def _request(
    url="https://example.com/start",
    session=None,
    headers=None,
    selectors=None,
    success_codes=None,
):
    return DispatchRequest(
        rendered=RenderedRequest(
            action="GET", url=url, body=None, headers=headers or {}
        ),
        selectors=selectors or [],
        session=session,
        timeout_seconds=5,
        success_codes=success_codes,
    )


@pytest.mark.anyio
async def test_cookies_from_every_response_are_captured():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/start" == request.url.path:
            return httpx.Response(
                302, headers={"Location": "/end", "Set-Cookie": "first=1; Path=/"}
            )
        return httpx.Response(200, text="ok", headers={"Set-Cookie": "second=2"})

    executor = HttpxRequestExecutor(transport=httpx.MockTransport(handler))
    try:
        result = await executor.execute(
            _request(
                selectors=[
                    _selector(
                        "cookie", r"^set-cookie: second=(\w+)", "headers", "second"
                    ),
                    _selector("url", r"/(\w+)$", "url", "last_path"),
                ]
            )
        )
    finally:
        await executor.aclose()

    assert 200 == result.status_code
    assert {"first": "1", "second": "2"} == result.session.cookies
    assert {"second": "2", "last_path": "end"} == flatten_harvest(result.harvest)


@pytest.mark.anyio
async def test_shared_cookies_and_headers_are_sent_and_template_headers_win():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok")

    executor = HttpxRequestExecutor(transport=httpx.MockTransport(handler))
    session = SessionState(
        cookies={"sid": "abc"},
        headers={"user-agent": "Chrome/140", "x-token": "shared"},
    )
    try:
        result = await executor.execute(
            _request(session=session, headers={"X-Token": "own"})
        )
    finally:
        await executor.aclose()

    [request] = seen
    assert "sid=abc" == request.headers["cookie"]
    assert "Chrome/140" == request.headers["user-agent"]
    assert "own" == request.headers["x-token"]
    assert {"user-agent": "Chrome/140", "x-token": "own"} == result.session.headers


@pytest.mark.anyio
async def test_httpx_default_headers_are_not_shared():
    executor = HttpxRequestExecutor(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    try:
        result = await executor.execute(_request())
    finally:
        await executor.aclose()

    assert {} == result.session.headers


@pytest.mark.anyio
async def test_an_error_status_fails_with_its_code():
    executor = HttpxRequestExecutor(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    try:
        with pytest.raises(RequestFailedException) as exc_info:
            await executor.execute(_request())
    finally:
        await executor.aclose()

    assert "503" == exc_info.value.failure_code


@pytest.mark.anyio
async def test_a_timeout_fails_with_the_timeout_code():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    executor = HttpxRequestExecutor(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RequestFailedException) as exc_info:
            await executor.execute(_request())
    finally:
        await executor.aclose()

    assert "timeout" == exc_info.value.failure_code


NEXT_404 = (
    "<html><body><h1>404</h1>"
    '<script id="__NEXT_DATA__" type="application/json">'
    '{"props":{},"page":"/_error","buildId":"J_b2bB7DDLbBIpC5ANCwA","isFallback":false}'
    "</script></body></html>"
)
BUILD_ID_PATH = (
    "(substring-before(substring-after("
    "//script[@id='__NEXT_DATA__'], '\"buildId\":\"'), '\"'))"
)


@pytest.mark.anyio
async def test_a_status_in_the_success_codes_is_harvested():
    executor = HttpxRequestExecutor(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                404, text=NEXT_404, headers={"content-type": "text/html"}
            )
        )
    )
    try:
        result = await executor.execute(
            _request(
                selectors=[_selector("b", BUILD_ID_PATH, "content", "build_id")],
                success_codes=("404",),
            )
        )
    finally:
        await executor.aclose()

    assert 404 == result.status_code
    assert {"build_id": "J_b2bB7DDLbBIpC5ANCwA"} == flatten_harvest(result.harvest)


@pytest.mark.anyio
async def test_a_status_outside_the_success_codes_fails():
    executor = HttpxRequestExecutor(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    try:
        with pytest.raises(RequestFailedException) as exc_info:
            await executor.execute(_request(success_codes=("404",)))
    finally:
        await executor.aclose()

    assert "200" == exc_info.value.failure_code
