"""Routes for rate-limit rules; updates and deletes are admin only."""

from fastapi import Depends, status
from fastapi.routing import APIRouter
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.presentation.api.dependencies import (
    get_current_user,
    get_read_repositories,
    get_write_repositories,
    require_admin,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.message_aid_rate_limit import (
    MessageAidRateLimitCreate,
    MessageAidRateLimitOut,
    MessageAidRateLimitUpdate,
)
from night_crawler.services import message_aid_rate_limit_service

router = APIRouter(prefix="/api/rate-limits", tags=["Message Aid Rate Limits"])


@router.post(
    "", response_model=MessageAidRateLimitOut, status_code=status.HTTP_201_CREATED
)
async def create_rate_limit(
    rate_limit_input: MessageAidRateLimitCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageAidRateLimitOut:
    """Create a rate-limit rule.

    Raises:
        ValidationException: 400 if the rate string is invalid.
    """
    return await message_aid_rate_limit_service.create_rate_limit(
        write_repositories, rate_limit_input
    )


@router.get("", response_model=list[MessageAidRateLimitOut])
async def get_rate_limits(
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[MessageAidRateLimitOut]:
    """List every rate-limit rule."""
    return await message_aid_rate_limit_service.get_rate_limits(read_repositories)


@router.get("/{rate_limit_id}", response_model=MessageAidRateLimitOut)
async def get_rate_limit(
    rate_limit_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageAidRateLimitOut:
    """Get one rate-limit rule.

    Raises:
        ValidationException: 404 if the rule is missing.
    """
    return await message_aid_rate_limit_service.get_rate_limit(
        read_repositories, rate_limit_id
    )


@router.patch("/{rate_limit_id}", response_model=MessageAidRateLimitOut)
async def update_rate_limit(
    rate_limit_id: str,
    rate_limit_input: MessageAidRateLimitUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> MessageAidRateLimitOut:
    """Partially update a rule (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the rule is
            missing; 400 if the rate string is invalid.
    """
    return await message_aid_rate_limit_service.update_rate_limit(
        write_repositories, rate_limit_id, rate_limit_input
    )


@router.delete("/{rate_limit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate_limit(
    rate_limit_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> None:
    """Delete a rule; aids and proxies lose it (admin only).

    Raises:
        ValidationException: 403 for non-admins.
    """
    await message_aid_rate_limit_service.delete_rate_limit(
        write_repositories, rate_limit_id
    )
