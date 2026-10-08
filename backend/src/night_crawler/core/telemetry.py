"""OpenTelemetry setup: traces and metrics pushed over OTLP.

Each process (the API, every Celery worker process, Celery Beat) sets
up its own providers and pushes to Grafana Alloy, which forwards
traces to Tempo and metrics to Prometheus
(docs/ARCHITECTURE.md#observability). Without an endpoint nothing is
set up and the OpenTelemetry API stays a no-op.
"""

from collections.abc import MutableMapping
from typing import Any
from uuid import uuid4

from fastapi.telemetry import TelemetryConfig
from night_crawler.core.config import get_settings
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

METRIC_EXPORT_INTERVAL_MILLISECONDS = 15_000
INSTRUMENTATION_SCOPE = "night_crawler"


def _is_metrics_scrape(scope: MutableMapping[str, Any]) -> bool:
    """Tell whether a request is Prometheus scraping `/metrics`."""
    return "/metrics" == scope.get("path")


API_TELEMETRY: TelemetryConfig = {
    # FastAPI would otherwise add its own OTLP exporter from
    # `OTEL_EXPORTER_OTLP_ENDPOINT` next to `setup_telemetry`'s one,
    # and every API span and metric would be sent twice.
    "auto_configure": False,
    "exclude": _is_metrics_scrape,
}
"""FastAPI's native telemetry settings (`FastAPI(telemetry=...)`).

FastAPI traces each request, with spans for dependency resolution,
the endpoint, and serialization, on the providers `setup_telemetry`
sets; without them its spans and metrics are no-ops.
"""


def setup_telemetry(service_name: str) -> bool:
    """Set this process's tracer and meter providers, if enabled.

    Also instruments Celery (trace context travels with each task),
    httpx, PyMongo, and Redis. Call it once per process, after any
    fork: the exporters' background threads don't survive one.

    Args:
        service_name: `service.name` of this process's telemetry,
            e.g. `night-crawler-worker`; Prometheus shows it as `job`.

    Returns:
        Whether telemetry is on (`OTEL_EXPORTER_OTLP_ENDPOINT` set).
    """
    endpoint = get_settings().otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint:
        return False
    # `service.instance.id` keeps each process's counters a series of
    # their own; without it, worker processes would overwrite each
    # other's totals in Prometheus.
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.instance.id": str(uuid4()),
            "deployment.environment.name": get_settings().app_env,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
                    export_interval_millis=METRIC_EXPORT_INTERVAL_MILLISECONDS,
                )
            ],
        )
    )
    for instrumentor in (
        CeleryInstrumentor(),
        HTTPXClientInstrumentor(),
        PymongoInstrumentor(),
        RedisInstrumentor(),
    ):
        instrumentor.instrument()
    return True


def shutdown_telemetry() -> None:
    """Flush and stop this process's providers, if any were set up.

    Celery ends worker processes without running `atexit` hooks, so
    their last spans and metrics would otherwise be lost.
    """
    for provider in (trace.get_tracer_provider(), metrics.get_meter_provider()):
        if isinstance(provider, TracerProvider | MeterProvider):
            provider.shutdown()


def get_meter() -> metrics.Meter:
    """Return the application's meter (a no-op one when disabled)."""
    return metrics.get_meter(INSTRUMENTATION_SCOPE)


def get_tracer() -> trace.Tracer:
    """Return the application's tracer (a no-op one when disabled)."""
    return trace.get_tracer(INSTRUMENTATION_SCOPE)
