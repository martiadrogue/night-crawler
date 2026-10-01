"""Routes for a template's Message Aid."""

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
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.message_aid import MessageAidCreate, MessageAidOut
from night_crawler.services import message_aid_service

router = APIRouter(tags=["Message Aids"])


@router.get("/api/templates/{template_id}/aid", response_model=MessageAidOut)
async def get_aid(
    template_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageAidOut:
    """Get a template's Message Aid.

    Raises:
        ValidationException: 404 if the template, its Crawler, or the
            aid is missing.
    """
    return await message_aid_service.get_aid(
        read_repositories, current_user, template_id
    )


@router.put("/api/templates/{template_id}/aid", response_model=MessageAidOut)
async def upsert_aid(
    template_id: str,
    aid_input: MessageAidCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageAidOut:
    """Create or replace a template's Message Aid.

    Raises:
        ValidationException: 404 if the template, version, Crawler,
            proxy, or rate limit is missing; 409 if the version is
            archived, or published with a draft already open.
    """
    return await message_aid_service.upsert_aid(
        write_repositories, current_user, template_id, aid_input
    )


@router.delete(
    "/api/templates/{template_id}/aid", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_aid(
    template_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> None:
    """Delete a template's Message Aid.

    Raises:
        ValidationException: 404 if the template, version, or Crawler is
            missing; 409 if the version is archived, or published with a
            draft already open.
    """
    await message_aid_service.delete_aid(write_repositories, current_user, template_id)
