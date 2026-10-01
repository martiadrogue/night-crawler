"""The Composition Root.

The only module that imports concrete `infrastructure/` adapters and
binds them to the domain ports (CONTRIBUTING R1.1.3, R1.2.9), so
swapping a backend means editing only this file. It also owns the
MongoDB client's lifecycle, so `main.py` never imports
`infrastructure/` itself.
"""

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from night_crawler.celery import app as celery_app
from night_crawler.core.config import get_settings
from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.bundles.request_executors import RequestExecutors
from night_crawler.domain.exceptions import ConfigurationException
from night_crawler.domain.ports.auth_attempt_limiter import (
    AbstractAuthAttemptLimiter,
)
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.infrastructure.cache.redis_auth_attempt_limiter import (
    RedisAuthAttemptLimiter,
)
from night_crawler.infrastructure.cache.redis_rate_limiter import RedisRateLimiter
from night_crawler.infrastructure.db.crawler_execution_context_repository import (
    MongoCrawlerExecutionContextRepository,
)
from night_crawler.infrastructure.db.crawler_execution_dataset_repository import (
    MongoCrawlerExecutionDatasetRepository,
)
from night_crawler.infrastructure.db.crawler_execution_repository import (
    MongoCrawlerExecutionRepository,
)
from night_crawler.infrastructure.db.crawler_repository import MongoCrawlerRepository
from night_crawler.infrastructure.db.crawler_version_repository import (
    MongoCrawlerVersionRepository,
)
from night_crawler.infrastructure.db.dataset_repository import MongoDatasetRepository
from night_crawler.infrastructure.db.message_aid_proxy_repository import (
    MongoMessageAidProxyRepository,
)
from night_crawler.infrastructure.db.message_aid_rate_limit_repository import (
    MongoMessageAidRateLimitRepository,
)
from night_crawler.infrastructure.db.message_aid_repository import (
    MongoMessageAidRepository,
)
from night_crawler.infrastructure.db.message_selector_repository import (
    MongoMessageSelectorRepository,
)
from night_crawler.infrastructure.db.message_template_repository import (
    MongoMessageTemplateRepository,
)
from night_crawler.infrastructure.db.read_repositories import MongoReadRepositories
from night_crawler.infrastructure.db.repository_factories import RepositoryFactory
from night_crawler.infrastructure.db.schema import initialize_database
from night_crawler.infrastructure.db.source_repository import MongoSourceRepository
from night_crawler.infrastructure.db.user_repository import MongoUserRepository
from night_crawler.infrastructure.db.write_repositories import MongoWriteRepositories
from night_crawler.infrastructure.external.httpx_request_executor import (
    HttpxRequestExecutor,
)
from night_crawler.infrastructure.external.patchright_request_executor import (
    PatchrightRequestExecutor,
)
from night_crawler.infrastructure.external.playwright_request_executor import (
    PlaywrightRequestExecutor,
)
from night_crawler.infrastructure.storage.local_dataset_export_storage import (
    LocalDatasetExportStorage,
)
from night_crawler.infrastructure.tasks.celery_execution_dispatcher import (
    CeleryExecutionDispatcher,
)
from night_crawler.presentation.api.dependencies import (
    get_auth_attempt_limiter,
    get_execution_dispatcher,
    get_read_repositories,
    get_write_repositories,
)
from night_crawler.services import dataset_service, user_service
from pymongo import AsyncMongoClient

logger = logging.getLogger(__name__)

REPOSITORY_FACTORIES: dict[str, RepositoryFactory] = {
    "users": MongoUserRepository,
    "sources": MongoSourceRepository,
    "datasets": MongoDatasetRepository,
    "crawlers": MongoCrawlerRepository,
    "crawler_versions": MongoCrawlerVersionRepository,
    "message_templates": MongoMessageTemplateRepository,
    "message_selectors": MongoMessageSelectorRepository,
    "message_aids": MongoMessageAidRepository,
    "message_aid_proxies": MongoMessageAidProxyRepository,
    "message_aid_rate_limits": MongoMessageAidRateLimitRepository,
    "crawler_executions": MongoCrawlerExecutionRepository,
    "crawler_execution_contexts": MongoCrawlerExecutionContextRepository,
    "crawler_execution_datasets": MongoCrawlerExecutionDatasetRepository,
}
"""Which adapter backs each repository port of both repository sets.

Write repositories build them per transaction, bound to its session;
read repositories build them without one.
"""

_settings = get_settings()
# The client connects lazily and binds to the event loop of its first
# operation, which in the web process is uvicorn's single loop.
_client: AsyncMongoClient = AsyncMongoClient(_settings.mongo_url, tz_aware=False)
_execution_dispatcher = CeleryExecutionDispatcher(celery_app)
_auth_attempt_limiter = RedisAuthAttemptLimiter(_settings.redis_url)


async def _get_read_repositories() -> AbstractReadRepositories:
    """Return read repositories for one request."""
    return create_read_repositories()


async def _get_write_repositories() -> AsyncGenerator[AbstractWriteRepositories, None]:
    """Yield write repositories whose transaction spans one request."""
    async with create_write_repositories() as write_repositories:
        yield write_repositories


def create_read_repositories() -> AbstractReadRepositories:
    """Return new read repositories, for callers without `Depends`."""
    return MongoReadRepositories(
        _client, _settings.mongo_database, REPOSITORY_FACTORIES
    )


def create_write_repositories() -> AbstractWriteRepositories:
    """Return new write repositories, for callers without `Depends`."""
    return MongoWriteRepositories(
        _client, _settings.mongo_database, REPOSITORY_FACTORIES
    )


def create_execution_dispatcher() -> AbstractExecutionDispatcher:
    """Return the process-wide Celery execution dispatcher."""
    return _execution_dispatcher


async def _get_execution_dispatcher() -> AbstractExecutionDispatcher:
    """Return the execution dispatcher for one request."""
    return _execution_dispatcher


async def _get_auth_attempt_limiter() -> AbstractAuthAttemptLimiter:
    """Return the process-wide auth attempt limiter."""
    return _auth_attempt_limiter


def create_dataset_export_storage() -> AbstractDatasetExportStorage:
    """Return where finished runs export their dataset CSV."""
    return LocalDatasetExportStorage(_settings.dataset_export_dir)


def create_request_executors() -> RequestExecutors:
    """Return fresh request executors for one run."""
    return RequestExecutors(
        httpx=HttpxRequestExecutor(),
        playwright=PlaywrightRequestExecutor(),
        stealth=PatchrightRequestExecutor(),
    )


def create_rate_limiter() -> AbstractRateLimiter:
    """Return a Redis rate limiter for one run.

    Its connection pool is bound to the task's event loop, like the
    MongoDB client, so each task creates and closes its own.
    """
    return RedisRateLimiter(_settings.redis_url)


@asynccontextmanager
async def open_task_repositories() -> AsyncIterator[RepositorySetFactories]:
    """Yield repository factories on a MongoDB client of the task's own.

    Each Celery task runs in a new event loop (`asyncio.run`) and an
    async client is bound to the loop that first uses it, so the web
    process's client can't be shared; this one is closed afterwards.
    """
    client: AsyncMongoClient = AsyncMongoClient(_settings.mongo_url, tz_aware=False)
    try:
        yield RepositorySetFactories(
            open_read=lambda: MongoReadRepositories(
                client, _settings.mongo_database, REPOSITORY_FACTORIES
            ),
            open_write=lambda: MongoWriteRepositories(
                client, _settings.mongo_database, REPOSITORY_FACTORIES
            ),
        )
    finally:
        await client.close()


def configure_dependencies(app: FastAPI) -> None:
    """Override the `presentation/api/dependencies.py` stubs."""
    app.dependency_overrides[get_execution_dispatcher] = _get_execution_dispatcher
    app.dependency_overrides[get_auth_attempt_limiter] = _get_auth_attempt_limiter
    app.dependency_overrides[get_read_repositories] = _get_read_repositories
    app.dependency_overrides[get_write_repositories] = _get_write_repositories
    logger.info("Composition root: infrastructure dependencies wired.")


async def startup_infrastructure() -> None:
    """Check settings, prepare the database, seed admin and datasets.

    Raises:
        ConfigurationException: `JWT_SECRET` is not set; signing tokens
            with a known fallback would let anyone forge one.
    """
    if not _settings.jwt_secret:
        raise ConfigurationException("JWT_SECRET must be set.")

    await initialize_database(_client[_settings.mongo_database])
    async with create_write_repositories() as write_repositories:
        await user_service.seed_admin_user(write_repositories)
        await dataset_service.seed_built_in_datasets(write_repositories)


async def shutdown_infrastructure() -> None:
    """Close database and Redis connection pools."""
    await _auth_attempt_limiter.aclose()
    await _client.close()
