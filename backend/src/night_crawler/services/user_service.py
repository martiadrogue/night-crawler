"""Admin use cases for managing user accounts."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.core.config import get_settings
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import User
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.pagination import MAX_PAGE_SIZE, resolve_page
from night_crawler.schemas.auth import (
    UserCreate,
    UserOut,
    UserRole,
    UsersPageOut,
    UserUpdate,
)
from night_crawler.services import crawler_service, crawler_version_service
from night_crawler.services.auth_service import hash_password

logger = logging.getLogger(__name__)
settings = get_settings()


def _to_out(user: User) -> UserOut:
    """Map a user onto its API schema, without the password hash."""
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
    )


async def get_users(
    read_repositories: AbstractReadRepositories,
    limit: int = MAX_PAGE_SIZE,
    offset: int = 0,
) -> UsersPageOut:
    """Return one page of users, newest first.

    Fetches one extra user to tell whether more exist, avoiding a count
    query.
    """
    page_limit, page_offset = resolve_page(False, limit, offset)
    if 0 == page_limit:
        return UsersPageOut(items=[], limit=0, offset=page_offset, has_more=False)

    users = await read_repositories.users.get_all(
        limit=page_limit + 1, offset=page_offset
    )
    return UsersPageOut(
        items=[_to_out(user) for user in users[:page_limit]],
        limit=page_limit,
        offset=page_offset,
        has_more=len(users) > page_limit,
    )


async def get_user(
    read_repositories: AbstractReadRepositories, user_id: str
) -> UserOut:
    """Return one user.

    Raises:
        ValidationException: the user does not exist (404).
    """
    return _to_out(await _get_user_or_404(read_repositories, user_id))


async def create_user(
    write_repositories: AbstractWriteRepositories,
    user_input: UserCreate,
    role: UserRole = "user",
) -> UserOut:
    """Create an account; only internal callers may pass `role`.

    The request payload never carries a role, so creating an account
    can't grant privileges; `update_user` is the only way to change it.

    Raises:
        ValidationException: the email is already taken (400).
    """
    await _ensure_email_free(write_repositories, user_input.email)

    new_user = User(
        id=str(uuid.uuid4()),
        email=user_input.email,
        hashed_password=await hash_password(user_input.password),
        role=role,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    saved_user = await write_repositories.users.save(new_user)
    await write_repositories.commit()

    logger.info("User created: id=%s, role=%s", saved_user.id, saved_user.role)
    return _to_out(saved_user)


async def update_user(
    write_repositories: AbstractWriteRepositories, user_id: str, user_input: UserUpdate
) -> UserOut:
    """Apply a partial update to an account.

    Raises:
        ValidationException: the user does not exist (404), the new
            email is taken (400), or this would demote the last admin
            (400).
    """
    user = await _get_user_or_404(write_repositories, user_id)
    updates = user_input.model_dump(exclude_unset=True, exclude_none=True)
    await _ensure_update_allowed(write_repositories, user, updates)
    if "password" in updates:
        updates["hashed_password"] = await hash_password(updates.pop("password"))

    saved_user = await write_repositories.users.save(replace(user, **updates))
    await write_repositories.commit()

    logger.info("User updated: id=%s, fields=%s", user.id, sorted(updates))
    return _to_out(saved_user)


async def delete_user(
    write_repositories: AbstractWriteRepositories, user_id: str
) -> None:
    """Delete an account, its Crawlers, and the versions it owns.

    Raises:
        ValidationException: the user does not exist (404), it is the
            last admin (400), or a version it owns in someone else's
            Crawler has run (409).
    """
    user = await _get_user_or_404(write_repositories, user_id)
    await _ensure_not_last_admin(write_repositories, user)

    await crawler_service.delete_crawlers_of_user(write_repositories, user.id)
    await crawler_version_service.delete_versions_of_user(write_repositories, user.id)
    await write_repositories.users.delete(user.id)
    await write_repositories.commit()

    logger.info("User deleted: id=%s", user.id)


async def seed_admin_user(write_repositories: AbstractWriteRepositories) -> None:
    """Create the bootstrap admin from settings, once.

    Skipped unless both seed email and password are set, so no
    deployment ships a guessable default admin. Skipped too when the
    email exists, whatever its role, so a restart never undoes an
    operator's changes.
    """
    email = settings.admin_seed_email
    password = settings.admin_seed_password
    if not email or not password:
        return

    if await write_repositories.users.get_by_email(email):
        logger.info("Admin seed skipped: the user already exists.")
        return

    await create_user(
        write_repositories, UserCreate(email=email, password=password), role="admin"
    )
    logger.info("Admin seed: bootstrap admin created.")


async def _get_user_or_404(repositories: AbstractRepositories, user_id: str) -> User:
    """Return the user.

    Raises:
        ValidationException: it does not exist (404).
    """
    user = await repositories.users.get_by_id(user_id)
    if None is user:
        raise ValidationException("User not found.", 404)
    return user


async def _ensure_update_allowed(
    write_repositories: AbstractWriteRepositories, user: User, updates: dict
) -> None:
    """Check a changed email is free and a role change keeps an admin.

    Raises:
        ValidationException: the new email is taken, or this would
            demote the last admin (400).
    """
    if updates.get("email", user.email) != user.email:
        await _ensure_email_free(write_repositories, updates["email"])
    if updates.get("role", user.role) != user.role:
        await _ensure_not_last_admin(write_repositories, user)


async def _ensure_email_free(
    write_repositories: AbstractWriteRepositories, email: str
) -> None:
    """Refuse an email another account already uses.

    Raises:
        ValidationException: the email is taken (400).
    """
    if await write_repositories.users.get_by_email(email):
        raise ValidationException("Email already taken", 400)


async def _ensure_not_last_admin(
    write_repositories: AbstractWriteRepositories, user: User
) -> None:
    """Refuse to demote or delete the last admin.

    With no admin left, every admin-only route, including this one,
    would be locked for good.

    Raises:
        ValidationException: `user` is the only admin (400).
    """
    if "admin" != user.role:
        return
    if await write_repositories.users.count_by_role("admin") <= 1:
        raise ValidationException("Cannot remove the only remaining admin.", 400)
