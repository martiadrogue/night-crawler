"""Request and response models for accounts and sessions."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

UserRole = Literal["admin", "user", "viewer"]
"""The roles a user can hold; mirrors the Keycloak realm roles."""


class PasswordValidationMixin:
    """Shared validation for all user passwords."""

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """Reject weak passwords before they reach persistence."""
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not any(ch.isupper() for ch in value):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(ch.islower() for ch in value):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(ch.isdigit() for ch in value):
            raise ValueError("Password must contain at least one digit")
        return value


class UserBase(BaseModel):
    """Fields shared by every user model."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr


class UserCreate(UserBase, PasswordValidationMixin):
    """Body for an admin creating an account.

    There is no `role`: new accounts always start as `user`, and roles
    change only through an admin's update. An admin-created account's
    password is temporary: the user replaces it at their first login.
    """

    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    """Body for an admin's partial user update; unset fields stay.

    A new `password` is temporary, like a created account's.
    """

    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        """Apply the same password rules to partial updates."""
        if value is None:
            return value
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not any(ch.isupper() for ch in value):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(ch.islower() for ch in value):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(ch.isdigit() for ch in value):
            raise ValueError("Password must contain at least one digit")
        return value


class UserOut(UserBase):
    """A user as returned by the API, without any password.

    `role` is `None` for an account holding none of the API's roles;
    `is_enabled` is `False` once an admin disabled it; `created_at` is
    `None` when Keycloak has no creation time (accounts imported with
    the realm).
    """

    id: str
    role: str | None = "user"
    is_enabled: bool = True
    created_at: datetime | None = Field(default_factory=lambda: datetime.now(UTC))


class UsersPageOut(BaseModel):
    """One page of users.

    `has_more` follows the pagination cap, so it is `False` at the cap
    even if the database holds more users.
    """

    items: list[UserOut]
    limit: int
    offset: int
    has_more: bool
