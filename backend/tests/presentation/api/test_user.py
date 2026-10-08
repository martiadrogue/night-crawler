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
async def test_admin_creates_updates_and_disables_a_user(
    client, act_as, user_directory
):
    act_as("admin")
    user_directory.add("admin-1", "admin@example.com", "admin")

    created = await client.post(
        "/api/users",
        json={"email": "carol@example.com", "password": "Secret123"},
    )
    user_id = created.json()["id"]
    updated = await client.patch(f"/api/users/{user_id}", json={"role": "viewer"})
    listed = await client.get("/api/users")
    disabled = await client.delete(f"/api/users/{user_id}")
    kept = await client.get(f"/api/users/{user_id}")

    assert 201 == created.status_code
    assert "password" not in created.json()
    assert "viewer" == updated.json()["role"]
    assert ["admin-1", user_id] == [user["id"] for user in listed.json()["items"]]
    assert 204 == disabled.status_code
    assert (200, False) == (kept.status_code, kept.json()["is_enabled"])


@pytest.mark.anyio
async def test_disabling_the_last_admin_is_refused(client, act_as, user_directory):
    act_as("admin")
    user_directory.add("admin-1", "admin@example.com", "admin")

    response = await client.delete("/api/users/admin-1")

    assert 400 == response.status_code


@pytest.mark.anyio
async def test_create_user_rejects_an_invalid_email(client, act_as):
    act_as("admin")

    response = await client.post(
        "/api/users",
        json={"email": "not-an-email", "password": "Secret123"},
    )

    assert 422 == response.status_code
