import pytest
from night_crawler.domain.rules.selector_paths import is_xpath


@pytest.mark.parametrize(
    "path", ["//h1", "/html/body", "./a", "../p", "(//li)[1]", ".//span"]
)
def test_xpath_paths(path):
    assert is_xpath(path)


@pytest.mark.parametrize(
    "path", ["h1", "div.venue > a", "#panel", "[data-id]", ".title"]
)
def test_css_paths(path):
    assert not is_xpath(path)
