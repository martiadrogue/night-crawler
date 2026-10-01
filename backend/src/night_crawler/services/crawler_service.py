"""Use cases for Crawlers."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import Crawler
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.crawler_fields import validate_crawler_fields
from night_crawler.domain.rules.pagination import MAX_FILTERED_RESULTS
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler import CrawlerCreate, CrawlerOut, CrawlerUpdate
from night_crawler.services import (
    crawler_execution_service,
    crawler_version_service,
    dataset_service,
    source_service,
)

logger = logging.getLogger(__name__)


def _to_out(crawler: Crawler) -> CrawlerOut:
    """Map a Crawler onto its API schema."""
    return CrawlerOut(
        id=crawler.id,
        user_id=crawler.user_id,
        title=crawler.title,
        source_id=crawler.source_id,
        dataset_id=crawler.dataset_id,
        fields=crawler.fields,
        schedule=crawler.schedule,
        queue=crawler.queue,
        created_at=crawler.created_at,
        updated_at=crawler.updated_at,
    )


async def find_ids_by_title(repositories: AbstractRepositories, text: str) -> list[str]:
    """Return the ids of Crawlers whose title contains `text`."""
    crawlers = await repositories.crawlers.get_all_by_title_containing(text)
    return [crawler.id for crawler in crawlers]


async def get_titles_by_id(
    repositories: AbstractRepositories, crawler_ids: list[str]
) -> dict[str, str]:
    """Return each existing Crawler's title by id, in one query."""
    crawlers = await repositories.crawlers.get_all_by_ids(list(set(crawler_ids)))
    return {crawler.id: crawler.title for crawler in crawlers}


async def get_crawler(
    repositories: AbstractRepositories, current_user: UserOut, crawler_id: str
) -> Crawler:
    """Return the Crawler entity, for services working on its children.

    Crawlers are shared: any authenticated user may access any Crawler.

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    crawler = await repositories.crawlers.get_by_id(crawler_id)
    if None is crawler:
        raise ValidationException("Crawler not found.", 404)
    return crawler


async def get_crawler_out(
    read_repositories: AbstractReadRepositories, current_user: UserOut, crawler_id: str
) -> CrawlerOut:
    """Return one Crawler.

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    return _to_out(await get_crawler(read_repositories, current_user, crawler_id))


async def get_crawlers(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    source_id: str | None = None,
    dataset_id: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> list[CrawlerOut]:
    """Return Crawlers, newest first, capped at one page.

    The listing always offers filters, so it never paginates.
    """
    crawlers = await read_repositories.crawlers.get_all(
        source_id=source_id,
        dataset_id=dataset_id,
        sort_by=sort_by,
        order=order,
        limit=MAX_FILTERED_RESULTS,
    )
    return [_to_out(crawler) for crawler in crawlers]


async def create_crawler(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    crawler_input: CrawlerCreate,
) -> CrawlerOut:
    """Create a Crawler together with its first, empty draft version.

    Raises:
        ValidationException: the fields don't fit the dataset, or the
            Source or Dataset doesn't exist (400).
    """
    await source_service.ensure_source_exists(
        write_repositories, crawler_input.source_id
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    crawler = Crawler(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=crawler_input.title,
        source_id=crawler_input.source_id,
        dataset_id=crawler_input.dataset_id,
        fields=crawler_input.fields,
        schedule=crawler_input.schedule,
        queue=crawler_input.queue,
        created_at=now,
        updated_at=now,
    )
    await _ensure_valid_fields(write_repositories, crawler)

    saved = await write_repositories.crawlers.save(crawler)
    await crawler_version_service.create_initial_draft(write_repositories, saved)
    await write_repositories.commit()

    logger.info("Crawler created: id=%s, title=%s", saved.id, saved.title)
    return _to_out(saved)


async def update_crawler(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    crawler_id: str,
    crawler_input: CrawlerUpdate,
) -> CrawlerOut:
    """Apply a partial update to a Crawler.

    Raises:
        ValidationException: the Crawler does not exist (404), or the
            fields don't fit the dataset or the Source or Dataset
            doesn't exist (400).
    """
    crawler = await get_crawler(write_repositories, current_user, crawler_id)

    updates = crawler_input.model_dump(exclude_unset=True)
    crawler = replace(
        crawler, **updates, updated_at=datetime.now(UTC).replace(tzinfo=None)
    )
    await _ensure_valid_fields(write_repositories, crawler)
    await source_service.ensure_source_exists(write_repositories, crawler.source_id)

    saved = await write_repositories.crawlers.save(crawler)
    await write_repositories.commit()
    return _to_out(saved)


async def delete_crawler(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    crawler_id: str,
) -> None:
    """Delete a Crawler and everything it owns (DOMAIN_MODEL DM-9).

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    crawler = await get_crawler(write_repositories, current_user, crawler_id)
    await _delete_crawler_tree(write_repositories, crawler.id)
    await write_repositories.commit()

    logger.info("Crawler deleted: id=%s", crawler.id)


async def delete_crawlers_of_user(
    write_repositories: AbstractWriteRepositories, user_id: str
) -> None:
    """Stage deleting every Crawler a user created; caller commits."""
    for crawler in await write_repositories.crawlers.get_all_by_user_id(user_id):
        await _delete_crawler_tree(write_repositories, crawler.id)


async def _delete_crawler_tree(
    write_repositories: AbstractWriteRepositories, crawler_id: str
) -> None:
    """Stage deleting a Crawler with its executions and versions.

    Executions go first: a version that has run can't be deleted while
    they reference it (DM-10).
    """
    await crawler_execution_service.delete_executions_of_crawler(
        write_repositories, crawler_id
    )
    await crawler_version_service.delete_versions_of_crawler(
        write_repositories, crawler_id
    )
    await write_repositories.crawlers.delete(crawler_id)


async def _ensure_valid_fields(
    write_repositories: AbstractWriteRepositories, crawler: Crawler
) -> None:
    """Refuse fields its Dataset's import couldn't read (DM-17).

    Raises:
        ValidationException: the Dataset doesn't exist, or the fields
            don't fit it (400).
    """
    dataset = await dataset_service.get_linkable_dataset(
        write_repositories, crawler.dataset_id
    )
    errors = validate_crawler_fields(dataset, crawler.fields)
    if errors:
        raise ValidationException("Invalid crawler fields: " + " ".join(errors), 400)
