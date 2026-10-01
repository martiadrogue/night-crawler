"""MongoDB storage for Message Aids."""

from night_crawler.domain.model.entities import MessageAid
from night_crawler.domain.ports.repositories import AbstractMessageAidRepository
from night_crawler.infrastructure.db.mongo_repository import MongoRepository


class MongoMessageAidRepository(
    MongoRepository[MessageAid], AbstractMessageAidRepository
):
    """MongoDB storage for Message Aids; one per template (DM-7)."""

    entity_type = MessageAid
    collection_name = "message_aids"
    conflict_message = "This template already has a message aid."

    async def get_by_message_template_id(self, template_id: str) -> MessageAid | None:
        """Return the template's aid, if any."""
        return await self._find_one({"message_template_id": template_id})

    async def save(self, aid: MessageAid) -> MessageAid:
        """Insert or update an aid; return a fresh copy.

        Raises:
            ValidationException: the template already has another aid
                (409).
        """
        return await self._save(aid)

    async def delete_by_message_template_id(self, template_id: str) -> None:
        """Delete the template's aid, if any."""
        await self._delete_many({"message_template_id": template_id})

    async def clear_selected_proxy_id(self, proxy_id: str) -> None:
        """Set `selected_proxy_id` to `None` where it is `proxy_id`."""
        await self._clear_reference("selected_proxy_id", proxy_id)

    async def clear_rate_limit_id(self, rate_limit_id: str) -> None:
        """Null every `rate_limit_id` equal to `rate_limit_id`."""
        await self._clear_reference("rate_limit_id", rate_limit_id)
