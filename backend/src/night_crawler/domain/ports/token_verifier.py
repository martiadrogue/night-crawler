"""The port for verifying the identity provider's access tokens."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    """Who a verified access token says is calling.

    Attributes:
        id: The identity provider's id for the user (the `sub` claim);
            what `user_id` references store from now on.
        email: The user's email.
        role: Their most privileged known role: `admin`, `user`, or
            `viewer`.
    """

    id: str
    email: str
    role: str


class AbstractTokenVerifier(ABC):
    """Checks a bearer token and says whose it is, with no database."""

    @abstractmethod
    async def verify(self, token: str) -> AuthenticatedUser:
        """Return the user `token` was issued to.

        Raises:
            ValidationException: the token is malformed, badly signed,
                expired, issued by or for someone else, or carries no
                known role (401).
            ExternalServiceException: the signing keys can't be
                fetched.
        """
