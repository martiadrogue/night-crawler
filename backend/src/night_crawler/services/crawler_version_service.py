"""Use cases for Crawler Versions: drafts, publishing, and settings.

Editing a published version never changes it: a draft is cloned from it
and the edit lands on the clone (auto-fork).
"""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import (
    Crawler,
    CrawlerVersion,
    MessageAid,
    MessageSelector,
    MessageTemplate,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.version_lifecycle import pick_draft_source
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_version import (
    CrawlerVersionOut,
    CrawlerVersionUpdate,
)
from night_crawler.services import crawler_execution_service, crawler_service

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Return the current time as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def _to_out(version: CrawlerVersion) -> CrawlerVersionOut:
    """Map a Crawler Version onto its API schema."""
    return CrawlerVersionOut(
        id=version.id,
        user_id=version.user_id,
        crawler_id=version.crawler_id,
        status=version.status,
        message_template_root_id=version.message_template_root_id,
        published_at=version.published_at,
        is_proxy_ladder_enabled=version.is_proxy_ladder_enabled,
        is_host_session_sharing_enabled=version.is_host_session_sharing_enabled,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


async def get_versions(
    read_repositories: AbstractReadRepositories, current_user: UserOut, crawler_id: str
) -> list[CrawlerVersionOut]:
    """Return every version of a Crawler, oldest first.

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    crawler = await crawler_service.get_crawler(
        read_repositories, current_user, crawler_id
    )
    versions = await read_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    return [_to_out(version) for version in versions]


async def get_version(
    read_repositories: AbstractReadRepositories, current_user: UserOut, version_id: str
) -> CrawlerVersionOut:
    """Return one version.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404).
    """
    return _to_out(
        await _get_version_or_404(read_repositories, current_user, version_id)
    )


async def resolve_editable_version(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    version_id: str,
) -> tuple[CrawlerVersion, dict[str, str], dict[str, str]]:
    """Return the version a mutation should land on, forking if needed.

    A draft is returned as-is. A published version is cloned into a new
    draft (staged, not committed, so the caller commits it with its own
    change). Anything else is rejected.

    Args:
        write_repositories: The write repositories.
        current_user: The acting user, who owns any new draft.
        version_id: The version the mutation targeted.

    Returns:
        The editable version plus old-to-new template and selector id
        maps; both empty unless a fork happened.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    version = await _get_version_or_404(write_repositories, current_user, version_id)
    if "draft" == version.status:
        return version, {}, {}
    if "published" != version.status:
        raise ValidationException("Cannot modify an archived crawler version.", 409)

    if None is not await write_repositories.crawler_versions.get_draft_by_crawler_id(
        version.crawler_id
    ):
        raise ValidationException(
            "An open draft already exists for this crawler - resolve it "
            "before editing the published version.",
            409,
        )

    draft, template_id_map, selector_id_map = await _fork_version(
        write_repositories, version, current_user.id
    )
    logger.info(
        "Draft auto-forked: crawler_id=%s, draft_id=%s, published_id=%s",
        version.crawler_id,
        draft.id,
        version.id,
    )
    return draft, template_id_map, selector_id_map


async def create_initial_draft(
    write_repositories: AbstractWriteRepositories, crawler: Crawler
) -> CrawlerVersion:
    """Stage a new Crawler's first version: an empty draft with a root.

    Called in the same transaction as the Crawler insert; never a route
    of its own.
    """
    draft = await _create_draft_shell(write_repositories, crawler.id, crawler.user_id)
    root = await _create_empty_root_template(write_repositories, draft.id)
    return await write_repositories.crawler_versions.save(
        replace(draft, message_template_root_id=root.id)
    )


async def create_draft(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    crawler_id: str,
) -> CrawlerVersionOut:
    """Open a draft cloned from the published version.

    Without one it clones the latest archived version, and without any
    version it starts empty (`pick_draft_source`).

    Raises:
        ValidationException: the Crawler does not exist (404), or a
            draft is already open (409).
    """
    crawler = await crawler_service.get_crawler(
        write_repositories, current_user, crawler_id
    )
    if None is not await write_repositories.crawler_versions.get_draft_by_crawler_id(
        crawler.id
    ):
        raise ValidationException("A draft already exists for this crawler.", 409)

    source = pick_draft_source(
        await write_repositories.crawler_versions.get_all_by_crawler_id(crawler.id)
    )
    if None is source:
        draft = await create_initial_draft(write_repositories, crawler)
    else:
        draft, _template_id_map, _selector_id_map = await _fork_version(
            write_repositories, source, current_user.id
        )
    await write_repositories.commit()

    logger.info(
        "Draft created: crawler_id=%s, draft_id=%s, cloned_from=%s",
        crawler.id,
        draft.id,
        source.id if source else None,
    )
    return _to_out(draft)


async def publish_draft(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    crawler_id: str,
    version_id: str,
) -> CrawlerVersionOut:
    """Publish a draft, archiving the previously published version.

    Raises:
        ValidationException: the Crawler or version does not exist
            (404), or the version is not a draft (409).
    """
    crawler = await crawler_service.get_crawler(
        write_repositories, current_user, crawler_id
    )
    version = await write_repositories.crawler_versions.get_by_id(version_id)
    if None is version or version.crawler_id != crawler.id:
        raise ValidationException("Crawler version not found.", 404)
    if "draft" != version.status:
        raise ValidationException("Only a draft version can be published.", 409)

    now = _now()
    current = await write_repositories.crawler_versions.get_published_by_crawler_id(
        crawler.id
    )
    if None is not current:
        await write_repositories.crawler_versions.save(
            replace(current, status="archived", updated_at=now)
        )
    published = await write_repositories.crawler_versions.save(
        replace(version, status="published", published_at=now, updated_at=now)
    )
    await write_repositories.commit()

    logger.info("Draft published: crawler_id=%s, version_id=%s", crawler.id, version.id)
    return _to_out(published)


async def update_version(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    version_id: str,
    version_input: CrawlerVersionUpdate,
) -> CrawlerVersionOut:
    """Apply a partial settings update, auto-forking a published one.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    version, _template_id_map, _selector_id_map = await resolve_editable_version(
        write_repositories, current_user, version_id
    )
    saved = await write_repositories.crawler_versions.save(
        replace(
            version,
            **version_input.model_dump(exclude_unset=True, exclude_none=True),
            updated_at=_now(),
        )
    )
    await write_repositories.commit()
    return _to_out(saved)


async def set_version_root_template(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    version_id: str,
    message_template_id: str,
) -> CrawlerVersionOut:
    """Point the version's root at another of its templates.

    A template id from the published version is mapped onto its clone
    after an auto-fork.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
        ValidationException: the template isn't in the version (404).
    """
    version, template_id_map, _selector_id_map = await resolve_editable_version(
        write_repositories, current_user, version_id
    )
    target_template_id = template_id_map.get(message_template_id, message_template_id)
    template = await write_repositories.message_templates.get_by_id(target_template_id)
    if None is template or template.crawler_version_id != version.id:
        raise ValidationException(
            "Message template not found in this crawler version.", 404
        )

    saved = await write_repositories.crawler_versions.save(
        replace(version, message_template_root_id=target_template_id, updated_at=_now())
    )
    await write_repositories.commit()
    return _to_out(saved)


async def delete_version(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    version_id: str,
) -> None:
    """Delete a draft or archived version and its template tree.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404), it is the published version, or an execution ran it
            (409).
    """
    version = await _get_version_or_404(write_repositories, current_user, version_id)
    if "published" == version.status:
        raise ValidationException(
            "Cannot delete the published version - publish another draft first.",
            409,
        )
    await _delete_version_tree(write_repositories, version)
    await write_repositories.commit()

    logger.info("Crawler version deleted: id=%s", version.id)


async def delete_versions_of_crawler(
    write_repositories: AbstractWriteRepositories, crawler_id: str
) -> None:
    """Stage deleting every version of a Crawler; caller commits.

    The Crawler's executions must already be staged for deletion.
    """
    for version in await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler_id
    ):
        await _delete_version_tree(write_repositories, version)


async def delete_versions_of_user(
    write_repositories: AbstractWriteRepositories, user_id: str
) -> None:
    """Stage deleting every version a user owns; caller commits.

    Raises:
        ValidationException: one of them has run (409).
    """
    for version in await write_repositories.crawler_versions.get_all_by_user_id(
        user_id
    ):
        await _delete_version_tree(write_repositories, version)


async def _get_version_or_404(
    repositories: AbstractRepositories, current_user: UserOut, version_id: str
) -> CrawlerVersion:
    """Return the version after checking its Crawler.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404).
    """
    version = await repositories.crawler_versions.get_by_id(version_id)
    if None is version:
        raise ValidationException("Crawler version not found.", 404)
    await crawler_service.get_crawler(repositories, current_user, version.crawler_id)
    return version


async def _delete_version_tree(
    write_repositories: AbstractWriteRepositories, version: CrawlerVersion
) -> None:
    """Stage deleting a version with its templates, selectors, and aids.

    Raises:
        ValidationException: an execution ran the version (409, DM-10).
    """
    if await crawler_execution_service.is_version_executed(
        write_repositories, version.id
    ):
        raise ValidationException(
            "This crawler version has been run and cannot be deleted.",
            409,
        )
    templates = (
        await write_repositories.message_templates.get_all_by_crawler_version_id(
            version.id
        )
    )
    for template in templates:
        await write_repositories.message_selectors.delete_by_message_template_id(
            template.id
        )
        await write_repositories.message_aids.delete_by_message_template_id(template.id)
        await write_repositories.message_templates.delete(template.id)
    await write_repositories.crawler_versions.delete(version.id)


async def _create_draft_shell(
    write_repositories: AbstractWriteRepositories, crawler_id: str, owner_id: str
) -> CrawlerVersion:
    """Stage an empty draft for the Crawler.

    `owner_id` becomes the draft's owner for good: publishing or
    archiving only changes the status.
    """
    now = _now()
    return await write_repositories.crawler_versions.save(
        CrawlerVersion(
            id=str(uuid.uuid4()),
            crawler_id=crawler_id,
            user_id=owner_id,
            status="draft",
            message_template_root_id=None,
            published_at=None,
            created_at=now,
            updated_at=now,
        )
    )


async def _fork_version(
    write_repositories: AbstractWriteRepositories, source: CrawlerVersion, owner_id: str
) -> tuple[CrawlerVersion, dict[str, str], dict[str, str]]:
    """Stage a draft cloned from `source`, owned by `owner_id`.

    Returns:
        The draft plus old-to-new template and selector id maps.
    """
    draft = await _create_draft_shell(write_repositories, source.crawler_id, owner_id)
    template_id_map, selector_id_map = await _clone_templates(
        write_repositories, source.id, draft.id
    )
    draft = await write_repositories.crawler_versions.save(
        replace(
            draft,
            message_template_root_id=template_id_map.get(
                source.message_template_root_id
            ),
            is_proxy_ladder_enabled=source.is_proxy_ladder_enabled,
            is_host_session_sharing_enabled=source.is_host_session_sharing_enabled,
        )
    )
    return draft, template_id_map, selector_id_map


async def _create_empty_root_template(
    write_repositories: AbstractWriteRepositories, version_id: str
) -> MessageTemplate:
    """Stage an empty root template for a version."""
    now = _now()
    return await write_repositories.message_templates.save(
        MessageTemplate(
            id=str(uuid.uuid4()),
            crawler_version_id=version_id,
            action="GET",
            url="",
            body=None,
            headers={},
            created_at=now,
            updated_at=now,
        )
    )


async def _clone_templates(
    write_repositories: AbstractWriteRepositories,
    source_version_id: str,
    target_version_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Clone every template of a version into another.

    Returns:
        Old-to-new template and selector id maps.
    """
    template_id_map: dict[str, str] = {}
    selector_id_map: dict[str, str] = {}
    templates = (
        await write_repositories.message_templates.get_all_by_crawler_version_id(
            source_version_id
        )
    )
    for template in templates:
        new_template = await write_repositories.message_templates.save(
            replace(
                template,
                id=str(uuid.uuid4()),
                crawler_version_id=target_version_id,
                created_at=_now(),
                updated_at=_now(),
            )
        )
        template_id_map[template.id] = new_template.id
        selector_id_map.update(
            await _clone_selectors(write_repositories, template.id, new_template.id)
        )
        await _clone_aid(write_repositories, template.id, new_template.id)
    return template_id_map, selector_id_map


async def _clone_selectors(
    write_repositories: AbstractWriteRepositories,
    source_template_id: str,
    target_template_id: str,
) -> dict[str, str]:
    """Clone a template's selector tree, keeping parent links."""
    selectors = (
        await write_repositories.message_selectors.get_all_by_message_template_id(
            source_template_id
        )
    )
    children_by_parent = _group_selector_tree(selectors)
    selector_id_map: dict[str, str] = {}
    # Reversed so popping from the end clones in depth-first preorder.
    pending = [(root, None) for root in reversed(children_by_parent.get(None, []))]
    while pending:
        selector, new_parent_id = pending.pop()
        new_selector = await write_repositories.message_selectors.save(
            replace(
                selector,
                id=str(uuid.uuid4()),
                message_template_id=target_template_id,
                parent_selector_id=new_parent_id,
                created_at=_now(),
                updated_at=_now(),
            )
        )
        selector_id_map[selector.id] = new_selector.id
        children = children_by_parent.get(selector.id, [])
        pending.extend((child, new_selector.id) for child in reversed(children))
    return selector_id_map


def _group_selector_tree(
    selectors: list[MessageSelector],
) -> dict[str | None, list[MessageSelector]]:
    """Group selectors by parent; orphans become roots, not lost."""
    known_ids = {selector.id for selector in selectors}
    children_by_parent: dict[str | None, list[MessageSelector]] = {}
    for selector in selectors:
        parent_id = selector.parent_selector_id
        if parent_id not in known_ids:
            parent_id = None
        children_by_parent.setdefault(parent_id, []).append(selector)
    return children_by_parent


async def _clone_aid(
    write_repositories: AbstractWriteRepositories,
    source_template_id: str,
    target_template_id: str,
) -> None:
    """Clone a template's Message Aid, if it has one."""
    aid: MessageAid | None = (
        await write_repositories.message_aids.get_by_message_template_id(
            source_template_id
        )
    )
    if None is aid:
        return
    await write_repositories.message_aids.save(
        replace(
            aid,
            id=str(uuid.uuid4()),
            message_template_id=target_template_id,
            created_at=_now(),
            updated_at=_now(),
        )
    )
