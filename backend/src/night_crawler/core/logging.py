"""Logging setup from `logging_config.yaml`: JSON lines on stdout.

Every process (the API, the Celery worker, Celery Beat) logs one JSON
object per line to stdout; Docker keeps the lines and Grafana Alloy
ships them to Loki (docs/ARCHITECTURE.md#observability).
"""

import json
import logging
import logging.config
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

import yaml
from night_crawler.core.config import get_settings
from opentelemetry import trace

# A ContextVar, not mutable module state (R1.4.3): each asyncio task
# and thread sees only the value it bound itself.
_execution_id: ContextVar[str | None] = ContextVar("execution_id", default=None)
_generation_id: ContextVar[str | None] = ContextVar("generation_id", default=None)


@contextmanager
def bind_execution_id(execution_id: str) -> Iterator[None]:
    """Add `execution_id` to every log line written inside the block.

    The current span (the run's Celery task span) gets it too, as
    `night_crawler.execution_id`, so Tempo can find the run's trace.
    """
    trace.get_current_span().set_attribute("night_crawler.execution_id", execution_id)
    token = _execution_id.set(execution_id)
    try:
        yield
    finally:
        _execution_id.reset(token)


@contextmanager
def bind_generation_id(generation_id: str) -> Iterator[None]:
    """Add `generation_id` to every log line written inside the block.

    The current span gets it too, as `night_crawler.generation_id`.
    """
    trace.get_current_span().set_attribute("night_crawler.generation_id", generation_id)
    token = _generation_id.set(generation_id)
    try:
        yield
    finally:
        _generation_id.reset(token)


class JsonFormatter(logging.Formatter):
    """Format a record as one JSON object on a single line.

    Keys: `time` (UTC, ISO 8601), `level`, `logger`, `message`, plus
    `execution_id` inside `bind_execution_id` (`generation_id` inside
    `bind_generation_id`), `trace_id` / `span_id`
    inside a span (Grafana links them to Tempo), and `exception` when
    the record carries a traceback. Newlines stay escaped inside the
    JSON strings, so a traceback never splits the line.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a JSON line."""
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(_get_context_fields())
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def _get_context_fields() -> dict[str, str]:
    """Return the bound `execution_id` and the current span's ids."""
    fields = {}
    execution_id = _execution_id.get()
    if None is not execution_id:
        fields["execution_id"] = execution_id
    generation_id = _generation_id.get()
    if None is not generation_id:
        fields["generation_id"] = generation_id
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        fields["trace_id"] = format(span_context.trace_id, "032x")
        fields["span_id"] = format(span_context.span_id, "016x")
    return fields


def setup_logging() -> None:
    """Configure logging from `logging_config.yaml`.

    Only the application's own loggers go down to `DEBUG` in
    development; libraries stay at the root's `INFO`.
    """
    settings = get_settings()
    log_level = "DEBUG" if "development" == settings.app_env else "INFO"

    with open("logging_config.yaml", "r") as config_file:
        config = yaml.safe_load(config_file)

    config["loggers"]["night_crawler"]["level"] = log_level

    logging.config.dictConfig(config)
