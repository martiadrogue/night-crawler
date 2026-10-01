"""The Celery app: broker, queues, and the Beat schedule."""

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from night_crawler.core.config import get_settings
from night_crawler.domain.model.constants import (
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
    # Each queue needs its own exchange and routing key: bare
    # `Queue(name)`s share one default exchange, and every task would be
    # delivered to every queue.
    task_queues=tuple(
        Queue(name, Exchange(name), routing_key=name)
        for name in (*EXECUTION_QUEUES, IMPORT_QUEUE)
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
