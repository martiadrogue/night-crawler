import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.auth import UserCreate, UserUpdate
from night_crawler.services import user_service


@pytest.mark.anyio
async def test_create_user_starts_as_user_with_a_temporary_password(user_directory):
    user = await user_service.create_user(
        user_directory, UserCreate(email="carol@example.com", password="Secret123")
    )

    assert ("user", True) == (user.role, user.is_enabled)
    assert "Secret123" == user_directory.temporary_passwords[user.id]


@pytest.mark.anyio
async def test_create_user_rejects_a_taken_email(user_directory):
    user_directory.add("kc-1", "carol@example.com")

    with pytest.raises(ValidationException) as exc_info:
        await user_service.create_user(
            user_directory,
            UserCreate(email="carol@example.com", password="Secret123"),
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_update_user_changes_role_email_and_password(user_directory):
    user_directory.add("kc-1", "carol@example.com")

    updated = await user_service.update_user(
        user_directory,
        "kc-1",
        UserUpdate(email="caroline@example.com", password="NewPass1", role="viewer"),
    )

    assert ("caroline@example.com", "viewer") == (updated.email, updated.role)
    assert "NewPass1" == user_directory.temporary_passwords["kc-1"]


@pytest.mark.anyio
async def test_update_user_rejects_a_taken_email(user_directory):
    user_directory.add("kc-1", "carol@example.com")
    user_directory.add("kc-2", "dora@example.com")

    with pytest.raises(ValidationException) as exc_info:
        await user_service.update_user(
            user_directory, "kc-2", UserUpdate(email="carol@example.com")
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_update_user_refuses_to_demote_the_last_admin(user_directory):
    user_directory.add("kc-1", "admin@example.com", "admin")

    with pytest.raises(ValidationException) as exc_info:
        await user_service.update_user(user_directory, "kc-1", UserUpdate(role="user"))

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_a_disabled_admin_is_not_the_last_admin(user_directory):
    user_directory.add("kc-1", "admin@example.com", "admin")
    user_directory.add("kc-2", "old-admin@example.com", "admin", is_enabled=False)

    with pytest.raises(ValidationException):
        await user_service.disable_user(user_directory, "kc-1")
    demoted = await user_service.update_user(
        user_directory, "kc-2", UserUpdate(role="viewer")
    )

    assert "viewer" == demoted.role


@pytest.mark.anyio
async def test_disable_user_keeps_the_account_disabled(user_directory):
    user_directory.add("kc-1", "admin@example.com", "admin")
    user_directory.add("kc-2", "carol@example.com")

    await user_service.disable_user(user_directory, "kc-2")
    user = await user_service.get_user(user_directory, "kc-2")

    assert False is user.is_enabled


@pytest.mark.anyio
async def test_disable_user_refuses_the_last_admin(user_directory):
    user_directory.add("kc-1", "admin@example.com", "admin")

    with pytest.raises(ValidationException) as exc_info:
        await user_service.disable_user(user_directory, "kc-1")

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    "call",
    [
        lambda directory: user_service.get_user(directory, "missing"),
        lambda directory: user_service.update_user(
            directory, "missing", UserUpdate(role="viewer")
        ),
        lambda directory: user_service.disable_user(directory, "missing"),
    ],
    ids=["get", "update", "disable"],
)
async def test_a_missing_user_is_a_404(user_directory, call):
    with pytest.raises(ValidationException) as exc_info:
        await call(user_directory)

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_get_users_pages_and_says_if_more_exist(user_directory):
    user_directory.add("kc-1", "a@example.com")
    user_directory.add("kc-2", "b@example.com")

    page = await user_service.get_users(user_directory, limit=1, offset=0)

    assert ["a@example.com"] == [user.email for user in page.items]
    assert page.has_more
