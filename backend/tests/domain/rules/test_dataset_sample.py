import csv
import io
import math

from night_crawler.domain.rules.dataset_rows import build_csv
from night_crawler.domain.rules.dataset_sample import sample_csv


def _csv(count):
    return build_csv(
        ["item_id", "name"],
        [{"item_id": f"p{index}", "name": f"Place {index}"} for index in range(count)],
    )


def _rows(csv_content):
    return list(csv.reader(io.StringIO(csv_content)))


def _positions(csv_content):
    _, *rows = _rows(csv_content)
    return [int(item_id[1:]) for item_id, _ in rows]


def test_a_csv_within_the_size_comes_back_whole():
    content = _csv(3)

    assert content == sample_csv(content, 3)


def test_a_larger_csv_keeps_the_header_and_size_rows():
    header, *rows = _rows(sample_csv(_csv(50), 10))

    assert ["item_id", "name"] == header
    assert 10 == len(rows)


def test_the_rows_are_evenly_spaced_from_the_first_one():
    assert [0, 2, 4, 6, 8] == _positions(sample_csv(_csv(10), 5))
    assert [0, 1, 3, 4, 6, 7] == _positions(sample_csv(_csv(9), 6))


def test_the_sample_reaches_the_last_slice_of_the_csv():
    positions = _positions(sample_csv(_csv(1273), 800))

    assert 800 == len(set(positions))
    assert positions == sorted(positions)
    assert positions[-1] >= 1273 - math.ceil(1273 / 800)


def test_the_same_csv_always_gives_the_same_sample():
    content = _csv(1000)

    assert sample_csv(content, 100) == sample_csv(content, 100)


def test_a_quoted_cell_with_a_line_break_stays_one_row():
    content = build_csv(
        ["item_id", "name"],
        [{"item_id": f"p{index}", "name": "Line\nbreak"} for index in range(5)],
    )

    _, *rows = _rows(sample_csv(content, 2))

    assert 2 == len(rows)
    assert ["Line\nbreak", "Line\nbreak"] == [name for _, name in rows]


def test_a_csv_without_rows_comes_back_unchanged():
    assert "item_id,name\r\n" == sample_csv("item_id,name\r\n", 800)
    assert "" == sample_csv("", 800)
