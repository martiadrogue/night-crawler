import pytest
from night_crawler.core.config import get_settings
from pymongo import AsyncMongoClient, monitoring


class _CommandRecorder(monitoring.CommandListener):
    """Keep every command the driver sends."""

    def __init__(self) -> None:
        self.commands: list[dict] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        self.commands.append(dict(event.command))

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass


def _transactional(commands: list[dict]) -> list[str]:
    return [
        next(iter(command))
        for command in commands
        if "txnNumber" in command or False is command.get("autocommit")
    ]


@pytest.mark.anyio
async def test_reads_start_no_transaction_but_writes_do(
    mongo_database, serve_app, act_as, venues_crawler
):
    _client, database_name = mongo_database
    recorder = _CommandRecorder()
    mongo_client = AsyncMongoClient(
        get_settings().mongo_url, event_listeners=[recorder]
    )
    act_as("member")
    try:
        async with serve_app(mongo_client, database_name) as client:
            created = await client.post("/api/crawlers", json=venues_crawler)
            write_commands = _transactional(recorder.commands)
            recorder.commands.clear()

            listed = await client.get("/api/crawlers")
            read_commands = _transactional(recorder.commands)
    finally:
        await mongo_client.close()

    assert 201 == created.status_code
    assert "commitTransaction" in write_commands
    assert 200 == listed.status_code
    assert recorder.commands
    assert [] == read_commands
