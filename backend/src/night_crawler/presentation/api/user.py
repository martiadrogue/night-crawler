"""Admin-only routes for user accounts."""

from fastapi import Depends, Query, status
from fastapi.routing import APIRouter
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.presentation.api.dependencies import (
    get_read_repositories,
    get_write_repositories,
    require_admin,
)
from night_crawler.schemas.auth import UserCreate, UserOut, UsersPageOut, UserUpdate
from night_crawler.services import user_service

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("", response_model=UsersPageOut)
async def get_users(
    limit: int = Query(default=50, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=250),
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    _: UserOut = Depends(require_admin),
) -> UsersPageOut:
    """List users, newest first (admin only).

    Unfiltered, so it paginates: pages of up to 50, at most 300 users
    deep.

    Raises:
        ValidationException: 403 for non-admins.
    """
    return await user_service.get_users(read_repositories, limit=limit, offset=offset)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_input: UserCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> UserOut:
    """Create a `user` account (admin only).

    Raises:
        ValidationException: 403 for non-admins; 400 if the email is
            taken.
    """
    return await user_service.create_user(write_repositories, user_input)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    _: UserOut = Depends(require_admin),
) -> UserOut:
    """Get one user (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the user is
            missing.
    """
    return await user_service.get_user(read_repositories, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    user_input: UserUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> UserOut:
    """Change a user's email, password, or role (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the user is
            missing; 400 if the email is taken or it would demote the
            last admin.
    """
    return await user_service.update_user(write_repositories, user_id, user_input)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> None:
    """Delete a user with their Crawlers and versions (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the user is
            missing; 400 if it is the last admin; 409 if a version they
            own in another Crawler has run.
    """
    await user_service.delete_user(write_repositories, user_id)
