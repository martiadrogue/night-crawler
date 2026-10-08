"""Verify access tokens against the identity provider's JWKS."""

import asyncio

import jwt
from jwt.exceptions import PyJWKClientConnectionError, PyJWTError
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    ValidationException,
)
from night_crawler.domain.ports.token_verifier import (
    AbstractTokenVerifier,
    AuthenticatedUser,
)
from night_crawler.domain.rules.user_roles import select_highest_role

INVALID_TOKEN_MESSAGE = "Invalid or expired session token"
REQUIRED_CLAIMS = ["exp", "iss", "aud", "sub"]


class JwksTokenVerifier(AbstractTokenVerifier):
    """Checks RS256 tokens with the keys Keycloak publishes.

    `PyJWKClient` caches the key set for 5 minutes and each key it
    resolved; a token naming an unknown `kid` (Keycloak rotated its
    keys) makes it fetch the set again. It fetches with blocking
    `urllib`, so key lookups run in a worker thread. One instance per
    process, so every request shares the cache.
    """

    def __init__(self, jwks_url: str, issuer: str, audience: str) -> None:
        """Verify tokens from `issuer` meant for `audience`."""
        self._jwk_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        self._issuer = issuer
        self._audience = audience

    async def verify(self, token: str) -> AuthenticatedUser:
        """Return the user `token` was issued to.

        `aud` may list several audiences; `audience` must be one.

        Raises:
            ValidationException: the token is malformed, badly signed,
                expired, has the wrong issuer or audience, or lacks an
                email or a known role (401).
            ExternalServiceException: the JWKS can't be fetched.
        """
        try:
            signing_key = await asyncio.to_thread(
                self._jwk_client.get_signing_key_from_jwt, token
            )
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS},
            )
        except PyJWKClientConnectionError as error:
            raise ExternalServiceException(
                "The identity provider's signing keys are unavailable."
            ) from error
        except PyJWTError as error:
            raise ValidationException(INVALID_TOKEN_MESSAGE, 401) from error
        return _to_authenticated_user(claims)


def _to_authenticated_user(claims: dict) -> AuthenticatedUser:
    """Map verified claims onto the user they describe.

    Raises:
        ValidationException: no email, or no known realm role (401).
    """
    realm_roles = (claims.get("realm_access") or {}).get("roles", [])
    role = select_highest_role(realm_roles)
    email = claims.get("email")
    if None is role or not email:
        raise ValidationException(INVALID_TOKEN_MESSAGE, 401)
    return AuthenticatedUser(id=claims["sub"], email=email, role=role)
