from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import pytest
from night_crawler.core.di import REPOSITORY_FACTORIES
from night_crawler.domain.ports.auth_attempt_limiter import (
    AbstractAuthAttemptLimiter,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.infrastructure.db.read_repositories import MongoReadRepositories
from night_crawler.infrastructure.db.write_repositories import MongoWriteRepositories
from night_crawler.main import app
from night_crawler.presentation.api.dependencies import (
    get_auth_attempt_limiter,
    get_current_user,
    get_execution_dispatcher,
    get_read_repositories,
    get_write_repositories,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.services import dataset_service
from pymongo import AsyncMongoClient

ADMIN = UserOut(
    id="admin-1",
    email="admin@example.com",
    role="admin",
    created_at=datetime(2026, 1, 1),
)
MEMBER = UserOut(
    id="member-1",
    email="member@example.com",
    role="user",
    created_at=datetime(2026, 1, 1),
)
USERS = {"admin": ADMIN, "member": MEMBER}


class RecordingAuthAttemptLimiter(AbstractAuthAttemptLimiter):
    """Keep auth attempt counters isolated to one test client."""

    def __init__(self) -> None:
        self.attempts: dict[str, int] = {}

    async def is_limited(self, key: str, max_attempts: int) -> bool:
        return self.attempts.get(key, 0) >= max_attempts

    async def record_attempt(self, key: str, window_seconds: int) -> None:
        self.attempts[key] = self.attempts.get(key, 0) + 1

    async def clear(self, key: str) -> None:
        self.attempts.pop(key, None)


@asynccontextmanager
async def _serve_app(
    mongo_client: AsyncMongoClient, database_name: str
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    An HTTP client on the real app whose repository sets point at
    `database_name` through `mongo_client`; overrides are restored
    afterwards (R3.5.3).
    """

    async def _get_read_repositories() -> AbstractReadRepositories:
        return MongoReadRepositories(mongo_client, database_name, REPOSITORY_FACTORIES)

    async def _get_write_repositories() -> AsyncGenerator[
        AbstractWriteRepositories, None
    ]:
        async with MongoWriteRepositories(
            mongo_client, database_name, REPOSITORY_FACTORIES
        ) as write_repositories:
            yield write_repositories

    previous_overrides = dict(app.dependency_overrides)
    auth_attempt_limiter = RecordingAuthAttemptLimiter()
    app.dependency_overrides[get_read_repositories] = _get_read_repositories
    app.dependency_overrides[get_write_repositories] = _get_write_repositories
    app.dependency_overrides[get_auth_attempt_limiter] = lambda: auth_attempt_limiter
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


@pytest.fixture
def serve_app():
    """Open an app client on a Mongo client of the test's choosing."""
    return _serve_app


@pytest.fixture
async def client(
    mongo_database, execution_dispatcher
) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with _serve_app(*mongo_database) as http_client:
        app.dependency_overrides[get_execution_dispatcher] = lambda: (
            execution_dispatcher
        )
        yield http_client


@pytest.fixture
def act_as():
    """Authenticate every following request as `admin` or `member`."""

    def _act_as(role: str) -> UserOut:
        user = USERS[role]
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    return _act_as


@pytest.fixture
async def source_id(mongo_database) -> str:
    """A Source stored straight in the test database, for crawlers."""
    client, database_name = mongo_database
    now = datetime(2026, 1, 1)
    await client[database_name]["sources"].insert_one(
        {
            "_id": "source-1",
            "name": "Google Maps",
            "url": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return "source-1"


@pytest.fixture
async def dataset_ids(mongo_database) -> dict[str, str]:
    """The built-in datasets, created in the test database, by name."""
    mongo_client, database_name = mongo_database
    async with MongoWriteRepositories(
        mongo_client, database_name, REPOSITORY_FACTORIES
    ) as write_repositories:
        await dataset_service.seed_built_in_datasets(write_repositories)
        datasets = await dataset_service.get_datasets(write_repositories)
    return {dataset.name: dataset.id for dataset in datasets}


@pytest.fixture
def venues_crawler(source_id, dataset_ids) -> dict:
    return {
        "title": "Andorra venues",
        "source_id": source_id,
        "dataset_id": dataset_ids["venues"],
        "fields": ["item_id", "name"],
    }
