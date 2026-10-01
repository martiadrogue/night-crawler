"""The pagination policy shared by listings.

Filtered listings get one capped page and never paginate; unfiltered
listings paginate up to a hard total.
"""

MAX_FILTERED_RESULTS = 50
MAX_PAGE_SIZE = 50
MAX_TOTAL_RESULTS = 300


def resolve_page(
    has_filters: bool, requested_limit: int, requested_offset: int
) -> tuple[int, int]:
    """Return the `(limit, offset)` a listing query should use.

    Args:
        has_filters: Whether the caller applied any filter.
        requested_limit: The page size asked for.
        requested_offset: The offset asked for.

    Returns:
        `(MAX_FILTERED_RESULTS, 0)` when filtered; otherwise the limit
        capped at `MAX_PAGE_SIZE` and the offset capped so `offset +
        limit` stays within `MAX_TOTAL_RESULTS`.
    """
    if has_filters:
        return MAX_FILTERED_RESULTS, 0

    offset = min(requested_offset, MAX_TOTAL_RESULTS)
    limit = max(min(requested_limit, MAX_PAGE_SIZE, MAX_TOTAL_RESULTS - offset), 0)
    return limit, offset
