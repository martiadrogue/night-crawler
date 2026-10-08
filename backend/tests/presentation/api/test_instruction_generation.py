import pytest
from night_crawler.main import app
from night_crawler.presentation.api.dependencies import (
    get_instruction_generation_dispatcher,
)


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch(self, generation_id: str) -> None:
        self.dispatched.append(generation_id)


@pytest.fixture
def generation_dispatcher(client) -> _RecordingDispatcher:
    """Record dispatches; `client` restores the overrides afterwards."""
    dispatcher = _RecordingDispatcher()
    app.dependency_overrides[get_instruction_generation_dispatcher] = lambda: (
        dispatcher
    )
    return dispatcher


async def _draft_id(client, venues_crawler) -> str:
    crawler = await client.post("/api/crawlers", json=venues_crawler)
    versions = await client.get(f"/api/crawlers/{crawler.json()['id']}/versions")
    return versions.json()[0]["id"]


@pytest.mark.anyio
async def test_create_then_poll_a_generation(
    client, act_as, venues_crawler, generation_dispatcher
):
    act_as("member")
    draft_id = await _draft_id(client, venues_crawler)

    created = await client.post(
        f"/api/crawler-versions/{draft_id}/instruction-generations",
        json={"prompt": "comedy shows in Barcelona"},
    )
    fetched = await client.get(f"/api/instruction-generations/{created.json()['id']}")

    assert 202 == created.status_code
    assert "pending" == created.json()["status"]
    assert [created.json()["id"]] == generation_dispatcher.dispatched
    assert 200 == fetched.status_code
    assert "comedy shows in Barcelona" == fetched.json()["prompt"]


@pytest.mark.anyio
@pytest.mark.parametrize("prompt", ["", "   ", "x" * 4001])
async def test_create_refuses_an_empty_or_long_prompt(
    client, act_as, venues_crawler, generation_dispatcher, prompt
):
    act_as("member")
    draft_id = await _draft_id(client, venues_crawler)

    response = await client.post(
        f"/api/crawler-versions/{draft_id}/instruction-generations",
        json={"prompt": prompt},
    )

    assert 422 == response.status_code
    assert [] == generation_dispatcher.dispatched


@pytest.mark.anyio
async def test_unknown_ids_are_404(client, act_as, generation_dispatcher):
    act_as("member")

    created = await client.post(
        "/api/crawler-versions/missing/instruction-generations", json={"prompt": "x"}
    )
    fetched = await client.get("/api/instruction-generations/missing")

    assert 404 == created.status_code
    assert 404 == fetched.status_code


@pytest.mark.anyio
async def test_generations_require_authentication(client, generation_dispatcher):
    created = await client.post(
        "/api/crawler-versions/any/instruction-generations", json={"prompt": "x"}
    )
    fetched = await client.get("/api/instruction-generations/any")

    assert 401 == created.status_code
    assert 401 == fetched.status_code


@pytest.mark.anyio
async def test_the_recording_is_returned_only_when_asked(
    client, act_as, venues_crawler, generation_dispatcher, mongo_database
):
    act_as("member")
    draft_id = await _draft_id(client, venues_crawler)
    created = await client.post(
        f"/api/crawler-versions/{draft_id}/instruction-generations",
        json={"prompt": "comedy shows in Barcelona"},
    )
    generation_id = created.json()["id"]
    client_, database_name = mongo_database
    await client_[database_name].instruction_generations.update_one(
        {"_id": generation_id},
        {
            "$set": {
                "recording": {
                    "steps": [
                        {
                            "index": 0,
                            "action": "navigate",
                            "url": "https://shows.example/",
                            "is_success": True,
                            "params": {"url": "https://shows.example/"},
                            "target_xpath": None,
                            "error": None,
                        }
                    ],
                    "requests": [],
                    "final_result": {"data": [{"name": "A"}], "is_success": True},
                    "is_truncated": False,
                }
            }
        },
    )

    polled = await client.get(f"/api/instruction-generations/{generation_id}")
    asked = await client.get(
        f"/api/instruction-generations/{generation_id}?include=recording"
    )
    unknown = await client.get(
        f"/api/instruction-generations/{generation_id}?include=everything"
    )

    assert None is polled.json()["recording"]
    assert ["navigate"] == [s["action"] for s in asked.json()["recording"]["steps"]]
    assert [{"name": "A"}] == asked.json()["recording"]["final_result"]["data"]
    assert 422 == unknown.status_code
