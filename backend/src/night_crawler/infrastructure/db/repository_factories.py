"""What both repository sets need to build their repositories.

The factories themselves are chosen in `core/di.py`, the only place
concrete repositories are named (CONTRIBUTING R1.2.9).
"""

from collections.abc import Callable, Mapping
from typing import Any

from night_crawler.domain.exceptions import ConfigurationException
from night_crawler.domain.ports.repository_sets import AbstractRepositories
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

RepositoryFactory = Callable[[AsyncDatabase, AsyncClientSession | None], Any]
"""Builds one repository; `None` session means no transaction."""

REPOSITORY_NAMES: tuple[str, ...] = tuple(AbstractRepositories.__annotations__)
"""Every repository attribute the repository-set ports declare."""


def ensure_all_bound(repository_factories: Mapping[str, RepositoryFactory]) -> None:
    """Refuse a mapping that leaves a repository port without a factory.

    Raises:
        ConfigurationException: a repository port has no factory.
    """
    missing = sorted(set(REPOSITORY_NAMES) - set(repository_factories))
    if missing:
        raise ConfigurationException("No repository bound for: " + ", ".join(missing))
