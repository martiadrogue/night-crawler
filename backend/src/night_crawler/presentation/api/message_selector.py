"""Routes for Message Selectors."""

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
from night_crawler.schemas.message_selector import (
    MessageSelectorCreate,
    MessageSelectorOut,
    MessageSelectorUpdate,
)
from night_crawler.services import message_selector_service

router = APIRouter(tags=["Message Selectors"])


@router.get(
    "/api/templates/{template_id}/selectors",
    response_model=list[MessageSelectorOut],
)
async def get_selectors(
    template_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[MessageSelectorOut]:
    """List a template's selectors.

    Raises:
        ValidationException: 404 if the template or its Crawler is
            missing.
    """
    return await message_selector_service.get_selectors(
        read_repositories, current_user, template_id
    )


@router.get("/api/selectors/{selector_id}", response_model=MessageSelectorOut)
async def get_selector(
    selector_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageSelectorOut:
    """Get one selector.

    Raises:
        ValidationException: 404 if the selector, template, or Crawler
            is missing.
    """
    return await message_selector_service.get_selector(
        read_repositories, current_user, selector_id
    )


@router.post(
    "/api/templates/{template_id}/selectors",
    response_model=MessageSelectorOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_selector(
    template_id: str,
    selector_input: MessageSelectorCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageSelectorOut:
    """Add a selector to a template.

    Raises:
        ValidationException: 404 if the template, version, or Crawler is
            missing; 400 if the parent is not on the same template; 409
            if the version is archived, or published with a draft
            already open.
    """
    return await message_selector_service.create_selector(
        write_repositories, current_user, template_id, selector_input
    )


@router.patch("/api/selectors/{selector_id}", response_model=MessageSelectorOut)
async def update_selector(
    selector_id: str,
    selector_input: MessageSelectorUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageSelectorOut:
    """Partially update a selector.

    Raises:
        ValidationException: 404 if the selector, version, or Crawler is
            missing; 400 if the parent would form a cycle or `config`
            doesn't match the type; 409 if the version is archived, or
            published with a draft already open.
    """
    return await message_selector_service.update_selector(
        write_repositories, current_user, selector_id, selector_input
    )


@router.delete("/api/selectors/{selector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_selector(
    selector_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> None:
    """Delete a selector and its descendants.

    Raises:
        ValidationException: 404 if the selector, version, or Crawler is
            missing; 409 if the version is archived, or published with a
            draft already open.
    """
    await message_selector_service.delete_selector(
        write_repositories, current_user, selector_id
    )
