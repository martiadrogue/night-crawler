"""Use cases for a template's Message Aid."""

import logging
import uuid
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageAid
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.message_aid import MessageAidCreate, MessageAidOut
from night_crawler.services import (
    message_aid_proxy_service,
    message_aid_rate_limit_service,
    message_template_service,
)

logger = logging.getLogger(__name__)


def _to_out(aid: MessageAid) -> MessageAidOut:
    """Map a Message Aid onto its API schema."""
    return MessageAidOut(
        id=aid.id,
        message_template_id=aid.message_template_id,
        selected_proxy_id=aid.selected_proxy_id,
        retry_codes=aid.retry_codes,
        success_codes=aid.success_codes,
        ttl=aid.ttl,
        render_mode=aid.render_mode,
        rate_limit_id=aid.rate_limit_id,
        max_retry_attempts=aid.max_retry_attempts,
        created_at=aid.created_at,
        updated_at=aid.updated_at,
    )


async def get_aid(
    read_repositories: AbstractReadRepositories, current_user: UserOut, template_id: str
) -> MessageAidOut:
    """Return a template's Message Aid.

    Raises:
        ValidationException: the template, its Crawler, or the aid does
            not exist (404).
    """
    await message_template_service.get_template(
        read_repositories, current_user, template_id
    )
    aid = await read_repositories.message_aids.get_by_message_template_id(template_id)
    if None is aid:
        raise ValidationException("Message aid not found.", 404)
    return _to_out(aid)


async def upsert_aid(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    template_id: str,
    aid_input: MessageAidCreate,
) -> MessageAidOut:
    """Create or replace a template's aid, auto-forking if needed.

    On a fork the aid lands on the template's clone, replacing the one
    cloned with it rather than adding a second.

    Raises:
        ValidationException: the template, the selected proxy, or the
            rate limit does not exist (404).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    template = await message_template_service.resolve_editable_template(
        write_repositories, current_user, template_id
    )
    await _ensure_references_exist(write_repositories, aid_input)

    existing = await write_repositories.message_aids.get_by_message_template_id(
        template.id
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    aid = MessageAid(
        **aid_input.model_dump(),
        id=existing.id if existing else str(uuid.uuid4()),
        message_template_id=template.id,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    saved = await write_repositories.message_aids.save(aid)
    await write_repositories.commit()
    return _to_out(saved)


async def delete_aid(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    template_id: str,
) -> None:
    """Delete a template's aid, auto-forking a published version.

    Raises:
        ValidationException: the template does not exist (404).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    template = await message_template_service.resolve_editable_template(
        write_repositories, current_user, template_id
    )
    await write_repositories.message_aids.delete_by_message_template_id(template.id)
    await write_repositories.commit()


async def _ensure_references_exist(
    write_repositories: AbstractWriteRepositories, aid_input: MessageAidCreate
) -> None:
    """Check the selected proxy and rate limit exist, when set.

    Raises:
        ValidationException: either does not exist (404).
    """
    if None is not aid_input.selected_proxy_id:
        await message_aid_proxy_service.get_proxy(
            write_repositories, aid_input.selected_proxy_id
        )
    if None is not aid_input.rate_limit_id:
        await message_aid_rate_limit_service.get_rate_limit(
            write_repositories, aid_input.rate_limit_id
        )
