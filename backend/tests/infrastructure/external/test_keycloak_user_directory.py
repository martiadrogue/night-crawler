import json
import re
from datetime import datetime

import httpx
import pytest
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    ValidationException,
)
from night_crawler.domain.ports.user_directory import (
    DirectoryUser,
    DirectoryUserChanges,
)
from night_crawler.infrastructure.external.keycloak_user_directory import (
    KeycloakUserDirectory,
)

BASE_URL = "http://keycloak.test"
ADMIN = "/admin/realms/night-crawler"
DEFAULT_ROLES = "default-roles-night-crawler"
DEFAULT_COMPOSITES = {"user", "offline_access"}
CREATED_MS = 1_767_225_600_000  # 2026-01-01T00:00:00Z


class FakeKeycloak:
    """The slice of Keycloak's token endpoint and Admin API used."""

    def __init__(self, expires_in: int = 300) -> None:
        self.expires_in = expires_in
        self.tokens_issued = 0
        self.users: dict[str, dict] = {}
        self.direct_roles: dict[str, set[str]] = {}
        self.requests: list[httpx.Request] = []

    def add_user(self, user_id, email, roles=(DEFAULT_ROLES,), enabled=True):
        self.users[user_id] = {
            "id": user_id,
            "username": email,
            "email": email,
            "enabled": enabled,
            "createdTimestamp": CREATED_MS,
            "firstName": "Kept",
        }
        self.direct_roles[user_id] = set(roles)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return self._issue_token(request)
        if f"Bearer token-{self.tokens_issued}" != request.headers["Authorization"]:
            return httpx.Response(401)
        return self._route(request, path.removeprefix(ADMIN))

    def _issue_token(self, request):
        form = dict(item.split("=") for item in request.content.decode().split("&"))
        if (
            "night-crawler-api" != form["client_id"]
            or "s3cret" != form["client_secret"]
        ):
            return httpx.Response(401)
        self.tokens_issued += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"token-{self.tokens_issued}",
                "expires_in": self.expires_in,
            },
        )

    def _route(self, request, path):
        method = request.method
        if (match := re.fullmatch(r"/roles/(\w+)/users", path)) and "GET" == method:
            return self._role_members(match[1], request.url.params)
        if "/users" == path:
            return self._users(request)
        if match := re.fullmatch(r"/users/([\w-]+)/reset-password", path):
            self.users[match[1]]["credentials"] = [json.loads(request.content)]
            return httpx.Response(204)
        match = re.fullmatch(r"/users/([\w-]+)(/role-mappings/realm(/\w+)?)?", path)
        user_id = match[1]
        if user_id not in self.users:
            return httpx.Response(404)
        if match[2]:
            return self._role_mappings(request, user_id, match[3])
        if "PUT" == method:
            return self._update_user(request, user_id)
        return httpx.Response(200, json=self.users[user_id])

    def _users(self, request):
        if "GET" == request.method:
            params = request.url.params
            by_email = sorted(self.users.values(), key=lambda user: user["email"])
            first, count = int(params["first"]), int(params["max"])
            return httpx.Response(
                200, json=_brief(by_email[first : first + count], params)
            )
        body = json.loads(request.content)
        if any(body["email"] == user["email"] for user in self.users.values()):
            return httpx.Response(409, json={"errorMessage": "User exists"})
        user_id = f"kc-{len(self.users) + 1}"
        self.add_user(user_id, body["email"])
        self.users[user_id]["credentials"] = body["credentials"]
        self.users[user_id]["requiredActions"] = body["requiredActions"]
        return httpx.Response(
            201, headers={"Location": f"{BASE_URL}{ADMIN}/users/{user_id}"}
        )

    def _update_user(self, request, user_id):
        body = json.loads(request.content)
        others = (user for key, user in self.users.items() if key != user_id)
        if any(body.get("email") == user["email"] for user in others):
            return httpx.Response(409, json={"errorMessage": "Email exists"})
        self.users[user_id] = body
        return httpx.Response(204)

    def _role_mappings(self, request, user_id, suffix):
        direct = self.direct_roles[user_id]
        if "/composite" == suffix:
            effective = direct | (
                DEFAULT_COMPOSITES if DEFAULT_ROLES in direct else set()
            )
            return httpx.Response(200, json=[_role(name) for name in effective])
        if "/available" == suffix:
            known = {"admin", "user", "viewer", "offline_access", DEFAULT_ROLES}
            return httpx.Response(200, json=[_role(name) for name in known - direct])
        if "GET" == request.method:
            return httpx.Response(200, json=[_role(name) for name in direct])
        names = {role["name"] for role in json.loads(request.content)}
        if "DELETE" == request.method:
            direct -= names
        else:
            direct |= names
        return httpx.Response(204)

    def _role_members(self, role, params):
        members = [
            self.users[user_id]
            for user_id, roles in sorted(self.direct_roles.items())
            if role in roles
        ]
        first, count = int(params["first"]), int(params["max"])
        return httpx.Response(200, json=_brief(members[first : first + count], params))


def _brief(users: list[dict], params) -> list[dict]:
    """Drop what Keycloak's brief representations leave out."""
    if "true" != params.get("briefRepresentation"):
        return users
    return [
        {key: value for key, value in user.items() if "createdTimestamp" != key}
        for user in users
    ]


def _role(name: str) -> dict:
    return {"id": f"role-{name}", "name": name}


@pytest.fixture
def keycloak() -> FakeKeycloak:
    return FakeKeycloak()


@pytest.fixture
async def directory(keycloak):
    user_directory = KeycloakUserDirectory(
        BASE_URL,
        "night-crawler",
        "night-crawler-api",
        "s3cret",
        transport=httpx.MockTransport(keycloak.handle),
    )
    yield user_directory
    await user_directory.aclose()


@pytest.mark.anyio
async def test_get_by_id_maps_the_account_and_its_effective_role(keycloak, directory):
    keycloak.add_user("kc-1", "dora@example.com", roles=(DEFAULT_ROLES, "admin"))

    user = await directory.get_by_id("kc-1")

    assert (
        DirectoryUser("kc-1", "dora@example.com", "admin", True, datetime(2026, 1, 1))
        == user
    )


@pytest.mark.anyio
async def test_get_by_id_of_a_missing_account_is_none(directory):
    assert None is await directory.get_by_id("missing")


@pytest.mark.anyio
async def test_the_admin_token_is_reused_until_it_nearly_expires(directory, keycloak):
    keycloak.add_user("kc-1", "dora@example.com")

    await directory.get_by_id("kc-1")
    await directory.get_all(limit=10, offset=0)

    assert 1 == keycloak.tokens_issued


@pytest.mark.anyio
async def test_a_token_about_to_expire_is_fetched_again(keycloak):
    keycloak.expires_in = 5
    keycloak.add_user("kc-1", "dora@example.com")
    directory = KeycloakUserDirectory(
        BASE_URL,
        "night-crawler",
        "night-crawler-api",
        "s3cret",
        transport=httpx.MockTransport(keycloak.handle),
    )

    await directory.get_by_id("kc-1")
    await directory.get_by_id("kc-1")
    await directory.aclose()

    admin_calls = [r for r in keycloak.requests if "/admin/" in r.url.path]
    assert len(admin_calls) == keycloak.tokens_issued


@pytest.mark.anyio
async def test_get_all_pages_through_accounts(keycloak, directory):
    keycloak.add_user("kc-1", "b@example.com")
    keycloak.add_user("kc-2", "a@example.com", roles=("viewer",))

    users = await directory.get_all(limit=1, offset=1)

    assert [("kc-1", "user")] == [(user.id, user.role) for user in users]


@pytest.mark.anyio
async def test_create_sets_a_temporary_password_and_the_role(keycloak, directory):
    user = await directory.create("carol@example.com", "user", "Secret123")

    stored = keycloak.users[user.id]
    assert [{"type": "password", "value": "Secret123", "temporary": True}] == (
        stored["credentials"]
    )
    assert ["UPDATE_PASSWORD"] == stored["requiredActions"]
    assert {"user"} == keycloak.direct_roles[user.id]
    assert ("carol@example.com", "user") == (user.email, user.role)


@pytest.mark.anyio
async def test_create_with_a_taken_email_is_a_400(keycloak, directory):
    keycloak.add_user("kc-1", "carol@example.com")

    with pytest.raises(ValidationException) as exc_info:
        await directory.create("carol@example.com", "user", "Secret123")

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_a_new_role_replaces_the_app_roles_and_the_default_composite(
    keycloak, directory
):
    keycloak.add_user("kc-1", "dora@example.com", roles=(DEFAULT_ROLES, "admin"))

    user = await directory.update("kc-1", DirectoryUserChanges(role="viewer"))

    assert {"viewer"} == keycloak.direct_roles["kc-1"]
    assert "viewer" == user.role


@pytest.mark.anyio
async def test_update_keeps_the_fields_it_does_not_change(keycloak, directory):
    keycloak.add_user("kc-1", "dora@example.com")

    user = await directory.update(
        "kc-1",
        DirectoryUserChanges(email="dora@new.example", temporary_password="NewPass1"),
    )

    stored = keycloak.users["kc-1"]
    assert ("dora@new.example", "Kept") == (stored["email"], stored["firstName"])
    assert True is stored["credentials"][0]["temporary"]
    assert "dora@new.example" == user.email


@pytest.mark.anyio
async def test_update_with_a_taken_email_is_a_400(keycloak, directory):
    keycloak.add_user("kc-1", "carol@example.com")
    keycloak.add_user("kc-2", "dora@example.com")

    with pytest.raises(ValidationException) as exc_info:
        await directory.update("kc-2", DirectoryUserChanges(email="carol@example.com"))

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_disable_turns_the_account_off(keycloak, directory):
    keycloak.add_user("kc-1", "dora@example.com")

    await directory.disable("kc-1")

    assert False is keycloak.users["kc-1"]["enabled"]
    assert "Kept" == keycloak.users["kc-1"]["firstName"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "call",
    [
        lambda directory: directory.disable("missing"),
        lambda directory: directory.update(
            "missing", DirectoryUserChanges(role="viewer")
        ),
    ],
    ids=["disable", "update"],
)
async def test_changing_a_missing_account_is_a_404(directory, call):
    with pytest.raises(ValidationException) as exc_info:
        await call(directory)

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_count_enabled_by_role_skips_disabled_holders(keycloak, directory):
    for index in range(150):
        keycloak.add_user(f"kc-{index:03}", f"admin{index}@example.com", ("admin",))
    keycloak.add_user("kc-off", "off@example.com", ("admin",), enabled=False)
    keycloak.add_user("kc-user", "user@example.com")

    assert 150 == await directory.count_enabled_by_role("admin")


@pytest.mark.anyio
async def test_wrong_client_credentials_are_an_external_service_error(keycloak):
    directory = KeycloakUserDirectory(
        BASE_URL,
        "night-crawler",
        "night-crawler-api",
        "wrong",
        transport=httpx.MockTransport(keycloak.handle),
    )

    with pytest.raises(ExternalServiceException) as exc_info:
        await directory.get_by_id("kc-1")
    await directory.aclose()

    assert "wrong" not in exc_info.value.message


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [httpx.ConnectError("refused"), httpx.Response(500)],
    ids=["unreachable", "server-error"],
)
async def test_a_failing_keycloak_is_an_external_service_error(response):
    def _fail(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    directory = KeycloakUserDirectory(
        BASE_URL,
        "night-crawler",
        "night-crawler-api",
        "s3cret",
        transport=httpx.MockTransport(_fail),
    )

    with pytest.raises(ExternalServiceException):
        await directory.get_all(limit=10, offset=0)
    await directory.aclose()


@pytest.mark.anyio
async def test_an_account_imported_with_the_realm_has_no_creation_time(
    keycloak, directory
):
    keycloak.add_user("kc-1", "dora@example.com")
    del keycloak.users["kc-1"]["createdTimestamp"]

    [user] = await directory.get_all(limit=10, offset=0)

    assert None is user.created_at
