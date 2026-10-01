import pytest
from night_crawler import forms


def test_parse_json_object_accepts_objects_and_blank():
    assert ({"a": 1}, "") == forms.parse_json_object('{"a": 1}')
    assert ({}, "") == forms.parse_json_object("  ")


@pytest.mark.parametrize("text", ["[1, 2]", "{broken"])
def test_parse_json_object_rejects_other_input(text):
    value, error = forms.parse_json_object(text)

    assert None is value
    assert error


def test_parse_codes_splits_on_commas_and_spaces():
    assert ["403", "429", "timeout"] == forms.parse_codes(" 403, 429 timeout ")
    assert None is forms.parse_codes("")


def test_parse_optional_int():
    assert 30 == forms.parse_optional_int(" 30 ")
    assert None is forms.parse_optional_int("")
    with pytest.raises(ValueError):
        forms.parse_optional_int("soon")


def test_selectors_are_ordered_as_a_tree_with_depths():
    selectors = [
        {"id": "child", "parent_selector_id": "root", "path": "h2"},
        {"id": "root", "parent_selector_id": None, "path": "div"},
        {"id": "other", "parent_selector_id": None, "path": "title"},
        {"id": "grandchild", "parent_selector_id": "child", "path": "a"},
    ]

    rows = forms.selector_tree_rows(selectors)

    assert [("root", 0), ("child", 1), ("grandchild", 2), ("other", 0)] == [
        (row["id"], row["depth"]) for row in rows
    ]
    assert "↳ ↳ a" == rows[2]["tree_label"]


def test_selector_tree_marks_titles_that_match_crawler_fields():
    rows = forms.selector_tree_rows(
        [
            {"id": "field", "path": "h1", "title": "name"},
            {"id": "context", "path": "a", "title": "next_page"},
        ],
        ["name", "item_id"],
    )

    assert [True, False] == [row["is_dataset_field"] for row in rows]


def test_blank_to_none():
    assert None is forms.blank_to_none("  ")
    assert None is forms.blank_to_none(forms.NO_SELECTION)
    assert "x" == forms.blank_to_none(" x ")


def test_build_template_payload_parses_headers_and_blank_body():
    payload, error = forms.build_template_payload(
        {"url": " https://a.test/{{q}} ", "body": " ", "headers_text": '{"A": "1"}'},
        "GET",
    )

    assert "" == error
    assert {
        "action": "GET",
        "url": "https://a.test/{{q}}",
        "body": None,
        "headers": {"A": "1"},
    } == payload


def test_build_template_payload_rejects_bad_headers():
    payload, error = forms.build_template_payload({"headers_text": "[1]"}, "GET")

    assert None is payload
    assert error.startswith("Headers:")


def test_build_selector_payload_drops_config_unless_pagination():
    choices = {"type": "value", "source": "headers", "parent_selector_id": "__none__"}

    payload, _ = forms.build_selector_payload(
        {"path": "set-cookie: (.*)", "target": "", "title": "", "config_text": "{}"},
        choices,
    )

    assert "__text" == payload["target"]
    assert None is payload["title"]
    assert None is payload["parent_selector_id"]
    assert None is payload["config"]


def test_build_aid_payload_rejects_non_numbers():
    choices = {
        "render_mode": "none",
        "selected_proxy_id": "__none__",
        "rate_limit_id": "__none__",
    }

    payload, error = forms.build_aid_payload({"ttl": "ten"}, choices)

    assert None is payload
    assert error


def test_build_aid_payload_parses_codes_and_numbers():
    choices = {
        "render_mode": "stealth",
        "selected_proxy_id": "p1",
        "rate_limit_id": "__none__",
    }

    payload, _ = forms.build_aid_payload(
        {
            "ttl": "30",
            "retry_codes": "",
            "success_codes": "200 204",
        },
        choices,
    )

    assert 30 == payload["ttl"]
    assert {"ban_codes", "max_rotating_retries"}.isdisjoint(payload)
    assert ["200", "204"] == payload["success_codes"]
    assert None is payload["retry_codes"]
    assert "p1" == payload["selected_proxy_id"]
    assert None is payload["rate_limit_id"]


def test_draft_id_finds_the_draft():
    versions = [{"id": "a", "status": "archived"}, {"id": "b", "status": "draft"}]

    assert "b" == forms.draft_id(versions)
    assert None is forms.draft_id(versions[:1])


def test_select_and_text_helpers_round_trip_blanks():
    assert forms.NO_SELECTION == forms.to_select(None)
    assert "p1" == forms.to_select("p1")
    assert "403, 429" == forms.codes_text(["403", "429"])
    assert "" == forms.codes_text(None)
    assert "" == forms.optional_text(None)
    assert "0" == forms.optional_text(0)


def test_id_options_fall_back_to_the_id_for_a_missing_label():
    items = [{"id": "r1", "name": "slow"}, {"id": "r2", "name": None}]

    assert [
        {"value": "r1", "label": "slow"},
        {"value": "r2", "label": "r2"},
    ] == forms.id_options(items, "name")


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["archived", "published", "draft"], "v3"),
        (["archived", "published"], "v2"),
        (["archived"], None),
        ([], None),
    ],
)
def test_editable_version_id_prefers_the_draft(statuses, expected):
    versions = [
        {"id": f"v{number}", "status": status}
        for number, status in enumerate(statuses, start=1)
    ]

    assert expected == forms.editable_version_id(versions)


def test_build_settings_payload_sends_only_host_sharing():
    payload = forms.build_settings_payload({"is_host_session_sharing_enabled": "on"})

    assert {"is_host_session_sharing_enabled": True} == payload


def test_build_crawler_payload_always_sends_the_source():
    form = {"title": " Maps ", "fields": "item_id, name\nrating", "schedule": " "}

    payload, error = forms.build_crawler_payload(
        form, {"source_id": "s1", "dataset_id": "d1", "queue": "priority"}
    )

    assert "" == error
    assert {
        "title": "Maps",
        "source_id": "s1",
        "dataset_id": "d1",
        "fields": ["item_id", "name", "rating"],
        "schedule": None,
        "queue": "priority",
    } == payload


def test_build_crawler_payload_needs_fields():
    payload, error = forms.build_crawler_payload(
        {"fields": " "},
        {"source_id": "s1", "dataset_id": "d1", "queue": "discovery"},
    )

    assert None is payload
    assert "field" in error.lower()


@pytest.mark.parametrize(
    ("aid", "expected"),
    [
        (None, "defaults"),
        ({"render_mode": "stealth", "ttl": 30}, "Stealth · 30 s"),
        ({"render_mode": "none", "ttl": None}, "No render"),
    ],
)
def test_aid_summary_names_the_engine_and_ttl(aid, expected):
    assert expected == forms.aid_summary(aid)


def test_render_mode_options_use_clear_labels_with_existing_api_values():
    assert [
        ("none", "No render"),
        ("playwright", "Render"),
        ("stealth", "Stealth"),
    ] == forms.RENDER_MODES


DEFAULT_AID = {
    "render_mode": "none",
    "selected_proxy_id": None,
    "rate_limit_id": None,
    "success_codes": None,
    "retry_codes": None,
    "ttl": None,
    "max_retry_attempts": None,
}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, True),
        ({"render_mode": "stealth"}, False),
        ({"ttl": 30}, False),
        ({"success_codes": ["200"]}, False),
        ({"max_retry_attempts": 0}, False),
    ],
)
def test_is_default_aid_is_true_only_with_nothing_set(changes, expected):
    assert expected == forms.is_default_aid({**DEFAULT_AID, **changes})


@pytest.mark.parametrize(
    ("current", "clicked", "expected"),
    [("", "t1", "t1"), ("t1", "t2", "t2"), ("t1", "t1", "")],
)
def test_toggle_selection_opens_another_or_closes_the_same(current, clicked, expected):
    assert expected == forms.toggle_selection(current, clicked)


def test_crawlers_cannot_pick_the_testing_queue():
    assert "testing" not in forms.CRAWLER_QUEUES
    assert "testing" in forms.EXECUTION_QUEUES


def test_names_by_id_labels_linked_records():
    sources = [{"id": "s1", "name": "TheFork"}, {"id": "s2", "name": "OpenTable"}]

    assert {"s1": "TheFork", "s2": "OpenTable"} == forms.names_by_id(sources)


def test_build_crawler_payload_needs_a_source():
    payload, error = forms.build_crawler_payload(
        {"fields": "item_id"},
        {"source_id": "", "dataset_id": "d1", "queue": "discovery"},
    )

    assert None is payload
    assert "source" in error.lower()


def test_build_crawler_payload_needs_a_dataset():
    payload, error = forms.build_crawler_payload(
        {"fields": "item_id"},
        {"source_id": "s1", "dataset_id": "", "queue": "discovery"},
    )

    assert None is payload
    assert "dataset" in error.lower()


def test_build_dataset_payload_reads_the_fields_json():
    payload, error = forms.build_dataset_payload(
        {
            "name": " hotels ",
            "fields_text": '[{"name": "item_id", "is_required": true, '
            '"is_unique": true}, {"name": "stars", "type": "integer"}]',
        }
    )

    assert "" == error
    assert {
        "name": "hotels",
        "fields": [
            {"name": "item_id", "is_required": True, "is_unique": True},
            {"name": "stars", "type": "integer"},
        ],
    } == payload


@pytest.mark.parametrize("text", ['{"name": "item_id"}', "[broken", '["item_id"]'])
def test_build_dataset_payload_needs_a_json_list_of_objects(text):
    payload, error = forms.build_dataset_payload({"name": "x", "fields_text": text})

    assert None is payload
    assert error.startswith("Fields:")


def test_fields_summary_marks_rules():
    assert "item_id*! · stars:integer · url ~^https?://" == forms.fields_summary(
        [
            {
                "name": "item_id",
                "type": "string",
                "is_required": True,
                "is_unique": True,
            },
            {"name": "stars", "type": "integer", "is_required": False},
            {"name": "url", "type": "string", "pattern": "^https?://"},
        ]
    )


def test_a_selector_can_read_the_context():
    assert "context" in forms.SELECTOR_SOURCES


def test_execution_params_drop_the_all_filter_and_page_only_unfiltered():
    every = {
        "status": forms.ALL_STATUSES,
        "parsing_status": forms.ALL_STATUSES,
        "queue": forms.ALL_STATUSES,
        "crawler_title": " ",
    }

    assert {
        "status": None,
        "parsing_status": None,
        "queue": None,
        "crawler_title": None,
        "offset": 100,
    } == forms.execution_params(every, 100)
    assert {
        "status": None,
        "parsing_status": None,
        "queue": "priority",
        "crawler_title": "maps",
        "offset": None,
    } == forms.execution_params(
        {**every, "queue": "priority", "crawler_title": " maps "}, 100
    )


def test_execution_filters_offer_every_status_and_all():
    assert forms.ALL_STATUSES == forms.EXECUTION_STATUS_FILTERS[0]
    assert [forms.ALL_STATUSES, *forms.EXECUTION_QUEUES] == forms.QUEUE_FILTERS
    assert "cancelled" in forms.EXECUTION_STATUS_FILTERS
    assert ["all", "pending", "parsing", "parsed", "failed"] == (
        forms.PARSING_STATUS_FILTERS
    )


@pytest.mark.parametrize(
    ("value", "text"),
    [("2026-10-01T12:30:05.123456", "2026-10-01 12:30:05"), (None, "—")],
)
def test_short_time_trims_iso_timestamps(value, text):
    assert text == forms.short_time(value)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(None, "—"), (0.4, "0s"), (45, "45s"), (125, "2m 05s"), (3780, "1h 03m")],
)
def test_format_duration(seconds, text):
    assert text == forms.format_duration(seconds)


def test_seconds_between_needs_both_ends():
    assert 90.5 == forms.seconds_between(
        "2026-10-01T12:00:00", "2026-10-01T12:01:30.500000"
    )
    assert None is forms.seconds_between("2026-10-01T12:00:00", None)


def test_runs_summary_covers_only_the_runs_shown():
    runs = [
        {
            "status": "succeeded",
            "created_at": "2026-10-01T12:00:00",
            "started_at": "2026-10-01T12:00:30",
        },
        {
            "status": "failed",
            "created_at": "2026-10-01T12:00:00",
            "started_at": "2026-10-01T12:01:30",
        },
        {
            "status": "succeeded",
            "created_at": "2026-10-01T12:00:00",
            "started_at": "2026-10-01T12:01:00",
        },
        {"status": "pending", "created_at": "2026-10-01T12:05:00", "started_at": None},
    ]

    assert {"success_rate": "50%", "failed": "1", "avg_wait": "1m 00s"} == (
        forms.runs_summary(runs)
    )
    assert {"success_rate": "—", "failed": "0", "avg_wait": "—"} == (
        forms.runs_summary([])
    )


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("3", 3),
        ('["ad", "ca"]', ["ad", "ca"]),
        ("true", True),
        ("null", None),
        ("plain text", "plain text"),
        ('"quoted"', "quoted"),
    ],
)
def test_parse_context_value_reads_json_else_text(text, value):
    assert value == forms.parse_context_value(text)


def test_context_rows_sort_keys_and_mask_secrets():
    rows = forms.context_rows(
        {"parish[]": ["ad", "ca"], "google_api_key": "AIza-secret", "page": 2}
    )

    assert [
        {"key": "google_api_key", "value_text": "••••••", "is_secret": True},
        {"key": "page", "value_text": "2", "is_secret": False},
        {"key": "parish[]", "value_text": '["ad", "ca"]', "is_secret": False},
    ] == rows


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("google_api_key", True),
        ("TOKEN", True),
        ("db_password", True),
        ("parish[]", False),
    ],
)
def test_is_secret_key(key, expected):
    assert expected is forms.is_secret_key(key)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("pending", False), ("running", False), ("succeeded", True), ("failed", True)],
)
def test_has_csv_only_once_a_run_ended(status, expected):
    assert expected is forms.has_csv({"status": status})


def test_build_rate_limit_payload_reads_the_rule_and_defaults_blanks():
    payload, error = forms.build_rate_limit_payload(
        {
            "name": " Places API ",
            "rate_limit_string": " 5/second ",
            "penalty_step_seconds": "10",
            "max_penalty_seconds": "",
            "decay_after_successes": " ",
            "decay_step_seconds": "2",
        }
    )

    assert "" == error
    assert {
        "name": "Places API",
        "rate_limit_string": "5/second",
        "penalty_step_seconds": 10,
        "max_penalty_seconds": 0,
        "decay_after_successes": 1,
        "decay_step_seconds": 2,
    } == payload


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"rate_limit_string": " "}, "limit"),
        ({"rate_limit_string": "5/second", "penalty_step_seconds": "ten"}, "whole"),
    ],
)
def test_build_rate_limit_payload_rejects_bad_input(form, message):
    payload, error = forms.build_rate_limit_payload(form)

    assert None is payload
    assert message in error.lower()


def test_rate_limit_summary_describes_the_penalty():
    assert "no penalty" == forms.rate_limit_summary(
        {"penalty_step_seconds": 0, "max_penalty_seconds": 0}
    )
    assert "+10 s per block, up to 60 s; −5 s after 3 successes" == (
        forms.rate_limit_summary(
            {
                "penalty_step_seconds": 10,
                "max_penalty_seconds": 60,
                "decay_after_successes": 3,
                "decay_step_seconds": 5,
            }
        )
    )
    assert "+10 s per block, up to 60 s; −5 s after 1 success" == (
        forms.rate_limit_summary(
            {
                "penalty_step_seconds": 10,
                "max_penalty_seconds": 60,
                "decay_after_successes": 1,
                "decay_step_seconds": 5,
            }
        )
    )
    assert "+10 s per block, up to 60 s; no decay" == forms.rate_limit_summary(
        {
            "penalty_step_seconds": 10,
            "max_penalty_seconds": 60,
            "decay_after_successes": 1,
            "decay_step_seconds": 0,
        }
    )


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://Places.GoogleAPIs.com/v1/places:searchText", "places.googleapis.com"),
        ("https://www.example.com:8443/a?b=1", "www.example.com"),
        ("https://{{host}}/search", ""),
        ("not a url", ""),
        ("", ""),
    ],
)
def test_url_host(url, host):
    assert host == forms.url_host(url)


def test_find_rate_limit_for_host_matches_the_rule_named_after_it():
    rules = [
        {"id": "r1", "name": "Google Places API"},
        {"id": "r2", "name": " Places.GoogleAPIs.com "},
        {"id": "r3", "name": None},
    ]

    assert "r2" == forms.find_rate_limit_for_host(rules, "places.googleapis.com")
    assert "" == forms.find_rate_limit_for_host(rules, "maps.google.com")
    assert "" == forms.find_rate_limit_for_host(rules, "")
