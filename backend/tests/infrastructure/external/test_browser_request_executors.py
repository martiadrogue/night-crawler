from datetime import datetime

import pytest
from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.model.value_objects import RenderedRequest, SessionState
from night_crawler.domain.ports.request_executor import DispatchRequest
from night_crawler.domain.rules.selector_tree import flatten_harvest
from night_crawler.infrastructure.external.patchright_request_executor import (
    PatchrightRequestExecutor,
)
from night_crawler.infrastructure.external.playwright_request_executor import (
    PlaywrightRequestExecutor,
)

NOW = datetime(2026, 1, 1)
EXECUTORS = [PlaywrightRequestExecutor, PatchrightRequestExecutor]


@pytest.fixture
async def browser_executor_factory():
    executors = []

    def create(executor_type):
        executor = executor_type()
        executors.append(executor)
        return executor

    yield create
    for executor in executors:
        await executor.aclose()


def _selector(selector_id, path, selector_type="value", title=None, parent=None):
    return MessageSelector(
        id=selector_id,
        message_template_id="template-1",
        parent_selector_id=parent,
        path=path,
        type=selector_type,
        target="__text",
        created_at=NOW,
        updated_at=NOW,
        title=title,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("executor_type", EXECUTORS)
async def test_a_page_gets_the_shared_session_and_gives_its_own_back(
    echo_server, executor_type, browser_executor_factory
):
    session = SessionState(
        cookies={"shared": "yes"},
        headers={"user-agent": "NightCrawlerTest/1.0", "x-custom": "hello"},
    )
    request = DispatchRequest(
        rendered=RenderedRequest(
            action="GET", url=f"{echo_server}/page", body=None, headers={}
        ),
        selectors=[
            _selector("cookie", "//p[@id='cookie']", title="cookie"),
            _selector("custom", "//p[@id='custom']", title="custom"),
            _selector("ua", "//p[@id='ua']", title="user_agent"),
        ],
        session=session,
        timeout_seconds=20,
    )

    result = await browser_executor_factory(executor_type).execute(request)
    harvested = flatten_harvest(result.harvest)

    assert "shared=yes" == harvested["cookie"]
    assert "hello" == harvested["custom"]
    assert "NightCrawlerTest/1.0" == harvested["user_agent"]
    assert {"shared": "yes", "server": "1"} == result.session.cookies
    assert "NightCrawlerTest/1.0" == result.session.headers["user-agent"]
    assert "hello" == result.session.headers["x-custom"]


@pytest.mark.anyio
@pytest.mark.parametrize("executor_type", EXECUTORS)
async def test_same_host_requests_reuse_the_browser_session(
    echo_server, executor_type, browser_executor_factory
):
    executor = browser_executor_factory(executor_type)
    first_request = DispatchRequest(
        rendered=RenderedRequest(
            action="GET", url=f"{echo_server}/session/start", body=None, headers={}
        ),
        selectors=[],
        session=None,
        timeout_seconds=20,
    )
    first_result = await executor.execute(first_request)
    second_request = DispatchRequest(
        rendered=RenderedRequest(
            action="GET",
            url=f"{echo_server}/session/check",
            body=None,
            headers={},
        ),
        selectors=[_selector("state", "//p[@id='state']", title="state")],
        session=first_result.session,
        timeout_seconds=20,
    )
    second_result = await executor.execute(second_request)

    assert {"state": "retained"} == flatten_harvest(second_result.harvest)


@pytest.mark.anyio
@pytest.mark.parametrize("executor_type", EXECUTORS)
async def test_host_session_sharing_off_uses_an_isolated_browser_context(
    echo_server, executor_type, browser_executor_factory
):
    executor = browser_executor_factory(executor_type)
    first_request = DispatchRequest(
        rendered=RenderedRequest(
            action="GET", url=f"{echo_server}/session/start", body=None, headers={}
        ),
        selectors=[],
        session=None,
        timeout_seconds=20,
        is_host_session_sharing_enabled=False,
    )
    second_request = DispatchRequest(
        rendered=RenderedRequest(
            action="GET", url=f"{echo_server}/session/check", body=None, headers={}
        ),
        selectors=[_selector("state", "//p[@id='state']", title="state")],
        session=None,
        timeout_seconds=20,
        is_host_session_sharing_enabled=False,
    )

    await executor.execute(first_request)
    second_result = await executor.execute(second_request)

    assert {"state": "empty"} == flatten_harvest(second_result.harvest)


@pytest.mark.anyio
@pytest.mark.parametrize("executor_type", EXECUTORS)
async def test_a_json_get_is_harvested_from_its_response_body(
    echo_server, executor_type, browser_executor_factory
):
    request = DispatchRequest(
        rendered=RenderedRequest(
            action="GET", url=f"{echo_server}/json", body=None, headers={}
        ),
        selectors=[
            _selector(
                "next_page",
                "pageProps.searchPageResultsFetchResult.pagination.hasNext && "
                "sum([pageProps.searchPageResultsFetchResult.pagination.currentPage, "
                "`1`]) || null",
                title="next_page",
            )
        ],
        session=None,
        timeout_seconds=20,
    )

    result = await browser_executor_factory(executor_type).execute(request)

    assert {"next_page": 18} == flatten_harvest(result.harvest)


@pytest.mark.anyio
@pytest.mark.parametrize("executor_type", EXECUTORS)
async def test_each_click_reads_the_whole_page_again(
    echo_server, executor_type, browser_executor_factory
):
    request = DispatchRequest(
        rendered=RenderedRequest(
            action="GET", url=f"{echo_server}/page", body=None, headers={}
        ),
        selectors=[
            _selector("tabs", "button.tab", "click"),
            _selector("panel", "#panel", title="panel", parent="tabs"),
            _selector("before", "//p[@id='panel']", title="panel_before"),
        ],
        session=None,
        timeout_seconds=20,
    )

    result = await browser_executor_factory(executor_type).execute(request)
    harvested = flatten_harvest(result.harvest)

    assert ["Menu", "Reviews"] == harvested["panel[]"]
    assert "empty" == harvested["panel_before"]


@pytest.mark.anyio
@pytest.mark.parametrize("executor_type", EXECUTORS)
async def test_a_non_get_request_is_fetched_and_harvested_as_json(
    echo_server, executor_type, browser_executor_factory
):
    request = DispatchRequest(
        rendered=RenderedRequest(
            action="POST",
            url=f"{echo_server}/api",
            body='{"q": "bars"}',
            headers={"Content-Type": "application/json", "X-Custom": "own"},
        ),
        selectors=[
            _selector("query", "received.q", title="query"),
            _selector("custom", "custom", title="custom"),
        ],
        session=SessionState(cookies={}, headers={"x-custom": "shared"}),
        timeout_seconds=20,
    )

    result = await browser_executor_factory(executor_type).execute(request)

    assert {"query": "bars", "custom": "own"} == flatten_harvest(result.harvest)
    assert "1" == result.session.cookies["server"]
