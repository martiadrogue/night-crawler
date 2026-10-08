import logging

from celery.signals import beat_init, worker_process_init, worker_process_shutdown
from celery.signals import setup_logging as celery_setup_logging
from night_crawler import celery as celery_module
from night_crawler.celery import app
from night_crawler.core.logging import JsonFormatter


def test_worker_logging_is_configured_by_the_application():
    logging.getLogger().handlers.clear()

    celery_setup_logging.send(sender=None, loglevel="INFO")

    handlers = logging.getLogger().handlers
    assert 1 == len(handlers)
    assert isinstance(handlers[0].formatter, JsonFormatter)


def test_workers_send_task_events_for_the_exporter():
    assert app.conf.worker_send_task_events
    assert app.conf.task_send_sent_event


def test_each_celery_process_sets_up_its_own_telemetry(monkeypatch):
    started = []
    monkeypatch.setattr(celery_module, "setup_telemetry", started.append)

    worker_process_init.send(sender=None)
    beat_init.send(sender=None)

    assert ["night-crawler-worker", "night-crawler-beat"] == started


def test_worker_processes_flush_telemetry_on_shutdown(monkeypatch):
    stopped = []
    monkeypatch.setattr(celery_module, "shutdown_telemetry", lambda: stopped.append(1))

    worker_process_shutdown.send(sender=None, pid=1, exitcode=0)

    assert [1] == stopped
