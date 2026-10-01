"""MongoDB write repositories: one transaction across every repository.

The Unit of Work pattern: a use case that writes runs, reads included,
in one transaction that commits or rolls back as a whole.

Multi-document transactions need a replica set; the Compose `db`
service runs a single-node one (`rs0`).
"""

from collections.abc import Mapping
from types import TracebackType
from typing import Self

from night_crawler.domain.ports.repository_sets import AbstractWriteRepositories
from night_crawler.infrastructure.db.mongo_repository import translate_errors
from night_crawler.infrastructure.db.repository_factories import (
    RepositoryFactory,
    ensure_all_bound,
)
from pymongo import AsyncMongoClient


class MongoWriteRepositories(AbstractWriteRepositories):
    """Write repositories sharing one session and transaction.

    A transaction is always open while inside `async with`: committing
    or rolling back immediately starts the next one, mirroring an ORM
    session, so a service may commit more than once.
    """

    def __init__(
        self,
        client: AsyncMongoClient,
        database_name: str,
        repository_factories: Mapping[str, RepositoryFactory],
    ) -> None:
        """Keep the client and factories; a session opens on enter.

        The factories come from `core/di.py`, the only place concrete
        repositories are named (CONTRIBUTING R1.2.9).

        Args:
            client: The shared MongoDB client.
            database_name: The database every repository works on.
            repository_factories: One factory per repository attribute
                of `AbstractRepositories`, e.g. `{"users": ...}`.

        Raises:
            ConfigurationException: a repository port has no factory.
        """
        ensure_all_bound(repository_factories)
        self._client = client
        self._database_name = database_name
        self._repository_factories = repository_factories

    async def __aenter__(self) -> Self:
        """Open a session and transaction and bind every repository."""
        self._session = self._client.start_session()
        with translate_errors("Transaction conflict."):
            await self._session.start_transaction()

        database = self._client[self._database_name]
        for name, factory in self._repository_factories.items():
            setattr(self, name, factory(database, self._session))
        return await super().__aenter__()

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        exception_traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back, then always end the session.

        Ending the session aborts the empty transaction left open by
        the last commit or rollback.
        """
        try:
            await super().__aexit__(
                exception_type, exception_value, exception_traceback
            )
        finally:
            await self._session.end_session()

    async def commit(self) -> None:
        """Commit the transaction and open the next one.

        Raises:
            ExternalServiceException: the database refused the commit,
                e.g. on a write conflict with another request (503).
        """
        with translate_errors("Transaction conflict."):
            await self._session.commit_transaction()
            await self._session.start_transaction()

    async def rollback(self) -> None:
        """Abort the transaction and open the next one."""
        with translate_errors("Transaction conflict."):
            await self._session.abort_transaction()
            await self._session.start_transaction()
