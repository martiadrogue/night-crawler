"""The port for the accounts the identity provider keeps."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DirectoryUser:
    """One account as the identity provider holds it.

    Attributes:
        id: The identity provider's id; what `user_id` references store.
        email: Unique across accounts.
        role: The most privileged of `admin`, `user`, `viewer` it holds,
            or `None` if it holds none (it then can't call the API).
        is_enabled: `False` once disabled: it can no longer log in.
        created_at: When the account was created (naive UTC), or
            `None` if the identity provider doesn't know (accounts
            imported with the realm).
    """

    id: str
    email: str
    role: str | None
    is_enabled: bool
    created_at: datetime | None


@dataclass(frozen=True)
class DirectoryUserChanges:
    """A partial account update; `None` leaves a field as it is.

    Attributes:
        email: The new email.
        role: The account's only role from now on.
        temporary_password: A password the user must change at their
            next login.
    """

    email: str | None = None
    role: str | None = None
    temporary_password: str | None = None


class AbstractUserDirectory(ABC):
    """Reads and changes accounts; accounts are disabled, never deleted.

    Every method may also raise `ExternalServiceException` when the
    identity provider is unreachable or refuses the API's credentials.
    """

    @abstractmethod
    async def get_all(self, limit: int, offset: int) -> list[DirectoryUser]:
        """Return one page of accounts, ordered by email.

        Raises:
            ExternalServiceException: the identity provider failed.
        """

    @abstractmethod
    async def get_by_id(self, user_id: str) -> DirectoryUser | None:
        """Return the account, or `None` if there is none.

        Raises:
            ExternalServiceException: the identity provider failed.
        """

    @abstractmethod
    async def create(
        self, email: str, role: str, temporary_password: str
    ) -> DirectoryUser:
        """Create an enabled account holding only `role`.

        The user must replace `temporary_password` at their first
        login.

        Raises:
            ValidationException: the email is taken (400).
            ExternalServiceException: the identity provider failed.
        """

    @abstractmethod
    async def update(
        self, user_id: str, changes: DirectoryUserChanges
    ) -> DirectoryUser:
        """Apply `changes` and return the updated account.

        Raises:
            ValidationException: the account does not exist (404), or
                the new email is taken (400).
            ExternalServiceException: the identity provider failed.
        """

    @abstractmethod
    async def disable(self, user_id: str) -> None:
        """Disable the account; its data and history stay.

        Raises:
            ValidationException: the account does not exist (404).
            ExternalServiceException: the identity provider failed.
        """

    @abstractmethod
    async def count_enabled_by_role(self, role: str) -> int:
        """Return how many enabled accounts hold `role` directly.

        Raises:
            ExternalServiceException: the identity provider failed.
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Release the connection pool."""
