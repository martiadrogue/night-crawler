"""MongoDB storage for Crawlers."""

import re

from night_crawler.domain.model.entities import Crawler
from night_crawler.domain.ports.repositories import AbstractCrawlerRepository
from night_crawler.infrastructure.db.mongo_repository import MongoRepository
from pymongo import ASCENDING, DESCENDING


class MongoCrawlerRepository(MongoRepository[Crawler], AbstractCrawlerRepository):
    """MongoDB storage for Crawlers."""

    entity_type = Crawler
    collection_name = "crawlers"

    async def get_by_id(self, crawler_id: str) -> Crawler | None:
        """Return the Crawler with this id, if any."""
        return await self._find_one({"_id": crawler_id})

    async def get_all_by_title_containing(self, text: str) -> list[Crawler]:
        """Return the Crawlers whose title contains `text`, any case."""
        return await self._find_many(
            {"title": {"$regex": re.escape(text), "$options": "i"}}
        )

    async def get_all_by_ids(self, crawler_ids: list[str]) -> list[Crawler]:
        """Return the Crawlers with these ids, skipping missing ones."""
        return await self._find_many({"_id": {"$in": crawler_ids}})

    async def get_all(
        self,
        source_id: str | None = None,
        dataset_id: str | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
        limit: int | None = None,
    ) -> list[Crawler]:
        """Return Crawlers, filtered and sorted."""
        query = {
            key: value
            for key, value in (("source_id", source_id), ("dataset_id", dataset_id))
            if None is not value
        }
        direction = ASCENDING if "asc" == order else DESCENDING
        return await self._find_many(query, [(sort_by, direction)], limit)

    async def get_all_by_user_id(self, user_id: str) -> list[Crawler]:
        """Return every Crawler a user created."""
        return await self._find_many({"user_id": user_id})

    async def has_any_by_source_id(self, source_id: str) -> bool:
        """Tell whether any Crawler is linked to this Source."""
        return bool(await self._find_many({"source_id": source_id}, limit=1))

    async def get_all_by_dataset_id(self, dataset_id: str) -> list[Crawler]:
        """Return every Crawler linked to this Dataset."""
        return await self._find_many({"dataset_id": dataset_id})

    async def save(self, crawler: Crawler) -> Crawler:
        """Insert or update a Crawler; return a fresh copy."""
        return await self._save(crawler)

    async def delete(self, crawler_id: str) -> None:
        """Delete a Crawler document only; children are the caller's."""
        await self._delete_many({"_id": crawler_id})
