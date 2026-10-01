from datetime import datetime

import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageSelector, MessageTemplate
from night_crawler.domain.rules.template_ordering import order_message_templates

NOW = datetime(2026, 1, 1)


def _template(template_id: str, url: str) -> MessageTemplate:
    return MessageTemplate(
        id=template_id,
        crawler_version_id="version-1",
        action="GET",
        url=url,
        body=None,
        headers={},
        created_at=NOW,
        updated_at=NOW,
    )


def _selector(template_id: str, title: str) -> MessageSelector:
    return MessageSelector(
        id=f"{template_id}-{title}",
        message_template_id=template_id,
        parent_selector_id=None,
        path="//a",
        type="value",
        target="__text",
        created_at=NOW,
        updated_at=NOW,
        title=title,
    )


def test_a_template_runs_after_the_one_whose_selector_it_uses():
    detail = _template("detail", "https://example.com/{{place_id}}")
    search = _template("search", "https://example.com/search")
    other = _template("other", "https://example.com/other")

    ordered = order_message_templates(
        [detail, search, other],
        {"search": [_selector("search", "place_id")], "detail": [], "other": []},
    )

    assert ["other", "search", "detail"] == [template.id for template in ordered]


def test_a_chain_of_dependencies_runs_in_order():
    first = _template("first", "https://example.com")
    second = _template("second", "https://example.com/{{a}}")
    third = _template("third", "https://example.com/{{b}}")

    ordered = order_message_templates(
        [third, second, first],
        {
            "first": [_selector("first", "a")],
            "second": [_selector("second", "b")],
            "third": [],
        },
    )

    assert ["first", "second", "third"] == [template.id for template in ordered]


def test_a_template_using_its_own_title_does_not_depend_on_itself():
    page = _template("page", "https://example.com/{{next}}")

    ordered = order_message_templates([page], {"page": [_selector("page", "next")]})

    assert ["page"] == [template.id for template in ordered]


def test_a_dependency_cycle_is_refused():
    a = _template("a", "https://example.com/{{from_b}}")
    b = _template("b", "https://example.com/{{from_a}}")

    with pytest.raises(ValidationException) as exc_info:
        order_message_templates(
            [a, b], {"a": [_selector("a", "from_a")], "b": [_selector("b", "from_b")]}
        )

    assert 409 == exc_info.value.status_code
