from datetime import datetime

import pytest
from night_crawler.core.di import REPOSITORY_FACTORIES
from night_crawler.domain.exceptions import ConfigurationException, ValidationException
from night_crawler.domain.model.entities import User
from night_crawler.infrastructure.db.write_repositories import MongoWriteRepositories
from pymongo import AsyncMongoClient

NOW = datetime(2026, 1, 1)


def _user(**overrides) -> User:
    defaults = {
        "id": "user-1",
        "email": "ada@example.com",
        "hashed_password": "hashed",
        "created_at": NOW,
    }
    return User(**{**defaults, **overrides})


@pytest.mark.anyio
async def test_commit_persists_across_units_of_work(mongo_database):
    client, database_name = mongo_database
    async with MongoWriteRepositories(
        client, database_name, REPOSITORY_FACTORIES
    ) as repositories:
        await repositories.users.save(_user())
        await repositories.commit()

    async with MongoWriteRepositories(
        client, database_name, REPOSITORY_FACTORIES
    ) as repositories:
        assert None is not await repositories.users.get_by_id("user-1")


@pytest.mark.anyio
async def test_an_escaping_exception_rolls_back(mongo_database):
    client, database_name = mongo_database
    with pytest.raises(RuntimeError):
        async with MongoWriteRepositories(
            client, database_name, REPOSITORY_FACTORIES
        ) as repositories:
            await repositories.users.save(_user())
            raise RuntimeError("boom")

    async with MongoWriteRepositories(
        client, database_name, REPOSITORY_FACTORIES
    ) as repositories:
        assert None is await repositories.users.get_by_id("user-1")


@pytest.mark.anyio
async def test_rollback_discards_uncommitted_writes(write_repositories):
    await write_repositories.users.save(_user())

    await write_repositories.rollback()

    assert None is await write_repositories.users.get_by_id("user-1")


@pytest.mark.anyio
async def test_a_duplicate_natural_key_is_a_conflict(write_repositories):
    await write_repositories.users.save(_user())

    with pytest.raises(ValidationException) as exc_info:
        await write_repositories.users.save(_user(id="user-2"))

    assert 409 == exc_info.value.status_code


def test_every_repository_port_must_be_bound():
    # Checked in the constructor, before the client is ever used.
    client = AsyncMongoClient(connect=False)
    partial = {
        name: factory
        for name, factory in REPOSITORY_FACTORIES.items()
        if "users" != name
    }

    with pytest.raises(ConfigurationException) as exc_info:
        MongoWriteRepositories(client, "unused", partial)

    assert "users" in exc_info.value.message


@pytest.mark.anyio
async def test_write_repositories_build_the_repositories_it_is_handed(
    mongo_database,
):
    client, database_name = mongo_database
    built = []

    def _factory(name):
        def _build(database, session):
            built.append(name)
            return REPOSITORY_FACTORIES[name](database, session)

        return _build

    repositories = MongoWriteRepositories(
        client,
        database_name,
        {name: _factory(name) for name in REPOSITORY_FACTORIES},
    )

    assert [] == built
    async with repositories:
        assert sorted(REPOSITORY_FACTORIES) == sorted(built)
