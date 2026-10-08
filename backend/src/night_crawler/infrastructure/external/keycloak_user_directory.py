"""Accounts in Keycloak, through its Admin REST API."""

import asyncio
import time
from datetime import UTC, datetime

import httpx
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    ValidationException,
)
from night_crawler.domain.ports.user_directory import (
    AbstractUserDirectory,
    DirectoryUser,
    DirectoryUserChanges,
)
from night_crawler.domain.rules.user_roles import (
    ROLES_BY_PRECEDENCE,
    select_highest_role,
)

TOKEN_REFRESH_MARGIN_SECONDS = 30
"""Fetch a new admin token this long before the current one expires."""

ROLE_MEMBERS_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 10


class KeycloakUserDirectory(AbstractUserDirectory):
    """Keycloak accounts, managed as the API's service account.

    It authenticates with the client-credentials grant and reuses the
    token until shortly before it expires. A role is read from the
    account's effective realm roles, so `user`, which every account gets
    through the realm's default-roles composite, counts. Setting a role
    therefore drops that composite along with the other API roles: the
    account then holds exactly the one role set. Keycloak lists accounts
    by username, which is the email in this realm. The client secret is
    sent only to the token endpoint and never logged.
    """

    def __init__(
        self,
        base_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Manage `realm`'s accounts as the client's service account."""
        self._token_url = f"{base_url}/realms/{realm}/protocol/openid-connect/token"
        self._replaced_roles = {*ROLES_BY_PRECEDENCE, f"default-roles-{realm}"}
        self._credentials = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/admin/realms/{realm}",
            transport=transport,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def get_all(self, limit: int, offset: int) -> list[DirectoryUser]:
        """Return one page of accounts, ordered by email.

        Raises:
            ExternalServiceException: Keycloak failed.
        """
        # Full representations: brief ones leave out `createdTimestamp`.
        response = await self._send(
            "GET", "/users", params={"first": offset, "max": limit}
        )
        return list(await asyncio.gather(*map(self._to_user, response.json())))

    async def get_by_id(self, user_id: str) -> DirectoryUser | None:
        """Return the account, or `None` if Keycloak has none.

        Raises:
            ExternalServiceException: Keycloak failed.
        """
        response = await self._send("GET", f"/users/{user_id}", allowed_statuses=(404,))
        if 404 == response.status_code:
            return None
        return await self._to_user(response.json())

    async def create(
        self, email: str, role: str, temporary_password: str
    ) -> DirectoryUser:
        """Create the account; its user sets a new password at login.

        Raises:
            ValidationException: the email is taken (400).
            ExternalServiceException: Keycloak failed.
        """
        response = await self._send(
            "POST",
            "/users",
            allowed_statuses=(409,),
            json={
                "username": email,
                "email": email,
                "emailVerified": True,
                "enabled": True,
                "credentials": [_temporary_password(temporary_password)],
                "requiredActions": ["UPDATE_PASSWORD"],
            },
        )
        if 409 == response.status_code:
            raise ValidationException("Email already taken", 400)
        user_id = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
        await self._replace_role(user_id, role)
        return await self._to_user(await self._get_representation(user_id))

    async def update(
        self, user_id: str, changes: DirectoryUserChanges
    ) -> DirectoryUser:
        """Apply `changes`, keeping every field they leave out.

        Raises:
            ValidationException: the account does not exist (404), or
                the new email is taken (400).
            ExternalServiceException: Keycloak failed.
        """
        representation = await self._get_representation(user_id)
        if changes.email:
            representation = {
                **representation,
                "username": changes.email,
                "email": changes.email,
            }
            await self._put_representation(user_id, representation)
        if changes.temporary_password:
            await self._send(
                "PUT",
                f"/users/{user_id}/reset-password",
                json=_temporary_password(changes.temporary_password),
            )
        if changes.role:
            await self._replace_role(user_id, changes.role)
        return await self._to_user(representation)

    async def disable(self, user_id: str) -> None:
        """Turn the account off; Keycloak keeps it and its id.

        Raises:
            ValidationException: the account does not exist (404).
            ExternalServiceException: Keycloak failed.
        """
        representation = await self._get_representation(user_id)
        await self._put_representation(user_id, {**representation, "enabled": False})

    async def count_enabled_by_role(self, role: str) -> int:
        """Return how many enabled accounts hold `role` directly.

        Composite holders (every account's `user`) are not counted.

        Raises:
            ExternalServiceException: Keycloak failed.
        """
        count, first = 0, 0
        while True:
            response = await self._send(
                "GET",
                f"/roles/{role}/users",
                params={
                    "first": first,
                    "max": ROLE_MEMBERS_PAGE_SIZE,
                    "briefRepresentation": "true",
                },
            )
            members = response.json()
            count += sum(1 for member in members if member.get("enabled"))
            if len(members) < ROLE_MEMBERS_PAGE_SIZE:
                return count
            first += ROLE_MEMBERS_PAGE_SIZE

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._client.aclose()

    async def _to_user(self, representation: dict) -> DirectoryUser:
        """Return the account with its highest effective role."""
        response = await self._send(
            "GET", f"/users/{representation['id']}/role-mappings/realm/composite"
        )
        return DirectoryUser(
            id=representation["id"],
            email=representation.get("email", ""),
            role=select_highest_role(role["name"] for role in response.json()),
            is_enabled=representation["enabled"],
            created_at=_to_created_at(representation.get("createdTimestamp")),
        )

    async def _get_representation(self, user_id: str) -> dict:
        """Return the account's full representation.

        Raises:
            ValidationException: the account does not exist (404).
            ExternalServiceException: Keycloak failed.
        """
        response = await self._send("GET", f"/users/{user_id}", allowed_statuses=(404,))
        if 404 == response.status_code:
            raise ValidationException("User not found.", 404)
        return response.json()

    async def _put_representation(self, user_id: str, representation: dict) -> None:
        """Save the whole representation, so no field is reset.

        Raises:
            ValidationException: the email is taken (400).
            ExternalServiceException: Keycloak failed.
        """
        response = await self._send(
            "PUT", f"/users/{user_id}", allowed_statuses=(409,), json=representation
        )
        if 409 == response.status_code:
            raise ValidationException("Email already taken", 400)

    async def _replace_role(self, user_id: str, role: str) -> None:
        """Leave `role` as the only API role mapped to the account.

        Raises:
            ExternalServiceException: Keycloak failed, or the realm has
                no such role.
        """
        mappings_path = f"/users/{user_id}/role-mappings/realm"
        mapped = (await self._send("GET", mappings_path)).json()
        stale = _get_stale_mappings(mapped, self._replaced_roles - {role})
        if stale:
            await self._send("DELETE", mappings_path, json=stale)
        if all(role != mapping["name"] for mapping in mapped):
            await self._add_role(mappings_path, role)

    async def _add_role(self, mappings_path: str, role: str) -> None:
        """Map the realm role named `role` through `mappings_path`.

        Raises:
            ExternalServiceException: Keycloak failed, or the realm has
                no such role.
        """
        available = (await self._send("GET", f"{mappings_path}/available")).json()
        new_roles = [mapping for mapping in available if role == mapping["name"]]
        if not new_roles:
            raise ExternalServiceException(f"Keycloak has no realm role {role!r}.")
        await self._send("POST", mappings_path, json=new_roles)

    async def _send(
        self,
        method: str,
        path: str,
        allowed_statuses: tuple[int, ...] = (),
        **kwargs: object,
    ) -> httpx.Response:
        """Call the Admin API as the service account.

        Raises:
            ExternalServiceException: Keycloak is unreachable, or
                answered an error status not in `allowed_statuses`.
        """
        headers = {"Authorization": f"Bearer {await self._get_access_token()}"}
        try:
            response = await self._client.request(
                method, path, headers=headers, **kwargs
            )
        except httpx.HTTPError as error:
            raise ExternalServiceException("Keycloak is unreachable.") from error
        if 400 <= response.status_code and response.status_code not in (
            allowed_statuses
        ):
            raise ExternalServiceException(
                f"Keycloak answered {response.status_code} to {method} {path}."
            )
        return response

    async def _get_access_token(self) -> str:
        """Return the cached admin token, fetching one when it is stale.

        The lock keeps concurrent requests from each fetching a token.

        Raises:
            ExternalServiceException: Keycloak is unreachable or refused
                the client credentials.
        """
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            try:
                response = await self._client.post(
                    self._token_url, data=self._credentials
                )
            except httpx.HTTPError as error:
                raise ExternalServiceException("Keycloak is unreachable.") from error
            if 200 != response.status_code:
                raise ExternalServiceException(
                    f"Keycloak refused the API's client credentials "
                    f"({response.status_code})."
                )
            token = response.json()
            self._access_token = token["access_token"]
            self._token_expires_at = (
                time.monotonic() + token["expires_in"] - TOKEN_REFRESH_MARGIN_SECONDS
            )
            return self._access_token


def _get_stale_mappings(mapped: list[dict], replaced_roles: set[str]) -> list[dict]:
    """Return the mappings among `mapped` that name a replaced role."""
    return [mapping for mapping in mapped if mapping["name"] in replaced_roles]


def _to_created_at(created_timestamp_ms: int | None) -> datetime | None:
    """Return Keycloak's creation time as naive UTC, if it has one.

    Accounts imported with the realm file carry none.
    """
    if None is created_timestamp_ms:
        return None
    return datetime.fromtimestamp(created_timestamp_ms / 1000, UTC).replace(tzinfo=None)


def _temporary_password(password: str) -> dict:
    """Return a password credential the user must change at login."""
    return {"type": "password", "value": password, "temporary": True}
