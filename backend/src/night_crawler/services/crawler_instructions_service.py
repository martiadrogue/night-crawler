"""Use cases for a version's instructions file: export and import.

The file holds one version's templates, aids, and selectors as flat
blocks, linked by file-local keys rather than ids (DOMAIN_MODEL §5.9).
Importing replaces the whole tree in one transaction, so a file is the
version's complete instructions, never a patch. The YAML is read and
written here, so the import route and the AI agents worker share it;
aliases (`&anchor`/`*alias`) are refused, so a small file can never
expand into a huge tree.
"""

import logging
import re
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import yaml
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.constants import CONTEXT_SELECTOR_TYPES
from night_crawler.domain.model.entities import (
    MessageAid,
    MessageSelector,
    MessageTemplate,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.placeholders import extract_placeholders
from night_crawler.domain.rules.selector_nesting import order_parents_first
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_instructions import (
    INSTRUCTIONS_FORMAT,
    CrawlerInstructionsCreate,
    CrawlerInstructionsOut,
    InstructionAidBase,
    InstructionSelectorBase,
    InstructionSettingsBase,
    InstructionTemplateBase,
)
from night_crawler.schemas.crawler_version import CrawlerVersionOut
from night_crawler.services import (
    crawler_version_service,
    message_aid_proxy_service,
    message_aid_rate_limit_service,
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)

MAX_KEY_LENGTH = 100
"""Mirrors the schema's `InstructionKey` length."""

YAML_LINE_WIDTH = 4096
"""Wide enough that URLs and XPath are never folded across lines."""


class _NoAliasLoader(yaml.SafeLoader):
    """A safe YAML loader that refuses aliases."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        """Refuse an alias before it is resolved.

        Raises:
            yaml.composer.ComposerError: the node is an alias.
        """
        if self.check_event(yaml.AliasEvent):
            raise yaml.composer.ComposerError(
                None, None, "aliases are not allowed", self.peek_event().start_mark
            )
        return super().compose_node(parent, index)


class _BlockTextDumper(yaml.SafeDumper):
    """A YAML dumper writing multi-line text as `|` blocks."""


def _represent_text(dumper: yaml.SafeDumper, text: str) -> yaml.ScalarNode:
    """Write a multi-line string as a literal block, else as usual."""
    style = "|" if "\n" in text else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", text, style=style)


def _represent_list(dumper: yaml.SafeDumper, items: list) -> yaml.SequenceNode:
    """Write a list of plain values on one line, e.g. retry codes."""
    is_flat = all(not isinstance(item, dict | list) for item in items)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", items, flow_style=is_flat)


_BlockTextDumper.add_representer(str, _represent_text)
_BlockTextDumper.add_representer(list, _represent_list)


def _now() -> datetime:
    """Return the current time as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


async def export_instructions(
    read_repositories: AbstractReadRepositories, current_user: UserOut, version_id: str
) -> CrawlerInstructionsOut:
    """Return a version's instructions as the file's blocks.

    Templates are named `template_1`, `template_2`, … with the root
    first; a selector is named after its title when no other selector
    shares it (see `_name_selectors`). Values left at their defaults
    are the caller's to omit.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404).
    """
    version = await crawler_version_service.get_version(
        read_repositories, current_user, version_id
    )
    templates = _root_first(
        await read_repositories.message_templates.get_all_by_crawler_version_id(
            version.id
        ),
        version.message_template_root_id,
    )
    template_keys = {
        template.id: f"template_{number}"
        for number, template in enumerate(templates, start=1)
    }
    selectors, aids = await _get_selectors_and_aids(read_repositories, templates)
    return CrawlerInstructionsOut(
        format=INSTRUCTIONS_FORMAT,
        settings=InstructionSettingsBase(
            root=template_keys.get(version.message_template_root_id),
            is_proxy_ladder_enabled=version.is_proxy_ladder_enabled,
            is_host_session_sharing_enabled=version.is_host_session_sharing_enabled,
        ),
        templates={
            template_keys[template.id]: _template_out(template)
            for template in templates
        },
        aids={template_keys[aid.message_template_id]: _aid_out(aid) for aid in aids},
        selectors=_selectors_out(selectors, template_keys),
    )


async def export_instructions_text(
    read_repositories: AbstractReadRepositories, current_user: UserOut, version_id: str
) -> str:
    """Return a version's instructions as the YAML file's text.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404).
    """
    return render_instructions_text(
        await export_instructions(read_repositories, current_user, version_id)
    )


def render_instructions_text(instructions: CrawlerInstructionsOut) -> str:
    """Return the file's YAML, leaving out values at their defaults."""
    document = {
        "format": instructions.format,
        **instructions.model_dump(
            mode="json", exclude_defaults=True, exclude={"format"}
        ),
    }
    return yaml.dump(
        document,
        Dumper=_BlockTextDumper,
        sort_keys=False,
        allow_unicode=True,
        width=YAML_LINE_WIDTH,
    )


def parse_instructions_text(text: str | bytes) -> CrawlerInstructionsCreate:
    """Read an instructions file's YAML.

    Raises:
        ValidationException: the text is not YAML, uses an alias, or
            doesn't match the file's schema (422; schema errors are
            listed by field, e.g. `templates.a.action: …`).
    """
    try:
        document = yaml.load(text, Loader=_NoAliasLoader)
    except yaml.YAMLError as error:
        raise ValidationException(
            f"Instructions file is not valid YAML: {error}", 422
        ) from error
    try:
        return CrawlerInstructionsCreate.model_validate(document)
    except ValidationError as error:
        raise ValidationException(
            "Invalid instructions: " + _describe_schema_errors(error), 422
        ) from error


def _describe_schema_errors(error: ValidationError) -> str:
    """Return the schema errors as `field.path: message`, joined."""
    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc']) or 'file'}: {detail['msg']}"
        for detail in error.errors(include_url=False)
    )


async def import_instructions(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    version_id: str,
    instructions: CrawlerInstructionsCreate,
) -> CrawlerVersionOut:
    """Replace a version's templates, aids, and selectors with a file's.

    A draft is replaced in place; a published version is forked into a
    new draft that takes the file, and stays as it was.

    Returns:
        The version the file landed on: the draft.

    Raises:
        ValidationException: a key the file points at is missing, a
            selector's parent is on another template, selectors nest in
            a cycle, or a non-`value`/`boolean` selector reads the
            context (422, every problem listed).
        ValidationException: the version or its Crawler does not exist
            (404), the version is archived, or it is published and a
            draft is already open (409).
        ValidationException: an aid's proxy or rate limit does not
            exist (404).
    """
    problems = find_instruction_problems(instructions)
    if problems:
        raise ValidationException("Invalid instructions: " + "; ".join(problems), 422)
    version, _template_id_map, _selector_id_map = (
        await crawler_version_service.resolve_editable_version(
            write_repositories, current_user, version_id
        )
    )
    await _ensure_aid_references_exist(write_repositories, instructions.aids.values())

    await _delete_templates(write_repositories, version.id)
    template_ids = await _create_templates(write_repositories, version.id, instructions)
    await _create_aids(write_repositories, template_ids, instructions)
    await _create_selectors(write_repositories, template_ids, instructions)
    saved = await write_repositories.crawler_versions.save(
        replace(
            version,
            message_template_root_id=template_ids[_root_key(instructions)],
            is_proxy_ladder_enabled=instructions.settings.is_proxy_ladder_enabled,
            is_host_session_sharing_enabled=(
                instructions.settings.is_host_session_sharing_enabled
            ),
            updated_at=_now(),
        )
    )
    await write_repositories.commit()

    logger.info(
        "Instructions imported: version_id=%s, templates=%d, selectors=%d",
        saved.id,
        len(instructions.templates),
        len(instructions.selectors),
    )
    return CrawlerVersionOut.model_validate(saved)


def find_instruction_problems(instructions: CrawlerInstructionsCreate) -> list[str]:
    """Return what is wrong with a file's links between its blocks.

    Each entry names where the problem is (`settings.root`,
    `aids.<key>`, `selectors.<key>`), so a whole file is fixed in one
    pass rather than one error at a time.
    """
    return [
        *_root_problems(instructions),
        *_aid_problems(instructions),
        *(
            f"selectors.{key}: {problem}"
            for key, selector in instructions.selectors.items()
            for problem in _selector_problems(instructions, selector)
        ),
        *_cycle_problems(instructions),
    ]


def find_unknown_placeholders(
    instructions: CrawlerInstructionsCreate, known_keys: set[str]
) -> list[str]:
    """Return the templates' placeholders nothing will fill.

    A placeholder is filled by a selector of the file titled like it,
    or by a key of the Crawler's Context, `name` or `name[]` alike
    (`known_keys`).
    """
    titles = {selector.title for selector in instructions.selectors.values()}
    known = titles | {key.removesuffix("[]") for key in known_keys}
    return [
        problem
        for key, template in instructions.templates.items()
        for problem in _unknown_placeholders(key, template, known)
    ]


def _unknown_placeholders(
    key: str, template: InstructionTemplateBase, known: set[str | None]
) -> list[str]:
    """Return a problem per placeholder of a template not in `known`."""
    unknown = extract_placeholders(_template_texts(template)) - known
    return [
        f"templates.{key}: placeholder `{name}` is neither harvested by a "
        f"selector titled `{name}` nor in the Crawler's Context"
        for name in sorted(unknown)
    ]


def _template_texts(template: InstructionTemplateBase) -> list[str]:
    """Return a template's texts that may hold placeholders."""
    header_values = [str(value) for value in (template.headers or {}).values()]
    return [template.url, template.body or "", *header_values]


def _root_problems(instructions: CrawlerInstructionsCreate) -> list[str]:
    """Return a problem when the root names no template."""
    root = instructions.settings.root
    if None is root or root in instructions.templates:
        return []
    return [f"settings.root: no template `{root}`"]


def _aid_problems(instructions: CrawlerInstructionsCreate) -> list[str]:
    """Return a problem for each aid keyed after no template."""
    return [
        f"aids.{key}: no template `{key}`"
        for key in instructions.aids
        if key not in instructions.templates
    ]


def _selector_problems(
    instructions: CrawlerInstructionsCreate, selector: InstructionSelectorBase
) -> list[str]:
    """Return what is wrong with one selector's links and source."""
    problems = _parent_problems(instructions, selector)
    if selector.template not in instructions.templates:
        problems.insert(0, f"no template `{selector.template}`")
    if "context" == selector.source and selector.type not in CONTEXT_SELECTOR_TYPES:
        problems.append("only value and boolean selectors can read the context")
    return problems


def _parent_problems(
    instructions: CrawlerInstructionsCreate, selector: InstructionSelectorBase
) -> list[str]:
    """Return a problem when the parent is missing or elsewhere."""
    if None is selector.parent:
        return []
    parent = instructions.selectors.get(selector.parent)
    if None is parent:
        return [f"no selector `{selector.parent}`"]
    if parent.template != selector.template:
        return [f"parent `{selector.parent}` is on another template"]
    return []


def _cycle_problems(instructions: CrawlerInstructionsCreate) -> list[str]:
    """Return a problem naming the selectors that nest in a cycle."""
    _ordered, cyclic = order_parents_first(_parent_keys(instructions))
    if not cyclic:
        return []
    return [f"selectors: parents nest in a cycle: {', '.join(cyclic)}"]


def _parent_keys(instructions: CrawlerInstructionsCreate) -> dict[str, str | None]:
    """Map each selector's key to its parent's key."""
    return {key: selector.parent for key, selector in instructions.selectors.items()}


def _root_key(instructions: CrawlerInstructionsCreate) -> str:
    """Return the root template's key; the first one when unset."""
    return instructions.settings.root or next(iter(instructions.templates))


async def _ensure_aid_references_exist(
    write_repositories: AbstractWriteRepositories,
    aids: Iterable[InstructionAidBase],
) -> None:
    """Check every proxy and rate limit the aids select exists.

    Raises:
        ValidationException: one does not exist (404).
    """
    aids = list(aids)
    for proxy_id in {aid.selected_proxy_id for aid in aids} - {None}:
        await message_aid_proxy_service.get_proxy(write_repositories, proxy_id)
    for rate_limit_id in {aid.rate_limit_id for aid in aids} - {None}:
        await message_aid_rate_limit_service.get_rate_limit(
            write_repositories, rate_limit_id
        )


async def _delete_templates(
    write_repositories: AbstractWriteRepositories, version_id: str
) -> None:
    """Stage deleting a version's templates, selectors, and aids."""
    templates = (
        await write_repositories.message_templates.get_all_by_crawler_version_id(
            version_id
        )
    )
    for template in templates:
        await write_repositories.message_selectors.delete_by_message_template_id(
            template.id
        )
        await write_repositories.message_aids.delete_by_message_template_id(template.id)
        await write_repositories.message_templates.delete(template.id)


async def _create_templates(
    write_repositories: AbstractWriteRepositories,
    version_id: str,
    instructions: CrawlerInstructionsCreate,
) -> dict[str, str]:
    """Stage the file's templates; return their ids by key."""
    template_ids: dict[str, str] = {}
    for key, template_input in instructions.templates.items():
        now = _now()
        template = await write_repositories.message_templates.save(
            MessageTemplate(
                **template_input.model_dump(),
                id=str(uuid.uuid4()),
                crawler_version_id=version_id,
                created_at=now,
                updated_at=now,
            )
        )
        template_ids[key] = template.id
    return template_ids


async def _create_aids(
    write_repositories: AbstractWriteRepositories,
    template_ids: dict[str, str],
    instructions: CrawlerInstructionsCreate,
) -> None:
    """Stage each aid on the template its key names."""
    for key, aid_input in instructions.aids.items():
        now = _now()
        await write_repositories.message_aids.save(
            MessageAid(
                **aid_input.model_dump(),
                id=str(uuid.uuid4()),
                message_template_id=template_ids[key],
                created_at=now,
                updated_at=now,
            )
        )


async def _create_selectors(
    write_repositories: AbstractWriteRepositories,
    template_ids: dict[str, str],
    instructions: CrawlerInstructionsCreate,
) -> None:
    """Stage the selectors, each parent before its children."""
    selector_ids: dict[str, str] = {}
    ordered, _cyclic = order_parents_first(_parent_keys(instructions))
    for key in ordered:
        selector_input = instructions.selectors[key]
        now = _now()
        selector = await write_repositories.message_selectors.save(
            MessageSelector(
                id=str(uuid.uuid4()),
                message_template_id=template_ids[selector_input.template],
                parent_selector_id=selector_ids.get(selector_input.parent or ""),
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
        )
        selector_ids[key] = selector.id


async def _get_selectors_and_aids(
    read_repositories: AbstractReadRepositories, templates: list[MessageTemplate]
) -> tuple[list[MessageSelector], list[MessageAid]]:
    """Return the templates' selectors (parents first) and aids."""
    selectors: list[MessageSelector] = []
    aids: list[MessageAid] = []
    for template in templates:
        selectors.extend(
            _parents_first(
                await read_repositories.message_selectors.get_all_by_message_template_id(
                    template.id
                )
            )
        )
        aid = await read_repositories.message_aids.get_by_message_template_id(
            template.id
        )
        aids.extend([] if None is aid else [aid])
    return selectors, aids


def _root_first(
    templates: list[MessageTemplate], root_id: str | None
) -> list[MessageTemplate]:
    """Return the templates with the root moved to the front."""
    return sorted(templates, key=lambda template: template.id != root_id)


def _parents_first(selectors: list[MessageSelector]) -> list[MessageSelector]:
    """Return a template's selectors, each right before its children."""
    by_id = {selector.id: selector for selector in selectors}
    ordered, cyclic = order_parents_first(
        {selector.id: selector.parent_selector_id for selector in selectors}
    )
    return [by_id[selector_id] for selector_id in [*ordered, *cyclic]]


def _template_out(template: MessageTemplate) -> InstructionTemplateBase:
    """Map a template onto its file entry."""
    return InstructionTemplateBase(
        action=template.action,
        url=template.url,
        body=template.body,
        headers=template.headers,
    )


def _aid_out(aid: MessageAid) -> InstructionAidBase:
    """Map an aid onto its file entry."""
    return InstructionAidBase(
        selected_proxy_id=aid.selected_proxy_id,
        retry_codes=aid.retry_codes,
        success_codes=aid.success_codes,
        ttl=aid.ttl,
        render_mode=aid.render_mode,
        rate_limit_id=aid.rate_limit_id,
        max_retry_attempts=aid.max_retry_attempts,
    )


def _selectors_out(
    selectors: list[MessageSelector], template_keys: dict[str, str]
) -> dict[str, InstructionSelectorBase]:
    """Map selectors onto their file entries, keyed by their names."""
    keys = _name_selectors(selectors, template_keys)
    return {
        keys[selector.id]: InstructionSelectorBase(
            template=template_keys[selector.message_template_id],
            parent=keys.get(selector.parent_selector_id or ""),
            type=selector.type,
            path=selector.path,
            source=selector.source,
            target=selector.target,
            title=selector.title,
            config=selector.config,
        )
        for selector in selectors
    }


def _name_selectors(
    selectors: list[MessageSelector], template_keys: dict[str, str]
) -> dict[str, str]:
    """Return a unique file key for each selector id.

    A title only one selector has is its key, so the file reads in the
    names templates use as placeholders. Otherwise the key is
    `<template key>.<title or type>`, numbered `_2`, `_3`, … on a clash.
    """
    title_counts = Counter(selector.title for selector in selectors)
    keys: dict[str, str] = {}
    for selector in selectors:
        base = _safe_key(_selector_name(selector, template_keys, title_counts))
        keys[selector.id] = _first_free_key(base, set(keys.values()))
    return keys


def _selector_name(
    selector: MessageSelector,
    template_keys: dict[str, str],
    title_counts: Counter[str | None],
) -> str:
    """Return its title when unique, else a template-scoped name."""
    if selector.title and 1 == title_counts[selector.title]:
        return selector.title
    template_key = template_keys[selector.message_template_id]
    return f"{template_key}.{selector.title or selector.type}"


def _safe_key(name: str) -> str:
    """Return `name` with characters a key can't hold made `_`."""
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    if not re.match(r"[A-Za-z0-9_]", key):
        key = f"_{key}"
    return key[: MAX_KEY_LENGTH - 4]


def _first_free_key(base: str, used: set[str]) -> str:
    """Return `base`, or `base_2`, `base_3`, … when it is taken."""
    key, number = base, 2
    while key in used:
        key, number = f"{base}_{number}", number + 1
    return key
