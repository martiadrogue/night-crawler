import pytest


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/proxies"),
        ("PATCH", "/api/proxies/proxy-1"),
        ("DELETE", "/api/proxies/proxy-1"),
        ("PATCH", "/api/rate-limits/rate-limit-1"),
        ("DELETE", "/api/rate-limits/rate-limit-1"),
    ],
)
async def test_shared_resource_writes_are_admin_only(client, act_as, method, path):
    act_as("member")

    response = await client.request(method, path, json={})

    assert 403 == response.status_code


@pytest.mark.anyio
async def test_admin_manages_proxies_and_rate_limits(client, act_as):
    act_as("admin")

    rate_limit = await client.post(
        "/api/rate-limits", json={"rate_limit_string": "10/second"}
    )
    proxy = await client.post(
        "/api/proxies",
        json={
            "url": "http://proxy:8080",
            "password": "secret",
            "rate_limit_id": rate_limit.json()["id"],
        },
    )
    proxy_id = proxy.json()["id"]
    updated = await client.patch(f"/api/proxies/{proxy_id}", json={"user": "bob"})
    deleted_rate_limit = await client.delete(
        f"/api/rate-limits/{rate_limit.json()['id']}"
    )
    fetched = await client.get(f"/api/proxies/{proxy_id}")
    deleted_proxy = await client.delete(f"/api/proxies/{proxy_id}")

    assert 201 == rate_limit.status_code
    assert 201 == proxy.status_code
    assert "password" not in proxy.json()
    assert "bob" == updated.json()["user"]
    assert 204 == deleted_rate_limit.status_code
    assert None is fetched.json()["rate_limit_id"]
    assert 204 == deleted_proxy.status_code


@pytest.mark.anyio
async def test_members_can_read_proxies_and_create_rate_limits(client, act_as):
    act_as("member")

    proxies = await client.get("/api/proxies")
    rate_limit = await client.post(
        "/api/rate-limits", json={"rate_limit_string": "garbage"}
    )

    assert 200 == proxies.status_code
    assert 400 == rate_limit.status_code
