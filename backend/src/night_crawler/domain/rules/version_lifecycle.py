"""Which version a new draft starts from."""

from night_crawler.domain.model.entities import CrawlerVersion


def pick_draft_source(versions: list[CrawlerVersion]) -> CrawlerVersion | None:
    """Return the version a new draft clones, or `None` to start empty.

    The published version if there is one, else the latest archived
    one, so a crawler whose versions are all archived keeps its
    instructions.
    """
    return _latest(versions, "published") or _latest(versions, "archived")


def _latest(versions: list[CrawlerVersion], status: str) -> CrawlerVersion | None:
    """Return the newest version with `status`, if any."""
    return max(
        (version for version in versions if status == version.status),
        key=lambda version: version.created_at,
        default=None,
    )
