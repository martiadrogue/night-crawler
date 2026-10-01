import pytest


@pytest.mark.anyio
async def test_register_login_and_use_the_token(client):
    registered = await client.post(
        "/api/auth/register",
        json={"email": "dora@example.com", "password": "Secret123"},
    )
    logged_in = await client.post(
        "/api/auth/login",
        json={"email": "dora@example.com", "password": "Secret123"},
    )
    token = logged_in.json()["access_token"]

    response = await client.get(
        "/api/crawlers", headers={"Authorization": f"Bearer {token}"}
    )

    assert 201 == registered.status_code
    assert 200 == logged_in.status_code
    assert "bearer" == logged_in.json()["token_type"]
    assert 200 == response.status_code


@pytest.mark.anyio
async def test_login_rejects_a_wrong_password(client):
    await client.post(
        "/api/auth/register",
        json={"email": "dora@example.com", "password": "Secret123"},
    )

    response = await client.post(
        "/api/auth/login",
        json={"email": "dora@example.com", "password": "Wrong123"},
    )

    assert 401 == response.status_code


@pytest.mark.anyio
async def test_login_temporarily_locks_after_repeated_failures(client):
    await client.post(
        "/api/auth/register",
        json={"email": "locked@example.com", "password": "Secret123"},
    )

    for _ in range(5):
        response = await client.post(
            "/api/auth/login",
            json={"email": "locked@example.com", "password": "Wrong123"},
        )
        assert 401 == response.status_code

    response = await client.post(
        "/api/auth/login",
        json={"email": "locked@example.com", "password": "Secret123"},
    )

    assert 429 == response.status_code
    assert "Too many failed login attempts" in response.json()["message"]


@pytest.mark.anyio
async def test_register_rate_limits_repeated_attempts_from_one_ip(client):
    registration = {
        "email": "existing@example.com",
        "password": "Secret123",
    }
    await client.post("/api/auth/register", json=registration)

    for _ in range(9):
        response = await client.post("/api/auth/register", json=registration)
        assert 400 == response.status_code

    response = await client.post(
        "/api/auth/register",
        json={"email": "another@example.com", "password": "Secret123"},
    )

    assert 429 == response.status_code
    assert "Too many registration attempts" in response.json()["message"]


@pytest.mark.anyio
async def test_protected_routes_need_a_token(client):
    response = await client.get("/api/crawlers")

    assert 401 == response.status_code


@pytest.mark.anyio
async def test_protected_routes_reject_an_invalid_token(client):
    response = await client.get(
        "/api/crawlers", headers={"Authorization": "Bearer not-a-jwt"}
    )

    assert 401 == response.status_code
    assert "Invalid or expired session token" == response.json()["message"]


@pytest.mark.anyio
async def test_the_root_route_is_public(client):
    response = await client.get("/")

    assert 200 == response.status_code
