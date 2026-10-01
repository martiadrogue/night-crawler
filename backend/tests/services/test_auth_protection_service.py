import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.auth import SessionCreate, UserCreate
from night_crawler.services import auth_service


@pytest.mark.anyio
async def test_login_locks_email_after_five_failed_attempts(
    write_repositories, read_repositories, auth_attempt_limiter
):
    credentials = UserCreate(email="locked@example.com", password="Secret123")
    await auth_service.register_user(
        write_repositories, auth_attempt_limiter, credentials, "192.0.2.1"
    )

    for _ in range(5):
        with pytest.raises(ValidationException) as exc_info:
            await auth_service.authenticate_user(
                read_repositories,
                auth_attempt_limiter,
                SessionCreate(email=credentials.email, password="Wrong123"),
                "192.0.2.1",
            )
        assert 401 == exc_info.value.status_code

    with pytest.raises(ValidationException) as exc_info:
        await auth_service.authenticate_user(
            read_repositories,
            auth_attempt_limiter,
            SessionCreate(email=credentials.email, password=credentials.password),
            "192.0.2.1",
        )

    assert 429 == exc_info.value.status_code
    assert "Too many failed login attempts" in exc_info.value.message
