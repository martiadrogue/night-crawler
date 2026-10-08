"""Picking a run's Sample CSV out of its full dataset CSV."""

import csv
import io


def sample_csv(csv_content: str, size: int) -> str:
    """Return the CSV's header and at most `size` evenly spaced rows.

    Rows are taken at a fixed step through the whole CSV (row
    `⌊i × rows ÷ size⌋` for each `i`), not from the top, so a
    paginated listing's last pages and a fan-out's last values are
    sampled too. They keep their order, and the same CSV always gives
    the same sample. A CSV of `size` rows or fewer comes back as is.

    Args:
        csv_content: The full CSV, header first.
        size: The most rows to keep.
    """
    header, *rows = list(csv.reader(io.StringIO(csv_content))) or [[]]
    if len(rows) <= size:
        return csv_content
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows[index * len(rows) // size] for index in range(size))
    return buffer.getvalue()
