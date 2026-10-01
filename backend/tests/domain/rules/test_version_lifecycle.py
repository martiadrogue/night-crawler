from datetime import datetime, timedelta

from night_crawler.domain.model.entities import CrawlerVersion
from night_crawler.domain.rules.version_lifecycle import pick_draft_source

NOW = datetime(2026, 1, 1)


def _version(day: int, status: str) -> CrawlerVersion:
    created_at = NOW + timedelta(days=day)
    return CrawlerVersion(
        id=f"day-{day}",
        crawler_id="c1",
        user_id="u1",
        status=status,
        message_template_root_id=None,
        published_at=None,
        created_at=created_at,
        updated_at=created_at,
    )


def test_the_published_version_wins_over_newer_archived_ones():
    versions = [_version(1, "published"), _version(2, "archived")]

    assert "day-1" == pick_draft_source(versions).id


def test_without_a_published_version_the_latest_archived_one_is_used():
    versions = [
        _version(3, "archived"),
        _version(1, "archived"),
        _version(2, "archived"),
    ]

    assert "day-3" == pick_draft_source(versions).id


def test_without_versions_there_is_no_source():
    assert None is pick_draft_source([])
