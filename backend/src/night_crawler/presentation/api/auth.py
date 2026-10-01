"""Public routes for registering and logging in."""

from fastapi import Depends, Request
from fastapi.routing import APIRouter
from night_crawler.domain.ports.auth_attempt_limiter import (
    AbstractAuthAttemptLimiter,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.presentation.api.dependencies import (
    get_auth_attempt_limiter,
    get_read_repositories,
    get_write_repositories,
)
from night_crawler.schemas.auth import SessionCreate, TokenOut, UserCreate
from night_crawler.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(
    request: Request,
    credentials: UserCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    auth_attempt_limiter: AbstractAuthAttemptLimiter = Depends(
        get_auth_attempt_limiter
    ),
) -> TokenOut:
    """Create a `user` account and return an access token.

    Raises:
        ValidationException: 400 if the email is taken, or 429 when the
            source IP has exceeded its registration limit.
        ExternalServiceException: the attempt counter is unavailable.
    """
    ip_address = request.client.host if request.client else "unknown"
    return await auth_service.register_user(
        write_repositories, auth_attempt_limiter, credentials, ip_address
    )


@router.post("/login", response_model=TokenOut)
async def login(
    request: Request,
    credentials: SessionCreate,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    auth_attempt_limiter: AbstractAuthAttemptLimiter = Depends(
        get_auth_attempt_limiter
    ),
) -> TokenOut:
    """Exchange email and password for an access token.

    Raises:
        ValidationException: 401 if the credentials are wrong, or 429
            when the email or source IP is temporarily locked.
        ExternalServiceException: the attempt counter is unavailable.
    """
    ip_address = request.client.host if request.client else "unknown"
    return await auth_service.authenticate_user(
        read_repositories, auth_attempt_limiter, credentials, ip_address
    )
