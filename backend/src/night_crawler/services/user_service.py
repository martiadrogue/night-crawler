"""Admin use cases for managing user accounts.

Accounts live in the identity provider (Keycloak); this module only
reaches them through `AbstractUserDirectory`. They are disabled, never
deleted, so every `user_id` stored here keeps pointing at an account.
"""

import logging

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.ports.user_directory import (
    AbstractUserDirectory,
    DirectoryUser,
    DirectoryUserChanges,
)
from night_crawler.domain.rules.pagination import MAX_PAGE_SIZE, resolve_page
from night_crawler.schemas.auth import UserCreate, UserOut, UsersPageOut, UserUpdate

logger = logging.getLogger(__name__)


def _to_out(user: DirectoryUser) -> UserOut:
    """Map a directory account onto its API schema."""
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_enabled=user.is_enabled,
        created_at=user.created_at,
    )


async def get_users(
    user_directory: AbstractUserDirectory,
    limit: int = MAX_PAGE_SIZE,
    offset: int = 0,
) -> UsersPageOut:
    """Return one page of users, ordered by email.

    Fetches one extra user to tell whether more exist, avoiding a count
    query.

    Raises:
        ExternalServiceException: the identity provider failed.
    """
    page_limit, page_offset = resolve_page(False, limit, offset)
    if 0 == page_limit:
        return UsersPageOut(items=[], limit=0, offset=page_offset, has_more=False)

    users = await user_directory.get_all(limit=page_limit + 1, offset=page_offset)
    return UsersPageOut(
        items=[_to_out(user) for user in users[:page_limit]],
        limit=page_limit,
        offset=page_offset,
        has_more=len(users) > page_limit,
    )


async def get_user(user_directory: AbstractUserDirectory, user_id: str) -> UserOut:
    """Return one user, enabled or not.

    Raises:
        ValidationException: the user does not exist (404).
        ExternalServiceException: the identity provider failed.
    """
    return _to_out(await _get_user_or_404(user_directory, user_id))


async def create_user(
    user_directory: AbstractUserDirectory, user_input: UserCreate
) -> UserOut:
    """Create a `user` account with a temporary password.

    The request payload never carries a role, so creating an account
    can't grant privileges; `update_user` is the only way to change it.

    Raises:
        ValidationException: the email is already taken (400).
        ExternalServiceException: the identity provider failed.
    """
    user = await user_directory.create(user_input.email, "user", user_input.password)

    logger.info("User created: id=%s, role=%s", user.id, user.role)
    return _to_out(user)


async def update_user(
    user_directory: AbstractUserDirectory, user_id: str, user_input: UserUpdate
) -> UserOut:
    """Apply a partial update to an account.

    Raises:
        ValidationException: the user does not exist (404), the new
            email is taken (400), or this would demote the last enabled
            admin (400).
        ExternalServiceException: the identity provider failed.
    """
    user = await _get_user_or_404(user_directory, user_id)
    if user_input.role not in (None, user.role):
        await _ensure_not_last_admin(user_directory, user)

    updated_user = await user_directory.update(
        user_id,
        DirectoryUserChanges(
            email=user_input.email,
            role=user_input.role,
            temporary_password=user_input.password,
        ),
    )

    changed_fields = sorted(user_input.model_dump(exclude_none=True))
    logger.info("User updated: id=%s, fields=%s", user_id, changed_fields)
    return _to_out(updated_user)


async def disable_user(user_directory: AbstractUserDirectory, user_id: str) -> None:
    """Disable an account; its Crawlers, versions, and runs stay.

    Raises:
        ValidationException: the user does not exist (404), or it is
            the last enabled admin (400).
        ExternalServiceException: the identity provider failed.
    """
    user = await _get_user_or_404(user_directory, user_id)
    await _ensure_not_last_admin(user_directory, user)

    await user_directory.disable(user_id)

    logger.info("User disabled: id=%s", user_id)


async def _get_user_or_404(
    user_directory: AbstractUserDirectory, user_id: str
) -> DirectoryUser:
    """Return the account.

    Raises:
        ValidationException: it does not exist (404).
    """
    user = await user_directory.get_by_id(user_id)
    if None is user:
        raise ValidationException("User not found.", 404)
    return user


async def _ensure_not_last_admin(
    user_directory: AbstractUserDirectory, user: DirectoryUser
) -> None:
    """Refuse to demote or disable the last enabled admin.

    With no admin left, every admin-only route, including this one,
    would be locked for good. A disabled admin can't act, so it never
    counts.

    Raises:
        ValidationException: `user` is the only enabled admin (400).
    """
    if "admin" != user.role or not user.is_enabled:
        return
    if await user_directory.count_enabled_by_role("admin") <= 1:
        raise ValidationException("Cannot remove the only remaining admin.", 400)
