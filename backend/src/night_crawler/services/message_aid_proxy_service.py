"""Use cases for the admin-managed proxy pool."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageAidProxy
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.schemas.message_aid_proxy import (
    MessageAidProxyCreate,
    MessageAidProxyOut,
    MessageAidProxyUpdate,
)
from night_crawler.services import message_aid_rate_limit_service

logger = logging.getLogger(__name__)


def _to_out(proxy: MessageAidProxy) -> MessageAidProxyOut:
    """Map a proxy onto its API schema, without the password."""
    return MessageAidProxyOut(
        id=proxy.id,
        url=proxy.url,
        user=proxy.user,
        headers=proxy.headers,
        rate_limit_id=proxy.rate_limit_id,
        created_at=proxy.created_at,
        updated_at=proxy.updated_at,
    )


async def get_proxies(
    read_repositories: AbstractReadRepositories,
) -> list[MessageAidProxyOut]:
    """Return every proxy in the pool."""
    proxies = await read_repositories.message_aid_proxies.get_all()
    return [_to_out(proxy) for proxy in proxies]


async def get_proxy(
    repositories: AbstractRepositories, proxy_id: str
) -> MessageAidProxyOut:
    """Return one proxy.

    Raises:
        ValidationException: the proxy does not exist (404).
    """
    return _to_out(await _get_proxy_or_404(repositories, proxy_id))


async def create_proxy(
    write_repositories: AbstractWriteRepositories, proxy_input: MessageAidProxyCreate
) -> MessageAidProxyOut:
    """Add a proxy to the pool.

    Raises:
        ValidationException: the rate limit does not exist (404).
    """
    await _ensure_rate_limit_exists(write_repositories, proxy_input.rate_limit_id)

    now = datetime.now(UTC).replace(tzinfo=None)
    proxy = MessageAidProxy(
        id=str(uuid.uuid4()),
        url=proxy_input.url,
        user=proxy_input.user,
        password=proxy_input.password,
        headers=proxy_input.headers,
        rate_limit_id=proxy_input.rate_limit_id,
        created_at=now,
        updated_at=now,
    )
    saved = await write_repositories.message_aid_proxies.save(proxy)
    await write_repositories.commit()

    logger.info("Message aid proxy created: id=%s", saved.id)
    return _to_out(saved)


async def update_proxy(
    write_repositories: AbstractWriteRepositories,
    proxy_id: str,
    proxy_input: MessageAidProxyUpdate,
) -> MessageAidProxyOut:
    """Apply a partial update to a proxy.

    Raises:
        ValidationException: the proxy or the new rate limit does not
            exist (404).
    """
    proxy = await _get_proxy_or_404(write_repositories, proxy_id)
    updates = proxy_input.model_dump(exclude_unset=True)
    await _ensure_rate_limit_exists(write_repositories, updates.get("rate_limit_id"))

    saved = await write_repositories.message_aid_proxies.save(
        replace(proxy, **updates, updated_at=datetime.now(UTC).replace(tzinfo=None))
    )
    await write_repositories.commit()
    return _to_out(saved)


async def delete_proxy(
    write_repositories: AbstractWriteRepositories, proxy_id: str
) -> None:
    """Remove a proxy; aids selecting it fall back to none (DM-11)."""
    await write_repositories.message_aids.clear_selected_proxy_id(proxy_id)
    await write_repositories.message_aid_proxies.delete(proxy_id)
    await write_repositories.commit()


async def clear_rate_limit(
    write_repositories: AbstractWriteRepositories, rate_limit_id: str
) -> None:
    """Stage unlinking a deleted rate limit from every proxy."""
    await write_repositories.message_aid_proxies.clear_rate_limit_id(rate_limit_id)


async def _get_proxy_or_404(
    repositories: AbstractRepositories, proxy_id: str
) -> MessageAidProxy:
    """Return the proxy.

    Raises:
        ValidationException: it does not exist (404).
    """
    proxy = await repositories.message_aid_proxies.get_by_id(proxy_id)
    if None is proxy:
        raise ValidationException("Message aid proxy not found.", 404)
    return proxy


async def _ensure_rate_limit_exists(
    write_repositories: AbstractWriteRepositories, rate_limit_id: str | None
) -> None:
    """Check the rate limit exists, when set.

    Raises:
        ValidationException: it does not exist (404).
    """
    if None is not rate_limit_id:
        await message_aid_rate_limit_service.get_rate_limit(
            write_repositories, rate_limit_id
        )
