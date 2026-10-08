import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.ports.token_verifier import AuthenticatedUser
from night_crawler.services import auth_service


@pytest.mark.anyio
async def test_a_verified_token_resolves_to_its_user(token_verifier_fake):
    token_verifier_fake.users["good-token"] = AuthenticatedUser(
        "kc-user-1", "dora@example.com", "viewer"
    )

    user = await auth_service.get_user_from_token(token_verifier_fake, "good-token")

    assert ("kc-user-1", "dora@example.com", "viewer") == (
        user.id,
        user.email,
        user.role,
    )


@pytest.mark.anyio
async def test_a_rejected_token_is_a_401(token_verifier_fake):
    with pytest.raises(ValidationException) as exc_info:
        await auth_service.get_user_from_token(token_verifier_fake, "not-a-jwt")

    assert 401 == exc_info.value.status_code
