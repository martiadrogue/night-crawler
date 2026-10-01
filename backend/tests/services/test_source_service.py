import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.source import SourceCreate, SourceUpdate
from night_crawler.services import source_service


@pytest.mark.anyio
async def test_create_list_and_rename_a_source(write_repositories):
    created = await source_service.create_source(
        write_repositories, SourceCreate(name="TheFork", url="https://www.thefork.com")
    )

    renamed = await source_service.update_source(
        write_repositories, created.id, SourceUpdate(name="The Fork")
    )
    listed = await source_service.get_sources(write_repositories)

    assert "The Fork" == renamed.name
    assert "https://www.thefork.com" == renamed.url
    assert [created.id] == [item.id for item in listed]


@pytest.mark.anyio
async def test_source_names_are_unique(write_repositories):
    await source_service.create_source(write_repositories, SourceCreate(name="TheFork"))

    with pytest.raises(ValidationException) as exc_info:
        await source_service.create_source(
            write_repositories, SourceCreate(name="TheFork")
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_a_source_in_use_cannot_be_deleted(
    write_repositories, create_crawler, source
):
    await create_crawler()

    with pytest.raises(ValidationException) as exc_info:
        await source_service.delete_source(write_repositories, source.id)

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_an_unused_source_is_deleted(write_repositories, source):
    await source_service.delete_source(write_repositories, source.id)

    with pytest.raises(ValidationException) as exc_info:
        await source_service.get_source(write_repositories, source.id)

    assert 404 == exc_info.value.status_code
