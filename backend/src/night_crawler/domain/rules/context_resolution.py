"""Placeholder resolution and fan-out for one template's runs."""

import itertools
from typing import Any

from night_crawler.domain.exceptions import MissingPlaceholderException
from night_crawler.domain.model.entities import MessageTemplate
from night_crawler.domain.model.value_objects import RenderedRequest
from night_crawler.domain.rules.placeholders import (
    extract_placeholders,
    render_placeholders,
    stringify,
)
from night_crawler.domain.rules.selector_tree import ITERATOR_KEY_SUFFIX
from night_crawler.domain.rules.template_ordering import template_texts


def resolve_template_runs(
    template: MessageTemplate, context: dict[str, Any]
) -> list[RenderedRequest]:
    """Render a template once per combination of its list placeholders.

    A placeholder found as `name` is one value; found as `name[]` it
    multiplies the runs. An empty list means no runs.

    Raises:
        MissingPlaceholderException: a placeholder exists under neither
            `name` nor `name[]`.
    """
    single_values, list_values = _classify(
        extract_placeholders(template_texts(template)), context
    )
    combinations = [
        dict(zip(list_values, combination, strict=True))
        for combination in itertools.product(*list_values.values())
    ]
    return [
        _render(template, {**single_values, **combination}, combination)
        for combination in combinations
    ]


def resolve_repeat_run(
    template: MessageTemplate, rendered: RenderedRequest, updates: dict[str, Any]
) -> RenderedRequest:
    """Render the same fan-out combination again with new values.

    Every placeholder keeps the value `rendered` used, except those in
    `updates` (e.g. the next page token).
    """
    return _render(
        template,
        {**rendered.placeholder_values, **updates},
        rendered.fanned_out_values,
    )


def _classify(
    names: set[str], context: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Split placeholders into single values and lists to fan out over.

    Raises:
        MissingPlaceholderException: a name is in neither form.
    """
    single_values: dict[str, Any] = {}
    list_values: dict[str, list[Any]] = {}
    for name in sorted(names):
        if name in context:
            single_values[name] = context[name]
        elif f"{name}{ITERATOR_KEY_SUFFIX}" in context:
            list_values[name] = context[f"{name}{ITERATOR_KEY_SUFFIX}"]
        else:
            raise MissingPlaceholderException(name)
    return single_values, list_values


def _render(
    template: MessageTemplate, values: dict[str, Any], combination: dict[str, Any]
) -> RenderedRequest:
    """Substitute `values` into every text field of `template`."""
    text_values = {name: stringify(value) for name, value in values.items()}
    return RenderedRequest(
        action=render_placeholders(template.action, text_values),
        url=render_placeholders(template.url, text_values),
        body=(
            None
            if None is template.body
            else render_placeholders(template.body, text_values)
        ),
        headers={
            key: (
                render_placeholders(value, text_values)
                if isinstance(value, str)
                else value
            )
            for key, value in template.headers.items()
        },
        fanned_out_values=combination,
        placeholder_values=values,
    )
