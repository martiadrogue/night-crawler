"""MongoDB storage for Message Selectors."""

from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.ports.repositories import (
    AbstractMessageSelectorRepository,
)
from night_crawler.infrastructure.db.mongo_repository import MongoRepository


class MongoMessageSelectorRepository(
    MongoRepository[MessageSelector], AbstractMessageSelectorRepository
):
    """MongoDB storage for Message Selectors."""

    entity_type = MessageSelector
    collection_name = "message_selectors"

    async def get_by_id(self, selector_id: str) -> MessageSelector | None:
        """Return the selector with this id, if any."""
        return await self._find_one({"_id": selector_id})

    async def get_all_by_message_template_id(
        self, template_id: str
    ) -> list[MessageSelector]:
        """Return a template's selectors, oldest first."""
        return await self._find_many({"message_template_id": template_id})

    async def save(self, selector: MessageSelector) -> MessageSelector:
        """Insert or update a selector; return a fresh copy."""
        return await self._save(selector)

    async def delete_all(self, selector_ids: list[str]) -> None:
        """Delete these selectors."""
        await self._delete_many({"_id": {"$in": selector_ids}})

    async def delete_by_message_template_id(self, template_id: str) -> None:
        """Delete every selector of a template."""
        await self._delete_many({"message_template_id": template_id})
