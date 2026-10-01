from datetime import datetime, timedelta

import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import CrawlerVersion

NOW = datetime(2026, 1, 1)


def _version(**overrides) -> CrawlerVersion:
    defaults = {
        "id": "version-1",
        "crawler_id": "crawler-1",
        "user_id": "user-1",
        "status": "draft",
        "message_template_root_id": None,
        "published_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return CrawlerVersion(**{**defaults, **overrides})


@pytest.mark.anyio
async def test_draft_and_published_lookups(write_repositories):
    repository = write_repositories.crawler_versions
    await repository.save(_version(status="published", published_at=NOW))
    await repository.save(_version(id="version-2"))

    published = await repository.get_published_by_crawler_id("crawler-1")
    draft = await repository.get_draft_by_crawler_id("crawler-1")

    assert "version-1" == published.id
    assert "version-2" == draft.id


@pytest.mark.anyio
async def test_a_second_draft_is_a_conflict(write_repositories):
    repository = write_repositories.crawler_versions
    await repository.save(_version())

    with pytest.raises(ValidationException) as exc_info:
        await repository.save(_version(id="version-2"))

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_archived_versions_do_not_count_as_drafts(write_repositories):
    repository = write_repositories.crawler_versions
    await repository.save(_version(status="archived"))

    await repository.save(_version(id="version-2"))

    assert 2 == len(await repository.get_all_by_crawler_id("crawler-1"))


@pytest.mark.anyio
async def test_versions_list_oldest_first_without_a_number(write_repositories):
    repository = write_repositories.crawler_versions
    later = NOW + timedelta(days=1)
    await repository.save(_version(status="archived", created_at=later))
    await repository.save(_version(id="version-2", status="archived"))

    versions = await repository.get_all_by_crawler_id("crawler-1")

    assert ["version-2", "version-1"] == [version.id for version in versions]
