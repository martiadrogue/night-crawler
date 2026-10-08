import json

import httpx
import pytest
from night_crawler import api_client


@pytest.fixture
def respond(monkeypatch):
    """Route the client through a handler; returns the requests seen."""
    seen: list[httpx.Request] = []

    def install(handler):
        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(api_client, "TRANSPORT", httpx.MockTransport(recording))
        return seen

    return install


@pytest.mark.anyio
async def test_requests_carry_the_token_and_return_json(respond):
    seen = respond(lambda request: httpx.Response(200, json=[{"id": "c1"}]))

    crawlers = await api_client.list_crawlers("tok")

    assert [{"id": "c1"}] == crawlers
    assert "Bearer tok" == seen[0].headers["authorization"]
    assert "/api/crawlers" == seen[0].url.path


@pytest.mark.anyio
async def test_api_errors_carry_the_backend_message(respond):
    respond(lambda request: httpx.Response(409, json={"message": "Nope."}))

    with pytest.raises(api_client.ApiError) as exc_info:
        await api_client.publish_version("tok", "c1", "v1")

    assert 409 == exc_info.value.status_code
    assert "Nope." == exc_info.value.message


@pytest.mark.anyio
async def test_validation_errors_are_flattened(respond):
    respond(
        lambda request: httpx.Response(
            422, json={"detail": [{"loc": ["body", "url"], "msg": "too long"}]}
        )
    )

    with pytest.raises(api_client.ApiError) as exc_info:
        await api_client.create_template("tok", "v1", {"url": "x"})

    assert "body.url: too long" == exc_info.value.message


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")],
    ids=["down", "timeout"],
)
async def test_an_unreachable_api_is_an_api_error(respond, error):
    def unreachable(request):
        raise error

    respond(unreachable)

    with pytest.raises(api_client.ApiError) as exc_info:
        await api_client.list_crawlers("tok")

    assert 503 == exc_info.value.status_code
    assert "unreachable" in exc_info.value.message


@pytest.mark.anyio
async def test_a_missing_aid_is_none(respond):
    respond(
        lambda request: httpx.Response(404, json={"message": "Message aid not found."})
    )

    assert None is await api_client.get_aid("tok", "t1")


@pytest.mark.anyio
async def test_empty_responses_are_none_and_none_params_are_dropped(respond):
    seen = respond(lambda request: httpx.Response(204))

    assert None is await api_client.delete_crawler("tok", "c1")
    await api_client.list_crawlers("tok", source=None, dataset="venues")

    assert "dataset=venues" == seen[1].url.query.decode()


ENDPOINTS = [
    (api_client.get_crawler, ("tok", "c1"), "GET", "/api/crawlers/c1"),
    (api_client.create_crawler, ("tok", {}), "POST", "/api/crawlers"),
    (api_client.update_crawler, ("tok", "c1", {}), "PATCH", "/api/crawlers/c1"),
    (api_client.list_versions, ("tok", "c1"), "GET", "/api/crawlers/c1/versions"),
    (api_client.get_version, ("tok", "v1"), "GET", "/api/crawler-versions/v1"),
    (
        api_client.create_draft,
        ("tok", "c1"),
        "POST",
        "/api/crawlers/c1/versions/draft",
    ),
    (
        api_client.update_version,
        ("tok", "v1", {}),
        "PATCH",
        "/api/crawler-versions/v1",
    ),
    (
        api_client.set_root_template,
        ("tok", "v1", "t1"),
        "PUT",
        "/api/crawler-versions/v1/root-template",
    ),
    (api_client.delete_version, ("tok", "v1"), "DELETE", "/api/crawler-versions/v1"),
    (
        api_client.list_templates,
        ("tok", "v1"),
        "GET",
        "/api/crawler-versions/v1/templates",
    ),
    (api_client.update_template, ("tok", "t1", {}), "PATCH", "/api/templates/t1"),
    (api_client.delete_template, ("tok", "t1"), "DELETE", "/api/templates/t1"),
    (api_client.list_selectors, ("tok", "t1"), "GET", "/api/templates/t1/selectors"),
    (
        api_client.create_selector,
        ("tok", "t1", {}),
        "POST",
        "/api/templates/t1/selectors",
    ),
    (api_client.update_selector, ("tok", "s1", {}), "PATCH", "/api/selectors/s1"),
    (api_client.delete_selector, ("tok", "s1"), "DELETE", "/api/selectors/s1"),
    (api_client.put_aid, ("tok", "t1", {}), "PUT", "/api/templates/t1/aid"),
    (api_client.delete_aid, ("tok", "t1"), "DELETE", "/api/templates/t1/aid"),
    (
        api_client.create_test_execution,
        ("tok", "v1"),
        "POST",
        "/api/crawler-versions/v1/test-executions",
    ),
    (api_client.list_sources, ("tok",), "GET", "/api/sources"),
    (api_client.create_source, ("tok", {}), "POST", "/api/sources"),
    (api_client.update_source, ("tok", "s1", {}), "PATCH", "/api/sources/s1"),
    (api_client.delete_source, ("tok", "s1"), "DELETE", "/api/sources/s1"),
    (api_client.list_datasets, ("tok",), "GET", "/api/datasets"),
    (api_client.create_dataset, ("tok", {}), "POST", "/api/datasets"),
    (api_client.update_dataset, ("tok", "d1", {}), "PATCH", "/api/datasets/d1"),
    (api_client.delete_dataset, ("tok", "d1"), "DELETE", "/api/datasets/d1"),
    (api_client.get_context, ("tok", "c1"), "GET", "/api/crawlers/c1/context"),
    (
        api_client.set_context_value,
        ("tok", "c1", "parish[]", ["a"]),
        "PUT",
        "/api/crawlers/c1/context/parish[]",
    ),
    (
        api_client.delete_context_value,
        ("tok", "c1", "api_key"),
        "DELETE",
        "/api/crawlers/c1/context/api_key",
    ),
    (api_client.list_proxies, ("tok",), "GET", "/api/proxies"),
    (api_client.list_rate_limits, ("tok",), "GET", "/api/rate-limits"),
    (api_client.create_rate_limit, ("tok", {}), "POST", "/api/rate-limits"),
    (
        api_client.update_rate_limit,
        ("tok", "r1", {}),
        "PATCH",
        "/api/rate-limits/r1",
    ),
    (api_client.delete_rate_limit, ("tok", "r1"), "DELETE", "/api/rate-limits/r1"),
    (
        api_client.import_instructions,
        ("tok", "v1", "templates: {}"),
        "PUT",
        "/api/crawler-versions/v1/instructions",
    ),
    (
        api_client.create_instruction_generation,
        ("tok", "v1", "comedy shows"),
        "POST",
        "/api/crawler-versions/v1/instruction-generations",
    ),
    (
        api_client.get_instruction_generation,
        ("tok", "g1"),
        "GET",
        "/api/instruction-generations/g1",
    ),
    (api_client.get_execution, ("tok", "e1"), "GET", "/api/crawler-executions/e1"),
    (
        api_client.get_execution_history,
        ("tok", "c1"),
        "GET",
        "/api/crawlers/c1/execution-history",
    ),
    (
        api_client.get_execution_summary,
        ("tok", "c1"),
        "GET",
        "/api/crawlers/c1/execution-summary",
    ),
    (api_client.list_users, ("tok", 0), "GET", "/api/users"),
    (api_client.create_user, ("tok", {}), "POST", "/api/users"),
    (api_client.update_user, ("tok", "u1", {}), "PATCH", "/api/users/u1"),
    (api_client.disable_user, ("tok", "u1"), "DELETE", "/api/users/u1"),
]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("call", "args", "method", "path"),
    ENDPOINTS,
    ids=[endpoint[0].__name__ for endpoint in ENDPOINTS],
)
async def test_each_call_hits_its_endpoint(respond, call, args, method, path):
    seen = respond(lambda request: httpx.Response(200, json={"id": "x"}))

    await call(*args)

    assert (method, path) == (seen[0].method, seen[0].url.path)


def test_there_is_no_way_to_archive_a_version_directly():
    assert not hasattr(api_client, "archive_version")


@pytest.mark.anyio
async def test_list_executions_sends_only_the_filters_set(respond):
    page = {"items": [], "limit": 50, "offset": 0, "has_more": False}
    seen = respond(lambda request: httpx.Response(200, json=page))

    listed = await api_client.list_executions(
        "tok",
        {"status": "running", "queue": "priority", "crawler_title": None, "offset": 50},
    )

    assert page == listed
    assert "/api/crawler-executions" == seen[0].url.path
    assert {"status": "running", "queue": "priority", "offset": "50"} == dict(
        seen[0].url.params
    )


@pytest.mark.anyio
async def test_set_context_value_sends_the_value_wrapped(respond):
    seen = respond(lambda request: httpx.Response(200, json={"values": {}}))

    await api_client.set_context_value("tok", "c1", "page", 3)

    assert b'{"value":3}' == seen[0].content.replace(b" ", b"")


@pytest.mark.anyio
async def test_download_execution_sample_csv_returns_its_name_and_text(respond):
    seen = respond(
        lambda request: httpx.Response(
            200,
            text="item_id,name\r\np1,Casa\r\n",
            headers={
                "content-type": "text/csv",
                "content-disposition": (
                    'attachment; filename="c1_e1_20261007T065600Z-sample.csv"'
                ),
            },
        )
    )

    filename, csv_text = await api_client.download_execution_sample_csv("tok", "e1")

    assert "c1_e1_20261007T065600Z-sample.csv" == filename
    assert "item_id,name\r\np1,Casa\r\n" == csv_text
    assert "/api/crawler-executions/e1/dataset-sample.csv" == seen[0].url.path
    assert "Bearer tok" == seen[0].headers["authorization"]


@pytest.mark.anyio
async def test_a_sample_without_a_file_name_is_named_after_the_run(respond):
    respond(lambda request: httpx.Response(200, text="item_id\r\n"))

    filename, _csv_text = await api_client.download_execution_sample_csv("tok", "e1")

    assert "e1-sample.csv" == filename


@pytest.mark.anyio
async def test_download_execution_sample_csv_raises_the_api_message(respond):
    respond(lambda request: httpx.Response(404, json={"message": "No CSV yet."}))

    with pytest.raises(api_client.ApiError) as exc_info:
        await api_client.download_execution_sample_csv("tok", "e1")

    assert "No CSV yet." == exc_info.value.message


@pytest.mark.anyio
async def test_export_instructions_returns_the_file_text(respond):
    seen = respond(
        lambda request: httpx.Response(
            200, text="templates: {}\n", headers={"content-type": "application/yaml"}
        )
    )

    text = await api_client.export_instructions("tok", "v1")

    assert "templates: {}\n" == text
    assert "/api/crawler-versions/v1/instructions" == seen[0].url.path


@pytest.mark.anyio
async def test_import_instructions_sends_the_file_as_is(respond):
    seen = respond(lambda request: httpx.Response(200, json={"id": "v2"}))

    version = await api_client.import_instructions("tok", "v1", "templates: {}\n")

    assert {"id": "v2"} == version
    assert b"templates: {}\n" == seen[0].content
    assert "application/yaml" == seen[0].headers["content-type"]


@pytest.mark.anyio
async def test_create_instruction_generation_sends_the_prompt(respond):
    seen = respond(
        lambda request: httpx.Response(202, json={"id": "g1", "status": "pending"})
    )

    generation = await api_client.create_instruction_generation(
        "tok", "v1", "comedy shows"
    )

    assert {"id": "g1", "status": "pending"} == generation
    assert {"prompt": "comedy shows"} == json.loads(seen[0].content)


@pytest.mark.anyio
async def test_list_users_asks_for_the_page_at_offset(respond):
    page = {"items": [], "limit": 50, "offset": 50, "has_more": False}
    seen = respond(lambda request: httpx.Response(200, json=page))

    listed = await api_client.list_users("tok", 50)

    assert page == listed
    assert {"limit": "50", "offset": "50"} == dict(seen[0].url.params)


@pytest.mark.anyio
async def test_get_execution_history_asks_for_the_days(respond):
    seen = respond(lambda request: httpx.Response(200, json={"runs": []}))

    await api_client.get_execution_history("tok", "c1", days=7)

    assert {"days": "7"} == dict(seen[0].url.params)


def test_logging_in_is_keycloak_s_not_the_api_s():
    assert not hasattr(api_client, "login")
    assert not hasattr(api_client, "register")
