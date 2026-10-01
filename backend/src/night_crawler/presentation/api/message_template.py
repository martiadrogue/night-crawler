"""Routes for Message Templates."""

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
from night_crawler.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateOut,
    MessageTemplateUpdate,
)
from night_crawler.services import message_template_service

router = APIRouter(tags=["Message Templates"])


@router.get(
    "/api/crawler-versions/{version_id}/templates",
    response_model=list[MessageTemplateOut],
)
async def get_templates(
    version_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[MessageTemplateOut]:
    """List a version's templates.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing.
    """
    return await message_template_service.get_templates(
        read_repositories, current_user, version_id
    )


@router.get("/api/templates/{template_id}", response_model=MessageTemplateOut)
async def get_template(
    template_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageTemplateOut:
    """Get one template.

    Raises:
        ValidationException: 404 if the template or its Crawler is
            missing.
    """
    return await message_template_service.get_template(
        read_repositories, current_user, template_id
    )


@router.post(
    "/api/crawler-versions/{version_id}/templates",
    response_model=MessageTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    version_id: str,
    template_input: MessageTemplateCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageTemplateOut:
    """Add a template to a version.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing; 409 if it is archived, or published with a draft
            already open.
    """
    return await message_template_service.create_template(
        write_repositories, current_user, version_id, template_input
    )


@router.patch("/api/templates/{template_id}", response_model=MessageTemplateOut)
async def update_template(
    template_id: str,
    template_input: MessageTemplateUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> MessageTemplateOut:
    """Partially update a template.

    Raises:
        ValidationException: 404 if the template, version, or Crawler is
            missing; 409 if the version is archived, or published with a
            draft already open.
    """
    return await message_template_service.update_template(
        write_repositories, current_user, template_id, template_input
    )


@router.delete("/api/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> None:
    """Delete a non-root template with its selectors and aid.

    Raises:
        ValidationException: 404 if the template, version, or Crawler is
            missing; 409 if it is the root, or the version is archived,
            or published with a draft already open.
    """
    await message_template_service.delete_template(
        write_repositories, current_user, template_id
    )
