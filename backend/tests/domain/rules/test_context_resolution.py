from datetime import datetime

import pytest
from night_crawler.domain.exceptions import MissingPlaceholderException
from night_crawler.domain.model.entities import MessageTemplate
from night_crawler.domain.rules.context_resolution import resolve_template_runs

NOW = datetime(2026, 1, 1)


def _template(**overrides) -> MessageTemplate:
    defaults = {
        "id": "template-1",
        "crawler_version_id": "version-1",
        "action": "POST",
        "url": "https://api.example.com/search",
        "body": '{"q": "{{category}} in {{parish}}"}',
        "headers": {"X-Api-Key": "{{api_key}}"},
        "created_at": NOW,
        "updated_at": NOW,
    }
    return MessageTemplate(**{**defaults, **overrides})


def test_fans_out_over_every_combination_of_lists():
    runs = resolve_template_runs(
        _template(),
        {"parish[]": ["Canillo", "Encamp"], "category[]": ["bars"], "api_key": "k"},
    )

    assert [
        '{"q": "bars in Canillo"}',
        '{"q": "bars in Encamp"}',
    ] == [run.body for run in runs]
    assert {"X-Api-Key": "k"} == runs[0].headers
    assert {"category": "bars", "parish": "Encamp"} == runs[1].fanned_out_values


def test_a_template_without_placeholders_runs_once():
    runs = resolve_template_runs(_template(body=None, headers={}), {})

    assert 1 == len(runs)
    assert "https://api.example.com/search" == runs[0].url


def test_an_empty_list_means_no_runs():
    runs = resolve_template_runs(
        _template(), {"parish[]": [], "category[]": ["bars"], "api_key": "k"}
    )

    assert [] == runs


def test_a_missing_placeholder_is_refused():
    with pytest.raises(MissingPlaceholderException) as exc_info:
        resolve_template_runs(_template(), {"parish[]": ["Canillo"]})

    assert "api_key" == exc_info.value.placeholder
