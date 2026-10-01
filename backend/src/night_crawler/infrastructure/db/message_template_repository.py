"""MongoDB storage for Message Templates."""

from night_crawler.domain.model.entities import MessageTemplate
from night_crawler.domain.ports.repositories import (
    AbstractMessageTemplateRepository,
)
from night_crawler.infrastructure.db.mongo_repository import MongoRepository


class MongoMessageTemplateRepository(
    MongoRepository[MessageTemplate], AbstractMessageTemplateRepository
):
    """MongoDB storage for Message Templates."""

    entity_type = MessageTemplate
    collection_name = "message_templates"

    async def get_by_id(self, template_id: str) -> MessageTemplate | None:
        """Return the template with this id, if any."""
        return await self._find_one({"_id": template_id})

    async def get_all_by_crawler_version_id(
        self, version_id: str
    ) -> list[MessageTemplate]:
        """Return a version's templates, oldest first."""
        return await self._find_many({"crawler_version_id": version_id})

    async def save(self, template: MessageTemplate) -> MessageTemplate:
        """Insert or update a template; return a fresh copy."""
        return await self._save(template)

    async def delete(self, template_id: str) -> None:
        """Delete a template document; children are the caller's."""
        await self._delete_many({"_id": template_id})
