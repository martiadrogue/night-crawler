"""Use cases for Datasets: the fields Crawlers download."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.constants import BUILT_IN_DATASETS
from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.model.value_objects import DatasetField
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.crawler_fields import validate_crawler_fields
from night_crawler.domain.rules.dataset_definition import validate_dataset_definition
from night_crawler.schemas.dataset import (
    DatasetCreate,
    DatasetFieldSchema,
    DatasetOut,
    DatasetUpdate,
)

logger = logging.getLogger(__name__)


def _to_out(dataset: Dataset) -> DatasetOut:
    """Map a Dataset onto its API schema."""
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        fields=[DatasetFieldSchema.model_validate(field) for field in dataset.fields],
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


async def get_datasets(read_repositories: AbstractReadRepositories) -> list[DatasetOut]:
    """Return every Dataset, by name."""
    return [_to_out(dataset) for dataset in await read_repositories.datasets.get_all()]


async def get_dataset(
    repositories: AbstractRepositories, dataset_id: str
) -> DatasetOut:
    """Return one Dataset.

    Raises:
        ValidationException: it does not exist (404).
    """
    return _to_out(await _get_dataset_or_404(repositories, dataset_id))


async def get_linkable_dataset(
    repositories: AbstractRepositories, dataset_id: str | None
) -> Dataset:
    """Return the Dataset a Crawler links to, to check its fields.

    Raises:
        ValidationException: no Dataset has this id (400).
    """
    dataset = (
        None
        if None is dataset_id
        else await repositories.datasets.get_by_id(dataset_id)
    )
    if None is dataset:
        raise ValidationException(f"Unknown dataset '{dataset_id}'.", 400)
    return dataset


async def create_dataset(
    write_repositories: AbstractWriteRepositories, dataset_input: DatasetCreate
) -> DatasetOut:
    """Create a Dataset.

    Raises:
        ValidationException: the definition is invalid (400), or
            another Dataset has this name (409).
    """
    now = _now()
    dataset = Dataset(
        **_to_definition(dataset_input.model_dump()),
        id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
    )
    _ensure_valid_definition(dataset)
    saved = await write_repositories.datasets.save(dataset)
    await write_repositories.commit()

    logger.info("Dataset created: id=%s, name=%s", saved.id, saved.name)
    return _to_out(saved)


async def update_dataset(
    write_repositories: AbstractWriteRepositories,
    dataset_id: str,
    dataset_input: DatasetUpdate,
) -> DatasetOut:
    """Apply a partial update to a Dataset.

    Raises:
        ValidationException: it does not exist (404), the definition is
            invalid (400), or another Dataset has the new name or a
            linked Crawler's fields would no longer fit (409).
    """
    dataset = replace(
        await _get_dataset_or_404(write_repositories, dataset_id),
        **_to_definition(dataset_input.model_dump(exclude_unset=True)),
        updated_at=_now(),
    )
    _ensure_valid_definition(dataset)
    await _ensure_crawlers_still_fit(write_repositories, dataset)

    saved = await write_repositories.datasets.save(dataset)
    await write_repositories.commit()
    return _to_out(saved)


async def delete_dataset(
    write_repositories: AbstractWriteRepositories, dataset_id: str
) -> None:
    """Delete a Dataset no Crawler is linked to.

    Raises:
        ValidationException: it does not exist (404), or a Crawler still
            uses it (409): every Crawler needs exactly one Dataset.
    """
    dataset = await _get_dataset_or_404(write_repositories, dataset_id)
    if await write_repositories.crawlers.get_all_by_dataset_id(dataset.id):
        raise ValidationException(
            "This dataset is used by a crawler; link the crawler to another "
            "dataset first.",
            409,
        )
    await write_repositories.datasets.delete(dataset.id)
    await write_repositories.commit()
    logger.info("Dataset deleted: id=%s", dataset.id)


async def seed_built_in_datasets(write_repositories: AbstractWriteRepositories) -> None:
    """Create each built-in Dataset whose name doesn't exist yet.

    Run at startup; an existing Dataset of that name is left as the
    operator edited it.
    """
    now = _now()
    for definition in BUILT_IN_DATASETS:
        if await write_repositories.datasets.get_by_name(definition["name"]):
            continue
        await write_repositories.datasets.save(
            Dataset(
                **_to_definition(definition),
                id=str(uuid.uuid4()),
                created_at=now,
                updated_at=now,
            )
        )
        logger.info("Built-in dataset created: name=%s", definition["name"])
    await write_repositories.commit()


def _to_definition(values: dict[str, Any]) -> dict[str, Any]:
    """Return Dataset values with each field as a `DatasetField`."""
    if "fields" not in values:
        return values
    return {
        **values,
        "fields": [DatasetField(**field) for field in values["fields"]],
    }


def _ensure_valid_definition(dataset: Dataset) -> None:
    """Refuse an inconsistent definition.

    Raises:
        ValidationException: it is invalid (400).
    """
    errors = validate_dataset_definition(dataset)
    if errors:
        raise ValidationException("Invalid dataset: " + " ".join(errors), 400)


async def _ensure_crawlers_still_fit(
    write_repositories: AbstractWriteRepositories, dataset: Dataset
) -> None:
    """Refuse a change that would break a linked Crawler's fields.

    Raises:
        ValidationException: a linked Crawler's fields no longer fit
            (409), naming it and why.
    """
    for crawler in await write_repositories.crawlers.get_all_by_dataset_id(dataset.id):
        errors = validate_crawler_fields(dataset, crawler.fields)
        if errors:
            raise ValidationException(
                f"Crawler '{crawler.title}' would no longer fit: " + " ".join(errors),
                409,
            )


async def _get_dataset_or_404(
    repositories: AbstractRepositories, dataset_id: str
) -> Dataset:
    """Return the Dataset.

    Raises:
        ValidationException: it does not exist (404).
    """
    dataset = await repositories.datasets.get_by_id(dataset_id)
    if None is dataset:
        raise ValidationException("Dataset not found.", 404)
    return dataset


def _now() -> datetime:
    """Return the current time as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)
