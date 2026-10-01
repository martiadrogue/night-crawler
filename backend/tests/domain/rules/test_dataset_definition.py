from datetime import datetime

from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.model.value_objects import DatasetField
from night_crawler.domain.rules.dataset_definition import validate_dataset_definition

NOW = datetime(2026, 1, 1)

ITEM_ID = DatasetField(name="item_id", is_required=True, is_unique=True)


def _dataset(**changes) -> Dataset:
    values = {
        "id": "d1",
        "name": "menus",
        "fields": [
            ITEM_ID,
            DatasetField(name="venue_item_id", is_required=True),
            DatasetField(name="item_name", pattern=r"\S"),
            DatasetField(name="item_price", type="float"),
            DatasetField(name="tags"),
        ],
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Dataset(**{**values, **changes})


def test_accepts_a_consistent_definition():
    assert [] == validate_dataset_definition(_dataset())


def test_item_id_is_a_required_unique_field():
    errors = validate_dataset_definition(
        _dataset(
            fields=[DatasetField(name="name", is_required=True)],
        )
    )

    assert ["Field 'item_id' is missing."] == errors


def test_item_id_must_be_required_and_unique():
    errors = validate_dataset_definition(
        _dataset(fields=[DatasetField(name="item_id")])
    )

    assert [
        "Field 'item_id' must be required.",
        "Field 'item_id' must be unique.",
    ] == errors


def test_rejects_unknown_or_duplicate_fields():
    errors = validate_dataset_definition(
        _dataset(
            fields=[ITEM_ID, DatasetField(name="venue_item_id"), ITEM_ID],
        )
    )

    assert [
        "Field 'item_id' is listed more than once.",
    ] == errors


def test_rejects_a_blank_name_an_unknown_type_and_a_bad_pattern():
    errors = validate_dataset_definition(
        _dataset(
            fields=[
                ITEM_ID,
                DatasetField(name=" "),
                DatasetField(name="opened", type="date"),
                DatasetField(name="price", pattern="("),
            ],
        )
    )

    assert [
        "A field name can't be blank.",
        "Field 'opened' has unknown type 'date'.",
        "Field 'price' has an invalid pattern.",
    ] == errors
