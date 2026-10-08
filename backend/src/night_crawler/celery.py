"""The Celery app: broker, queues, and the Beat schedule."""

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, worker_process_init, worker_process_shutdown
from celery.signals import setup_logging as celery_setup_logging
from kombu import Exchange, Queue

from night_crawler.core.config import get_settings
from night_crawler.core.logging import setup_logging
from night_crawler.core.telemetry import setup_telemetry, shutdown_telemetry
from night_crawler.domain.model.constants import (
    AI_AGENTS_QUEUE,
    DEFAULT_EXECUTION_QUEUE,
    EXECUTION_QUEUES,
    IMPORT_QUEUE,
)

app = Celery(
    "night_crawler",
    broker=get_settings().broker_url,
    include=["night_crawler.presentation.worker.tasks"],
)

app.conf.update(
    timezone="UTC",
    task_track_started=True,
    # A run is acknowledged only once it finishes, so a worker crash
    # hands it to another worker; `start_execution` skips a run that
    # already started.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Task events feed `celery-exporter`'s Prometheus metrics
    # (docs/ARCHITECTURE.md#observability).
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Each queue needs its own exchange and routing key: bare
    # `Queue(name)`s share one default exchange, and every task would be
    # delivered to every queue.
    task_queues=tuple(
        Queue(name, Exchange(name), routing_key=name)
        for name in (*EXECUTION_QUEUES, IMPORT_QUEUE, AI_AGENTS_QUEUE)
    ),
    task_default_queue=DEFAULT_EXECUTION_QUEUE,
    beat_schedule={
        # Every minute: the finest resolution a cron expression has.
        "dispatch-scheduled-crawlers": {
            "task": "night_crawler.tasks.dispatch_scheduled_crawlers",
            "schedule": crontab(minute="*"),
        },
    },
)


@celery_setup_logging.connect
def configure_logging(**_: object) -> None:
    """Log as the API does: JSON lines on stdout.

    A receiver on this signal stops Celery from configuring logging
    itself, so the worker's and Beat's `--loglevel` are ignored.
    """
    setup_logging()


@worker_process_init.connect
def start_worker_telemetry(**_: object) -> None:
    """Set up telemetry in each worker process, after the fork.

    The exporters' background threads don't survive a fork, so the
    parent process never sets them up.
    """
    setup_telemetry("night-crawler-worker")


@worker_process_shutdown.connect
def stop_worker_telemetry(**_: object) -> None:
    """Flush the worker process's last spans and metrics."""
    shutdown_telemetry()


@beat_init.connect
def start_beat_telemetry(**_: object) -> None:
    """Set up telemetry in Celery Beat, which sends scheduled tasks."""
    setup_telemetry("night-crawler-beat")
