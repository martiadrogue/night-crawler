"""MongoDB storage for user accounts."""

from night_crawler.domain.model.entities import User
from night_crawler.domain.ports.repositories import AbstractUserRepository
from night_crawler.infrastructure.db.mongo_repository import (
    NEWEST_FIRST,
    MongoRepository,
)


class MongoUserRepository(MongoRepository[User], AbstractUserRepository):
    """MongoDB storage for user accounts; `email` is unique."""

    entity_type = User
    collection_name = "users"
    conflict_message = "Email already taken."

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this email, if any."""
        return await self._find_one({"email": email})

    async def get_by_id(self, user_id: str) -> User | None:
        """Return the user with this id, if any."""
        return await self._find_one({"_id": user_id})

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[User]:
        """Return users, newest first."""
        return await self._find_many({}, NEWEST_FIRST, limit, offset)

    async def count_by_role(self, role: str) -> int:
        """Return how many users hold `role`."""
        return await self._count({"role": role})

    async def save(self, user: User) -> User:
        """Insert or update a user; return a fresh copy.

        Raises:
            ValidationException: the email is already taken (409).
        """
        return await self._save(user)

    async def delete(self, user_id: str) -> None:
        """Delete a user, if present."""
        await self._delete_many({"_id": user_id})
