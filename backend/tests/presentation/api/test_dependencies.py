from datetime import UTC, datetime, timedelta

import pytest


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_a_route_needs_a_token(client):
    response = await client.get("/api/crawlers")

    assert 401 == response.status_code


@pytest.mark.anyio
async def test_a_keycloak_token_authenticates_its_user(client, issue_token):
    response = await client.get(
        "/api/crawlers", headers=_bearer(issue_token(roles=["viewer"]))
    )

    assert 200 == response.status_code


@pytest.mark.anyio
async def test_an_expired_token_is_a_401(client, issue_token):
    token = issue_token(exp=datetime.now(UTC) - timedelta(minutes=1))

    response = await client.get("/api/crawlers", headers=_bearer(token))

    assert 401 == response.status_code
    assert "Invalid or expired session token" == response.json()["message"]


@pytest.mark.anyio
async def test_an_admin_token_opens_admin_routes(client, issue_token):
    response = await client.get(
        "/api/users", headers=_bearer(issue_token(roles=["user", "admin"]))
    )

    assert 200 == response.status_code


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["user", "viewer"])
async def test_a_non_admin_token_is_a_403_on_admin_routes(client, issue_token, role):
    response = await client.get(
        "/api/users", headers=_bearer(issue_token(roles=[role]))
    )

    assert 403 == response.status_code
