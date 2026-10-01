"""Use cases for Message Templates."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageTemplate
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateOut,
    MessageTemplateUpdate,
)
from night_crawler.services import crawler_version_service

logger = logging.getLogger(__name__)


def _to_out(template: MessageTemplate) -> MessageTemplateOut:
    """Map a template onto its API schema."""
    return MessageTemplateOut(
        id=template.id,
        crawler_version_id=template.crawler_version_id,
        action=template.action,
        url=template.url,
        body=template.body,
        headers=template.headers,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


async def get_templates(
    read_repositories: AbstractReadRepositories, current_user: UserOut, version_id: str
) -> list[MessageTemplateOut]:
    """Return every template of a version.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404).
    """
    await crawler_version_service.get_version(
        read_repositories, current_user, version_id
    )
    templates = await read_repositories.message_templates.get_all_by_crawler_version_id(
        version_id
    )
    return [_to_out(template) for template in templates]


async def get_template(
    read_repositories: AbstractReadRepositories, current_user: UserOut, template_id: str
) -> MessageTemplateOut:
    """Return one template.

    Raises:
        ValidationException: the template, its version, or its Crawler
            does not exist (404).
    """
    template = await get_template_or_404(read_repositories, template_id)
    await crawler_version_service.get_version(
        read_repositories, current_user, template.crawler_version_id
    )
    return _to_out(template)


async def create_template(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    version_id: str,
    template_input: MessageTemplateCreate,
) -> MessageTemplateOut:
    """Add a template, auto-forking a published version.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    version, _template_id_map, _selector_id_map = (
        await crawler_version_service.resolve_editable_version(
            write_repositories, current_user, version_id
        )
    )

    now = datetime.now(UTC).replace(tzinfo=None)
    template = MessageTemplate(
        id=str(uuid.uuid4()),
        crawler_version_id=version.id,
        action=template_input.action,
        url=template_input.url,
        body=template_input.body,
        headers=template_input.headers,
        created_at=now,
        updated_at=now,
    )
    saved = await write_repositories.message_templates.save(template)
    await write_repositories.commit()

    logger.info("Message template created: id=%s", saved.id)
    return _to_out(saved)


async def update_template(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    template_id: str,
    template_input: MessageTemplateUpdate,
) -> MessageTemplateOut:
    """Apply a partial update, auto-forking a published version.

    Raises:
        ValidationException: the template does not exist (404).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    template = await resolve_editable_template(
        write_repositories, current_user, template_id
    )
    saved = await write_repositories.message_templates.save(
        replace(
            template,
            **template_input.model_dump(exclude_unset=True),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await write_repositories.commit()
    return _to_out(saved)


async def delete_template(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    template_id: str,
) -> None:
    """Delete a non-root template, auto-forking a published version.

    Its selectors and aid go with it.

    Raises:
        ValidationException: the template does not exist (404), or it is
            the root (409).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    template = await resolve_editable_template(
        write_repositories, current_user, template_id
    )
    version = await write_repositories.crawler_versions.get_by_id(
        template.crawler_version_id
    )
    if version.message_template_root_id == template.id:
        raise ValidationException(
            "Cannot delete a crawler version's root template - point the root "
            "at another template first.",
            409,
        )

    await write_repositories.message_selectors.delete_by_message_template_id(
        template.id
    )
    await write_repositories.message_aids.delete_by_message_template_id(template.id)
    await write_repositories.message_templates.delete(template.id)
    await write_repositories.commit()


async def resolve_editable_template(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    template_id: str,
) -> MessageTemplate:
    """Return the template a mutation should land on.

    After an auto-fork that is the template's clone in the new draft.

    Raises:
        ValidationException: the template does not exist (404).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    template = await get_template_or_404(write_repositories, template_id)
    _version, template_id_map, _selector_id_map = (
        await crawler_version_service.resolve_editable_version(
            write_repositories, current_user, template.crawler_version_id
        )
    )
    if template_id in template_id_map:
        return await get_template_or_404(
            write_repositories, template_id_map[template_id]
        )
    return template


async def get_template_or_404(
    repositories: AbstractRepositories, template_id: str
) -> MessageTemplate:
    """Return the template.

    Raises:
        ValidationException: it does not exist (404).
    """
    template = await repositories.message_templates.get_by_id(template_id)
    if None is template:
        raise ValidationException("Message template not found.", 404)
    return template
