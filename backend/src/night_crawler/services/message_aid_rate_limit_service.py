"""Use cases for reusable rate-limit rules."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageAidRateLimit
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.schemas.message_aid_rate_limit import (
    MessageAidRateLimitCreate,
    MessageAidRateLimitOut,
    MessageAidRateLimitUpdate,
)
from night_crawler.services import message_aid_proxy_service

logger = logging.getLogger(__name__)


def _to_out(rate_limit: MessageAidRateLimit) -> MessageAidRateLimitOut:
    """Map a rate-limit rule onto its API schema."""
    return MessageAidRateLimitOut(
        id=rate_limit.id,
        name=rate_limit.name,
        rate_limit_string=rate_limit.rate_limit_string,
        penalty_step_seconds=rate_limit.penalty_step_seconds,
        max_penalty_seconds=rate_limit.max_penalty_seconds,
        decay_after_successes=rate_limit.decay_after_successes,
        decay_step_seconds=rate_limit.decay_step_seconds,
        created_at=rate_limit.created_at,
        updated_at=rate_limit.updated_at,
    )


async def get_rate_limits(
    read_repositories: AbstractReadRepositories,
) -> list[MessageAidRateLimitOut]:
    """Return every rate-limit rule."""
    rate_limits = await read_repositories.message_aid_rate_limits.get_all()
    return [_to_out(rate_limit) for rate_limit in rate_limits]


async def get_rate_limit(
    repositories: AbstractRepositories, rate_limit_id: str
) -> MessageAidRateLimitOut:
    """Return one rate-limit rule.

    Raises:
        ValidationException: the rule does not exist (404).
    """
    return _to_out(await _get_rate_limit_or_404(repositories, rate_limit_id))


async def create_rate_limit(
    write_repositories: AbstractWriteRepositories,
    rate_limit_input: MessageAidRateLimitCreate,
) -> MessageAidRateLimitOut:
    """Create a rate-limit rule.

    Raises:
        ValidationException: the rate string is not valid `limits`
            syntax (400).
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    rate_limit = MessageAidRateLimit(
        **rate_limit_input.model_dump(),
        id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
    )
    saved = await write_repositories.message_aid_rate_limits.save(rate_limit)
    await write_repositories.commit()

    logger.info("Message aid rate limit created: id=%s", saved.id)
    return _to_out(saved)


async def update_rate_limit(
    write_repositories: AbstractWriteRepositories,
    rate_limit_id: str,
    rate_limit_input: MessageAidRateLimitUpdate,
) -> MessageAidRateLimitOut:
    """Apply a partial update to a rate-limit rule.

    Raises:
        ValidationException: the rule does not exist (404), or the new
            rate string is invalid (400).
    """
    rate_limit = await _get_rate_limit_or_404(write_repositories, rate_limit_id)
    rate_limit = replace(
        rate_limit,
        **rate_limit_input.model_dump(exclude_unset=True, exclude_none=True),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )

    saved = await write_repositories.message_aid_rate_limits.save(rate_limit)
    await write_repositories.commit()
    return _to_out(saved)


async def delete_rate_limit(
    write_repositories: AbstractWriteRepositories, rate_limit_id: str
) -> None:
    """Delete a rule; aids and proxies using it lose it (DM-11)."""
    await write_repositories.message_aids.clear_rate_limit_id(rate_limit_id)
    await message_aid_proxy_service.clear_rate_limit(write_repositories, rate_limit_id)
    await write_repositories.message_aid_rate_limits.delete(rate_limit_id)
    await write_repositories.commit()


async def _get_rate_limit_or_404(
    repositories: AbstractRepositories, rate_limit_id: str
) -> MessageAidRateLimit:
    """Return the rule.

    Raises:
        ValidationException: it does not exist (404).
    """
    rate_limit = await repositories.message_aid_rate_limits.get_by_id(rate_limit_id)
    if None is rate_limit:
        raise ValidationException("Message aid rate limit not found.", 404)
    return rate_limit
