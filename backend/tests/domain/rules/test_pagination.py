from night_crawler.domain.rules.pagination import (
    MAX_FILTERED_RESULTS,
    MAX_PAGE_SIZE,
    resolve_page,
)


def test_filtered_listings_get_one_capped_page():
    assert (MAX_FILTERED_RESULTS, 0) == resolve_page(True, 10, 40)


def test_unfiltered_listings_cap_the_page_size():
    assert (MAX_PAGE_SIZE, 0) == resolve_page(False, 500, 0)


def test_unfiltered_listings_stop_at_the_total_cap():
    assert (0, 300) == resolve_page(False, 50, 900)
