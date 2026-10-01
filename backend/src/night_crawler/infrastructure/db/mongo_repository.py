"""Shared MongoDB plumbing for the per-entity repositories.

Entities map onto documents field by field, with the surrogate `id`
stored as `_id` (CONTRIBUTING R1.4.5). With write repositories every
call runs in their session and joins its transaction; with read
repositories the session is `None` and each call runs on its own.
"""

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar, Generic, TypeVar

from night_crawler.domain.exceptions import (
    ExternalServiceException,
    ValidationException,
)
from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

DOCUMENT_VALIDATION_FAILURE = 121
"""MongoDB's error code for a write its `$jsonSchema` rejects."""

EntityT = TypeVar("EntityT")
Query = dict[str, Any]
Sort = list[tuple[str, int]]


@contextmanager
def translate_errors(conflict_message: str) -> Iterator[None]:
    """Turn driver errors into `AppException`s (CONTRIBUTING R1.6.4).

    Raises:
        ValidationException: a unique index was broken (409), or the
            collection validator rejected the document (400).
        ExternalServiceException: any other database failure (503).
    """
    try:
        yield
    except DuplicateKeyError as error:
        raise ValidationException(conflict_message, 409) from error
    except WriteError as error:
        if DOCUMENT_VALIDATION_FAILURE != error.code:
            raise ExternalServiceException("Database write failed.", 503) from error
        raise ValidationException("Document failed validation.", 400) from error
    except PyMongoError as error:
        raise ExternalServiceException("Database unavailable.", 503) from error


class MongoRepository(Generic[EntityT]):
    """Base for one entity's collection; subclasses add queries."""

    entity_type: ClassVar[type]
    collection_name: ClassVar[str]
    conflict_message: ClassVar[str] = "Conflicts with an existing record."

    def __init__(
        self, database: AsyncDatabase, session: AsyncClientSession | None
    ) -> None:
        """Bind the repository to a transaction's session, or none."""
        self._collection = database[self.collection_name]
        self._session = session

    def _to_domain(self, document: dict[str, Any]) -> EntityT:
        """Map a document onto the entity, ignoring unknown keys."""
        names = {field.name for field in dataclasses.fields(self.entity_type)}
        values = {key: value for key, value in document.items() if key in names}
        return self.entity_type(**values, id=document["_id"])

    async def _find_one(self, query: Query) -> EntityT | None:
        """Return the first entity matching `query`, if any."""
        with translate_errors(self.conflict_message):
            db_document = await self._collection.find_one(query, session=self._session)
        return None if None is db_document else self._to_domain(db_document)

    async def _find_many(
        self,
        query: Query,
        sort: Sort | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[EntityT]:
        """Return entities matching `query`, oldest first by default."""
        order = [*(sort or [("created_at", ASCENDING)]), ("_id", ASCENDING)]
        cursor = self._collection.find(query, session=self._session).sort(order)
        cursor = cursor.skip(offset).limit(limit or 0)
        with translate_errors(self.conflict_message):
            db_documents = await cursor.to_list()
        return [self._to_domain(db_document) for db_document in db_documents]

    async def _count(self, query: Query) -> int:
        """Return how many documents match `query`."""
        with translate_errors(self.conflict_message):
            return await self._collection.count_documents(query, session=self._session)

    async def _save(self, entity: EntityT) -> EntityT:
        """Insert or replace the entity's document; return a copy."""
        db_document = dataclasses.asdict(entity)
        db_document["_id"] = db_document.pop("id")
        with translate_errors(self.conflict_message):
            await self._collection.replace_one(
                {"_id": db_document["_id"]},
                db_document,
                upsert=True,
                session=self._session,
            )
        return self._to_domain(db_document)

    async def _delete_many(self, query: Query) -> None:
        """Delete every document matching `query`."""
        with translate_errors(self.conflict_message):
            await self._collection.delete_many(query, session=self._session)

    async def _clear_reference(self, field_name: str, target_id: str) -> None:
        """Set `field_name` to `None` where it points at `target_id`."""
        with translate_errors(self.conflict_message):
            await self._collection.update_many(
                {field_name: target_id},
                {"$set": {field_name: None}},
                session=self._session,
            )


NEWEST_FIRST: Sort = [("created_at", DESCENDING)]
