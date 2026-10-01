"""Routes for the proxy pool; writes are admin only."""

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
from night_crawler.schemas.message_aid_proxy import (
    MessageAidProxyCreate,
    MessageAidProxyOut,
    MessageAidProxyUpdate,
)
from night_crawler.services import message_aid_proxy_service

router = APIRouter(prefix="/api/proxies", tags=["Message Aid Proxies"])


@router.post("", response_model=MessageAidProxyOut, status_code=status.HTTP_201_CREATED)
async def create_proxy(
    proxy_input: MessageAidProxyCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> MessageAidProxyOut:
    """Add a proxy (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the rate limit
            is missing.
    """
    return await message_aid_proxy_service.create_proxy(write_repositories, proxy_input)


@router.get("", response_model=list[MessageAidProxyOut])
async def get_proxies(
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[MessageAidProxyOut]:
    """List every proxy, without passwords."""
    return await message_aid_proxy_service.get_proxies(read_repositories)


@router.get("/{proxy_id}", response_model=MessageAidProxyOut)
async def get_proxy(
    proxy_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageAidProxyOut:
    """Get one proxy, without its password.

    Raises:
        ValidationException: 404 if the proxy is missing.
    """
    return await message_aid_proxy_service.get_proxy(read_repositories, proxy_id)


@router.patch("/{proxy_id}", response_model=MessageAidProxyOut)
async def update_proxy(
    proxy_id: str,
    proxy_input: MessageAidProxyUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> MessageAidProxyOut:
    """Partially update a proxy (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the proxy or
            rate limit is missing.
    """
    return await message_aid_proxy_service.update_proxy(
        write_repositories, proxy_id, proxy_input
    )


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> None:
    """Delete a proxy; aids using it fall back to none (admin only).

    Raises:
        ValidationException: 403 for non-admins.
    """
    await message_aid_proxy_service.delete_proxy(write_repositories, proxy_id)
