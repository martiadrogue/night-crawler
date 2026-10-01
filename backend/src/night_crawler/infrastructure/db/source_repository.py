"""MongoDB storage for Sources."""

from night_crawler.domain.model.entities import Source
from night_crawler.domain.ports.repositories import AbstractSourceRepository
from night_crawler.infrastructure.db.mongo_repository import MongoRepository
from pymongo import ASCENDING


class MongoSourceRepository(MongoRepository[Source], AbstractSourceRepository):
    """MongoDB storage for Sources."""

    entity_type = Source
    collection_name = "sources"
    conflict_message = "A source with this name already exists."

    async def get_by_id(self, source_id: str) -> Source | None:
        """Return the Source with this id, if any."""
        return await self._find_one({"_id": source_id})

    async def get_all(self) -> list[Source]:
        """Return every Source, by name."""
        return await self._find_many({}, [("name", ASCENDING)])

    async def save(self, source: Source) -> Source:
        """Insert or update a Source; return a fresh copy.

        Raises:
            ValidationException: another Source has this name (409).
        """
        return await self._save(source)

    async def delete(self, source_id: str) -> None:
        """Delete a Source document only; crawlers are the caller's."""
        await self._delete_many({"_id": source_id})
