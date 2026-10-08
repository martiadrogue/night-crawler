from night_crawler.core import telemetry
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider


def test_stays_off_without_an_endpoint(monkeypatch):
    settings = type("Settings", (), {"otel_exporter_otlp_endpoint": ""})()
    monkeypatch.setattr(telemetry, "get_settings", lambda: settings)

    assert not telemetry.setup_telemetry("night-crawler-test")

    assert not isinstance(trace.get_tracer_provider(), TracerProvider)
    assert not isinstance(metrics.get_meter_provider(), MeterProvider)


def test_shutting_down_without_setup_is_harmless():
    telemetry.shutdown_telemetry()


def test_the_api_never_adds_exporters_of_its_own():
    assert not telemetry.API_TELEMETRY["auto_configure"]


def test_the_api_skips_prometheus_scrapes_only():
    exclude = telemetry.API_TELEMETRY["exclude"]

    assert exclude({"type": "http", "path": "/metrics"})
    assert not exclude({"type": "http", "path": "/api/crawlers"})
