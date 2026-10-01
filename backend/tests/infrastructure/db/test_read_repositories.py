import inspect
from datetime import datetime

import pytest
from night_crawler.core.di import REPOSITORY_FACTORIES
from night_crawler.domain.exceptions import ConfigurationException
from night_crawler.domain.model.entities import User
from night_crawler.infrastructure.db.read_repositories import MongoReadRepositories
from night_crawler.infrastructure.db.repository_factories import REPOSITORY_NAMES
from pymongo import AsyncMongoClient

READ_PREFIXES = ("get_", "has_", "count_")


def _public_methods(repository) -> list[str]:
    return [
        name
        for name, _member in inspect.getmembers(
            type(repository), predicate=inspect.isfunction
        )
        if not name.startswith("_")
    ]


@pytest.mark.anyio
async def test_reads_see_committed_data(write_repositories, read_repositories):
    await write_repositories.users.save(
        User(
            id="user-1",
            email="ada@example.com",
            hashed_password="hashed",
            created_at=datetime(2026, 1, 1),
        )
    )
    await write_repositories.commit()

    user = await read_repositories.users.get_by_email("ada@example.com")

    assert "user-1" == user.id


@pytest.mark.anyio
@pytest.mark.parametrize("repository_name", REPOSITORY_NAMES)
async def test_every_write_method_is_refused(read_repositories, repository_name):
    wrapped = getattr(read_repositories, repository_name)
    write_methods = [
        name
        for name in _public_methods(REPOSITORY_FACTORIES[repository_name])
        if not name.startswith(READ_PREFIXES)
    ]

    assert write_methods
    for name in write_methods:
        with pytest.raises(ConfigurationException):
            getattr(wrapped, name)()


def test_every_repository_port_must_be_bound():
    # Checked in the constructor, before the client is ever used.
    client = AsyncMongoClient(connect=False)
    partial = {
        name: factory
        for name, factory in REPOSITORY_FACTORIES.items()
        if "crawlers" != name
    }

    with pytest.raises(ConfigurationException) as exc_info:
        MongoReadRepositories(client, "unused", partial)

    assert "crawlers" in exc_info.value.message
