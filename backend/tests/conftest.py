import asyncio
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import datetime

import pytest
from night_crawler.core.config import get_settings
from night_crawler.core.di import REPOSITORY_FACTORIES
from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.infrastructure.db.read_repositories import MongoReadRepositories
from night_crawler.infrastructure.db.schema import initialize_database
from night_crawler.infrastructure.db.write_repositories import MongoWriteRepositories
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler import CrawlerCreate, CrawlerOut
from night_crawler.schemas.source import SourceCreate, SourceOut
from night_crawler.services import crawler_service, dataset_service, source_service
from pymongo import AsyncMongoClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def test_database_name() -> Generator[str, None, None]:
    """
    One throwaway MongoDB database per test session, with every index
    and validator in place, dropped at the end (R3.5.4). Creating one
    per test would churn thousands of WiredTiger files.
    """
    database_name = f"night_crawler_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_run_on_database(database_name, initialize_database))
    try:
        yield database_name
    finally:
        asyncio.run(_run_on_database(database_name, _drop_database))


async def _run_on_database(database_name, action) -> None:
    # A client of its own: an async client is bound to the event loop
    # that first uses it, and each test runs on a fresh loop.
    client = AsyncMongoClient(get_settings().mongo_url)
    try:
        await action(client[database_name])
    finally:
        await client.close()


async def _drop_database(database) -> None:
    await database.client.drop_database(database.name)


@pytest.fixture
async def mongo_database(
    test_database_name,
) -> AsyncGenerator[tuple[AsyncMongoClient, str], None]:
    """A client on the test database, emptied before each test."""
    client = AsyncMongoClient(get_settings().mongo_url)
    database = client[test_database_name]
    for collection_name in await database.list_collection_names():
        await database[collection_name].delete_many({})
    try:
        yield client, test_database_name
    finally:
        await client.close()


@pytest.fixture
async def write_repositories(
    mongo_database,
) -> AsyncGenerator[AbstractWriteRepositories, None]:
    """
    Write repositories on the test database. Services commit themselves;
    teardown rolls back, since a failed write inside a transaction makes
    MongoDB abort it and a final commit would then fail.
    """
    client, database_name = mongo_database
    async with MongoWriteRepositories(
        client, database_name, REPOSITORY_FACTORIES
    ) as repositories:
        yield repositories
        await repositories.rollback()


@pytest.fixture
async def read_repositories(mongo_database) -> AbstractReadRepositories:
    """Read repositories on the test database: no transaction."""
    client, database_name = mongo_database
    return MongoReadRepositories(client, database_name, REPOSITORY_FACTORIES)


class RecordingDispatcher(AbstractExecutionDispatcher):
    """Keeps every dispatch instead of enqueuing it."""

    def __init__(self) -> None:
        self.dispatched: list[tuple[str, str]] = []

    async def dispatch(self, execution_id: str, queue: str) -> None:
        self.dispatched.append((execution_id, queue))


@pytest.fixture
def execution_dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


class RecordingExportStorage(AbstractDatasetExportStorage):
    """Keeps every exported CSV, by path, instead of writing files.

    With `is_failing`, every save raises, like a full or read-only disk;
    with `is_move_failing`, only moving to `validated/` does.
    """

    def __init__(self) -> None:
        self.exports: dict[str, str] = {}
        self.is_failing = False
        self.is_move_failing = False

    async def save(self, file_stem: str, csv_content: str) -> str:
        if self.is_failing:
            raise ExternalServiceException("Disk full.")
        path = f"/exports/raw/{file_stem}.csv"
        self.exports[path] = csv_content
        return path

    async def move_to_validated(self, file_stem: str) -> str:
        if self.is_move_failing:
            raise ExternalServiceException("Cannot move.")
        path = f"/exports/validated/{file_stem}.csv"
        self.exports[path] = self.exports.pop(f"/exports/raw/{file_stem}.csv")
        return path


@pytest.fixture
def export_storage() -> RecordingExportStorage:
    return RecordingExportStorage()


@pytest.fixture
async def repository_factories(mongo_database) -> RepositorySetFactories:
    """Open read or write repositories on the test database, like a task."""
    client, database_name = mongo_database
    return RepositorySetFactories(
        open_read=lambda: MongoReadRepositories(
            client, database_name, REPOSITORY_FACTORIES
        ),
        open_write=lambda: MongoWriteRepositories(
            client, database_name, REPOSITORY_FACTORIES
        ),
    )


VENUES_FIELDS = ["item_id", "name", "rating"]


@pytest.fixture
def member() -> UserOut:
    return UserOut(
        id="member-1",
        email="member@example.com",
        role="user",
        created_at=datetime(2026, 1, 1),
    )


@pytest.fixture
def admin() -> UserOut:
    return UserOut(
        id="admin-1",
        email="admin@example.com",
        role="admin",
        created_at=datetime(2026, 1, 1),
    )


@pytest.fixture
async def source(write_repositories) -> SourceOut:
    """A Source every test crawler is linked to by default."""
    return await source_service.create_source(
        write_repositories, SourceCreate(name="Google Maps")
    )


@pytest.fixture
async def dataset_ids(write_repositories) -> dict[str, str]:
    """The built-in datasets, created as at startup, by name."""
    await dataset_service.seed_built_in_datasets(write_repositories)
    datasets = await dataset_service.get_datasets(write_repositories)
    return {dataset.name: dataset.id for dataset in datasets}


@pytest.fixture
def create_crawler(write_repositories, member, source, dataset_ids):
    async def _create(dataset: str = "venues", **overrides) -> CrawlerOut:
        crawler_input = CrawlerCreate(
            **{
                "title": "Andorra venues",
                "source_id": source.id,
                "dataset_id": dataset_ids[dataset],
                "fields": VENUES_FIELDS,
                **overrides,
            }
        )
        return await crawler_service.create_crawler(
            write_repositories, member, crawler_input
        )

    return _create
