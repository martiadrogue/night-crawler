import pytest
from night_crawler.core.config import Settings
from pydantic import ValidationError


def test_the_agent_samples_five_pages_by_default():
    assert 5 == Settings(_env_file=None).agent_max_pages


@pytest.mark.parametrize("max_pages", [0, -1])
def test_the_agent_must_sample_at_least_one_page(max_pages):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, agent_max_pages=max_pages)
