import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.dataset import DatasetCreate, DatasetUpdate
from night_crawler.services import dataset_service

HOTELS = DatasetCreate(
    name="hotels",
    fields=[
        {"name": "item_id", "is_required": True, "is_unique": True},
        {"name": "name", "is_required": True},
        {"name": "stars", "type": "integer", "pattern": "^[1-5]$"},
        {"name": "rooms"},
    ],
)


@pytest.mark.anyio
async def test_the_built_in_datasets_are_created_once(write_repositories):
    await dataset_service.seed_built_in_datasets(write_repositories)
    await dataset_service.seed_built_in_datasets(write_repositories)

    datasets = await dataset_service.get_datasets(write_repositories)

    assert ["menus", "reviews", "venues"] == [dataset.name for dataset in datasets]
    assert all("item_id_from" not in dataset.model_dump() for dataset in datasets)


@pytest.mark.anyio
async def test_create_and_update_a_dataset(write_repositories):
    created = await dataset_service.create_dataset(write_repositories, HOTELS)

    updated = await dataset_service.update_dataset(
        write_repositories, created.id, DatasetUpdate(name="lodging")
    )

    assert "lodging" == updated.name
    assert ["item_id", "name", "stars", "rooms"] == [
        field.name for field in updated.fields
    ]
    assert ("integer", "^[1-5]$") == (updated.fields[2].type, updated.fields[2].pattern)


@pytest.mark.anyio
async def test_a_dataset_needs_a_required_item_id(write_repositories):
    with pytest.raises(ValidationException) as exc_info:
        await dataset_service.create_dataset(
            write_repositories,
            DatasetCreate(name="bad", fields=[{"name": "name", "is_required": True}]),
        )

    assert 400 == exc_info.value.status_code
    assert "item_id" in exc_info.value.message


@pytest.mark.anyio
async def test_dataset_names_are_unique(write_repositories):
    await dataset_service.create_dataset(write_repositories, HOTELS)

    with pytest.raises(ValidationException) as exc_info:
        await dataset_service.create_dataset(write_repositories, HOTELS)

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_a_dataset_in_use_cannot_be_deleted(
    write_repositories, create_crawler, dataset_ids
):
    await create_crawler()

    with pytest.raises(ValidationException) as exc_info:
        await dataset_service.delete_dataset(write_repositories, dataset_ids["venues"])

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_an_update_may_not_break_a_crawlers_fields(
    write_repositories, create_crawler, dataset_ids
):
    await create_crawler()  # its fields use `rating`

    with pytest.raises(ValidationException) as exc_info:
        await dataset_service.update_dataset(
            write_repositories,
            dataset_ids["venues"],
            DatasetUpdate(
                fields=[
                    {"name": "item_id", "is_required": True, "is_unique": True},
                    {"name": "name", "is_required": True},
                ],
            ),
        )

    assert 409 == exc_info.value.status_code
    assert "rating" in exc_info.value.message


@pytest.mark.anyio
async def test_an_unused_dataset_is_deleted(write_repositories):
    created = await dataset_service.create_dataset(write_repositories, HOTELS)

    await dataset_service.delete_dataset(write_repositories, created.id)

    with pytest.raises(ValidationException) as exc_info:
        await dataset_service.get_dataset(write_repositories, created.id)

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_an_update_may_not_newly_require_a_field_a_crawler_skips(
    write_repositories, create_crawler, dataset_ids
):
    await create_crawler()  # its fields leave `address` out
    venues = await dataset_service.get_dataset(
        write_repositories, dataset_ids["venues"]
    )
    fields = [
        (
            field.model_copy(update={"is_required": True})
            if "address" == field.name
            else field
        )
        for field in venues.fields
    ]

    with pytest.raises(ValidationException) as exc_info:
        await dataset_service.update_dataset(
            write_repositories, venues.id, DatasetUpdate(fields=fields)
        )

    assert 409 == exc_info.value.status_code
    assert "Required field 'address' is missing." in exc_info.value.message
