"""Request executor decorator adding OpenTelemetry metrics and spans."""

from time import perf_counter
from urllib.parse import urlsplit

from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.ports.request_executor import (
    AbstractRequestExecutor,
    DispatchRequest,
    DispatchResult,
)
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, StatusCode, Tracer

# Crawl requests take from tens of milliseconds (httpx) to tens of
# seconds (a browser page with clicks).
DURATION_BUCKETS_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)


class OpenTelemetryRequestExecutor(AbstractRequestExecutor):
    """Measures and traces every try of a wrapped executor.

    Each `execute` (retries included, since the run service retries by
    calling it again) is one `crawler request` span and one sample of
    `crawler_requests_total` / `crawler_request_duration_seconds`,
    labelled by `engine`, `host`, and `code`: the response status, the
    failure code (`"429"`, `"timeout"`), or `"error"` for a failure
    without one. Never by URL: a fan-out has one URL per element.
    """

    def __init__(
        self,
        executor: AbstractRequestExecutor,
        engine: str,
        meter: Meter,
        tracer: Tracer,
    ) -> None:
        """Wrap `executor`, the one used for render mode `engine`."""
        self._executor = executor
        self._engine = engine
        self._tracer = tracer
        self._requests = meter.create_counter(
            "crawler.requests", description="Crawl request tries."
        )
        self._duration = meter.create_histogram(
            "crawler.request.duration",
            unit="s",
            description="Time to send and harvest one try.",
            explicit_bucket_boundaries_advisory=DURATION_BUCKETS_SECONDS,
        )

    async def execute(self, request: DispatchRequest) -> DispatchResult:
        """Send the request through the wrapped executor, measured.

        Raises:
            RequestFailedException: as the wrapped executor does.
            ExternalServiceException: as the wrapped executor does.
        """
        host = urlsplit(request.rendered.url).hostname or ""
        started = perf_counter()
        with self._tracer.start_as_current_span(
            "crawler request",
            attributes={
                "http.request.method": request.rendered.action,
                "url.full": request.rendered.url,
                "server.address": host,
                "night_crawler.engine": self._engine,
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                result = await self._executor.execute(request)
            except ExternalServiceException as exception:
                code = _mark_failed(span, exception)
                self._record(host, code, started)
                raise
            if None is not result.status_code:
                span.set_attribute("http.response.status_code", result.status_code)
            self._record(host, str(result.status_code or "ok"), started)
            return result

    async def aclose(self) -> None:
        """Release the wrapped executor's resources."""
        await self._executor.aclose()

    def _record(self, host: str, code: str, started: float) -> None:
        """Count one try and its duration."""
        labels = {"engine": self._engine, "host": host, "code": code}
        self._requests.add(1, labels)
        self._duration.record(perf_counter() - started, labels)


def _mark_failed(span: Span, exception: ExternalServiceException) -> str:
    """Mark the span failed and return the failure's metric code."""
    code = getattr(exception, "failure_code", None) or "error"
    span.set_attribute("night_crawler.failure_code", code)
    span.record_exception(exception)
    span.set_status(StatusCode.ERROR, exception.message)
    return code
