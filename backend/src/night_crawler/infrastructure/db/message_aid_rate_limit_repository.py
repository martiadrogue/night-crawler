"""MongoDB storage for rate-limit rules."""

import limits
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageAidRateLimit
from night_crawler.domain.ports.repositories import (
    AbstractMessageAidRateLimitRepository,
)
from night_crawler.infrastructure.db.mongo_repository import (
    NEWEST_FIRST,
    MongoRepository,
)


class MongoMessageAidRateLimitRepository(
    MongoRepository[MessageAidRateLimit], AbstractMessageAidRateLimitRepository
):
    """MongoDB storage for rate-limit rules."""

    entity_type = MessageAidRateLimit
    collection_name = "message_aid_rate_limits"

    async def get_by_id(self, rate_limit_id: str) -> MessageAidRateLimit | None:
        """Return the rule with this id, if any."""
        return await self._find_one({"_id": rate_limit_id})

    async def get_all(self) -> list[MessageAidRateLimit]:
        """Return every rule, newest first."""
        return await self._find_many({}, NEWEST_FIRST)

    async def save(self, rate_limit: MessageAidRateLimit) -> MessageAidRateLimit:
        """Insert or update a rule; return a fresh copy.

        The string is parsed here because `limits`, the library that
        enforces it, is the only authority on its syntax.

        Raises:
            ValidationException: `rate_limit_string` is not valid
                `limits` syntax, e.g. `"100/minute"` (400).
        """
        try:
            limits.parse(rate_limit.rate_limit_string)
        except ValueError as exception:
            raise ValidationException(
                f"Invalid rate limit string: {rate_limit.rate_limit_string!r}.", 400
            ) from exception
        return await self._save(rate_limit)

    async def delete(self, rate_limit_id: str) -> None:
        """Delete a rule document only; references are the caller's."""
        await self._delete_many({"_id": rate_limit_id})
