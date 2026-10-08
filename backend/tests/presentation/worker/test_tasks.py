import json
import logging
from contextlib import asynccontextmanager

import pytest
from night_crawler.core.logging import JsonFormatter
from night_crawler.presentation.worker import tasks


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


@pytest.mark.anyio
async def test_logs_of_a_run_carry_its_execution_id(monkeypatch, caplog):
    @asynccontextmanager
    async def open_infrastructure():
        yield object()

    async def process_execution(infrastructure, execution_id):
        logging.getLogger("night_crawler.services.example").info("Run step")
        return "succeeded"

    monkeypatch.setattr(tasks, "open_execution_infrastructure", open_infrastructure)
    monkeypatch.setattr(
        tasks.execution_processing_service, "process_execution", process_execution
    )
    caplog.set_level(logging.INFO, logger="night_crawler")
    handler = _ListHandler()
    logger = logging.getLogger("night_crawler.services.example")
    logger.addHandler(handler)
    try:
        assert "succeeded" == await tasks._process_crawler_execution("execution-1")
        logger.info("After the run")
    finally:
        logger.removeHandler(handler)

    assert "execution-1" == handler.lines[0]["execution_id"]
    assert "execution_id" not in handler.lines[1]


@pytest.mark.anyio
async def test_logs_of_a_generation_carry_its_generation_id(monkeypatch):
    @asynccontextmanager
    async def open_infrastructure():
        yield object()

    async def process_generation(infrastructure, generation_id):
        logging.getLogger("night_crawler.services.example").info("Generation step")
        return "succeeded"

    monkeypatch.setattr(
        tasks, "open_instruction_generation_infrastructure", open_infrastructure
    )
    monkeypatch.setattr(
        tasks.instruction_generation_service, "process_generation", process_generation
    )
    handler = _ListHandler()
    logger = logging.getLogger("night_crawler.services.example")
    logger.addHandler(handler)
    try:
        assert "succeeded" == await tasks._generate_crawler_instructions("generation-1")
    finally:
        logger.removeHandler(handler)

    assert "generation-1" == handler.lines[0]["generation_id"]
