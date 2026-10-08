from unittest.mock import create_autospec

import pytest
from night_crawler.domain.exceptions import RequestFailedException
from night_crawler.domain.model.value_objects import (
    Harvest,
    RenderedRequest,
    SessionState,
)
from night_crawler.domain.ports.request_executor import (
    AbstractRequestExecutor,
    DispatchRequest,
    DispatchResult,
)
from night_crawler.infrastructure.telemetry.open_telemetry_request_executor import (
    OpenTelemetryRequestExecutor,
)
from opentelemetry.trace import StatusCode

REQUEST = DispatchRequest(
    rendered=RenderedRequest(
        action="GET",
        url="https://example.com/places?page=2",
        body=None,
        headers={},
    ),
    selectors=[],
    session=None,
    timeout_seconds=10,
)


def _executor(meter, tracer, *, result=None, error=None):
    inner = create_autospec(AbstractRequestExecutor, instance=True)
    inner.execute.return_value = result
    inner.execute.side_effect = error
    return inner, OpenTelemetryRequestExecutor(inner, "playwright", meter, tracer)


def _result(status_code=200):
    return DispatchResult(
        harvest=Harvest(rows=[]), status_code=status_code, session=SessionState()
    )


@pytest.mark.anyio
async def test_counts_a_success_by_engine_host_and_status(meter, tracer, read_points):
    inner, executor = _executor(meter, tracer, result=_result())

    assert _result() == await executor.execute(REQUEST)

    inner.execute.assert_awaited_once_with(REQUEST)
    [(attributes, point)] = read_points("crawler.requests")
    assert {"engine": "playwright", "host": "example.com", "code": "200"} == (
        attributes
    )
    assert 1 == point.value
    [(attributes, point)] = read_points("crawler.request.duration")
    assert "200" == attributes["code"]
    assert 1 == point.count


@pytest.mark.anyio
async def test_traces_each_request(meter, tracer, span_exporter):
    _, executor = _executor(meter, tracer, result=_result())

    await executor.execute(REQUEST)

    [span] = span_exporter.get_finished_spans()
    assert "crawler request" == span.name
    assert "GET" == span.attributes["http.request.method"]
    assert "https://example.com/places?page=2" == span.attributes["url.full"]
    assert "example.com" == span.attributes["server.address"]
    assert "playwright" == span.attributes["night_crawler.engine"]
    assert 200 == span.attributes["http.response.status_code"]


@pytest.mark.anyio
async def test_counts_and_reraises_a_failure_with_its_code(
    meter, tracer, read_points, span_exporter
):
    failure = RequestFailedException("Too many requests", failure_code="429")
    _, executor = _executor(meter, tracer, error=failure)

    with pytest.raises(RequestFailedException) as raised:
        await executor.execute(REQUEST)

    assert failure is raised.value
    [(attributes, _)] = read_points("crawler.requests")
    assert "429" == attributes["code"]
    [span] = span_exporter.get_finished_spans()
    assert StatusCode.ERROR == span.status.status_code
    assert "429" == span.attributes["night_crawler.failure_code"]


@pytest.mark.anyio
async def test_a_failure_without_a_code_counts_as_error(meter, tracer, read_points):
    _, executor = _executor(
        meter, tracer, error=RequestFailedException("Connection dropped")
    )

    with pytest.raises(RequestFailedException):
        await executor.execute(REQUEST)

    [(attributes, _)] = read_points("crawler.requests")
    assert "error" == attributes["code"]


@pytest.mark.anyio
async def test_closes_the_wrapped_executor(meter, tracer):
    inner, executor = _executor(meter, tracer)

    await executor.aclose()

    inner.aclose.assert_awaited_once_with()
