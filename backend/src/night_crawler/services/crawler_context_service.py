"""Use cases for editing a Crawler's current Context.

The current Context is the latest execution's. The next execution
starts from it, so editing it shapes the next run.
"""

import logging

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.execution_context import validate_seed_context
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_context import (
    CrawlerContextOut,
    CrawlerContextValueUpdate,
)
from night_crawler.services import crawler_execution_service, crawler_service

logger = logging.getLogger(__name__)


async def get_context(
    read_repositories: AbstractReadRepositories, current_user: UserOut, crawler_id: str
) -> CrawlerContextOut:
    """Return the Context of the Crawler's latest execution.

    Raises:
        ValidationException: the Crawler does not exist, or has no
            execution yet (404).
    """
    execution = await _latest_execution(read_repositories, current_user, crawler_id)
    return await _to_out(read_repositories, execution)


async def set_context_value(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    crawler_id: str,
    key: str,
    value_input: CrawlerContextValueUpdate,
) -> CrawlerContextOut:
    """Create or replace one key of the latest execution's Context.

    Raises:
        ValidationException: the Crawler does not exist, or has no
            execution yet (404); the key or value breaks the Context
            rules (400).
    """
    errors = validate_seed_context({key: value_input.value})
    if errors:
        raise ValidationException("Invalid context: " + " ".join(errors), 400)
    execution = await _latest_execution(write_repositories, current_user, crawler_id)
    context = await crawler_execution_service.get_context(
        write_repositories, execution.id
    )
    await crawler_execution_service.save_context(
        write_repositories, execution.id, {**context, key: value_input.value}
    )
    await write_repositories.commit()
    logger.info("Context key set: execution_id=%s, key=%s", execution.id, key)
    return await _to_out(write_repositories, execution)


async def delete_context_value(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    crawler_id: str,
    key: str,
) -> None:
    """Delete one key from the latest execution's Context, if present.

    Raises:
        ValidationException: the Crawler does not exist, or has no
            execution yet (404).
    """
    execution = await _latest_execution(write_repositories, current_user, crawler_id)
    await write_repositories.crawler_execution_contexts.delete_by_crawler_execution_id_and_key(
        execution.id, key
    )
    await write_repositories.commit()


async def _latest_execution(
    repositories: AbstractRepositories, current_user: UserOut, crawler_id: str
) -> CrawlerExecution:
    """Return the Crawler's latest execution.

    Raises:
        ValidationException: the Crawler does not exist, or has no
            execution yet (404).
    """
    crawler = await crawler_service.get_crawler(repositories, current_user, crawler_id)
    execution = await repositories.crawler_executions.get_latest_by_crawler_id(
        crawler.id
    )
    if None is execution:
        raise ValidationException(
            "This crawler has no execution yet; seed a Context when "
            "creating its first one.",
            404,
        )
    return execution


async def _to_out(
    repositories: AbstractRepositories, execution: CrawlerExecution
) -> CrawlerContextOut:
    """Map an execution's Context onto its API schema."""
    return CrawlerContextOut(
        crawler_execution_id=execution.id,
        values=await crawler_execution_service.get_context(repositories, execution.id),
    )
