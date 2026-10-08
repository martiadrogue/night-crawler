import re

import pytest
from night_crawler.core.di import REPOSITORY_FACTORIES
from night_crawler.domain.bundles.execution_plan import RunOutcome
from night_crawler.infrastructure.db.write_repositories import MongoWriteRepositories
from night_crawler.services import crawler_execution_service


async def _published_run(client, venues_crawler) -> dict:
    crawler_id = (await client.post("/api/crawlers", json=venues_crawler)).json()["id"]
    [draft] = (await client.get(f"/api/crawlers/{crawler_id}/versions")).json()
    await client.post(f"/api/crawlers/{crawler_id}/versions/{draft['id']}/publish")
    return (await client.post(f"/api/crawlers/{crawler_id}/executions")).json()


@pytest.mark.anyio
async def test_the_dashboard_lists_and_filters_every_run(
    client, act_as, venues_crawler, execution_dispatcher
):
    act_as("member")
    run = await _published_run(client, venues_crawler)

    listed = await client.get("/api/crawler-executions")
    pending = await client.get(
        "/api/crawler-executions",
        params={"status": "pending", "parsing_status": "pending"},
    )
    running = await client.get("/api/crawler-executions", params={"status": "running"})
    by_title = await client.get(
        "/api/crawler-executions",
        params={"crawler_title": "ANDORRA", "queue": "discovery"},
    )
    other_title = await client.get(
        "/api/crawler-executions", params={"crawler_title": "reviews"}
    )
    counts = await client.get("/api/crawler-executions/counts")

    assert 200 == listed.status_code
    assert [run["id"]] == [item["id"] for item in listed.json()["items"]]
    assert "Andorra venues" == listed.json()["items"][0]["crawler_title"]
    assert [run["id"]] == [item["id"] for item in pending.json()["items"]]
    assert [] == running.json()["items"]
    assert [run["id"]] == [item["id"] for item in by_title.json()["items"]]
    assert [] == other_title.json()["items"]
    assert 404 == counts.status_code


@pytest.mark.anyio
async def test_the_dashboard_rejects_an_unknown_status(client, act_as):
    act_as("member")

    status = await client.get("/api/crawler-executions", params={"status": "done"})
    queue = await client.get("/api/crawler-executions", params={"queue": "slow"})

    assert (422, 422) == (status.status_code, queue.status_code)


@pytest.mark.anyio
async def test_the_dashboard_needs_a_session(client):
    listed = await client.get("/api/crawler-executions")

    assert 401 == listed.status_code


@pytest.mark.anyio
async def test_a_run_without_a_csv_cannot_be_downloaded(
    client, act_as, venues_crawler, execution_dispatcher
):
    act_as("member")
    run = await _published_run(client, venues_crawler)

    pending = await client.get(f"/api/crawler-executions/{run['id']}/dataset.csv")

    assert 404 == pending.status_code


@pytest.mark.anyio
async def test_downloading_a_csv_needs_a_session(client):
    response = await client.get("/api/crawler-executions/any/dataset.csv")

    assert 401 == response.status_code


@pytest.mark.anyio
async def test_a_finished_run_downloads_as_a_csv_file(
    client,
    act_as,
    venues_crawler,
    execution_dispatcher,
    mongo_database,
    export_storage,
    execution_metrics,
):
    act_as("member")
    run = await _published_run(client, venues_crawler)
    mongo_client, database_name = mongo_database
    async with MongoWriteRepositories(
        mongo_client, database_name, REPOSITORY_FACTORIES
    ) as write_repositories:
        await crawler_execution_service.finish_execution(
            write_repositories,
            export_storage,
            execution_metrics,
            run["id"],
            RunOutcome(context={}, dataset_rows=[{"item_id": "p1", "name": "Casa"}]),
        )

    response = await client.get(f"/api/crawler-executions/{run['id']}/dataset.csv")

    assert 200 == response.status_code
    assert response.headers["content-type"].startswith("text/csv")
    assert f'attachment; filename="{run["id"]}.csv"' == (
        response.headers["content-disposition"]
    )
    assert "item_id,name\r\np1,Casa\r\n" == response.text


@pytest.mark.anyio
async def test_a_finished_run_downloads_as_a_sample_csv_file(
    client,
    act_as,
    venues_crawler,
    execution_dispatcher,
    mongo_database,
    export_storage,
    execution_metrics,
):
    act_as("member")
    run = await _published_run(client, venues_crawler)
    mongo_client, database_name = mongo_database
    async with MongoWriteRepositories(
        mongo_client, database_name, REPOSITORY_FACTORIES
    ) as write_repositories:
        await crawler_execution_service.finish_execution(
            write_repositories,
            export_storage,
            execution_metrics,
            run["id"],
            RunOutcome(context={}, dataset_rows=[{"item_id": "p1", "name": "Casa"}]),
        )

    response = await client.get(
        f"/api/crawler-executions/{run['id']}/dataset-sample.csv"
    )

    assert 200 == response.status_code
    assert response.headers["content-type"].startswith("text/csv")
    assert re.fullmatch(
        rf'attachment; filename="{run["crawler_id"]}_{run["id"]}_\d{{8}}T\d{{6}}Z'
        r'-sample\.csv"',
        response.headers["content-disposition"],
    )
    assert "item_id,name\r\np1,Casa\r\n" == response.text


@pytest.mark.anyio
async def test_a_sample_csv_needs_a_session_and_a_finished_run(
    client, act_as, venues_crawler, execution_dispatcher
):
    anonymous = await client.get("/api/crawler-executions/any/dataset-sample.csv")
    act_as("member")
    run = await _published_run(client, venues_crawler)

    pending = await client.get(
        f"/api/crawler-executions/{run['id']}/dataset-sample.csv"
    )

    assert 401 == anonymous.status_code
    assert 404 == pending.status_code


@pytest.mark.anyio
async def test_a_crawlers_history_pages_its_runs(
    client, act_as, venues_crawler, execution_dispatcher
):
    act_as("member")
    run = await _published_run(client, venues_crawler)
    crawler_id = run["crawler_id"]

    listed = await client.get(
        f"/api/crawlers/{crawler_id}/executions", params={"limit": 1}
    )
    tests = await client.get(
        f"/api/crawlers/{crawler_id}/executions", params={"queue": "testing"}
    )
    unknown = await client.get(
        f"/api/crawlers/{crawler_id}/executions", params={"queue": "slow"}
    )
    too_big = await client.get(
        f"/api/crawlers/{crawler_id}/executions", params={"limit": 51}
    )
    missing = await client.get("/api/crawlers/missing/executions")

    assert 200 == listed.status_code
    assert [run["id"]] == [item["id"] for item in listed.json()["items"]]
    assert None is listed.json()["items"][0]["dataset"]
    assert (1, 0, False) == (
        listed.json()["limit"],
        listed.json()["offset"],
        listed.json()["has_more"],
    )
    assert [] == tests.json()["items"]
    assert (422, 422) == (unknown.status_code, too_big.status_code)
    assert 404 == missing.status_code


@pytest.mark.anyio
async def test_a_crawlers_execution_summary(
    client, act_as, venues_crawler, execution_dispatcher
):
    act_as("member")
    run = await _published_run(client, venues_crawler)

    summary = await client.get(f"/api/crawlers/{run['crawler_id']}/execution-summary")
    unknown = await client.get(
        f"/api/crawlers/{run['crawler_id']}/execution-summary",
        params={"queue": "slow"},
    )
    missing = await client.get("/api/crawlers/missing/execution-summary")

    assert 200 == summary.status_code
    assert {
        "consecutive_successful_runs": 0,
        "avg_completion_seconds": None,
        "success_rate": None,
        "recent_run_count": 0,
        "last_success_at": None,
        "last_verification_failure_at": None,
        "last_failure_at": None,
        "avg_completeness_rate": None,
    } == summary.json()
    assert 422 == unknown.status_code
    assert 404 == missing.status_code


@pytest.mark.anyio
async def test_a_crawlers_history_needs_a_session(client):
    listed = await client.get("/api/crawlers/any/executions")
    summary = await client.get("/api/crawlers/any/execution-summary")

    assert (401, 401) == (listed.status_code, summary.status_code)


@pytest.mark.anyio
async def test_a_crawlers_execution_history_window(
    client, act_as, venues_crawler, execution_dispatcher
):
    act_as("member")
    run = await _published_run(client, venues_crawler)
    url = f"/api/crawlers/{run['crawler_id']}/execution-history"

    history = await client.get(url, params={"days": 7})
    too_short = await client.get(url, params={"days": 0})
    too_long = await client.get(url, params={"days": 91})
    unknown = await client.get(url, params={"queue": "slow"})
    missing = await client.get("/api/crawlers/missing/execution-history")

    body = history.json()
    assert 200 == history.status_code
    assert [run["id"]] == [item["id"] for item in body["runs"]]
    assert "in_progress" == body["runs"][0]["outcome"]
    assert {
        "all": 1,
        "success": 0,
        "verification_failed": 0,
        "failed": 0,
        "in_progress": 1,
    } == body["counts"]
    assert not body["is_truncated"]
    assert {"window_start", "window_end"} <= set(body)
    assert (422, 422, 422) == (
        too_short.status_code,
        too_long.status_code,
        unknown.status_code,
    )
    assert 404 == missing.status_code


@pytest.mark.anyio
async def test_the_execution_history_needs_a_session(client):
    response = await client.get("/api/crawlers/any/execution-history")

    assert 401 == response.status_code
