"""Use cases for Sources, the websites crawled data comes from."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import Source
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.schemas.source import SourceCreate, SourceOut, SourceUpdate

logger = logging.getLogger(__name__)


def _to_out(source: Source) -> SourceOut:
    """Map a Source onto its API schema."""
    return SourceOut(
        id=source.id,
        name=source.name,
        url=source.url,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


async def get_sources(read_repositories: AbstractReadRepositories) -> list[SourceOut]:
    """Return every Source, by name."""
    return [_to_out(source) for source in await read_repositories.sources.get_all()]


async def get_source(repositories: AbstractRepositories, source_id: str) -> SourceOut:
    """Return one Source.

    Raises:
        ValidationException: it does not exist (404).
    """
    return _to_out(await _get_source_or_404(repositories, source_id))


async def ensure_source_exists(
    repositories: AbstractRepositories, source_id: str
) -> None:
    """Check a Crawler may link to this Source.

    Raises:
        ValidationException: no Source has this id (400).
    """
    if None is await repositories.sources.get_by_id(source_id):
        raise ValidationException(f"Unknown source '{source_id}'.", 400)


async def create_source(
    write_repositories: AbstractWriteRepositories, source_input: SourceCreate
) -> SourceOut:
    """Create a Source.

    Raises:
        ValidationException: another Source has this name (409).
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    saved = await write_repositories.sources.save(
        Source(
            **source_input.model_dump(),
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
        )
    )
    await write_repositories.commit()

    logger.info("Source created: id=%s, name=%s", saved.id, saved.name)
    return _to_out(saved)


async def update_source(
    write_repositories: AbstractWriteRepositories,
    source_id: str,
    source_input: SourceUpdate,
) -> SourceOut:
    """Apply a partial update to a Source.

    Raises:
        ValidationException: it does not exist (404), or another Source
            has the new name (409).
    """
    source = await _get_source_or_404(write_repositories, source_id)
    saved = await write_repositories.sources.save(
        replace(
            source,
            **source_input.model_dump(exclude_unset=True),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await write_repositories.commit()
    return _to_out(saved)


async def delete_source(
    write_repositories: AbstractWriteRepositories, source_id: str
) -> None:
    """Delete a Source no Crawler is linked to.

    Raises:
        ValidationException: it does not exist (404), or a Crawler still
            uses it (409): every Crawler needs exactly one Source.
    """
    source = await _get_source_or_404(write_repositories, source_id)
    if await write_repositories.crawlers.has_any_by_source_id(source.id):
        raise ValidationException(
            "This source is used by a crawler; link the crawler to another "
            "source first.",
            409,
        )
    await write_repositories.sources.delete(source.id)
    await write_repositories.commit()
    logger.info("Source deleted: id=%s", source.id)


async def _get_source_or_404(
    repositories: AbstractRepositories, source_id: str
) -> Source:
    """Return the Source.

    Raises:
        ValidationException: it does not exist (404).
    """
    source = await repositories.sources.get_by_id(source_id)
    if None is source:
        raise ValidationException("Source not found.", 404)
    return source
