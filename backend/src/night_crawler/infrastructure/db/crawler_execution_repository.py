"""MongoDB storage for Crawler Executions."""

from datetime import datetime

from night_crawler.domain.model.constants import TESTING_QUEUE
from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.ports.repositories import (
    AbstractCrawlerExecutionRepository,
    StatusCount,
)
from night_crawler.domain.rules.execution_history import (
    ENDED_STATUSES,
    FAILED_STATUSES,
    SUCCESSFUL_PARSING_STATUS,
    SUCCESSFUL_STATUS,
)
from night_crawler.infrastructure.db.mongo_repository import (
    NEWEST_FIRST,
    MongoRepository,
    translate_errors,
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
        *,
        queues: tuple[str, ...] | None = None,
        offset: int = 0,
        created_since: datetime | None = None,
    ) -> list[CrawlerExecution]:
        """Return a Crawler's executions, newest first."""
        query: dict = {"crawler_id": crawler_id}
        if None is not status:
            query["status"] = status
        if None is not queues:
            query["queue"] = {"$in": list(queues)}
        if None is not created_since:
            query["created_at"] = {"$gte": created_since}
        return await self._find_many(query, NEWEST_FIRST, limit, offset)

    async def count_by_status_by_crawler_id(
        self, crawler_id: str, queues: tuple[str, ...], created_since: datetime
    ) -> list[StatusCount]:
        """Count runs per status pair, in one `$group` aggregation."""
        pipeline = [
            {
                "$match": {
                    "crawler_id": crawler_id,
                    "queue": {"$in": list(queues)},
                    "created_at": {"$gte": created_since},
                }
            },
            {
                "$group": {
                    "_id": {"status": "$status", "parsing_status": "$parsing_status"},
                    "count": {"$sum": 1},
                }
            },
        ]
        with translate_errors(self.conflict_message):
            cursor = await self._collection.aggregate(pipeline, session=self._session)
            db_groups = await cursor.to_list()
        return [
            StatusCount(
                status=db_group["_id"]["status"],
                parsing_status=db_group["_id"]["parsing_status"],
                count=db_group["count"],
            )
            for db_group in db_groups
        ]

    async def get_latest_verification_failure_by_crawler_id(
        self, crawler_id: str, queues: tuple[str, ...]
    ) -> CrawlerExecution | None:
        """Return the newest run that succeeded without being parsed."""
        return await self._find_latest(
            {
                "crawler_id": crawler_id,
                "status": SUCCESSFUL_STATUS,
                "parsing_status": {"$ne": SUCCESSFUL_PARSING_STATUS},
                "queue": {"$in": list(queues)},
            }
        )

    async def get_latest_failure_by_crawler_id(
        self, crawler_id: str, queues: tuple[str, ...]
    ) -> CrawlerExecution | None:
        """Return the newest run that failed or was cancelled."""
        return await self._find_latest(
            {
                "crawler_id": crawler_id,
                "status": {"$in": list(FAILED_STATUSES)},
                "queue": {"$in": list(queues)},
            }
        )

    async def _find_latest(self, query: dict) -> CrawlerExecution | None:
        """Return the newest execution matching `query`, if any."""
        latest = await self._find_many(query, NEWEST_FIRST, 1)
        return latest[0] if latest else None

    async def get_ended_by_crawler_id(
        self,
        crawler_id: str,
        queues: tuple[str, ...],
        limit: int,
        offset: int = 0,
    ) -> list[CrawlerExecution]:
        """Return a Crawler's ended executions, newest first."""
        query = {
            "crawler_id": crawler_id,
            "status": {"$in": list(ENDED_STATUSES)},
            "queue": {"$in": list(queues)},
        }
        return await self._find_many(query, NEWEST_FIRST, limit, offset)

    async def get_successful_by_crawler_id(
        self, crawler_id: str, queues: tuple[str, ...], limit: int
    ) -> list[CrawlerExecution]:
        """Return a Crawler's successful executions, newest first."""
        query = {
            "crawler_id": crawler_id,
            "status": SUCCESSFUL_STATUS,
            "parsing_status": SUCCESSFUL_PARSING_STATUS,
            "queue": {"$in": list(queues)},
        }
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
