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
    (api_client.register, ("e@x.io", "pw"), "POST", "/api/auth/register"),
    (api_client.login, ("e@x.io", "pw"), "POST", "/api/auth/login"),
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
async def test_download_execution_csv_returns_the_csv_text(respond):
    seen = respond(
        lambda request: httpx.Response(
            200,
            text="item_id,name\r\np1,Casa\r\n",
            headers={"content-type": "text/csv"},
        )
    )

    csv_text = await api_client.download_execution_csv("tok", "e1")

    assert "item_id,name\r\np1,Casa\r\n" == csv_text
    assert "/api/crawler-executions/e1/dataset.csv" == seen[0].url.path
    assert "Bearer tok" == seen[0].headers["authorization"]


@pytest.mark.anyio
async def test_download_execution_csv_raises_the_api_message(respond):
    respond(lambda request: httpx.Response(404, json={"message": "No CSV yet."}))

    with pytest.raises(api_client.ApiError) as exc_info:
        await api_client.download_execution_csv("tok", "e1")

    assert "No CSV yet." == exc_info.value.message
