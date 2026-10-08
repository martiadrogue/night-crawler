from datetime import datetime

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


def test_context_rows_sort_keys_mask_secrets_and_flag_harvested_keys():
    rows = forms.context_rows(
        {"parish[]": ["ad", "ca"], "google_api_key": "AIza-secret", "page": 2},
        ["page", "page[]"],
    )

    assert [
        {
            "key": "google_api_key",
            "value_text": "••••••",
            "is_secret": True,
            "is_harvested": False,
        },
        {"key": "page", "value_text": "2", "is_secret": False, "is_harvested": True},
        {
            "key": "parish[]",
            "value_text": '["ad", "ca"]',
            "is_secret": False,
            "is_harvested": False,
        },
    ] == rows


def test_context_rows_without_harvested_keys():
    assert [False] == [
        row["is_harvested"] for row in forms.context_rows({"token": "a"})
    ]


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


@pytest.mark.parametrize(
    ("title", "status", "filename"),
    [
        ("Andorra venues", "draft", "andorra-venues-draft-instructions.yaml"),
        ("  Café & Bar!  ", "published", "caf-bar-published-instructions.yaml"),
        ("", "archived", "crawler-archived-instructions.yaml"),
    ],
)
def test_instructions_filename(title, status, filename):
    assert filename == forms.instructions_filename(title, status)


@pytest.mark.parametrize(
    ("data", "text", "error"),
    [
        (b"templates: {}\n", "templates: {}\n", ""),
        (b"\xef\xbb\xbftemplates: {}", "templates: {}", ""),
        (b"  \n", None, "The file is empty."),
        (b"\xff\xfe", None, "The file must be UTF-8 YAML text."),
    ],
)
def test_decode_instructions_file(data, text, error):
    assert (text, error) == forms.decode_instructions_file(data)


@pytest.mark.parametrize(
    ("form", "payload", "error"),
    [
        (
            {"prompt": "  comedy shows in Barcelona  "},
            {"prompt": "comedy shows in Barcelona"},
            "",
        ),
        ({"prompt": "   "}, None, "Describe what the crawler should get."),
        ({}, None, "Describe what the crawler should get."),
        (
            {"prompt": "x" * 4001},
            None,
            "Keep the prompt to 4000 characters (it has 4001).",
        ),
        ({"prompt": "x" * 4000}, {"prompt": "x" * 4000}, ""),
    ],
)
def test_build_generation_payload(form, payload, error):
    assert (payload, error) == forms.build_generation_payload(form)


RUNNING = {"status": "running", "filtered_requests": [], "result_version_id": None}


@pytest.mark.parametrize(
    ("generation", "execution", "text"),
    [
        ({"status": "pending"}, None, "Waiting for a worker…"),
        (RUNNING, None, "Recording the browser session…"),
        (
            {**RUNNING, "filtered_requests": [{"url": "https://x"}]},
            None,
            "Writing instructions…",
        ),
        (
            {**RUNNING, "filtered_requests": [{"url": "x"}], "result_version_id": "v2"},
            None,
            "Starting the test run…",
        ),
        (
            {"status": "failed", "error": "No recorded response…"},
            None,
            "Failed: No recorded response…",
        ),
        ({"status": "succeeded", "test_execution_id": "e1"}, None, "Test run pending…"),
        (
            {"status": "succeeded", "test_execution_id": "e1"},
            {"status": "running"},
            "Test run running…",
        ),
        (
            {"status": "succeeded", "test_execution_id": "e1"},
            {"status": "succeeded", "validation": {"rows_checked": 120}},
            "Test run succeeded: 120 rows",
        ),
        (
            {"status": "succeeded", "test_execution_id": "e1"},
            {"status": "failed", "validation": None},
            "Test run failed",
        ),
        (
            {"status": "succeeded", "test_execution_id": None},
            None,
            "Instructions written.",
        ),
    ],
)
def test_generation_status_text(generation, execution, text):
    assert text == forms.generation_status_text(generation, execution)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"status": "pending"}, False),
        ({"status": "running"}, False),
        ({"status": "succeeded"}, True),
        ({"status": "failed"}, True),
        ({"status": "cancelled"}, True),
        ({}, False),
    ],
)
def test_has_ended(record, expected):
    assert expected is forms.has_ended(record)


def test_build_user_payload_creates_with_email_and_password():
    payload, error = forms.build_user_payload(
        {"email": " ana@example.com ", "password": "Secret123"}, "admin", is_new=True
    )

    assert "" == error
    assert {"email": "ana@example.com", "password": "Secret123"} == payload


def test_build_user_payload_edits_and_keeps_a_blank_password():
    payload, error = forms.build_user_payload(
        {"email": "ana@example.com", "password": " "}, "viewer", is_new=False
    )

    assert "" == error
    assert {"email": "ana@example.com", "role": "viewer"} == payload


def test_build_user_payload_edits_a_typed_password():
    payload, _ = forms.build_user_payload(
        {"email": "ana@example.com", "password": "Secret123"}, "user", is_new=False
    )

    assert "Secret123" == payload["password"]


@pytest.mark.parametrize(
    ("form", "is_new", "message"),
    [
        ({"email": " ", "password": "Secret123"}, True, "email"),
        ({"email": "ana@example.com", "password": ""}, True, "password"),
        ({"email": "", "password": ""}, False, "email"),
    ],
)
def test_build_user_payload_rejects_missing_input(form, is_new, message):
    payload, error = forms.build_user_payload(form, "user", is_new=is_new)

    assert None is payload
    assert message in error.lower()


NOW = datetime.fromisoformat("2026-10-01T15:30:00")  # naive UTC, as the API sends


@pytest.mark.parametrize(
    ("cron", "text"),
    [
        (None, "Manual runs only"),
        ("", "Manual runs only"),
        ("0 2 * * *", "Runs daily at 02:00 UTC"),
        ("30 18 * * *", "Runs daily at 18:30 UTC"),
        ("15 * * * *", "Runs every hour at :15 UTC"),
        ("0 6 * * 1", "Runs on Mondays at 06:00 UTC"),
        ("0 6 * * 0", "Runs on Sundays at 06:00 UTC"),
        ("0 6 * * 7", "Runs on Sundays at 06:00 UTC"),
        ("0 3 1 * *", "Runs monthly on day 1 at 03:00 UTC"),
        ("*/15 * * * *", "Runs every 15 minutes"),
        ("0 */6 * * *", "Runs on cron 0 */6 * * * (UTC)"),
        ("0 6 * * 1-5", "Runs on cron 0 6 * * 1-5 (UTC)"),
    ],
)
def test_schedule_text(cron, text):
    assert text == forms.schedule_text(cron)


@pytest.mark.parametrize(
    ("value", "parts"),
    [
        (None, ("—", "")),
        ("2026-10-01T15:29:40", ("<1", "minute ago")),
        ("2026-10-01T15:05:00", ("25", "minutes ago")),
        ("2026-09-30T12:00:00", ("1", "day ago")),
        ("2026-09-26T12:00:00", ("5", "days ago")),
    ],
)
def test_split_time_ago(value, parts):
    assert parts == forms.split_time_ago(value, NOW)


def _run(**overrides):
    return {
        "id": "e1",
        "status": "succeeded",
        "outcome": "success",
        "created_at": "2026-10-07T02:00:00",
        "started_at": "2026-10-07T02:09:37.250000",
        "finished_at": "2026-10-07T02:51:11",
        "dataset": {"row_count": 50171},
        "validation": {"completeness_rate": 0.99812},
        **overrides,
    }


def test_history_row_shows_the_run_like_the_table():
    row = forms.history_row(_run(), is_latest=True)

    assert "Oct 7, 2026" == row["date_text"]
    assert ("02:09:37", "02:51:11") == (row["start_text"], row["end_text"])
    assert "41m 33s" == row["duration_text"]
    assert "Success" == row["outcome_label"]
    assert "50,171" == row["records_text"]
    assert "99.8%" == row["completeness_text"]
    assert row["is_latest"]


def test_history_row_of_a_pending_run_is_dated_by_its_creation():
    row = forms.history_row(
        _run(
            status="pending",
            outcome="in_progress",
            started_at=None,
            finished_at=None,
            dataset=None,
            validation=None,
        )
    )

    assert "Oct 7, 2026" == row["date_text"]
    assert ("—", "—", "—") == (
        row["start_text"],
        row["end_text"],
        row["duration_text"],
    )
    assert ("In progress", "—", "–") == (
        row["outcome_label"],
        row["records_text"],
        row["completeness_text"],
    )
    assert not row["is_latest"]


def test_history_row_without_a_completeness_rate_shows_a_dash():
    row = forms.history_row(_run(outcome="failed", validation={"is_valid": False}))

    assert ("Failed", "–") == (row["outcome_label"], row["completeness_text"])


def test_history_rows_mark_only_the_newest_as_latest():
    rows = forms.history_rows([_run(id="new"), _run(id="old")])

    assert [True, False] == [row["is_latest"] for row in rows]


def test_filter_runs_by_outcome():
    runs = [_run(id="a"), _run(id="b", outcome="failed"), _run(id="c")]

    assert ["a", "b", "c"] == [
        run["id"] for run in forms.filter_runs_by_outcome(runs, forms.ALL_OUTCOMES)
    ]
    assert ["b"] == [run["id"] for run in forms.filter_runs_by_outcome(runs, "failed")]


def test_page_slice_and_showing_text():
    rows = list(range(30))

    assert list(range(12)) == forms.page_slice(rows, 0)
    assert list(range(24, 30)) == forms.page_slice(rows, 2)
    assert "Showing 1–12 of 30" == forms.showing_text(0, 30)
    assert "Showing 25–30 of 30" == forms.showing_text(2, 30)
    assert "No runs to show" == forms.showing_text(0, 0)


def test_build_history_csv_keeps_numbers_plain():
    rows = forms.history_rows(
        [
            _run(),
            _run(
                id="e2",
                outcome="failed",
                status="failed",
                dataset=None,
                validation=None,
            ),
        ]
    )

    assert (
        "Execution ID,Execution date,Start (UTC),End (UTC),Duration (s),Status,"
        "Records extracted,Completeness rate (%)\r\n"
        "e1,2026-10-07,02:09:37,02:51:11,2493,Success,50171,99.8\r\n"
        "e2,2026-10-07,02:09:37,02:51:11,2493,Failed,,\r\n"
    ) == forms.build_history_csv(rows)


def test_history_csv_filename():
    assert "andorra-venues-history.csv" == forms.history_csv_filename("Andorra Venues")
    assert "crawler-history.csv" == forms.history_csv_filename("!!!")


def test_history_summary_turns_the_numbers_into_card_texts():
    summary = forms.history_summary(
        {
            "consecutive_successful_runs": 5,
            "success_rate": 0.8,
            "recent_run_count": 30,
            "last_verification_failure_at": "2026-09-26T12:00:00",
            "last_failure_at": "2026-09-23T12:00:00",
            "avg_completeness_rate": 0.98612,
        },
        NOW,
    )

    assert {
        "streak": "5",
        "streak_unit": "successful runs",
        "verification_failure": "5",
        "verification_failure_unit": "days ago",
        "failure": "8",
        "failure_unit": "days ago",
        "success_rate": "80%",
        "success_hint": "avg completeness 98.6%",
    } == summary


def test_history_summary_before_any_run_ended():
    summary = forms.history_summary(
        {
            "consecutive_successful_runs": 1,
            "success_rate": None,
            "recent_run_count": 0,
            "last_verification_failure_at": None,
            "last_failure_at": None,
            "avg_completeness_rate": None,
        },
        NOW,
    )

    assert ("1", "successful run") == (summary["streak"], summary["streak_unit"])
    assert ("—", "") == (summary["failure"], summary["failure_unit"])
    assert ("—", "no completeness yet") == (
        summary["success_rate"],
        summary["success_hint"],
    )


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "—"),
        ("2026-10-01T15:29:40", "just now"),
        ("2026-10-01T15:29:00", "1 minute ago"),
        ("2026-10-01T15:05:00", "25 minutes ago"),
        ("2026-10-01T14:20:00", "1 hour ago"),
        ("2026-09-30T16:00:00", "23 hours ago"),
        ("2026-09-30T12:00:00", "yesterday"),
        ("2026-09-21T12:00:00", "10 days ago"),
        ("2026-10-01T15:31:00", "just now"),
    ],
)
def test_time_ago(value, text):
    assert text == forms.time_ago(value, NOW)


def _window():
    """Rows of a window, newest first, as the state keeps them."""
    return forms.history_rows(
        [
            _run(id="running", outcome="in_progress", status="running"),
            _run(id="ok", validation={"completeness_rate": 0.998}),
            _run(
                id="unverified",
                outcome="verification_failed",
                validation={"completeness_rate": 0.958},
            ),
            _run(id="failed", outcome="failed", status="failed", validation=None),
        ]
    )


def test_chart_points_are_ended_runs_oldest_first():
    points = forms.chart_points(_window(), forms.ALL_OUTCOMES)

    assert ["failed", "unverified", "ok"] == [point["id"] for point in points]
    assert [0, 1, 2] == [point["x"] for point in points]
    assert [None, 95.8, 99.8] == [point["completeness_pct"] for point in points]
    assert [False, True, True] == [point["has_data"] for point in points]
    assert [1.0, 1.0, 1.0] == [point["opacity"] for point in points]
    assert "Oct 7, 2026 · Success · 50,171 records" == points[2]["label"]
    assert ("Oct 7", "99.8%") == (
        points[2]["date_label"],
        points[2]["completeness_text"],
    )


def test_chart_points_dim_what_the_chip_leaves_out():
    points = forms.chart_points(_window(), "verification_failed")

    assert [0.25, 1.0, 0.25] == [point["opacity"] for point in points]


def test_chart_floor_sits_below_the_lowest_rate_and_at_most_94():
    def points(*rates):
        return [
            {"completeness_pct": rate, "has_data": rate is not None} for rate in rates
        ]

    assert 94 == forms.chart_floor(points(99.8, 98.0))
    assert 94 == forms.chart_floor(points(95.0))
    assert 90 == forms.chart_floor(points(99.0, 91.4))
    assert 94 == forms.chart_floor(points(None))
    assert 94 == forms.chart_floor([])


def test_chart_series_split_points_by_outcome_data_and_highlight():
    points = forms.chart_points(_window(), "verification_failed")

    series = forms.chart_series(points, 94)

    assert set(series) == {key for key, *_style in forms.CHART_SERIES}
    assert [{"x": 1, "y": 95.8, "stem": [1.8, 0]}] == [
        {key: point[key] for key in ("x", "y", "stem")}
        for point in series["verification_failed"]
    ]
    assert [2] == [point["x"] for point in series["success_dim"]]
    assert [{"x": 0, "y": 94, "stem": [0, 0]}] == [
        {key: point[key] for key in ("x", "y", "stem")}
        for point in series["no_data_dim"]
    ]
    assert [] == series["success"]


def test_chip_options_follow_the_counts_and_the_selection():
    chips = forms.chip_options(
        {"all": 30, "success": 24, "verification_failed": 4, "failed": 2},
        "failed",
    )

    assert [
        ("all", "All", 30, False),
        ("success", "Success", 24, False),
        ("verification_failed", "Verification failed", 4, False),
        ("failed", "Failed", 2, True),
    ] == [
        (chip["value"], chip["label"], chip["count"], chip["is_selected"])
        for chip in chips
    ]
