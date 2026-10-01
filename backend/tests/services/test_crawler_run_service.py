from datetime import datetime

import pytest
from night_crawler.domain.bundles.execution_plan import ExecutionPlan
from night_crawler.domain.bundles.request_executors import RequestExecutors
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    RequestFailedException,
)
from night_crawler.domain.model.entities import (
    Crawler,
    CrawlerExecution,
    CrawlerVersion,
    Dataset,
    MessageAid,
    MessageAidRateLimit,
    MessageSelector,
    MessageTemplate,
)
from night_crawler.domain.model.value_objects import (
    DatasetField,
    Harvest,
    RateLimitTarget,
    SessionState,
)
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.ports.request_executor import (
    AbstractRequestExecutor,
    DispatchRequest,
    DispatchResult,
)
from night_crawler.services import crawler_run_service

NOW = datetime(2026, 1, 1)


class FakeExecutor(AbstractRequestExecutor):
    """Records requests and answers from a script keyed by URL."""

    def __init__(self, name, answers, log):
        self.name, self.answers, self.log = name, answers, log

    async def execute(self, request: DispatchRequest) -> DispatchResult:
        self.log.append((self.name, request))
        answer = self.answers[request.rendered.url]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def aclose(self) -> None:
        pass


class FakeRateLimiter(AbstractRateLimiter):
    """Records what the run asked of each rate-limit key."""

    def __init__(self):
        self.calls = []

    async def acquire(self, target: RateLimitTarget) -> float:
        self.calls.append(("acquire", target.key))
        return 0.0

    async def record_block(self, target: RateLimitTarget) -> None:
        self.calls.append(("block", target.key))

    async def record_success(self, target: RateLimitTarget) -> None:
        self.calls.append(("success", target.key))

    async def aclose(self) -> None:
        pass


def _executors(answers):
    log = []
    executors = RequestExecutors(
        httpx=FakeExecutor("httpx", answers, log),
        playwright=FakeExecutor("playwright", answers, log),
        stealth=FakeExecutor("stealth", answers, log),
    )
    return executors, log


def _template(template_id, url):
    return MessageTemplate(
        id=template_id,
        crawler_version_id="version-1",
        action="GET",
        url=url,
        body=None,
        headers={},
        created_at=NOW,
        updated_at=NOW,
    )


def _selector(template_id, title, parent=None, selector_type="value"):
    return MessageSelector(
        id=f"{template_id}-{title}",
        message_template_id=template_id,
        parent_selector_id=parent,
        path="//x",
        type=selector_type,
        target="__text",
        created_at=NOW,
        updated_at=NOW,
        title=title,
    )


def _aid(template_id, render_mode="none", **settings):
    return MessageAid(
        id=f"aid-{template_id}",
        message_template_id=template_id,
        render_mode=render_mode,
        created_at=NOW,
        updated_at=NOW,
        **settings,
    )


def _plan(
    templates,
    selectors,
    aids=None,
    context=None,
    sharing=True,
    fields=None,
    rate_limits=None,
):
    return ExecutionPlan(
        execution=CrawlerExecution(
            id="execution-1",
            crawler_id="crawler-1",
            crawler_version_id="version-1",
            status="running",
            parsing_status="pending",
            queue="discovery",
            started_at=NOW,
            finished_at=None,
            created_at=NOW,
            updated_at=NOW,
        ),
        crawler=Crawler(
            id="crawler-1",
            user_id="user-1",
            title="Test",
            source_id="source-1",
            dataset_id="dataset-1",
            fields=fields or ["item_id", "name"],
            schedule=None,
            created_at=NOW,
            updated_at=NOW,
        ),
        version=CrawlerVersion(
            id="version-1",
            crawler_id="crawler-1",
            user_id="user-1",
            status="published",
            message_template_root_id=templates[0].id,
            published_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            is_host_session_sharing_enabled=sharing,
        ),
        dataset=Dataset(
            id="dataset-1",
            name="venues",
            fields=[
                DatasetField(name="item_id", is_required=True, is_unique=True),
                DatasetField(name="name", is_required=True),
                DatasetField(name="rating", type="float"),
            ],
            created_at=NOW,
            updated_at=NOW,
        ),
        ordered_templates=templates,
        selectors_by_template_id=selectors,
        aids_by_template_id=aids or {},
        proxies_by_id={},
        context=context or {},
        rate_limits_by_id=rate_limits or {},
    )


def _result(rows=None, array_titles=(), cookies=None, headers=None):
    return DispatchResult(
        harvest=Harvest(rows=rows or [{}], array_titles=frozenset(array_titles)),
        status_code=200,
        session=SessionState(cookies=cookies or {}, headers=headers or {}),
    )


@pytest.mark.anyio
async def test_harvested_lists_fan_out_the_dependent_template():
    search = _template("search", "https://api.example.com/search")
    detail = _template("detail", "https://example.com/place/{{place_id}}")
    executors, log = _executors(
        {
            "https://api.example.com/search": _result(
                [{"place_id": "p1"}, {"place_id": "p2"}], {"place_id"}
            ),
            "https://example.com/place/p1": _result([{"name": "One"}]),
            "https://example.com/place/p2": _result([{"name": "Two"}]),
        }
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [search, detail],
            {"search": [_selector("search", "place_id")], "detail": []},
            aids={"detail": _aid("detail", "stealth")},
        ),
    )

    assert [
        ("httpx", "https://api.example.com/search"),
        ("stealth", "https://example.com/place/p1"),
        ("stealth", "https://example.com/place/p2"),
    ] == [(name, request.rendered.url) for name, request in log]
    assert ["p1", "p2"] == outcome.context["place_id[]"]
    assert "name" not in outcome.context
    assert 3 == outcome.request_count
    assert None is outcome.failure


@pytest.mark.anyio
async def test_the_session_flows_between_engines_for_the_same_host():
    first = _template("first", "https://example.com/a")
    second = _template("second", "https://example.com/b")
    other = _template("other", "https://other.com/c")
    executors, log = _executors(
        {
            "https://example.com/a": _result(
                cookies={"sid": "1"}, headers={"user-agent": "Chrome/140"}
            ),
            "https://example.com/b": _result(cookies={"lang": "ca"}),
            "https://other.com/c": _result(),
        }
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [first, second, other],
            {},
            aids={"first": _aid("first", "playwright")},
        ),
    )

    [(_, first_request), (_, second_request), (_, other_request)] = log
    assert None is first_request.session
    assert first_request.is_host_session_sharing_enabled
    assert {"sid": "1"} == second_request.session.cookies
    assert {"user-agent": "Chrome/140"} == second_request.session.headers
    assert second_request.is_host_session_sharing_enabled
    assert None is other_request.session
    assert other_request.is_host_session_sharing_enabled
    assert {"sid": "1", "lang": "ca"} == outcome.sessions["example.com"].cookies


@pytest.mark.anyio
async def test_nothing_is_shared_when_sharing_is_off():
    first = _template("first", "https://example.com/a")
    second = _template("second", "https://example.com/b")
    executors, log = _executors(
        {
            "https://example.com/a": _result(cookies={"sid": "1"}),
            "https://example.com/b": _result(),
        }
    )

    await crawler_run_service.execute_plan(
        executors, FakeRateLimiter(), _plan([first, second], {}, sharing=False)
    )

    assert [None, None] == [request.session for _name, request in log]
    assert not any(request.is_host_session_sharing_enabled for _name, request in log)


@pytest.mark.anyio
async def test_a_request_failing_for_good_stops_the_run():
    search = _template("search", "https://example.com/search")
    fan_out = _template("fan", "https://example.com/{{page}}")
    after = _template("after", "https://example.com/after")
    executors, log = _executors(
        {
            "https://example.com/search": _result([{"token": "t"}]),
            "https://example.com/1": _result([{"item_id": "a", "name": "A"}]),
            "https://example.com/2": ExternalServiceException("Request failed: 404"),
            "https://example.com/3": _result(),
            "https://example.com/after": _result(),
        }
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [search, fan_out, after],
            {
                "search": [_selector("search", "token")],
                "fan": [_selector("fan", "item_id"), _selector("fan", "name")],
            },
            context={"page[]": [1, 2, 3]},
        ),
    )

    assert [
        "https://example.com/search",
        "https://example.com/1",
        "https://example.com/2",
    ] == _urls(log)
    assert (3, 1) == (outcome.request_count, outcome.error_count)
    assert "Request failed: 404" == outcome.failure
    assert "t" == outcome.context["token"]
    assert [{"item_id": "a", "name": "A"}] == outcome.dataset_rows


@pytest.mark.anyio
async def test_a_run_where_every_request_fails_is_a_failure():
    only = _template("only", "https://example.com/a")
    executors, _log = _executors(
        {"https://example.com/a": ExternalServiceException("Request failed: 503")}
    )

    outcome = await crawler_run_service.execute_plan(
        executors, FakeRateLimiter(), _plan([only], {})
    )

    assert "Request failed: 503" == outcome.failure


@pytest.mark.anyio
async def test_a_missing_placeholder_stops_the_run():
    first = _template("first", "https://example.com/{{nowhere}}")
    executors, log = _executors({})

    outcome = await crawler_run_service.execute_plan(
        executors, FakeRateLimiter(), _plan([first], {})
    )

    assert [] == log
    assert "Required placeholder is missing: nowhere" == outcome.failure


@pytest.mark.anyio
async def test_crawler_fields_become_dataset_rows_all_kept_for_validation():
    detail = _template("detail", "https://example.com/place/{{place_id}}")
    executors, _log = _executors(
        {
            "https://example.com/place/p1": _result(
                [{"item_id": "p1", "name": "One", "rating": 4.5}]
            ),
            "https://example.com/place/p2": _result([{"item_id": "p2"}]),
        }
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [detail],
            {"detail": [_selector("detail", "item_id"), _selector("detail", "name")]},
            context={"place_id[]": ["p1", "p2"]},
            fields=["item_id", "name"],
        ),
    )

    assert [{"item_id": "p1", "name": "One"}, {"item_id": "p2", "name": None}] == (
        outcome.dataset_rows
    )


@pytest.mark.anyio
async def test_a_first_harvest_replaces_the_inherited_list():
    search = _template("search", "https://api.example.com/search")
    executors, _log = _executors(
        {"https://api.example.com/search": _result([{"place_id": "new"}], {"place_id"})}
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [search],
            {"search": [_selector("search", "place_id")]},
            context={"place_id[]": ["old"]},
        ),
    )

    assert ["new"] == outcome.context["place_id[]"]


@pytest.mark.anyio
async def test_a_template_without_field_selectors_adds_no_rows():
    search = _template("search", "https://api.example.com/search")
    executors, _log = _executors(
        {"https://api.example.com/search": _result([{"place_id": "p1"}])}
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan([search], {"search": [_selector("search", "place_id")]}),
    )

    assert [] == outcome.dataset_rows


def _urls(log):
    return [request.rendered.url for _engine, request in log]


@pytest.mark.anyio
async def test_a_template_repeats_per_search_while_its_token_changes():
    search = _template(
        "search", "https://api.example.com/?q={{q}}&page={{next_page_token}}"
    )
    executors, log = _executors(
        {
            "https://api.example.com/?q=a&page=": _result(
                [{"next_page_token": "a2", "item_id": "a-1", "name": "A1"}]
            ),
            "https://api.example.com/?q=a&page=a2": _result(
                [{"next_page_token": "a3", "item_id": "a-2", "name": "A2"}]
            ),
            "https://api.example.com/?q=a&page=a3": _result(
                [{"item_id": "a-3", "name": "A3"}]
            ),
            "https://api.example.com/?q=b&page=": _result(
                [{"item_id": "b-1", "name": "B1"}]
            ),
        }
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [search],
            {
                "search": [
                    _selector("search", "next_page_token"),
                    _selector("search", "item_id"),
                    _selector("search", "name"),
                ]
            },
            context={"q[]": ["a", "b"], "next_page_token": "stale-from-last-run"},
        ),
    )

    assert [
        "https://api.example.com/?q=a&page=",
        "https://api.example.com/?q=a&page=a2",
        "https://api.example.com/?q=a&page=a3",
        "https://api.example.com/?q=b&page=",
    ] == _urls(log)
    assert ["a-1", "a-2", "a-3", "b-1"] == [
        row["item_id"] for row in outcome.dataset_rows
    ]
    assert None is outcome.failure


@pytest.mark.anyio
async def test_a_token_that_comes_back_unchanged_stops_the_repeat():
    search = _template("search", "https://api.example.com/?page={{cursor}}")
    executors, log = _executors(
        {
            "https://api.example.com/?page=": _result([{"cursor": "c1"}]),
            "https://api.example.com/?page=c1": _result([{"cursor": "c1"}]),
        }
    )

    await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan([search], {"search": [_selector("search", "cursor")]}),
    )

    assert [
        "https://api.example.com/?page=",
        "https://api.example.com/?page=c1",
    ] == _urls(log)


@pytest.mark.anyio
async def test_a_template_follows_the_list_elements_it_harvests_once_each():
    page = _template("page", "https://site.example.com{{path}}")
    links = _selector("page", "links", selector_type="iterator")
    executors, log = _executors(
        {
            "https://site.example.com/": _result(
                [{"path": "/a"}, {"path": "/b"}], {"path"}
            ),
            "https://site.example.com/a": _result(
                [{"path": "/b"}, {"path": "/c"}], {"path"}
            ),
            "https://site.example.com/b": _result(),
            "https://site.example.com/c": _result([{"path": "/"}], {"path"}),
        }
    )

    await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [page],
            {"page": [links, _selector("page", "path", parent=links.id)]},
            context={"path[]": ["/"]},
        ),
    )

    assert [
        "https://site.example.com/",
        "https://site.example.com/a",
        "https://site.example.com/b",
        "https://site.example.com/c",
    ] == _urls(log)


@pytest.fixture
def waits(monkeypatch):
    """Record the run's waits between retries instead of sleeping."""
    recorded = []

    async def record(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(crawler_run_service, "sleep", record)
    return recorded


def _failed(code):
    return RequestFailedException(f"Request failed: {code}", failure_code=code)


@pytest.mark.anyio
async def test_a_retry_code_is_retried_and_a_later_success_counts(waits):
    page = _template("page", "https://example.com/")
    executors, log = _executors(
        {
            "https://example.com/": [
                _failed("503"),
                _failed("503"),
                _result([{"name": "x"}]),
            ]
        }
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan([page], {"page": [_selector("page", "name")]}),
    )

    assert 3 == len(log)
    assert (1, 0, 2) == (
        outcome.request_count,
        outcome.error_count,
        outcome.retry_count,
    )
    assert [1.0, 2.0] == waits
    assert None is outcome.failure


@pytest.mark.anyio
async def test_a_request_fails_only_once_its_retries_are_used_up(waits):
    page = _template("page", "https://example.com/")
    executors, log = _executors({"https://example.com/": [_failed("429")] * 3})

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [page],
            {"page": [_selector("page", "name")]},
            aids={"page": _aid("page", max_retry_attempts=2)},
        ),
    )

    assert 3 == len(log)
    assert (1, 1, 2) == (
        outcome.request_count,
        outcome.error_count,
        outcome.retry_count,
    )
    assert "Request failed: 429" == outcome.failure


@pytest.mark.anyio
async def test_a_code_outside_the_retry_codes_fails_at_once(waits):
    page = _template("page", "https://example.com/")
    executors, log = _executors({"https://example.com/": [_failed("404")]})

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan([page], {"page": [_selector("page", "name")]}),
    )

    assert 1 == len(log)
    assert (1, 1, 0) == (
        outcome.request_count,
        outcome.error_count,
        outcome.retry_count,
    )
    assert [] == waits


@pytest.mark.anyio
async def test_a_timeout_is_retried_when_listed(waits):
    page = _template("page", "https://example.com/")
    executors, log = _executors(
        {"https://example.com/": [_failed("timeout"), _result([{"name": "x"}])]}
    )

    outcome = await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [page],
            {"page": [_selector("page", "name")]},
            aids={"page": _aid("page", retry_codes=["timeout"])},
        ),
    )

    assert 2 == len(log)
    assert (0, 1) == (outcome.error_count, outcome.retry_count)


@pytest.mark.anyio
async def test_a_templates_success_codes_reach_the_engine():
    page = _template("page", "https://example.com/missing.ico")
    executors, log = _executors({"https://example.com/missing.ico": _result()})

    await crawler_run_service.execute_plan(
        executors,
        FakeRateLimiter(),
        _plan(
            [page],
            {"page": [_selector("page", "name")]},
            aids={"page": _aid("page", success_codes=["404"])},
        ),
    )

    [(_engine, request)] = log
    assert ("404",) == request.success_codes


def _rate_limit(rate_limit_id):
    return MessageAidRateLimit(
        id=rate_limit_id,
        rate_limit_string="5/second",
        penalty_step_seconds=10,
        max_penalty_seconds=60,
        decay_after_successes=3,
        decay_step_seconds=5,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.anyio
async def test_a_rate_limited_request_waits_before_every_try(waits):
    page = _template("page", "https://example.com/")
    executors, _log = _executors(
        {"https://example.com/": [_failed("429"), _result([{"name": "x"}])]}
    )
    limiter = FakeRateLimiter()

    await crawler_run_service.execute_plan(
        executors,
        limiter,
        _plan(
            [page],
            {"page": [_selector("page", "name")]},
            aids={"page": _aid("page", rate_limit_id="r1")},
            rate_limits={"r1": _rate_limit("r1")},
        ),
    )

    assert [
        ("acquire", "domain:example.com"),
        ("block", "domain:example.com"),
        ("acquire", "domain:example.com"),
        ("success", "domain:example.com"),
    ] == limiter.calls


@pytest.mark.anyio
async def test_a_failure_outside_the_retry_codes_is_not_a_block():
    page = _template("page", "https://example.com/")
    executors, _log = _executors({"https://example.com/": [_failed("404")]})
    limiter = FakeRateLimiter()

    await crawler_run_service.execute_plan(
        executors,
        limiter,
        _plan(
            [page],
            {"page": [_selector("page", "name")]},
            aids={"page": _aid("page", rate_limit_id="r1")},
            rate_limits={"r1": _rate_limit("r1")},
        ),
    )

    assert [("acquire", "domain:example.com")] == limiter.calls


@pytest.mark.anyio
async def test_a_template_without_a_rate_limit_never_waits():
    page = _template("page", "https://example.com/")
    executors, _log = _executors({"https://example.com/": _result()})
    limiter = FakeRateLimiter()

    await crawler_run_service.execute_plan(
        executors, limiter, _plan([page], {"page": [_selector("page", "name")]})
    )

    assert [] == limiter.calls
