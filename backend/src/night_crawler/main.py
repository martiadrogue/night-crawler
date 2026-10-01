"""The FastAPI application and its dev-only instrumentation."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from night_crawler.core.config import get_settings
from night_crawler.core.di import (
    configure_dependencies,
    shutdown_infrastructure,
    startup_infrastructure,
)
from night_crawler.core.logging import setup_logging
from night_crawler.domain.exceptions import AppException
from night_crawler.presentation.api.auth import router as auth_router
from night_crawler.presentation.api.crawler import router as crawler_router
from night_crawler.presentation.api.crawler_context import (
    router as crawler_context_router,
)
from night_crawler.presentation.api.crawler_execution import (
    router as crawler_execution_router,
)
from night_crawler.presentation.api.crawler_version import (
    router as crawler_version_router,
)
from night_crawler.presentation.api.dataset import router as dataset_router
from night_crawler.presentation.api.exception_handler import app_exception_handler
from night_crawler.presentation.api.message_aid import router as message_aid_router
from night_crawler.presentation.api.message_aid_proxy import (
    router as message_aid_proxy_router,
)
from night_crawler.presentation.api.message_aid_rate_limit import (
    router as message_aid_rate_limit_router,
)
from night_crawler.presentation.api.message_selector import (
    router as message_selector_router,
)
from night_crawler.presentation.api.message_template import (
    router as message_template_router,
)
from night_crawler.presentation.api.root import router as root_router
from night_crawler.presentation.api.source import router as source_router
from night_crawler.presentation.api.user import router as user_router

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start infrastructure on startup and release it on shutdown."""
    await startup_infrastructure()
    yield
    await shutdown_infrastructure()


app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
    docs_url=None if "production" == settings.app_env else "/docs",
    redoc_url=None if "production" == settings.app_env else "/redoc",
    openapi_url=None if "production" == settings.app_env else "/openapi.json",
    root_path=settings.root_path,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.cors_allow_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def configure_app():
    """Build the app with its routers, handlers, and dependencies."""
    setup_logging()
    setup_metrics()

    configure_dependencies(app)
    app.add_exception_handler(AppException, app_exception_handler)
    for router in (
        root_router,
        auth_router,
        user_router,
        source_router,
        dataset_router,
        crawler_router,
        crawler_version_router,
        message_template_router,
        message_selector_router,
        message_aid_router,
        message_aid_proxy_router,
        message_aid_rate_limit_router,
        crawler_execution_router,
        crawler_context_router,
    ):
        app.include_router(router)

    logger.info("Night Crawler API routes configured.")


def setup_metrics():
    """Expose Prometheus metrics (development only).

    The instrumentator is a dev-only dependency, so it is imported here;
    the production image never installs it.
    """
    if "development" == settings.app_env:
        from prometheus_fastapi_instrumentator import Instrumentator

        logger.info("Prometheus instrumentation enabled (Development Mode)")
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")


configure_app()
