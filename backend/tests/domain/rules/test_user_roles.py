import pytest
from night_crawler.domain.rules.user_roles import select_highest_role


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["viewer", "user", "admin"], "admin"),
        (["offline_access", "viewer", "user"], "user"),
        (["viewer", "uma_authorization"], "viewer"),
    ],
)
def test_the_highest_known_role_wins(roles, expected):
    assert expected == select_highest_role(roles)


def test_no_known_role_selects_none():
    assert None is select_highest_role(["offline_access", "default-roles-x"])
