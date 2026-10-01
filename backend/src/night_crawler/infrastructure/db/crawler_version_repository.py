"""MongoDB storage for Crawler Versions."""

from night_crawler.domain.model.entities import CrawlerVersion
from night_crawler.domain.ports.repositories import AbstractCrawlerVersionRepository
from night_crawler.infrastructure.db.mongo_repository import MongoRepository
from pymongo import ASCENDING


class MongoCrawlerVersionRepository(
    MongoRepository[CrawlerVersion], AbstractCrawlerVersionRepository
):
    """MongoDB storage for Crawler Versions.

    Partial unique indexes allow at most one draft and one published
    version per Crawler (DOMAIN_MODEL DM-3).
    """

    entity_type = CrawlerVersion
    collection_name = "crawler_versions"
    conflict_message = "This crawler already has a version with that status."

    async def get_by_id(self, version_id: str) -> CrawlerVersion | None:
        """Return the version with this id, if any."""
        return await self._find_one({"_id": version_id})

    async def get_all_by_crawler_id(self, crawler_id: str) -> list[CrawlerVersion]:
        """Return a Crawler's versions, oldest first."""
        return await self._find_many(
            {"crawler_id": crawler_id}, [("created_at", ASCENDING)]
        )

    async def get_all_by_user_id(self, user_id: str) -> list[CrawlerVersion]:
        """Return every version a user owns."""
        return await self._find_many({"user_id": user_id})

    async def get_published_by_crawler_id(
        self, crawler_id: str
    ) -> CrawlerVersion | None:
        """Return the Crawler's published version, if any."""
        return await self._find_one({"crawler_id": crawler_id, "status": "published"})

    async def get_draft_by_crawler_id(self, crawler_id: str) -> CrawlerVersion | None:
        """Return the Crawler's open draft, if any."""
        return await self._find_one({"crawler_id": crawler_id, "status": "draft"})

    async def save(self, version: CrawlerVersion) -> CrawlerVersion:
        """Insert or update a version; return a fresh copy.

        Raises:
            ValidationException: a second draft or published version
                (409).
        """
        return await self._save(version)

    async def delete(self, version_id: str) -> None:
        """Delete a version document only; its tree is the caller's."""
        await self._delete_many({"_id": version_id})
