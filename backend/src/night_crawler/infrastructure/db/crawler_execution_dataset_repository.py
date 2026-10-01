"""MongoDB storage for the CSV each Crawler Execution produced."""

from typing import Any

from night_crawler.domain.model.entities import CrawlerExecutionDataset
from night_crawler.domain.ports.repositories import (
    AbstractCrawlerExecutionDatasetRepository,
)
from night_crawler.infrastructure.db.mongo_repository import (
    MongoRepository,
    translate_errors,
)


class MongoCrawlerExecutionDatasetRepository(
    MongoRepository[CrawlerExecutionDataset],
    AbstractCrawlerExecutionDatasetRepository,
):
    """MongoDB storage for execution datasets, one per run (DM-7)."""

    entity_type = CrawlerExecutionDataset
    collection_name = "crawler_execution_datasets"
    conflict_message = "This execution already has a dataset."

    async def get_by_crawler_execution_id(
        self, execution_id: str
    ) -> CrawlerExecutionDataset | None:
        """Return the execution's dataset, if it has one."""
        return await self._find_one({"crawler_execution_id": execution_id})

    async def get_validations_by_crawler_execution_ids(
        self, execution_ids: list[str]
    ) -> dict[str, dict[str, Any] | None]:
        """Return each execution's validation report, not its CSV."""
        with translate_errors(self.conflict_message):
            cursor = self._collection.find(
                {"crawler_execution_id": {"$in": execution_ids}},
                {"crawler_execution_id": 1, "validation": 1},
                session=self._session,
            )
            documents = await cursor.to_list()
        return {
            document["crawler_execution_id"]: document.get("validation")
            for document in documents
        }

    async def save(self, dataset: CrawlerExecutionDataset) -> CrawlerExecutionDataset:
        """Insert or update a dataset; return a fresh copy.

        Raises:
            ValidationException: the execution already has another
                dataset (409).
        """
        return await self._save(dataset)

    async def delete_by_crawler_execution_ids(self, execution_ids: list[str]) -> None:
        """Delete the datasets of these executions."""
        await self._delete_many({"crawler_execution_id": {"$in": execution_ids}})
