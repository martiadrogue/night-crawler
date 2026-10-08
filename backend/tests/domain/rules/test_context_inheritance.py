from datetime import datetime

from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.rules.context_inheritance import (
    drop_harvested,
    harvested_keys,
)

NOW = datetime(2026, 1, 1)


def _selector(title, selector_type="value"):
    return MessageSelector(
        id=f"s-{title}",
        message_template_id="t1",
        parent_selector_id=None,
        path="//x",
        type=selector_type,
        target="__text",
        created_at=NOW,
        updated_at=NOW,
        title=title,
    )


def test_each_selector_title_is_harvested_as_value_and_list():
    keys = harvested_keys(
        [_selector("listing_page"), _selector("next_token")], ["item_id", "name"]
    )

    assert {"listing_page", "listing_page[]", "next_token", "next_token[]"} == keys


def test_field_titles_and_untitled_selectors_are_not_harvested():
    keys = harvested_keys(
        [_selector("name"), _selector(None, "iterator"), _selector("")], ["name"]
    )

    assert frozenset() == keys


def test_dropping_harvested_keys_keeps_every_other_key():
    context = {"show_path[]": ["/s1"], "token": "t", "api_key": "secret"}

    assert {"api_key": "secret"} == drop_harvested(
        context, frozenset({"show_path", "show_path[]", "token", "token[]"})
    )
    assert context == drop_harvested(context, frozenset())
