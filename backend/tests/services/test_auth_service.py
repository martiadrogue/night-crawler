import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.auth import SessionCreate, UserCreate
from night_crawler.services import auth_service


@pytest.mark.anyio
async def test_register_then_resolve_the_token_to_the_user(
    write_repositories, read_repositories, auth_attempt_limiter
):
    token = await auth_service.register_user(
        write_repositories,
        auth_attempt_limiter,
        UserCreate(email="dora@example.com", password="Secret123"),
        "192.0.2.10",
    )

    user = await auth_service.get_user_from_token(read_repositories, token.access_token)

    assert "user" == token.role
    assert "dora@example.com" == user.email


@pytest.mark.anyio
async def test_login_with_the_right_password(
    write_repositories, read_repositories, auth_attempt_limiter
):
    await auth_service.register_user(
        write_repositories,
        auth_attempt_limiter,
        UserCreate(email="dora@example.com", password="Secret123"),
        "192.0.2.10",
    )

    token = await auth_service.authenticate_user(
        read_repositories,
        auth_attempt_limiter,
        SessionCreate(email="dora@example.com", password="Secret123"),
        "192.0.2.10",
    )

    assert token.access_token


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("email", "password"),
    [("dora@example.com", "Wrong123"), ("nobody@example.com", "Secret123")],
)
async def test_login_rejects_bad_credentials_alike(
    write_repositories, read_repositories, auth_attempt_limiter, email, password
):
    await auth_service.register_user(
        write_repositories,
        auth_attempt_limiter,
        UserCreate(email="dora@example.com", password="Secret123"),
        "192.0.2.10",
    )

    with pytest.raises(ValidationException) as exc_info:
        await auth_service.authenticate_user(
            read_repositories,
            auth_attempt_limiter,
            SessionCreate(email=email, password=password),
            "192.0.2.10",
        )

    assert 401 == exc_info.value.status_code


@pytest.mark.anyio
async def test_a_tampered_token_is_rejected(write_repositories):
    with pytest.raises(ValidationException) as exc_info:
        await auth_service.get_user_from_token(write_repositories, "not-a-jwt")

    assert 401 == exc_info.value.status_code
