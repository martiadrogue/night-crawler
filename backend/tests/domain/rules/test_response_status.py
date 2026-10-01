from night_crawler.domain.rules.response_status import is_success_status


def test_without_success_codes_any_status_below_400_succeeds():
    assert is_success_status(200, None)
    assert is_success_status(302, None)
    assert not is_success_status(404, None)


def test_success_codes_name_exactly_the_statuses_that_succeed():
    assert is_success_status(404, ("404",))
    assert not is_success_status(200, ("404",))
    assert is_success_status(200, ("200", "404"))
