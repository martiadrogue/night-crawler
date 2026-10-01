"""MongoDB storage for Crawler Execution Context entries."""

from night_crawler.domain.model.entities import CrawlerExecutionContext
from night_crawler.domain.ports.repositories import (
    AbstractCrawlerExecutionContextRepository,
)
from night_crawler.infrastructure.db.mongo_repository import MongoRepository
from pymongo import ASCENDING


class MongoCrawlerExecutionContextRepository(
    MongoRepository[CrawlerExecutionContext],
    AbstractCrawlerExecutionContextRepository,
):
    """MongoDB storage for Context entries.

    Unique on execution, key, and position: one entry per scalar key,
    one per element of a `name[]` key (DM-8).
    """

    entity_type = CrawlerExecutionContext
    collection_name = "crawler_execution_contexts"
    conflict_message = "This execution already has that Context value."

    async def get_all_by_crawler_execution_ids(
        self, execution_ids: list[str]
    ) -> list[CrawlerExecutionContext]:
        """Return the Context entries of these executions."""
        return await self._find_many(
            {"crawler_execution_id": {"$in": execution_ids}},
            [("key", ASCENDING), ("position", ASCENDING)],
        )

    async def save_all(
        self, contexts: list[CrawlerExecutionContext]
    ) -> list[CrawlerExecutionContext]:
        """Insert or update entries; return fresh copies.

        Raises:
            ValidationException: a scalar key, or a list key's position,
                repeats within an execution (409).
        """
        return [await self._save(context) for context in contexts]

    async def delete_by_crawler_execution_id_and_key(
        self, execution_id: str, key: str
    ) -> None:
        """Delete every entry of one key in one execution."""
        await self._delete_many({"crawler_execution_id": execution_id, "key": key})

    async def delete_by_crawler_execution_ids(self, execution_ids: list[str]) -> None:
        """Delete every Context entry of these executions."""
        await self._delete_many({"crawler_execution_id": {"$in": execution_ids}})
