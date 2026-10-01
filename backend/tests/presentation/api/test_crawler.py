import pytest


@pytest.mark.anyio
async def test_crawler_crud(client, act_as, venues_crawler):
    member = act_as("member")

    created = await client.post("/api/crawlers", json=venues_crawler)
    crawler_id = created.json()["id"]
    updated = await client.patch(
        f"/api/crawlers/{crawler_id}", json={"title": "Renamed"}
    )
    listed = await client.get(
        "/api/crawlers", params={"dataset_id": venues_crawler["dataset_id"]}
    )
    deleted = await client.delete(f"/api/crawlers/{crawler_id}")
    missing = await client.get(f"/api/crawlers/{crawler_id}")

    assert 201 == created.status_code
    assert venues_crawler["fields"] == created.json()["fields"]
    assert "schema" not in created.json()
    assert member.id == created.json()["user_id"]
    assert "Renamed" == updated.json()["title"]
    assert [crawler_id] == [crawler["id"] for crawler in listed.json()]
    assert 204 == deleted.status_code
    assert 404 == missing.status_code


@pytest.mark.anyio
async def test_create_crawler_rejects_fields_missing_a_required_one(
    client, act_as, venues_crawler
):
    act_as("member")

    response = await client.post(
        "/api/crawlers", json={**venues_crawler, "fields": ["name"]}
    )

    assert 400 == response.status_code
    assert "item_id" in response.json()["message"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "overrides",
    [
        {"schedule": "not cron"},
        {"queue": "testing"},
    ],
)
async def test_create_crawler_rejects_invalid_fields(
    client, act_as, overrides, venues_crawler
):
    act_as("member")

    response = await client.post("/api/crawlers", json={**venues_crawler, **overrides})

    assert 422 == response.status_code


@pytest.mark.anyio
async def test_create_crawler_needs_an_existing_source(client, act_as, venues_crawler):
    act_as("member")

    response = await client.post(
        "/api/crawlers", json={**venues_crawler, "source_id": "missing"}
    )

    assert 400 == response.status_code
    assert "source" in response.json()["message"].lower()


@pytest.mark.anyio
async def test_create_crawler_needs_an_existing_dataset(client, act_as, venues_crawler):
    act_as("member")

    response = await client.post(
        "/api/crawlers", json={**venues_crawler, "dataset_id": "missing"}
    )

    assert 400 == response.status_code
    assert "dataset" in response.json()["message"].lower()
