from datetime import datetime

from night_crawler.domain.model.constants import BUILT_IN_DATASETS
from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.model.value_objects import DatasetField
from night_crawler.domain.rules.crawler_fields import validate_crawler_fields

NOW = datetime(2026, 1, 1)


def _built_in(name: str) -> Dataset:
    """Return the built-in dataset `name` as an entity."""
    definition = next(item for item in BUILT_IN_DATASETS if name == item["name"])
    return Dataset(
        id=name,
        created_at=NOW,
        updated_at=NOW,
        **{
            **definition,
            "fields": [DatasetField(**field) for field in definition["fields"]],
        },
    )


def test_accepts_fields_with_the_required_ones():
    assert [] == validate_crawler_fields(
        _built_in("venues"), ["item_id", "name", "rating"]
    )


def test_rejects_fields_outside_the_dataset():
    errors = validate_crawler_fields(
        _built_in("reviews"), ["item_id", "venue_item_id", "name"]
    )

    assert ["Field 'name' is not a 'reviews' field."] == errors


def test_rejects_missing_required_fields():
    errors = validate_crawler_fields(_built_in("menus"), ["item_id", "venue_item_id"])

    assert ["Required field 'item_name' is missing."] == errors


def test_rejects_duplicate_fields():
    errors = validate_crawler_fields(_built_in("venues"), ["item_id", "name", "name"])

    assert ["Field 'name' is listed more than once."] == errors


def test_every_dataset_requires_the_item_id():
    for dataset, fields in (
        ("venues", ["name"]),
        ("reviews", ["venue_item_id"]),
        ("menus", ["venue_item_id", "item_name"]),
    ):
        errors = validate_crawler_fields(_built_in(dataset), fields)

        assert ["Required field 'item_id' is missing."] == errors


def test_the_built_in_item_ids_are_required_and_unique():
    for definition in BUILT_IN_DATASETS:
        dataset = _built_in(definition["name"])
        [item_id] = [field for field in dataset.fields if "item_id" == field.name]

        assert (True, True) == (item_id.is_required, item_id.is_unique)
