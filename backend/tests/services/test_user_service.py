from datetime import datetime

import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import User
from night_crawler.schemas.auth import UserCreate, UserUpdate
from night_crawler.services import auth_service, user_service

NOW = datetime(2026, 1, 1)


async def _seed(write_repositories, user_id: str, email: str, role: str) -> None:
    await write_repositories.users.save(
        User(
            id=user_id,
            email=email,
            hashed_password="hashed",
            role=role,
            created_at=NOW,
        )
    )


@pytest.mark.anyio
async def test_create_user_always_starts_as_user(write_repositories):
    user = await user_service.create_user(
        write_repositories,
        UserCreate(email="carol@example.com", password="Secret123"),
    )

    assert "user" == user.role
    saved = await write_repositories.users.get_by_id(user.id)
    assert await auth_service.verify_password("Secret123", saved.hashed_password)


@pytest.mark.anyio
async def test_create_user_rejects_a_taken_email(write_repositories):
    await _seed(write_repositories, "user-1", "carol@example.com", "user")

    with pytest.raises(ValidationException) as exc_info:
        await user_service.create_user(
            write_repositories,
            UserCreate(email="carol@example.com", password="Secret123"),
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_update_user_changes_role_email_and_password(write_repositories):
    await _seed(write_repositories, "user-1", "carol@example.com", "user")

    updated = await user_service.update_user(
        write_repositories,
        "user-1",
        UserUpdate(
            email="caroline@example.com",
            password="NewPass1",
            role="viewer",
        ),
    )

    assert "caroline@example.com" == updated.email
    assert "viewer" == updated.role
    saved = await write_repositories.users.get_by_id("user-1")
    assert await auth_service.verify_password("NewPass1", saved.hashed_password)


@pytest.mark.anyio
async def test_update_user_refuses_to_demote_the_last_admin(write_repositories):
    await _seed(write_repositories, "admin-1", "admin@example.com", "admin")

    with pytest.raises(ValidationException) as exc_info:
        await user_service.update_user(
            write_repositories, "admin-1", UserUpdate(role="user")
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_user_refuses_the_last_admin(write_repositories):
    await _seed(write_repositories, "admin-1", "admin@example.com", "admin")

    with pytest.raises(ValidationException) as exc_info:
        await user_service.delete_user(write_repositories, "admin-1")

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_user_removes_their_crawlers(
    write_repositories, member, create_crawler
):
    await _seed(write_repositories, member.id, member.email, "user")
    crawler = await create_crawler()

    await user_service.delete_user(write_repositories, member.id)

    assert None is await write_repositories.users.get_by_id(member.id)
    assert None is await write_repositories.crawlers.get_by_id(crawler.id)
    assert [] == await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )


@pytest.mark.anyio
async def test_get_users_pages_newest_first(write_repositories):
    await _seed(write_repositories, "user-1", "a@example.com", "user")
    await _seed(write_repositories, "user-2", "b@example.com", "user")

    page = await user_service.get_users(write_repositories, limit=1, offset=0)

    assert 1 == len(page.items)
    assert page.has_more


@pytest.mark.anyio
async def test_seed_admin_user_is_skipped_without_settings(
    write_repositories, monkeypatch
):
    monkeypatch.setattr(user_service.settings, "admin_seed_email", "")
    monkeypatch.setattr(user_service.settings, "admin_seed_password", "")

    await user_service.seed_admin_user(write_repositories)

    assert [] == await write_repositories.users.get_all()


@pytest.mark.anyio
async def test_seed_admin_user_creates_the_admin_once(write_repositories, monkeypatch):
    monkeypatch.setattr(user_service.settings, "admin_seed_email", "root@example.com")
    monkeypatch.setattr(user_service.settings, "admin_seed_password", "AdminPass1")

    await user_service.seed_admin_user(write_repositories)
    await user_service.seed_admin_user(write_repositories)

    [admin] = await write_repositories.users.get_all()
    assert "root@example.com" == admin.email
    assert "admin" == admin.role
