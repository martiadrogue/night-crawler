"""Routes for Sources; updates and deletes are admin only."""

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
from night_crawler.schemas.source import SourceCreate, SourceOut, SourceUpdate
from night_crawler.services import source_service

router = APIRouter(prefix="/api/sources", tags=["Sources"])


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    source_input: SourceCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> SourceOut:
    """Create a Source.

    Raises:
        ValidationException: 409 if another Source has this name.
    """
    return await source_service.create_source(write_repositories, source_input)


@router.get("", response_model=list[SourceOut])
async def get_sources(
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[SourceOut]:
    """List every Source, by name."""
    return await source_service.get_sources(read_repositories)


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> SourceOut:
    """Get one Source.

    Raises:
        ValidationException: 404 if the Source is missing.
    """
    return await source_service.get_source(read_repositories, source_id)


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: str,
    source_input: SourceUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> SourceOut:
    """Partially update a Source (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the Source is
            missing; 409 if another Source has the new name.
    """
    return await source_service.update_source(
        write_repositories, source_id, source_input
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> None:
    """Delete a Source no Crawler uses (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the Source is
            missing; 409 while a Crawler is linked to it.
    """
    await source_service.delete_source(write_repositories, source_id)
