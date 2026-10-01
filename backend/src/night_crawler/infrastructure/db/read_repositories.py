"""MongoDB read repositories: every repository, no transaction."""

from collections.abc import Mapping

from night_crawler.domain.ports.repository_sets import AbstractReadRepositories
from night_crawler.infrastructure.db.read_only_repository import ReadOnlyRepository
from night_crawler.infrastructure.db.repository_factories import (
    RepositoryFactory,
    ensure_all_bound,
)
from pymongo import AsyncMongoClient


class MongoReadRepositories(AbstractReadRepositories):
    """Repositories built without a session; writes are refused.

    Each query runs on its own, so there is no snapshot across queries
    and no commit round trip at the end of a request.
    """

    def __init__(
        self,
        client: AsyncMongoClient,
        database_name: str,
        repository_factories: Mapping[str, RepositoryFactory],
    ) -> None:
        """Build every repository, each behind a read-only guard.

        Args:
            client: The shared MongoDB client.
            database_name: The database every repository works on.
            repository_factories: One factory per repository attribute
                of `AbstractRepositories`, e.g. `{"users": ...}`.

        Raises:
            ConfigurationException: a repository port has no factory.
        """
        ensure_all_bound(repository_factories)
        database = client[database_name]
        for name, factory in repository_factories.items():
            setattr(self, name, ReadOnlyRepository(factory(database, None)))
