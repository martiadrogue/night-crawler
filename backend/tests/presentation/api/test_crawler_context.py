import pytest


async def _published_crawler_with_run(client, venues_crawler, context=None):
    crawler = await client.post("/api/crawlers", json=venues_crawler)
    crawler_id = crawler.json()["id"]
    [draft] = (await client.get(f"/api/crawlers/{crawler_id}/versions")).json()
    await client.post(f"/api/crawlers/{crawler_id}/versions/{draft['id']}/publish")
    execution = await client.post(
        f"/api/crawlers/{crawler_id}/executions", json={"context": context or {}}
    )
    return crawler_id, execution.json()["id"]


@pytest.mark.anyio
async def test_read_edit_and_delete_the_last_executions_context(
    client, act_as, venues_crawler
):
    act_as("member")
    crawler_id, execution_id = await _published_crawler_with_run(
        client, venues_crawler, {"token": "a"}
    )

    set_list = await client.put(
        f"/api/crawlers/{crawler_id}/context/parish[]", json={"value": ["Encamp"]}
    )
    set_scalar = await client.put(
        f"/api/crawlers/{crawler_id}/context/token", json={"value": "b"}
    )
    deleted = await client.delete(f"/api/crawlers/{crawler_id}/context/token")
    current = await client.get(f"/api/crawlers/{crawler_id}/context")

    assert 200 == set_list.status_code
    assert "b" == set_scalar.json()["values"]["token"]
    assert 204 == deleted.status_code
    assert execution_id == current.json()["crawler_execution_id"]
    assert {"parish[]": ["Encamp"]} == current.json()["values"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("key", "value"),
    [("token", {"nested": 1}), ("parish[]", "not a list"), ("_pagination", 1)],
)
async def test_context_values_must_follow_the_rules(
    client, act_as, venues_crawler, key, value
):
    act_as("member")
    crawler_id, _execution_id = await _published_crawler_with_run(
        client, venues_crawler
    )

    response = await client.put(
        f"/api/crawlers/{crawler_id}/context/{key}", json={"value": value}
    )

    assert 400 == response.status_code


@pytest.mark.anyio
async def test_a_crawler_without_executions_has_no_context(
    client, act_as, venues_crawler
):
    act_as("member")
    crawler = await client.post("/api/crawlers", json=venues_crawler)

    response = await client.get(f"/api/crawlers/{crawler.json()['id']}/context")

    assert 404 == response.status_code


@pytest.mark.anyio
async def test_harvested_keys_are_listed_and_cannot_be_edited(
    client, act_as, venues_crawler
):
    act_as("member")
    crawler = (await client.post("/api/crawlers", json=venues_crawler)).json()
    [draft] = (await client.get(f"/api/crawlers/{crawler['id']}/versions")).json()
    await client.post(
        f"/api/templates/{draft['message_template_root_id']}/selectors",
        json={"title": "next_token", "type": "value", "path": "//a/@href"},
    )
    versions = (await client.get(f"/api/crawlers/{crawler['id']}/versions")).json()
    draft_id = next(v["id"] for v in versions if "draft" == v["status"])
    await client.post(f"/api/crawlers/{crawler['id']}/versions/{draft_id}/publish")
    await client.post(
        f"/api/crawlers/{crawler['id']}/executions",
        json={"context": {"next_token": "t1", "api_key": "secret"}},
    )
    url = f"/api/crawlers/{crawler['id']}/context"

    current = await client.get(url)
    refused = await client.put(f"{url}/next_token", json={"value": "t2"})
    allowed = await client.put(f"{url}/api_key", json={"value": "new"})
    deleted = await client.delete(f"{url}/next_token")

    assert {"next_token", "next_token[]"} == set(current.json()["harvested_keys"])
    assert 409 == refused.status_code
    assert "set by a selector" in refused.json()["message"]
    assert 200 == allowed.status_code
    assert 204 == deleted.status_code
    assert {"api_key": "new"} == (await client.get(url)).json()["values"]


@pytest.mark.anyio
async def test_a_crawler_without_selectors_harvests_no_keys(
    client, act_as, venues_crawler
):
    act_as("member")
    crawler_id, _execution_id = await _published_crawler_with_run(
        client, venues_crawler, {"token": "a"}
    )

    current = await client.get(f"/api/crawlers/{crawler_id}/context")

    assert [] == current.json()["harvested_keys"]
