import pytest


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/users"),
        ("POST", "/api/users"),
        ("GET", "/api/users/user-1"),
        ("PATCH", "/api/users/user-1"),
        ("DELETE", "/api/users/user-1"),
    ],
)
async def test_user_routes_reject_non_admins(client, act_as, method, path):
    act_as("member")

    response = await client.request(method, path, json={})

    assert 403 == response.status_code


@pytest.mark.anyio
async def test_admin_creates_updates_and_deletes_a_user(client, act_as):
    act_as("admin")

    created = await client.post(
        "/api/users",
        json={"email": "carol@example.com", "password": "Secret123"},
    )
    user_id = created.json()["id"]
    updated = await client.patch(f"/api/users/{user_id}", json={"role": "viewer"})
    listed = await client.get("/api/users")
    deleted = await client.delete(f"/api/users/{user_id}")
    missing = await client.get(f"/api/users/{user_id}")

    assert 201 == created.status_code
    assert "hashed_password" not in created.json()
    assert "viewer" == updated.json()["role"]
    assert [user_id] == [user["id"] for user in listed.json()["items"]]
    assert 204 == deleted.status_code
    assert 404 == missing.status_code


@pytest.mark.anyio
async def test_create_user_rejects_an_invalid_email(client, act_as):
    act_as("admin")

    response = await client.post(
        "/api/users",
        json={"email": "not-an-email", "password": "Secret123"},
    )

    assert 422 == response.status_code
