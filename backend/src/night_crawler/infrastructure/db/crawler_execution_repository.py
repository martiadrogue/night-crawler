"""MongoDB storage for Crawler Executions."""

from night_crawler.domain.model.constants import TESTING_QUEUE
from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.ports.repositories import (
    AbstractCrawlerExecutionRepository,
)
from night_crawler.infrastructure.db.mongo_repository import (
    NEWEST_FIRST,
    MongoRepository,
)


class MongoCrawlerExecutionRepository(
    MongoRepository[CrawlerExecution], AbstractCrawlerExecutionRepository
):
    """MongoDB storage for Crawler Executions."""

    entity_type = CrawlerExecution
    collection_name = "crawler_executions"

    async def get_by_id(self, execution_id: str) -> CrawlerExecution | None:
        """Return the execution with this id, if any."""
        return await self._find_one({"_id": execution_id})

    async def get_all_by_crawler_id(
        self,
        crawler_id: str,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[CrawlerExecution]:
        """Return a Crawler's executions, newest first."""
        query = {"crawler_id": crawler_id}
        if None is not status:
            query["status"] = status
        return await self._find_many(query, NEWEST_FIRST, limit)

    async def get_all(
        self,
        status: str | None = None,
        parsing_status: str | None = None,
        queue: str | None = None,
        crawler_ids: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CrawlerExecution]:
        """Return every Crawler's executions, newest first."""
        filters = (("status", status), ("parsing_status", parsing_status))
        query: dict = {
            key: value for key, value in (*filters, ("queue", queue)) if value
        }
        if None is not crawler_ids:
            query["crawler_id"] = {"$in": crawler_ids}
        return await self._find_many(query, NEWEST_FIRST, limit, offset)

    async def get_latest_by_crawler_id(
        self, crawler_id: str
    ) -> CrawlerExecution | None:
        """Return the Crawler's most recent run, test runs excluded."""
        latest = await self._find_many(
            {"crawler_id": crawler_id, "queue": {"$ne": TESTING_QUEUE}},
            NEWEST_FIRST,
            1,
        )
        return latest[0] if latest else None

    async def has_any_by_crawler_version_id(self, version_id: str) -> bool:
        """Tell whether any execution ran this version."""
        return 0 < await self._count({"crawler_version_id": version_id})

    async def save(self, execution: CrawlerExecution) -> CrawlerExecution:
        """Insert or update an execution; return a fresh copy."""
        return await self._save(execution)

    async def delete_by_crawler_id(self, crawler_id: str) -> None:
        """Delete every execution of a Crawler."""
        await self._delete_many({"crawler_id": crawler_id})
