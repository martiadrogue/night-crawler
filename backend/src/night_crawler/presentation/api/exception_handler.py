"""The single handler turning `AppException` into a JSON response."""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from night_crawler.domain.exceptions import AppException

logger = logging.getLogger(__name__)


async def app_exception_handler(request: Request, exception: Exception) -> JSONResponse:
    """Return `{"message": ...}` with the exception's HTTP status."""
    if not isinstance(exception, AppException):
        logger.error(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path,
            exc_info=exception,
        )
        return JSONResponse(
            status_code=500,
            content={"message": "Internal Server Error"},
        )

    return JSONResponse(
        status_code=exception.status_code,
        content={"message": exception.message},
    )
