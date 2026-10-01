"""MongoDB storage for the proxy pool."""

from night_crawler.domain.model.entities import MessageAidProxy
from night_crawler.domain.ports.repositories import (
    AbstractMessageAidProxyRepository,
)
from night_crawler.infrastructure.db.mongo_repository import (
    NEWEST_FIRST,
    MongoRepository,
)


class MongoMessageAidProxyRepository(
    MongoRepository[MessageAidProxy], AbstractMessageAidProxyRepository
):
    """MongoDB storage for the proxy pool."""

    entity_type = MessageAidProxy
    collection_name = "message_aid_proxies"

    async def get_by_id(self, proxy_id: str) -> MessageAidProxy | None:
        """Return the proxy with this id, if any."""
        return await self._find_one({"_id": proxy_id})

    async def get_all(self) -> list[MessageAidProxy]:
        """Return every proxy, newest first."""
        return await self._find_many({}, NEWEST_FIRST)

    async def save(self, proxy: MessageAidProxy) -> MessageAidProxy:
        """Insert or update a proxy; return a fresh copy."""
        return await self._save(proxy)

    async def delete(self, proxy_id: str) -> None:
        """Delete a proxy document only; references are the caller's."""
        await self._delete_many({"_id": proxy_id})

    async def clear_rate_limit_id(self, rate_limit_id: str) -> None:
        """Null every `rate_limit_id` equal to `rate_limit_id`."""
        await self._clear_reference("rate_limit_id", rate_limit_id)
