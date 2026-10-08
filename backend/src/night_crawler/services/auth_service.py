"""Use case for knowing who calls the API.

Logging in, registering, and passwords are Keycloak's; the API only
checks the access tokens it issues.
"""

from night_crawler.domain.ports.token_verifier import AbstractTokenVerifier
from night_crawler.schemas.auth import UserOut


async def get_user_from_token(
    token_verifier: AbstractTokenVerifier, token: str
) -> UserOut:
    """Return the user an access token belongs to.

    The token carries everything needed, so no account is looked up:
    a disabled account or a changed role shows only once the token
    expires.

    Raises:
        ValidationException: the token is invalid, expired, or has no
            known role (401).
        ExternalServiceException: the signing keys can't be fetched.
    """
    user = await token_verifier.verify(token)
    return UserOut(id=user.id, email=user.email, role=user.role)
