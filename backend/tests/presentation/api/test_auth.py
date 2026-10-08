import pytest


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/api/auth/register", "/api/auth/login"])
async def test_the_local_login_routes_are_gone(client, path):
    response = await client.post(
        path, json={"email": "dora@example.com", "password": "Secret123"}
    )

    assert 404 == response.status_code


@pytest.mark.anyio
async def test_the_root_route_is_public(client):
    response = await client.get("/")

    assert 200 == response.status_code
