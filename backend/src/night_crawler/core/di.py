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
from functools import lru_cache

from browser_use import ChatGoogle
from browser_use.llm.base import BaseChatModel
from fastapi import FastAPI
from night_crawler.celery import app as celery_app
from night_crawler.core.config import get_settings
from night_crawler.core.telemetry import get_meter, get_tracer
from night_crawler.domain.bundles.execution_infrastructure import (
    ExecutionInfrastructure,
)
from night_crawler.domain.bundles.instruction_generation_infrastructure import (
    InstructionGenerationInfrastructure,
)
from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.bundles.request_executors import RequestExecutors
from night_crawler.domain.exceptions import ConfigurationException
from night_crawler.domain.ports.browser_agent_recorder import (
    AbstractBrowserAgentRecorder,
)
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.execution_metrics import AbstractExecutionMetrics
from night_crawler.domain.ports.instruction_generation_dispatcher import (
    AbstractInstructionGenerationDispatcher,
)
from night_crawler.domain.ports.instruction_synthesizer import (
    AbstractInstructionSynthesizer,
)
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.ports.token_verifier import AbstractTokenVerifier
from night_crawler.domain.ports.user_directory import AbstractUserDirectory
from night_crawler.domain.rules.llm_rate_limits import LlmBudget
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
from night_crawler.infrastructure.db.instruction_generation_repository import (
    MongoInstructionGenerationRepository,
)
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
from night_crawler.infrastructure.db.write_repositories import MongoWriteRepositories
from night_crawler.infrastructure.external.browser_use_agent_recorder import (
    BrowserUseAgentRecorder,
)
from night_crawler.infrastructure.external.gemini_instruction_synthesizer import (
    GeminiInstructionSynthesizer,
)
from night_crawler.infrastructure.external.httpx_request_executor import (
    HttpxRequestExecutor,
)
from night_crawler.infrastructure.external.jwks_token_verifier import (
    JwksTokenVerifier,
)
from night_crawler.infrastructure.external.keycloak_user_directory import (
    KeycloakUserDirectory,
)
from night_crawler.infrastructure.external.patchright_request_executor import (
    PatchrightRequestExecutor,
)
from night_crawler.infrastructure.external.playwright_request_executor import (
    PlaywrightRequestExecutor,
)
from night_crawler.infrastructure.external.rate_limited_gemini_model import (
    RateLimitedGeminiModel,
)
from night_crawler.infrastructure.storage.local_dataset_export_storage import (
    LocalDatasetExportStorage,
)
from night_crawler.infrastructure.tasks.celery_execution_dispatcher import (
    CeleryExecutionDispatcher,
)
from night_crawler.infrastructure.tasks.celery_instruction_generation_dispatcher import (
    CeleryInstructionGenerationDispatcher,
)
from night_crawler.infrastructure.telemetry.open_telemetry_execution_metrics import (
    OpenTelemetryExecutionMetrics,
)
from night_crawler.infrastructure.telemetry.open_telemetry_rate_limiter import (
    OpenTelemetryRateLimiter,
)
from night_crawler.infrastructure.telemetry.open_telemetry_request_executor import (
    OpenTelemetryRequestExecutor,
)
from night_crawler.presentation.api.dependencies import (
    get_dataset_export_storage,
    get_execution_dispatcher,
    get_instruction_generation_dispatcher,
    get_read_repositories,
    get_token_verifier,
    get_user_directory,
    get_write_repositories,
)
from night_crawler.services import dataset_service
from pymongo import AsyncMongoClient

logger = logging.getLogger(__name__)

REPOSITORY_FACTORIES: dict[str, RepositoryFactory] = {
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
    "instruction_generations": MongoInstructionGenerationRepository,
}
"""Which adapter backs each repository port of both repository sets.

Write repositories build them per transaction, bound to its session;
read repositories build them without one.
"""

_settings = get_settings()


@lru_cache
def _get_client() -> AsyncMongoClient:
    """Return the web process's MongoDB client, created on first use.

    Not at import: PyMongo's tracing listener (`setup_telemetry`) only
    reaches clients created after it. The client connects lazily and
    binds to the event loop of its first operation, uvicorn's only one.
    """
    return AsyncMongoClient(_settings.mongo_url, tz_aware=False)


_execution_dispatcher = CeleryExecutionDispatcher(celery_app)
_instruction_generation_dispatcher = CeleryInstructionGenerationDispatcher(celery_app)
_token_verifier = JwksTokenVerifier(
    _settings.oidc_jwks_url, _settings.oidc_issuer, _settings.oidc_audience
)


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
        _get_client(), _settings.mongo_database, REPOSITORY_FACTORIES
    )


def create_write_repositories() -> AbstractWriteRepositories:
    """Return new write repositories, for callers without `Depends`."""
    return MongoWriteRepositories(
        _get_client(), _settings.mongo_database, REPOSITORY_FACTORIES
    )


def create_execution_dispatcher() -> AbstractExecutionDispatcher:
    """Return the process-wide Celery execution dispatcher."""
    return _execution_dispatcher


async def _get_execution_dispatcher() -> AbstractExecutionDispatcher:
    """Return the execution dispatcher for one request."""
    return _execution_dispatcher


async def _get_instruction_generation_dispatcher() -> (
    AbstractInstructionGenerationDispatcher
):
    """Return the AI agents queue dispatcher for one request."""
    return _instruction_generation_dispatcher


def create_user_directory() -> AbstractUserDirectory:
    """Return a Keycloak directory with a connection pool of its own.

    The pool is bound to the event loop that first uses it, so the web
    process keeps one and each worker task opens and closes its own.
    """
    return KeycloakUserDirectory(
        _settings.keycloak_url,
        _settings.keycloak_realm,
        _settings.keycloak_admin_client_id,
        _settings.keycloak_admin_client_secret.get_secret_value(),
    )


_user_directory = create_user_directory()


async def _get_user_directory() -> AbstractUserDirectory:
    """Return the web process's directory, sharing its admin token."""
    return _user_directory


async def _get_token_verifier() -> AbstractTokenVerifier:
    """Return the process-wide verifier, so its key cache is shared."""
    return _token_verifier


def create_dataset_export_storage() -> AbstractDatasetExportStorage:
    """Return where runs' dataset CSVs are stored and read back from."""
    return LocalDatasetExportStorage(_settings.dataset_export_dir)


def create_request_executors() -> RequestExecutors:
    """Return fresh request executors for one run, each measured.

    The wrappers record metrics and spans per try; with telemetry off
    (`core/telemetry.py`) they write to no-op instruments.
    """
    meter, tracer = get_meter(), get_tracer()
    return RequestExecutors(
        httpx=OpenTelemetryRequestExecutor(
            HttpxRequestExecutor(), "httpx", meter, tracer
        ),
        playwright=OpenTelemetryRequestExecutor(
            PlaywrightRequestExecutor(), "playwright", meter, tracer
        ),
        stealth=OpenTelemetryRequestExecutor(
            PatchrightRequestExecutor(), "stealth", meter, tracer
        ),
    )


def create_rate_limiter() -> AbstractRateLimiter:
    """Return a measured Redis rate limiter for one run.

    Its connection pool is bound to the task's event loop, like the
    MongoDB client, so each task creates and closes its own.
    """
    return OpenTelemetryRateLimiter(
        RedisRateLimiter(_settings.redis_url), get_meter(), get_tracer()
    )


def create_execution_metrics() -> AbstractExecutionMetrics:
    """Return where finished runs are recorded for monitoring."""
    return OpenTelemetryExecutionMetrics(get_meter())


def create_gemini_chat_model(rate_limiter: AbstractRateLimiter) -> BaseChatModel:
    """Return the Gemini chat model the AI agents run on, rate-limited.

    The one place it is built, so the browser agent and the instruction
    synthesizer share one Gemini budget: every call waits on
    `rate_limiter`'s `llm:<model>` keys, shared by every worker.
    Gemini's 429s are left to the wrapper, which knows that budget;
    `ChatGoogle` still retries server errors itself.

    Raises:
        ConfigurationException: `GEMINI_API_KEY` is not set.
    """
    api_key = _settings.gemini_api_key.get_secret_value()
    if not api_key:
        raise ConfigurationException("GEMINI_API_KEY must be set.")
    chat_model = ChatGoogle(
        model=_settings.gemini_model,
        api_key=api_key,
        retryable_status_codes=[500, 502, 503, 504],
    )
    return RateLimitedGeminiModel(
        chat_model,
        rate_limiter,
        get_meter(),
        LlmBudget(
            requests_per_minute=_settings.gemini_requests_per_minute,
            requests_per_day=_settings.gemini_requests_per_day,
            tokens_per_minute=_settings.gemini_tokens_per_minute,
        ),
        _settings.gemini_max_retry_attempts,
    )


def create_browser_agent_recorder(
    rate_limiter: AbstractRateLimiter,
) -> AbstractBrowserAgentRecorder:
    """Return the browser agent recorder, for worker tasks only.

    The model is built per run, so a missing key fails a generation
    with its reason instead of the worker. The API process never calls
    this, so it never starts a browser.
    """
    return BrowserUseAgentRecorder(
        lambda: create_gemini_chat_model(rate_limiter),
        max_steps=_settings.agent_max_steps,
        max_pages=_settings.agent_max_pages,
        timeout_seconds=_settings.agent_timeout_seconds,
        response_body_max_bytes=_settings.agent_response_body_max_bytes,
    )


def create_instruction_synthesizer(
    rate_limiter: AbstractRateLimiter,
) -> AbstractInstructionSynthesizer:
    """Return the instruction synthesizer, for worker tasks only.

    Its model comes from `create_gemini_chat_model`, like the
    recorder's, so both share one Gemini budget.
    """
    return GeminiInstructionSynthesizer(
        lambda: create_gemini_chat_model(rate_limiter),
        body_max_bytes=_settings.synthesis_body_max_bytes,
        total_body_max_bytes=_settings.synthesis_total_body_max_bytes,
    )


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


@asynccontextmanager
async def open_execution_infrastructure() -> AsyncIterator[ExecutionInfrastructure]:
    """Yield what one execution run needs, and close it afterwards.

    Executors and the rate limiter pool resources bound to the task's
    event loop, like the task's MongoDB client, so they are created
    here and released when the run ends, however it ends.
    """
    executors = create_request_executors()
    rate_limiter = create_rate_limiter()
    try:
        async with open_task_repositories() as repository_factories:
            yield ExecutionInfrastructure(
                repository_factories=repository_factories,
                executors=executors,
                rate_limiter=rate_limiter,
                export_storage=create_dataset_export_storage(),
                execution_metrics=create_execution_metrics(),
            )
    finally:
        await executors.aclose()
        await rate_limiter.aclose()


@asynccontextmanager
async def open_instruction_generation_infrastructure() -> (
    AsyncIterator[InstructionGenerationInfrastructure]
):
    """Yield what one Instruction Generation needs, closed afterwards.

    Its Gemini calls, the recorder's and the synthesizer's, wait on a
    Redis rate limiter of the task's own (its pool is bound to the
    task's event loop), on keys every worker shares.
    """
    rate_limiter = RedisRateLimiter(_settings.redis_url)
    user_directory = create_user_directory()
    try:
        async with open_task_repositories() as repository_factories:
            yield InstructionGenerationInfrastructure(
                repository_factories=repository_factories,
                user_directory=user_directory,
                recorder=create_browser_agent_recorder(rate_limiter),
                synthesizer=create_instruction_synthesizer(rate_limiter),
                execution_dispatcher=_execution_dispatcher,
                recording_max_bytes=_settings.generation_recording_max_bytes,
                synthesis_max_attempts=_settings.synthesis_max_attempts,
                ignored_hosts=_settings.synthesis_ignored_host_names,
            )
    finally:
        await user_directory.aclose()
        await rate_limiter.aclose()


def configure_dependencies(app: FastAPI) -> None:
    """Override the `presentation/api/dependencies.py` stubs."""
    app.dependency_overrides[get_execution_dispatcher] = _get_execution_dispatcher
    app.dependency_overrides[get_instruction_generation_dispatcher] = (
        _get_instruction_generation_dispatcher
    )
    app.dependency_overrides[get_token_verifier] = _get_token_verifier
    app.dependency_overrides[get_user_directory] = _get_user_directory
    app.dependency_overrides[get_dataset_export_storage] = create_dataset_export_storage
    app.dependency_overrides[get_read_repositories] = _get_read_repositories
    app.dependency_overrides[get_write_repositories] = _get_write_repositories
    logger.info("Composition root: infrastructure dependencies wired.")


async def startup_infrastructure() -> None:
    """Prepare the database and seed the built-in datasets."""
    await initialize_database(_get_client()[_settings.mongo_database])
    async with create_write_repositories() as write_repositories:
        await dataset_service.seed_built_in_datasets(write_repositories)


async def shutdown_infrastructure() -> None:
    """Close the database and Keycloak connection pools."""
    await _user_directory.aclose()
    await _get_client().close()
