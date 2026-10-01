"""Use cases for Message Selectors."""

import logging
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.constants import CONTEXT_SELECTOR_TYPES
from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.message_selector import (
    MessageSelectorCreate,
    MessageSelectorOut,
    MessageSelectorUpdate,
)
from night_crawler.services import crawler_version_service, message_template_service

logger = logging.getLogger(__name__)


def _to_out(selector: MessageSelector) -> MessageSelectorOut:
    """Map a selector onto its API schema."""
    return MessageSelectorOut(
        id=selector.id,
        message_template_id=selector.message_template_id,
        parent_selector_id=selector.parent_selector_id,
        path=selector.path,
        type=selector.type,
        target=selector.target,
        title=selector.title,
        config=selector.config,
        source=selector.source,
        created_at=selector.created_at,
        updated_at=selector.updated_at,
    )


def _collect_subtree_ids(selectors: list[MessageSelector], root_id: str) -> set[str]:
    """Return `root_id` and the ids of every selector below it."""
    children_by_parent: dict[str | None, list[str]] = {}
    for selector in selectors:
        children_by_parent.setdefault(selector.parent_selector_id, []).append(
            selector.id
        )

    subtree = {root_id}
    pending = [root_id]
    while pending:
        children = children_by_parent.get(pending.pop(), [])
        subtree.update(children)
        pending.extend(children)
    return subtree


async def get_selectors(
    read_repositories: AbstractReadRepositories, current_user: UserOut, template_id: str
) -> list[MessageSelectorOut]:
    """Return a template's selectors.

    Raises:
        ValidationException: the template, its version, or its Crawler
            does not exist (404).
    """
    await message_template_service.get_template(
        read_repositories, current_user, template_id
    )
    selectors = (
        await read_repositories.message_selectors.get_all_by_message_template_id(
            template_id
        )
    )
    return [_to_out(selector) for selector in selectors]


async def get_selector(
    read_repositories: AbstractReadRepositories, current_user: UserOut, selector_id: str
) -> MessageSelectorOut:
    """Return one selector.

    Raises:
        ValidationException: the selector, its template, or its Crawler
            does not exist (404).
    """
    selector = await _get_selector_or_404(read_repositories, selector_id)
    await message_template_service.get_template(
        read_repositories, current_user, selector.message_template_id
    )
    return _to_out(selector)


async def create_selector(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    template_id: str,
    selector_input: MessageSelectorCreate,
) -> MessageSelectorOut:
    """Add a selector, auto-forking a published version.

    Raises:
        ValidationException: the template does not exist (404), or the
            parent is not a selector of the same template (400).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    template = await message_template_service.get_template_or_404(
        write_repositories, template_id
    )
    _version, template_id_map, selector_id_map = (
        await crawler_version_service.resolve_editable_version(
            write_repositories, current_user, template.crawler_version_id
        )
    )

    now = datetime.now(UTC).replace(tzinfo=None)
    selector = MessageSelector(
        id=str(uuid.uuid4()),
        message_template_id=template_id_map.get(template_id, template_id),
        parent_selector_id=_map_id(selector_id_map, selector_input.parent_selector_id),
        path=selector_input.path,
        type=selector_input.type,
        target=selector_input.target,
        title=selector_input.title,
        config=(
            None
            if None is selector_input.config
            else selector_input.config.model_dump()
        ),
        source=selector_input.source,
        created_at=now,
        updated_at=now,
    )
    _ensure_context_reads_a_value(selector)
    await _ensure_valid_parent(write_repositories, selector)

    saved = await write_repositories.message_selectors.save(selector)
    await write_repositories.commit()
    return _to_out(saved)


async def update_selector(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    selector_id: str,
    selector_input: MessageSelectorUpdate,
) -> MessageSelectorOut:
    """Apply a partial update, auto-forking a published version.

    Raises:
        ValidationException: the selector does not exist (404); the new
            parent is outside the template or inside the selector's own
            subtree (400); or `config` doesn't match the type (400).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    selector, selector_id_map = await _resolve_editable_selector(
        write_repositories, current_user, selector_id
    )
    updates = selector_input.model_dump(exclude_unset=True)
    if "parent_selector_id" in updates:
        updates["parent_selector_id"] = _map_id(
            selector_id_map, updates["parent_selector_id"]
        )
    selector = replace(
        selector, **updates, updated_at=datetime.now(UTC).replace(tzinfo=None)
    )
    _ensure_config_matches_type(selector)
    _ensure_regex_path(selector)
    _ensure_context_reads_a_value(selector)
    await _ensure_valid_parent(write_repositories, selector)

    saved = await write_repositories.message_selectors.save(selector)
    await write_repositories.commit()
    return _to_out(saved)


async def delete_selector(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    selector_id: str,
) -> None:
    """Delete a selector and its descendants, auto-forking if needed.

    Raises:
        ValidationException: the selector does not exist (404).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    selector, _selector_id_map = await _resolve_editable_selector(
        write_repositories, current_user, selector_id
    )
    siblings = (
        await write_repositories.message_selectors.get_all_by_message_template_id(
            selector.message_template_id
        )
    )
    await write_repositories.message_selectors.delete_all(
        sorted(_collect_subtree_ids(siblings, selector.id))
    )
    await write_repositories.commit()


def _map_id(id_map: dict[str, str], original_id: str | None) -> str | None:
    """Return the clone of `original_id` after a fork, else itself."""
    return None if None is original_id else id_map.get(original_id, original_id)


async def _resolve_editable_selector(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    selector_id: str,
) -> tuple[MessageSelector, dict[str, str]]:
    """Return the selector a mutation should land on, and the id map.

    After an auto-fork that is the selector's clone in the new draft.

    Raises:
        ValidationException: the selector does not exist (404).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
    """
    selector = await _get_selector_or_404(write_repositories, selector_id)
    template = await message_template_service.get_template_or_404(
        write_repositories, selector.message_template_id
    )
    _version, _template_id_map, selector_id_map = (
        await crawler_version_service.resolve_editable_version(
            write_repositories, current_user, template.crawler_version_id
        )
    )
    if selector_id in selector_id_map:
        selector = await _get_selector_or_404(
            write_repositories, selector_id_map[selector_id]
        )
    return selector, selector_id_map


async def _ensure_valid_parent(
    write_repositories: AbstractWriteRepositories, selector: MessageSelector
) -> None:
    """Check the parent is on the same template and not a descendant.

    Raises:
        ValidationException: the parent is missing, on another template,
            or inside the selector's own subtree (400).
    """
    if None is selector.parent_selector_id:
        return
    siblings = (
        await write_repositories.message_selectors.get_all_by_message_template_id(
            selector.message_template_id
        )
    )
    if selector.parent_selector_id not in {sibling.id for sibling in siblings}:
        raise ValidationException(
            "Parent selector not found on the same template.", 400
        )
    if selector.parent_selector_id in _collect_subtree_ids(siblings, selector.id):
        raise ValidationException(
            "A selector can't be nested under itself or its descendants.", 400
        )


def _ensure_regex_path(selector: MessageSelector) -> None:
    """Check a `headers`/`url` selector's path compiles as a regex.

    Raises:
        ValidationException: it doesn't (400).
    """
    if selector.source not in ("headers", "url"):
        return
    try:
        re.compile(selector.path)
    except re.error as error:
        raise ValidationException(
            f"`path` must be a regex for {selector.source}: {error}", 400
        ) from error


def _ensure_context_reads_a_value(selector: MessageSelector) -> None:
    """Check a `context` selector is a `value` or `boolean` one.

    Its `path` names a placeholder, so there is nothing to loop over or
    act on.

    Raises:
        ValidationException: another type reads the context (400).
    """
    if "context" == selector.source and selector.type not in CONTEXT_SELECTOR_TYPES:
        raise ValidationException(
            "Only value and boolean selectors can read the context.", 400
        )


def _ensure_config_matches_type(selector: MessageSelector) -> None:
    """Check `config` is set exactly for `pagination` selectors.

    Raises:
        ValidationException: `config` is missing on a `pagination`
            selector or set on any other type (400).
    """
    if ("pagination" == selector.type) != (None is not selector.config):
        raise ValidationException(
            "`config` is required for, and only for, pagination.", 400
        )


async def _get_selector_or_404(
    repositories: AbstractRepositories, selector_id: str
) -> MessageSelector:
    """Return the selector.

    Raises:
        ValidationException: it does not exist (404).
    """
    selector = await repositories.message_selectors.get_by_id(selector_id)
    if None is selector:
        raise ValidationException("Message selector not found.", 404)
    return selector
