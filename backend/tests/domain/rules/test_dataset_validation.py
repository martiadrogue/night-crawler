from datetime import datetime

from night_crawler.domain.model.entities import Dataset
from night_crawler.domain.model.value_objects import DatasetField
from night_crawler.domain.rules.dataset_validation import validate_dataset_rows

NOW = datetime(2026, 1, 1)
FIELDS = ["item_id", "name", "rating", "review_count", "is_open", "source_url"]


def _dataset() -> Dataset:
    return Dataset(
        id="d1",
        name="venues",
        fields=[
            DatasetField(name="item_id", is_required=True, is_unique=True),
            DatasetField(name="name", is_required=True),
            DatasetField(name="rating", type="float"),
            DatasetField(name="review_count", type="integer"),
            DatasetField(name="is_open", type="boolean"),
            DatasetField(name="source_url", pattern=r"^https?://"),
            DatasetField(name="location"),
        ],
        created_at=NOW,
        updated_at=NOW,
    )


def _row(**values):
    return {
        "item_id": "p1",
        "name": "Casa",
        "rating": 4.5,
        "review_count": 12,
        "is_open": True,
        "source_url": "https://example.com/p1",
        **values,
    }


def test_valid_rows_pass_untouched():
    rows = [_row(), _row(item_id="p2", rating="4.0", review_count="7", is_open="false")]

    kept, report = validate_dataset_rows(rows, FIELDS, _dataset())

    assert rows == kept
    assert report.is_valid
    assert (2, 0, 0) == (
        report.rows_checked,
        report.rows_dropped_missing_required,
        report.rows_dropped_duplicate,
    )


def test_a_row_missing_a_required_value_is_dropped_and_fails():
    rows = [_row(), _row(item_id="p2", name=""), _row(item_id="p3", name=None)]

    kept, report = validate_dataset_rows(rows, FIELDS, _dataset())

    assert ["p1"] == [row["item_id"] for row in kept]
    assert 2 == report.rows_dropped_missing_required
    assert not report.is_valid


def test_type_and_pattern_mismatches_are_kept_counted_and_fail():
    rows = [
        _row(rating="n/a", review_count=1.5, is_open="maybe", source_url="ftp://x"),
        _row(item_id="p2", review_count=True),
    ]

    kept, report = validate_dataset_rows(rows, FIELDS, _dataset())

    assert rows == kept
    assert {"rating": 1, "review_count": 2, "is_open": 1} == report.type_mismatches
    assert {"source_url": 1} == report.pattern_mismatches
    assert not report.is_valid


def test_empty_optional_values_are_not_mismatches():
    rows = [_row(), _row(item_id="p2", rating=None, review_count="", source_url=None)]

    _kept, report = validate_dataset_rows(rows, FIELDS, _dataset())

    assert {} == report.type_mismatches
    assert {} == report.pattern_mismatches
    assert report.is_valid


def test_duplicates_of_a_unique_value_keep_the_first_and_still_pass():
    rows = [_row(name="First"), _row(name="Second"), _row(item_id="p2")]

    kept, report = validate_dataset_rows(rows, FIELDS, _dataset())

    assert [("p1", "First"), ("p2", "Casa")] == [
        (row["item_id"], row["name"]) for row in kept
    ]
    assert 1 == report.rows_dropped_duplicate
    assert report.is_valid


def test_a_crawler_field_empty_in_every_row_fails():
    rows = [_row(rating=None), _row(item_id="p2", rating="")]

    _kept, report = validate_dataset_rows(rows, FIELDS, _dataset())

    assert ("rating",) == report.empty_columns
    assert not report.is_valid


def test_no_rows_leaves_every_column_empty():
    kept, report = validate_dataset_rows([], ["item_id", "name"], _dataset())

    assert [] == kept
    assert ("item_id", "name") == report.empty_columns
    assert not report.is_valid


def test_string_fields_accept_objects_and_lists():
    fields = ["item_id", "name", "location"]
    rows = [{"item_id": "p1", "name": "Casa", "location": {"latitude": 1.0}}]

    _kept, report = validate_dataset_rows(rows, fields, _dataset())

    assert report.is_valid
