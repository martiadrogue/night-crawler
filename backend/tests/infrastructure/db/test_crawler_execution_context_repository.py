from datetime import datetime

import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import CrawlerExecutionContext

NOW = datetime(2026, 1, 1)


def _entry(entry_id, key, value, position=None):
    return CrawlerExecutionContext(
        id=entry_id,
        crawler_execution_id="execution-1",
        key=key,
        value=value,
        position=position,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.anyio
async def test_a_list_key_holds_one_entry_per_element(write_repositories):
    repository = write_repositories.crawler_execution_contexts

    await repository.save_all(
        [_entry("e1", "parish[]", "Canillo", 0), _entry("e2", "parish[]", "Encamp", 1)]
    )

    entries = await repository.get_all_by_crawler_execution_ids(["execution-1"])
    assert [("parish[]", 0, "Canillo"), ("parish[]", 1, "Encamp")] == [
        (entry.key, entry.position, entry.value) for entry in entries
    ]


@pytest.mark.anyio
async def test_a_scalar_key_holds_one_value(write_repositories):
    repository = write_repositories.crawler_execution_contexts
    await repository.save_all([_entry("e1", "token", "a")])

    with pytest.raises(ValidationException) as exc_info:
        await repository.save_all([_entry("e2", "token", "b")])

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_deleting_a_key_removes_all_its_entries(write_repositories):
    repository = write_repositories.crawler_execution_contexts
    await repository.save_all(
        [
            _entry("e1", "parish[]", "Canillo", 0),
            _entry("e2", "parish[]", "Encamp", 1),
            _entry("e3", "token", "t"),
        ]
    )

    await repository.delete_by_crawler_execution_id_and_key("execution-1", "parish[]")

    entries = await repository.get_all_by_crawler_execution_ids(["execution-1"])
    assert ["token"] == [entry.key for entry in entries]
