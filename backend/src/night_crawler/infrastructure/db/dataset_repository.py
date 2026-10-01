"""MongoDB storage for Datasets."""

from dataclasses import replace
from typing import Any

from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.model.value_objects import DatasetField
from night_crawler.domain.ports.repositories import AbstractDatasetRepository
from night_crawler.infrastructure.db.mongo_repository import MongoRepository
from pymongo import ASCENDING


class MongoDatasetRepository(MongoRepository[Dataset], AbstractDatasetRepository):
    """MongoDB storage for Datasets."""

    entity_type = Dataset
    collection_name = "datasets"
    conflict_message = "A dataset with this name already exists."

    def _to_domain(self, document: dict[str, Any]) -> Dataset:
        """Map a document onto a Dataset, its fields included."""
        dataset = super()._to_domain(document)
        return replace(
            dataset, fields=[DatasetField(**field) for field in dataset.fields]
        )

    async def get_by_id(self, dataset_id: str) -> Dataset | None:
        """Return the Dataset with this id, if any."""
        return await self._find_one({"_id": dataset_id})

    async def get_by_name(self, name: str) -> Dataset | None:
        """Return the Dataset with this name, if any."""
        return await self._find_one({"name": name})

    async def get_all(self) -> list[Dataset]:
        """Return every Dataset, by name."""
        return await self._find_many({}, [("name", ASCENDING)])

    async def save(self, dataset: Dataset) -> Dataset:
        """Insert or update a Dataset; return a fresh copy.

        Raises:
            ValidationException: another Dataset has this name (409).
        """
        return await self._save(dataset)

    async def delete(self, dataset_id: str) -> None:
        """Delete a Dataset document only; crawlers are the caller's."""
        await self._delete_many({"_id": dataset_id})
