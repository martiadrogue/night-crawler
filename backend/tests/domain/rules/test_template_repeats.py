from datetime import datetime

from night_crawler.domain.model.entities import MessageSelector, MessageTemplate
from night_crawler.domain.rules.template_repeats import (
    SelfFedPlaceholders,
    find_self_fed_placeholders,
    next_scalar_values,
    unrun_list_elements,
)

NOW = datetime(2026, 1, 1)


def _template(url, body=None):
    return MessageTemplate(
        id="t1",
        crawler_version_id="v1",
        action="POST",
        url=url,
        body=body,
        headers={},
        created_at=NOW,
        updated_at=NOW,
    )


def _selector(selector_id, title=None, parent=None, selector_type="value"):
    return MessageSelector(
        id=selector_id,
        message_template_id="t1",
        parent_selector_id=parent,
        path="x",
        type=selector_type,
        target="__text",
        created_at=NOW,
        updated_at=NOW,
        title=title,
    )


def test_a_template_feeding_its_own_placeholders_repeats():
    template = _template(
        "https://api.example.com/{{path}}?q={{q}}",
        body='{"pageToken": "{{next_page_token}}"}',
    )
    selectors = [
        _selector("token", "next_page_token"),
        _selector("links", selector_type="iterator"),
        _selector("path", "path", parent="links"),
        _selector("name", "name", parent="links"),
    ]

    assert SelfFedPlaceholders(
        scalars=frozenset({"next_page_token"}), lists=frozenset({"path"})
    ) == find_self_fed_placeholders(template, selectors)


def test_a_click_makes_its_children_lists_too():
    template = _template("https://example.com/{{tab}}")
    selectors = [
        _selector("click", selector_type="click"),
        _selector("tab", "tab", parent="click"),
    ]

    assert frozenset({"tab"}) == find_self_fed_placeholders(template, selectors).lists


def test_placeholders_other_templates_fill_do_not_repeat():
    template = _template("https://example.com/{{place_id}}")

    found = find_self_fed_placeholders(template, [_selector("name", "name")])

    assert not found.scalars and not found.lists


def test_a_new_value_repeats_and_a_used_missing_or_empty_one_stops():
    used = {"next_page_token": {"", "t1"}}

    assert {"next_page_token": "t2"} == next_scalar_values(
        {"next_page_token": "t2"}, used
    )
    for harvested in ("t1", "", None):
        assert {} == next_scalar_values({"next_page_token": harvested}, used)


def test_list_elements_already_run_are_skipped():
    context = {"path[]": ["/", "/a", "/b", "/a"], "other[]": ["x"]}

    assert {"path": ["/b"]} == unrun_list_elements(
        context, frozenset({"path"}), {"path": ["/", "/a"]}
    )
    assert {} == unrun_list_elements(
        context, frozenset({"path"}), {"path": ["/", "/a", "/b"]}
    )
