"""Which of a user's identity-provider roles the API acts on."""

from collections.abc import Iterable

ROLES_BY_PRECEDENCE = ("admin", "user", "viewer")
"""The roles the API knows, the most privileged first."""


def select_highest_role(roles: Iterable[str]) -> str | None:
    """Return the most privileged known role in `roles`.

    An account can hold several realm roles (an admin usually keeps
    the default `user` too); the API acts on one. Roles it doesn't
    know, such as Keycloak's `offline_access`, are ignored.

    Returns:
        The highest of `ROLES_BY_PRECEDENCE` held, or `None` if `roles`
        holds none of them.
    """
    held_roles = set(roles)
    return next((role for role in ROLES_BY_PRECEDENCE if role in held_roles), None)
