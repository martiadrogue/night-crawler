import json
import logging
import sys

from night_crawler.core.logging import JsonFormatter, bind_execution_id, setup_logging
from opentelemetry.sdk.trace import TracerProvider


def _record(message="Run started: id=%s", args=("run-1",), exc_info=None):
    return logging.LogRecord(
        name="night_crawler.services.example",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=exc_info,
    )


def _format(record):
    return json.loads(JsonFormatter().format(record))


def test_formats_a_record_as_one_json_line():
    line = JsonFormatter().format(_record())

    assert "\n" not in line
    entry = json.loads(line)
    assert "WARNING" == entry["level"]
    assert "night_crawler.services.example" == entry["logger"]
    assert "Run started: id=run-1" == entry["message"]
    assert entry["time"].endswith("Z")


def test_adds_the_bound_execution_id():
    with bind_execution_id("execution-1"):
        entry = _format(_record())

    assert "execution-1" == entry["execution_id"]


def test_omits_the_execution_id_once_unbound():
    with bind_execution_id("execution-1"):
        pass

    assert "execution_id" not in _format(_record())


def test_adds_the_current_trace_and_span():
    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("run") as span:
        entry = _format(_record())

    context = span.get_span_context()
    assert format(context.trace_id, "032x") == entry["trace_id"]
    assert format(context.span_id, "016x") == entry["span_id"]


def test_omits_the_trace_outside_a_span():
    entry = _format(_record())

    assert "trace_id" not in entry
    assert "span_id" not in entry


def test_tags_the_current_span_with_the_execution_id():
    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("run") as span, bind_execution_id("execution-1"):
        pass

    assert "execution-1" == span.attributes["night_crawler.execution_id"]


def test_includes_the_traceback_of_a_logged_exception():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        entry = _format(_record(exc_info=sys.exc_info()))

    assert "RuntimeError: boom" in entry["exception"]


def test_sends_every_logger_to_one_json_console_handler():
    setup_logging()

    handlers = logging.getLogger().handlers
    assert 1 == len(handlers)
    assert isinstance(handlers[0], logging.StreamHandler)
    assert isinstance(handlers[0].formatter, JsonFormatter)
    for name in ("night_crawler", "uvicorn", "uvicorn.access", "celery"):
        assert [] == logging.getLogger(name).handlers
        assert logging.getLogger(name).propagate


def test_logs_debug_in_development_only(monkeypatch):
    settings = type("Settings", (), {"app_env": "development"})()
    monkeypatch.setattr("night_crawler.core.logging.get_settings", lambda: settings)
    setup_logging()
    assert logging.DEBUG == logging.getLogger("night_crawler").level

    settings.app_env = "production"
    setup_logging()
    assert logging.INFO == logging.getLogger("night_crawler").level
