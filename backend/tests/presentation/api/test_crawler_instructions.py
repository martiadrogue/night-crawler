import pytest
import yaml

INSTRUCTIONS_YAML = """\
format: night-crawler/instructions/v1
settings:
  root: search
templates:
  search:
    action: POST
    url: https://example.com/search
    body: |
      {"q": "{{query}}"}
aids:
  search:
    render_mode: stealth
    retry_codes: ["429", timeout]
selectors:
  results:
    template: search
    type: iterator
    path: results
  item_id:
    template: search
    parent: results
    type: value
    path: id
    title: item_id
"""


async def _draft_id(client, venues_crawler) -> str:
    crawler = await client.post("/api/crawlers", json=venues_crawler)
    versions = await client.get(f"/api/crawlers/{crawler.json()['id']}/versions")
    return versions.json()[0]["id"]


@pytest.mark.anyio
async def test_import_yaml_then_export_it_as_a_file(client, act_as, venues_crawler):
    act_as("member")
    draft_id = await _draft_id(client, venues_crawler)

    imported = await client.put(
        f"/api/crawler-versions/{draft_id}/instructions",
        content=INSTRUCTIONS_YAML,
        headers={"Content-Type": "application/yaml"},
    )
    exported = await client.get(f"/api/crawler-versions/{draft_id}/instructions")

    assert 200 == imported.status_code
    assert draft_id == imported.json()["id"]
    assert 200 == exported.status_code
    assert exported.headers["content-type"].startswith("application/yaml")
    assert "attachment" in exported.headers["content-disposition"]
    document = yaml.safe_load(exported.text)
    assert "night-crawler/instructions/v1" == document["format"]
    assert {"action": "POST", "url": "https://example.com/search"}.items() <= (
        document["templates"]["template_1"].items()
    )
    assert "body: |" in exported.text
    assert "template_1.iterator" == document["selectors"]["item_id"]["parent"]
    assert "retry_codes: ['429', timeout]" in exported.text
    assert {"render_mode": "stealth", "retry_codes": ["429", "timeout"]} == (
        document["aids"]["template_1"]
    )


@pytest.mark.anyio
async def test_import_refuses_a_json_upload(client, act_as, venues_crawler):
    act_as("member")
    draft_id = await _draft_id(client, venues_crawler)

    response = await client.put(
        f"/api/crawler-versions/{draft_id}/instructions",
        content='{"templates": {"a": {"action": "GET", "url": "x"}}}',
        headers={"Content-Type": "application/json"},
    )

    assert 415 == response.status_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content",
    [
        "templates: [unclosed",
        "templates: {}",
        "settings: {root: a}\ntemplates:\n  a: {action: FETCH, url: x}",
        "base: &base {action: GET, url: x}\ntemplates:\n  a: *base",
    ],
)
async def test_import_rejects_malformed_files(client, act_as, venues_crawler, content):
    act_as("member")
    draft_id = await _draft_id(client, venues_crawler)

    response = await client.put(
        f"/api/crawler-versions/{draft_id}/instructions", content=content
    )

    assert 422 == response.status_code


@pytest.mark.anyio
async def test_import_rejects_an_oversized_file(client, act_as, venues_crawler):
    act_as("member")
    draft_id = await _draft_id(client, venues_crawler)

    response = await client.put(
        f"/api/crawler-versions/{draft_id}/instructions",
        content="# " + "x" * (1024 * 1024),
    )

    assert 413 == response.status_code


@pytest.mark.anyio
async def test_instructions_require_authentication(client):
    exported = await client.get("/api/crawler-versions/any/instructions")
    imported = await client.put(
        "/api/crawler-versions/any/instructions", content=INSTRUCTIONS_YAML
    )

    assert 401 == exported.status_code
    assert 401 == imported.status_code
