import pytest


async def _crawler_and_draft(client, venues_crawler) -> tuple[str, dict]:
    crawler = await client.post("/api/crawlers", json=venues_crawler)
    crawler_id = crawler.json()["id"]
    versions = await client.get(f"/api/crawlers/{crawler_id}/versions")
    [draft] = versions.json()
    return crawler_id, draft


@pytest.mark.anyio
async def test_build_a_version_tree_publish_and_create_an_execution(
    client, act_as, venues_crawler, execution_dispatcher
):
    act_as("member")
    crawler_id, draft = await _crawler_and_draft(client, venues_crawler)
    root_id = draft["message_template_root_id"]

    root = await client.patch(
        f"/api/templates/{root_id}",
        json={"url": "https://www.google.com/maps/search/restaurants+andorra"},
    )
    detail = await client.post(
        f"/api/crawler-versions/{draft['id']}/templates",
        json={"action": "GET", "url": "https://maps.google.com/?cid={{item_id}}"},
    )
    iterator = await client.post(
        f"/api/templates/{root_id}/selectors",
        json={"path": "//div[@role='article']", "type": "iterator"},
    )
    field = await client.post(
        f"/api/templates/{root_id}/selectors",
        json={
            "path": "./@data-cid",
            "type": "value",
            "target": "data-cid",
            "title": "item_id",
            "parent_selector_id": iterator.json()["id"],
        },
    )
    aid = await client.put(
        f"/api/templates/{root_id}/aid",
        json={"render_mode": "playwright", "ttl": 30},
    )
    settings = await client.patch(
        f"/api/crawler-versions/{draft['id']}",
        json={"is_proxy_ladder_enabled": True},
    )
    scheduled = await client.patch(
        f"/api/crawlers/{crawler_id}", json={"queue": "priority"}
    )
    published = await client.post(
        f"/api/crawlers/{crawler_id}/versions/{draft['id']}/publish"
    )
    execution = await client.post(f"/api/crawlers/{crawler_id}/executions")
    executions = await client.get(f"/api/crawlers/{crawler_id}/executions")
    fetched = await client.get(f"/api/crawler-executions/{execution.json()['id']}")

    assert 200 == root.status_code
    assert 201 == detail.status_code
    assert 201 == iterator.status_code
    assert iterator.json()["id"] == field.json()["parent_selector_id"]
    assert "playwright" == aid.json()["render_mode"]
    assert "queue" not in settings.json()
    assert "priority" == scheduled.json()["queue"]
    assert "published" == published.json()["status"]
    assert 201 == execution.status_code
    assert "pending" == execution.json()["status"]
    assert "priority" == execution.json()["queue"]
    assert [execution.json()["id"]] == [item["id"] for item in executions.json()]
    assert draft["id"] == fetched.json()["crawler_version_id"]
    assert [(execution.json()["id"], "priority")] == execution_dispatcher.dispatched


@pytest.mark.anyio
async def test_create_execution_without_a_published_version_conflicts(
    client, act_as, venues_crawler
):
    act_as("member")
    crawler_id, _draft = await _crawler_and_draft(client, venues_crawler)

    response = await client.post(f"/api/crawlers/{crawler_id}/executions")

    assert 409 == response.status_code


@pytest.mark.anyio
async def test_draft_lifecycle_routes(client, act_as, venues_crawler):
    act_as("member")
    crawler_id, draft = await _crawler_and_draft(client, venues_crawler)
    await client.post(f"/api/crawlers/{crawler_id}/versions/{draft['id']}/publish")

    second = await client.post(f"/api/crawlers/{crawler_id}/versions/draft")
    duplicate = await client.post(f"/api/crawlers/{crawler_id}/versions/draft")
    templates = await client.get(
        f"/api/crawler-versions/{second.json()['id']}/templates"
    )
    new_root = await client.post(
        f"/api/crawler-versions/{second.json()['id']}/templates",
        json={"action": "GET", "url": "https://example.com"},
    )
    rerooted = await client.put(
        f"/api/crawler-versions/{second.json()['id']}/root-template",
        json={"message_template_id": new_root.json()["id"]},
    )
    deleted = await client.delete(f"/api/crawler-versions/{second.json()['id']}")
    remaining = await client.get(f"/api/crawlers/{crawler_id}/versions")

    assert 201 == second.status_code
    assert "version_number" not in second.json()
    assert 409 == duplicate.status_code
    assert 1 == len(templates.json())
    assert new_root.json()["id"] == rerooted.json()["message_template_root_id"]
    assert 204 == deleted.status_code
    assert [draft["id"]] == [version["id"] for version in remaining.json()]


@pytest.mark.anyio
async def test_selector_and_aid_validation_errors(client, act_as, venues_crawler):
    act_as("member")
    _crawler_id, draft = await _crawler_and_draft(client, venues_crawler)
    root_id = draft["message_template_root_id"]

    unknown_type = await client.post(
        f"/api/templates/{root_id}/selectors", json={"path": "//a", "type": "magic"}
    )
    pagination_without_config = await client.post(
        f"/api/templates/{root_id}/selectors",
        json={"path": "//nav", "type": "pagination"},
    )
    unknown_proxy = await client.put(
        f"/api/templates/{root_id}/aid", json={"selected_proxy_id": "missing"}
    )
    bad_ttl = await client.put(f"/api/templates/{root_id}/aid", json={"ttl": 0})

    assert 422 == unknown_type.status_code
    assert 422 == pagination_without_config.status_code
    assert 404 == unknown_proxy.status_code
    assert 422 == bad_ttl.status_code


@pytest.mark.anyio
async def test_template_selector_and_aid_deletes(client, act_as, venues_crawler):
    act_as("member")
    _crawler_id, draft = await _crawler_and_draft(client, venues_crawler)
    root_id = draft["message_template_root_id"]
    template = await client.post(
        f"/api/crawler-versions/{draft['id']}/templates",
        json={"action": "GET", "url": "https://example.com"},
    )
    template_id = template.json()["id"]
    selector = await client.post(
        f"/api/templates/{template_id}/selectors", json={"path": "//a", "type": "value"}
    )
    await client.put(f"/api/templates/{template_id}/aid", json={})

    deleted_selector = await client.delete(f"/api/selectors/{selector.json()['id']}")
    deleted_aid = await client.delete(f"/api/templates/{template_id}/aid")
    deleted_template = await client.delete(f"/api/templates/{template_id}")
    root_delete = await client.delete(f"/api/templates/{root_id}")

    assert 204 == deleted_selector.status_code
    assert 204 == deleted_aid.status_code
    assert 204 == deleted_template.status_code
    assert 409 == root_delete.status_code


@pytest.mark.anyio
async def test_create_execution_with_a_seeded_context(client, act_as, venues_crawler):
    act_as("member")
    crawler_id, draft = await _crawler_and_draft(client, venues_crawler)
    await client.post(f"/api/crawlers/{crawler_id}/versions/{draft['id']}/publish")

    created = await client.post(
        f"/api/crawlers/{crawler_id}/executions",
        json={"context": {"parish[]": ["Canillo"], "google_api_key": "secret"}},
    )
    fetched = await client.get(f"/api/crawler-executions/{created.json()['id']}")

    assert 201 == created.status_code
    assert ["google_api_key", "parish[]"] == fetched.json()["context_keys"]
    assert "secret" not in created.text


@pytest.mark.anyio
async def test_a_published_version_cannot_be_archived_directly(
    client, act_as, venues_crawler
):
    act_as("member")
    crawler_id, draft = await _crawler_and_draft(client, venues_crawler)
    await client.post(f"/api/crawlers/{crawler_id}/versions/{draft['id']}/publish")

    archived = await client.post(
        f"/api/crawlers/{crawler_id}/versions/{draft['id']}/archive"
    )
    version = await client.get(f"/api/crawler-versions/{draft['id']}")

    assert 404 == archived.status_code
    assert "published" == version.json()["status"]


@pytest.mark.anyio
async def test_a_test_run_of_the_draft_goes_to_the_testing_queue(
    client, act_as, venues_crawler, execution_dispatcher
):
    act_as("member")
    _crawler_id, draft = await _crawler_and_draft(client, venues_crawler)

    response = await client.post(f"/api/crawler-versions/{draft['id']}/test-executions")

    assert 201 == response.status_code
    assert "testing" == response.json()["queue"]
    assert draft["id"] == response.json()["crawler_version_id"]


@pytest.mark.anyio
async def test_a_selector_title_never_ends_in_brackets(client, act_as, venues_crawler):
    act_as("member")
    _crawler_id, draft = await _crawler_and_draft(client, venues_crawler)
    root_id = draft["message_template_root_id"]
    iterator = await client.post(
        f"/api/templates/{root_id}/selectors", json={"path": "//a", "type": "iterator"}
    )

    created = await client.post(
        f"/api/templates/{root_id}/selectors",
        json={
            "path": "./@href",
            "type": "value",
            "title": "links[]",
            "parent_selector_id": iterator.json()["id"],
        },
    )
    plain = await client.post(
        f"/api/templates/{root_id}/selectors",
        json={
            "path": "./@href",
            "type": "value",
            "title": "links",
            "parent_selector_id": iterator.json()["id"],
        },
    )
    renamed = await client.patch(
        f"/api/selectors/{plain.json()['id']}", json={"title": "links[]"}
    )

    assert 422 == created.status_code
    assert "[]" in created.text
    assert 201 == plain.status_code
    assert 422 == renamed.status_code
