"""Pure helpers turning form input into API payloads, and back.

No Reflex and no I/O here, so every rule is unit-testable.
"""

import csv
import io
import json
import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

NO_SELECTION = "__none__"
"""A select's "nothing chosen" value; Radix selects can't hold ""."""

RENDER_MODES = [
    ("none", "No render"),
    ("playwright", "Render"),
    ("stealth", "Stealth"),
]
SELECTOR_TYPES = ["value", "iterator", "boolean", "click", "select", "pagination"]
SELECTOR_SOURCES = ["content", "headers", "url", "context"]
"""`context` reads the value of the placeholder its path names."""
TEMPLATE_ACTIONS = ["GET", "POST", "PUT", "PATCH", "DELETE", "CLICK"]
EXECUTION_QUEUES = ["discovery", "priority", "real-time", "testing"]
CRAWLER_QUEUES = [queue for queue in EXECUTION_QUEUES if "testing" != queue]
"""A crawler's own queues; `testing` is only for test runs."""
ALL_STATUSES = "all"
"""The Runs filters' "any status" value."""
EXECUTION_STATUS_FILTERS = [
    ALL_STATUSES,
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
]
PARSING_STATUS_FILTERS = [ALL_STATUSES, "pending", "parsing", "parsed", "failed"]
QUEUE_FILTERS = [ALL_STATUSES, *EXECUTION_QUEUES]


def parse_json_object(text: str) -> tuple[dict | None, str]:
    """Return `(object, "")`, or `(None, error)`; blank means `{}`."""
    if not text.strip():
        return {}, ""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"
    if not isinstance(value, dict):
        return None, "Expected a JSON object, e.g. {}."
    return value, ""


def parse_codes(text: str) -> list[str] | None:
    """Return status codes from `403, 429 timeout`; blank means `None`."""
    codes = [code for code in re.split(r"[\s,]+", text.strip()) if code]
    return codes or None


def parse_optional_int(text: str) -> int | None:
    """Return an int, or `None` for blank.

    Raises:
        ValueError: the text isn't a whole number.
    """
    stripped = text.strip()
    return int(stripped) if stripped else None


def blank_to_none(value: str | None) -> str | None:
    """Return a stripped value, or `None` for blank or `NO_SELECTION`."""
    stripped = (value or "").strip()
    return None if stripped in ("", NO_SELECTION) else stripped


def to_select(value: str | None) -> str:
    """Return a select's value for an optional id."""
    return value or NO_SELECTION


def selector_tree_rows(
    selectors: list[dict], crawler_fields: list[str] | None = None
) -> list[dict]:
    """Return selectors parent-first, each with `depth` and `tree_label`.

    Orphans (a parent on another template) are shown at the top level.
    """
    children = _children_by_parent(selectors)
    field_names = set(crawler_fields or [])
    rows: list[dict] = []
    pending = [(selector, 0) for selector in reversed(children.get(None, []))]
    while pending:
        selector, depth = pending.pop()
        rows.append(
            {
                **selector,
                "depth": depth,
                "tree_label": "↳ " * depth + selector["path"],
                "is_dataset_field": selector.get("title") in field_names,
            }
        )
        pending.extend(
            (child, depth + 1) for child in reversed(children.get(selector["id"], []))
        )
    return rows


def _children_by_parent(selectors: list[dict]) -> dict[str | None, list[dict]]:
    """Group selectors by parent; an unknown parent counts as none."""
    known = {selector["id"] for selector in selectors}
    children: dict[str | None, list[dict]] = {}
    for selector in selectors:
        parent = selector.get("parent_selector_id")
        children.setdefault(parent if parent in known else None, []).append(selector)
    return children


def toggle_selection(current: str, clicked: str) -> str:
    """Return the clicked id, or `""` when it is already the open one."""
    return "" if current == clicked else clicked


def draft_id(versions: list[dict]) -> str | None:
    """Return the id of the crawler's draft, if it has one."""
    return next((v["id"] for v in versions if "draft" == v["status"]), None)


def editable_version_id(versions: list[dict]) -> str | None:
    """Return the version whose instructions to edit.

    The draft if there is one, else the published version (editing it
    forks a draft); `None` when every version is archived.
    """
    return draft_id(versions) or next(
        (v["id"] for v in versions if "published" == v["status"]), None
    )


def codes_text(codes: list[str] | None) -> str:
    """Return codes as `403, 429`, or blank."""
    return ", ".join(codes or [])


def optional_text(value: Any) -> str:
    """Return a value as text, or blank for `None`."""
    return "" if None is value else str(value)


def names_by_id(items: list[dict]) -> dict[str, str]:
    """Return each record's name keyed by id, to label references."""
    return {item["id"]: item["name"] for item in items}


def id_options(items: list[dict], label_key: str) -> list[dict]:
    """Return `{value, label}` pairs for a select of ids."""
    return [
        {"value": item["id"], "label": str(item.get(label_key) or item["id"])}
        for item in items
    ]


def build_crawler_payload(
    form: dict, choices: dict[str, str | None]
) -> tuple[dict | None, str]:
    """Return a crawler body from the Schedule dialog, or an error.

    `choices` holds the selects: `source_id` (where the dataset comes
    from), `dataset_id` (what the CSV holds), and `queue` (where every
    run goes).
    """
    error = _missing_link(choices)
    if error:
        return None, error
    fields = parse_names(form.get("fields", ""))
    if not fields:
        return None, "List the dataset fields this crawler downloads."
    payload = {
        "title": form.get("title", "").strip(),
        "source_id": choices["source_id"],
        "dataset_id": choices["dataset_id"],
        "fields": fields,
        "schedule": blank_to_none(form.get("schedule")),
        "queue": choices["queue"],
    }
    return payload, ""


def _missing_link(choices: dict[str, str | None]) -> str:
    """Return why the Source or Dataset pick is missing, or blank."""
    for key, page in (("source_id", "Sources"), ("dataset_id", "Datasets")):
        if not choices[key]:
            label = page[:-1].lower()
            return f"Pick a {label}; create one on the {page} page first."
    return ""


def parse_names(text: str) -> list[str]:
    """Return names from `a, b` or one per line; blank means none."""
    return [name for name in re.split(r"[\s,]+", text.strip()) if name]


def parse_json_objects(text: str) -> tuple[list[dict] | None, str]:
    """Return `(objects, "")` from a JSON list of objects, or an error."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"
    if not isinstance(value, list) or not all(isinstance(i, dict) for i in value):
        return None, 'Expected a JSON list of objects, e.g. [{"name": "item_id"}].'
    return value, ""


def build_dataset_payload(form: dict) -> tuple[dict | None, str]:
    """Return a dataset body from the Datasets dialog, or an error."""
    fields, error = parse_json_objects(form.get("fields_text", ""))
    if error:
        return None, f"Fields: {error}"
    return {
        "name": form.get("name", "").strip(),
        "fields": fields,
    }, ""


def fields_summary(fields: list[dict]) -> str:
    """Return e.g. `item_id*! · stars:integer · url ~^https?://`.

    `*` marks a required field, `!` a unique one; the type shows when
    it isn't `string`, the pattern after `~`.
    """
    return " · ".join(_field_summary(field) for field in fields)


def _field_summary(field: dict) -> str:
    """Return one field's part of `fields_summary`."""
    text = field["name"]
    text += "*" if field.get("is_required") else ""
    text += "!" if field.get("is_unique") else ""
    if field.get("type", "string") != "string":
        text += f":{field['type']}"
    if field.get("pattern"):
        text += f" ~{field['pattern']}"
    return text


def build_settings_payload(form: dict) -> dict:
    """Return a version settings body.

    The proxy ladder is left out: no crawl reads it yet, so the UI
    doesn't offer it and the stored value stays as it is.
    """
    return {
        "is_host_session_sharing_enabled": bool(
            form.get("is_host_session_sharing_enabled")
        ),
    }


def build_template_payload(form: dict, action: str) -> tuple[dict | None, str]:
    """Return a template body from the dialog's fields, or an error."""
    headers, error = parse_json_object(form.get("headers_text", ""))
    if error:
        return None, f"Headers: {error}"
    return {
        "action": action,
        "url": form.get("url", "").strip(),
        "body": blank_to_none(form.get("body")),
        "headers": headers,
    }, ""


def build_selector_payload(
    form: dict, choices: dict[str, str]
) -> tuple[dict | None, str]:
    """Return a selector body, or an error.

    `choices` holds the selects: `type`, `source`, `parent_selector_id`.
    Only a `pagination` selector takes the JSON `config`.
    """
    config = None
    if "pagination" == choices["type"]:
        config, error = parse_json_object(form.get("config_text", ""))
        if error:
            return None, f"Config: {error}"
    return {
        "path": form.get("path", "").strip(),
        "type": choices["type"],
        "source": choices["source"],
        "target": (form.get("target") or "").strip() or "__text",
        "title": blank_to_none(form.get("title")),
        "parent_selector_id": blank_to_none(choices["parent_selector_id"]),
        "config": config,
    }, ""


def aid_summary(aid: dict | None) -> str:
    """Return e.g. `httpx (no browser) · 30 s`, or `defaults`."""
    if not aid:
        return "defaults"
    engine = dict(RENDER_MODES).get(aid.get("render_mode"), "httpx (no browser)")
    return f"{engine} · {aid['ttl']} s" if aid.get("ttl") else engine


def is_default_aid(payload: dict) -> bool:
    """Tell whether an aid body sets nothing beyond the defaults.

    Such an aid is not stored: a template without one already behaves
    as httpx with every other setting at its default.
    """
    return "none" == payload["render_mode"] and all(
        None is value for key, value in payload.items() if "render_mode" != key
    )


def build_aid_payload(form: dict, choices: dict[str, str]) -> tuple[dict | None, str]:
    """Return an aid body, or an error.

    `choices` holds the selects: `render_mode`, `selected_proxy_id`,
    `rate_limit_id`.
    """
    try:
        numbers = {
            name: parse_optional_int(form.get(name, ""))
            for name in ("ttl", "max_retry_attempts")
        }
    except ValueError:
        return None, "TTL and retry counts must be whole numbers."
    return {
        "render_mode": choices["render_mode"],
        "selected_proxy_id": blank_to_none(choices["selected_proxy_id"]),
        "rate_limit_id": blank_to_none(choices["rate_limit_id"]),
        "retry_codes": parse_codes(form.get("retry_codes", "")),
        "success_codes": parse_codes(form.get("success_codes", "")),
        **numbers,
    }, ""


def execution_params(filters: dict, offset: int) -> dict:
    """Return the Runs query from its filters.

    `filters` holds the `status`, `parsing_status`, and `queue` selects
    (`all` sends no filter) and the `crawler_title` text (blank sends
    none). A filtered listing is one capped page, so it sends no offset.
    """
    params = {
        "status": _select_filter(filters["status"]),
        "parsing_status": _select_filter(filters["parsing_status"]),
        "queue": _select_filter(filters["queue"]),
        "crawler_title": filters["crawler_title"].strip() or None,
    }
    is_filtered = any(value is not None for value in params.values())
    return {**params, "offset": None if is_filtered else offset}


def _select_filter(value: str) -> str | None:
    """Return a filter select's value, or `None` for `all`."""
    return None if ALL_STATUSES == value else value


def short_time(value: str | None) -> str:
    """Return `2026-10-01 12:30:05` from an ISO timestamp, or `—`."""
    return value[:19].replace("T", " ") if value else "—"


def seconds_between(start: str | None, end: str | None) -> float | None:
    """Return the seconds from one ISO timestamp to another, or `None`."""
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def format_duration(seconds: float | None) -> str:
    """Return e.g. `45s`, `2m 05s`, or `1h 03m`; `—` for `None`."""
    if seconds is None:
        return "—"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def runs_summary(runs: list[dict]) -> dict:
    """Return the Runs cards for the runs shown, as texts.

    `success_rate` is the share of those runs that succeeded; the
    average wait covers only runs that have started.
    """
    return {
        "success_rate": _success_rate(runs),
        "failed": str(sum("failed" == run["status"] for run in runs)),
        "avg_wait": _average_wait(runs),
    }


def _success_rate(runs: list[dict]) -> str:
    """Return the share of `runs` that succeeded, e.g. `50%`."""
    if not runs:
        return "—"
    succeeded = sum("succeeded" == run["status"] for run in runs)
    return f"{round(100 * succeeded / len(runs))}%"


def _average_wait(runs: list[dict]) -> str:
    """Return the average time started runs waited in the queue."""
    waits = [seconds_between(run["created_at"], run["started_at"]) for run in runs]
    started = [wait for wait in waits if wait is not None]
    return format_duration(sum(started) / len(started)) if started else "—"


HISTORY_TABLE_PAGE_SIZE = 12
ALL_OUTCOMES = "all"
OUTCOME_LABELS = {
    "success": "Success",
    "verification_failed": "Verification failed",
    "failed": "Failed",
    "in_progress": "In progress",
}
"""What each run outcome the API returns reads as."""

WEEKDAYS = (
    "Sundays",
    "Mondays",
    "Tuesdays",
    "Wednesdays",
    "Thursdays",
    "Fridays",
    "Saturdays",
    "Sundays",
)
"""Cron day-of-week names: 0 and 7 are both Sunday."""


def _at(minute: str, hour: str) -> str:
    """Return e.g. `02:00 UTC`."""
    return f"{int(hour):02d}:{int(minute):02d} UTC"


SCHEDULE_SHAPES = (
    (r"(\d{1,2}) (\d{1,2}) \* \* \*", lambda m, h: f"Runs daily at {_at(m, h)}"),
    (r"(\d{1,2}) \* \* \* \*", lambda m: f"Runs every hour at :{int(m):02d} UTC"),
    (
        r"(\d{1,2}) (\d{1,2}) \* \* ([0-7])",
        lambda m, h, d: f"Runs on {WEEKDAYS[int(d)]} at {_at(m, h)}",
    ),
    (
        r"(\d{1,2}) (\d{1,2}) (\d{1,2}) \* \*",
        lambda m, h, d: f"Runs monthly on day {int(d)} at {_at(m, h)}",
    ),
    (r"\*/(\d{1,2}) \* \* \* \*", lambda n: f"Runs every {int(n)} minutes"),
)
"""Cron shapes put into words, tried in order; others stay as cron."""


def schedule_text(cron: str | None) -> str:
    """Return a crawler's schedule in plain English; cron runs in UTC."""
    expression = " ".join((cron or "").split())
    if not expression:
        return "Manual runs only"
    for pattern, describe in SCHEDULE_SHAPES:
        match = re.fullmatch(pattern, expression)
        if match:
            return describe(*match.groups())
    return f"Runs on cron {expression} (UTC)"


def split_time_ago(value: str | None, now: datetime) -> tuple[str, str]:
    """Return `time_ago` as a number and its unit, e.g. `("5", "days ago")`."""
    text = time_ago(value, now)
    if "—" == text:
        return "—", ""
    if "just now" == text:
        return "<1", "minute ago"
    if "yesterday" == text:
        return "1", "day ago"
    number, unit = text.split(" ", 1)
    return number, unit


def history_row(run: dict, is_latest: bool = False) -> dict:
    """Return a run with the texts its Execution history row shows.

    Times are the API's, which are UTC. The date is when the run
    started, or was created while it waits; `—` stands for what
    hasn't happened yet.
    """
    started, finished = run["started_at"], run["finished_at"]
    return {
        **run,
        "date_text": _long_date(started or run["created_at"]),
        "start_text": _clock_time(started),
        "end_text": _clock_time(finished),
        "duration_text": format_duration(seconds_between(started, finished)),
        "outcome_label": OUTCOME_LABELS[run["outcome"]],
        "records_text": _records_text(run["dataset"]),
        "completeness_text": _completeness_text(_completeness_rate(run)),
        "is_latest": is_latest,
    }


def history_rows(runs: list[dict]) -> list[dict]:
    """Return the table rows of runs listed newest first."""
    return [history_row(run, is_latest=0 == index) for index, run in enumerate(runs)]


def _long_date(value: str) -> str:
    """Return `Oct 7, 2026` from an ISO timestamp."""
    moment = datetime.fromisoformat(value)
    return f"{moment:%b} {moment.day}, {moment.year}"


def _clock_time(value: str | None) -> str:
    """Return `12:30:05` from an ISO timestamp, or `—`."""
    return value[11:19] if value else "—"


def _records_text(dataset: dict | None) -> str:
    """Return the rows the run extracted into its CSV, e.g. `1,263`."""
    return f"{dataset['row_count']:,}" if dataset else "—"


def _completeness_rate(run: dict) -> float | None:
    """Return the run's completeness rate, 0 to 1, if it has one."""
    return (run["validation"] or {}).get("completeness_rate")


def _completeness_text(rate: float | None) -> str:
    """Return e.g. `99.8%`, or `–` without a rate."""
    return "–" if rate is None else f"{100 * rate:.1f}%"


def filter_runs_by_outcome(runs: list[dict], outcome: str) -> list[dict]:
    """Return the runs that came to `outcome`; `all` keeps every run."""
    if ALL_OUTCOMES == outcome:
        return runs
    return [run for run in runs if outcome == run["outcome"]]


def page_slice(rows: list, page: int) -> list:
    """Return the rows of one table page, counting pages from 0."""
    start = page * HISTORY_TABLE_PAGE_SIZE
    return rows[start : start + HISTORY_TABLE_PAGE_SIZE]


def showing_text(page: int, total: int) -> str:
    """Return e.g. `Showing 1–12 of 30` for a table page."""
    if not total:
        return "No runs to show"
    start = page * HISTORY_TABLE_PAGE_SIZE
    return (
        f"Showing {start + 1}–{min(start + HISTORY_TABLE_PAGE_SIZE, total)} of {total}"
    )


CHART_FLOOR_MAX = 94
"""The completeness chart's y-axis never starts above 94%."""
DIMMED_OPACITY = 0.25
CHART_OUTCOMES = ("success", "verification_failed", "failed")
CHART_SERIES = tuple(
    (f"{base}{suffix}", color, shape, opacity)
    for base, color, shape in (
        ("success", "var(--green-9)", "circle"),
        ("verification_failed", "var(--amber-9)", "circle"),
        ("failed", "var(--red-9)", "circle"),
        ("no_data", "var(--red-9)", "cross"),
    )
    for suffix, opacity in (("", 1.0), ("_dim", DIMMED_OPACITY))
)
"""The chart's series: `(key, fill, shape, opacity)`, drawn in order.

Each point lands in one, by outcome (or no data) and by whether the
selected chip highlights it, so every series has a single style.
"""
CHIP_OUTCOMES = (ALL_OUTCOMES, *CHART_OUTCOMES)


def chart_points(rows: list[dict], selected_outcome: str) -> list[dict]:
    """Return the chart's points: ended runs, oldest first.

    A point the selected chip doesn't cover is dimmed, never removed.
    `completeness_pct` is `None` for a run without a completeness rate.
    """
    ended = [row for row in reversed(rows) if row["outcome"] in CHART_OUTCOMES]
    return [
        _chart_point(row, index, selected_outcome) for index, row in enumerate(ended)
    ]


def _chart_point(row: dict, index: int, selected_outcome: str) -> dict:
    """Return one run as a chart point at position `index`."""
    rate = _completeness_rate(row)
    is_highlighted = selected_outcome in (ALL_OUTCOMES, row["outcome"])
    return {
        "id": row["id"],
        "x": index,
        "outcome": row["outcome"],
        "date_label": row["date_text"].rsplit(",", 1)[0],
        "label": f"{row['date_text']} · {row['outcome_label']} · "
        f"{row['records_text']} records",
        "completeness_pct": None if rate is None else round(100 * rate, 1),
        "completeness_text": row["completeness_text"],
        "has_data": rate is not None,
        "opacity": 1.0 if is_highlighted else DIMMED_OPACITY,
    }


def chart_floor(points: list[dict]) -> int:
    """Return where the y-axis starts: 1 point under the lowest rate."""
    rates = [point["completeness_pct"] for point in points if point["has_data"]]
    if not rates:
        return CHART_FLOOR_MAX
    return min(CHART_FLOOR_MAX, math.floor(min(rates) - 1))


def chart_series(points: list[dict], floor: int) -> dict[str, list[dict]]:
    """Return the points of each `CHART_SERIES`, with their stems.

    A point's stem runs from the floor up to it; a run without a rate
    sits on the floor with none.
    """
    series: dict[str, list[dict]] = {key: [] for key, *_style in CHART_SERIES}
    for point in points:
        y = point["completeness_pct"] if point["has_data"] else floor
        series[_series_key(point)].append(
            {**point, "y": y, "stem": [round(y - floor, 1), 0]}
        )
    return series


def _series_key(point: dict) -> str:
    """Return the `CHART_SERIES` key a point is drawn in."""
    base = point["outcome"] if point["has_data"] else "no_data"
    return base if 1.0 == point["opacity"] else f"{base}_dim"


def chip_options(counts: dict, selected: str) -> list[dict]:
    """Return the outcome chips: All, Success, Verification failed, Failed."""
    labels = {ALL_OUTCOMES: "All", **OUTCOME_LABELS}
    return [
        {
            "value": outcome,
            "label": labels[outcome],
            "count": counts.get(outcome, 0),
            "is_selected": selected == outcome,
        }
        for outcome in CHIP_OUTCOMES
    ]


HISTORY_CSV_HEADER = (
    "Execution ID",
    "Execution date",
    "Start (UTC)",
    "End (UTC)",
    "Duration (s)",
    "Status",
    "Records extracted",
    "Completeness rate (%)",
)


def build_history_csv(rows: list[dict]) -> str:
    """Return the rows as CSV, numbers plain and missing values blank."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HISTORY_CSV_HEADER)
    writer.writerows(_csv_row(row) for row in rows)
    return buffer.getvalue()


def _csv_row(row: dict) -> list:
    """Return one run as the CSV's columns."""
    started, finished = row["started_at"], row["finished_at"]
    return [
        row["id"],
        (started or row["created_at"])[:10],
        _or_blank(started, _clock_time),
        _or_blank(finished, _clock_time),
        _or_blank(seconds_between(started, finished), int),
        row["outcome_label"],
        _or_blank((row["dataset"] or {}).get("row_count"), int),
        _or_blank(_completeness_rate(row), lambda rate: round(100 * rate, 1)),
    ]


def _or_blank(value: Any, convert) -> Any:
    """Return `convert(value)`, or `""` for a missing value."""
    return "" if value is None else convert(value)


def history_csv_filename(crawler_title: str) -> str:
    """Return a download name like `andorra-venues-history.csv`."""
    slug = re.sub(r"[^a-z0-9]+", "-", crawler_title.lower()).strip("-") or "crawler"
    return f"{slug}-history.csv"


def history_summary(summary: dict, now: datetime) -> dict:
    """Return the Execution history cards from the API's summary.

    `now` is the current time as naive UTC, like the API's timestamps:
    the last failures read relative to it.
    """
    streak = summary["consecutive_successful_runs"]
    rate = summary["success_rate"]
    completeness = summary["avg_completeness_rate"]
    verification_failure = split_time_ago(summary["last_verification_failure_at"], now)
    failure = split_time_ago(summary["last_failure_at"], now)
    return {
        "streak": str(streak),
        "streak_unit": "successful run" if 1 == streak else "successful runs",
        "verification_failure": verification_failure[0],
        "verification_failure_unit": verification_failure[1],
        "failure": failure[0],
        "failure_unit": failure[1],
        "success_rate": "—" if rate is None else f"{round(100 * rate)}%",
        "success_hint": (
            "no completeness yet"
            if completeness is None
            else f"avg completeness {100 * completeness:.1f}%"
        ),
    }


def time_ago(value: str | None, now: datetime) -> str:
    """Return how long before `now` an ISO timestamp was, or `—`.

    E.g. `just now`, `25 minutes ago`, `3 hours ago`, `yesterday`,
    `10 days ago`. A time after `now` (clock skew) reads `just now`.
    """
    if not value:
        return "—"
    seconds = int((now - datetime.fromisoformat(value)).total_seconds())
    if seconds < 60:
        return "just now"
    unit, size = _largest_unit(seconds)
    count = seconds // size
    return "yesterday" if ("day", 1) == (unit, count) else _ago(count, unit)


AGO_UNITS = (("day", 86400), ("hour", 3600), ("minute", 60))


def _largest_unit(seconds: int) -> tuple[str, int]:
    """Return the largest unit, and its seconds, that fits once."""
    return next((unit, size) for unit, size in AGO_UNITS if seconds >= size)


def _ago(count: int, unit: str) -> str:
    """Return e.g. `1 hour ago` or `3 hours ago`."""
    return f"{count} {unit}{'' if 1 == count else 's'} ago"


SECRET_KEY_PARTS = ("key", "token", "secret", "password")
"""Context keys holding one of these are masked, never rendered."""
MASKED_VALUE = "••••••"


def is_secret_key(key: str) -> bool:
    """Tell whether a Context key looks like it holds a credential."""
    return any(part in key.lower() for part in SECRET_KEY_PARTS)


def parse_context_value(text: str):
    """Return the value typed for a Context key.

    JSON when it parses (`3`, `true`, `null`, `["ad", "ca"]`), else the
    text itself as a string. The API checks the value's shape.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def context_rows(values: dict, harvested_keys: list[str] | None = None) -> list[dict]:
    """Return the Context as `{key, value_text, is_secret, is_harvested}`.

    Sorted by key. `value_text` is the value as JSON, or a mask for a
    secret key. `is_harvested` marks a key a selector sets: the API
    says the next run won't inherit it.
    """
    harvested = set(harvested_keys or ())
    return [
        {
            "key": key,
            "value_text": (
                MASKED_VALUE
                if is_secret_key(key)
                else json.dumps(values[key], ensure_ascii=False)
            ),
            "is_secret": is_secret_key(key),
            "is_harvested": key in harvested,
        }
        for key in sorted(values)
    ]


def has_csv(run: dict) -> bool:
    """Tell whether a run has a dataset CSV: only once it has ended.

    A cancelled run never reaches the end, so it has none.
    """
    return run["status"] in ("succeeded", "failed")


RATE_LIMIT_DEFAULTS = {
    "penalty_step_seconds": 0,
    "max_penalty_seconds": 0,
    "decay_after_successes": 1,
    "decay_step_seconds": 0,
}
"""A rule's numbers when left blank: the API's own defaults."""


def build_rate_limit_payload(form: dict) -> tuple[dict | None, str]:
    """Return a rate-limit body from the dialog, or an error.

    Blank numbers take `RATE_LIMIT_DEFAULTS`; the API checks the rest.
    """
    rule = form.get("rate_limit_string", "").strip()
    if not rule:
        return None, "Set the limit, e.g. 5/second or 50/minute."
    try:
        numbers = {
            name: _int_or_default(form.get(name, ""), default)
            for name, default in RATE_LIMIT_DEFAULTS.items()
        }
    except ValueError:
        return None, "Penalties and decay must be whole numbers."
    return {
        "name": blank_to_none(form.get("name")),
        "rate_limit_string": rule,
        **numbers,
    }, ""


def _int_or_default(text: str, default: int) -> int:
    """Return `text` as an int, or `default` when blank."""
    value = parse_optional_int(text)
    return default if value is None else value


def rate_limit_summary(rule: dict) -> str:
    """Return e.g. `+10 s per block, up to 60 s; −5 s after 3 successes`."""
    if not rule.get("penalty_step_seconds"):
        return "no penalty"
    penalty = (
        f"+{rule['penalty_step_seconds']} s per block, "
        f"up to {rule['max_penalty_seconds']} s"
    )
    return f"{penalty}; {_decay_summary(rule)}"


def _decay_summary(rule: dict) -> str:
    """Return e.g. `−5 s after 3 successes`, or `no decay`."""
    if not rule.get("decay_step_seconds"):
        return "no decay"
    successes = rule["decay_after_successes"]
    noun = "success" if 1 == successes else "successes"
    return f"−{rule['decay_step_seconds']} s after {successes} {noun}"


def url_host(url: str) -> str:
    """Return a template URL's host, lower-cased, or blank.

    Blank when there is none or it is a placeholder (`{{host}}`), since
    such a template has no fixed domain to rate-limit.
    """
    try:
        host = urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
    return "" if "{" in host or "}" in host else host


def find_rate_limit_for_host(rules: list[dict], host: str) -> str:
    """Return the id of the rule named after `host`, or blank.

    A rule's name holds the domain it is for, compared in any case.
    """
    if not host:
        return ""
    return next(
        (
            rule["id"]
            for rule in rules
            if host == (rule.get("name") or "").strip().lower()
        ),
        "",
    )


def instructions_filename(crawler_title: str, status: str) -> str:
    """Return a download name like `andorra-venues-draft-instructions.yaml`."""
    slug = re.sub(r"[^a-z0-9]+", "-", crawler_title.lower()).strip("-") or "crawler"
    return f"{slug}-{status}-instructions.yaml"


def decode_instructions_file(data: bytes) -> tuple[str | None, str]:
    """Return an uploaded instructions file as text, or an error.

    A UTF-8 byte order mark, which some editors write, is dropped.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "The file must be UTF-8 YAML text."
    if not text.strip():
        return None, "The file is empty."
    return text, ""


GENERATION_PROMPT_MAX_CHARS = 4000
"""The longest prompt the API takes for an Instruction Generation."""

ENDED_STATUSES = ("succeeded", "failed", "cancelled")
"""The statuses a generation or a run never leaves."""


def build_generation_payload(form: dict) -> tuple[dict | None, str]:
    """Return the Instruction Generation body from the dialog's prompt."""
    prompt = (form.get("prompt") or "").strip()
    if not prompt:
        return None, "Describe what the crawler should get."
    if GENERATION_PROMPT_MAX_CHARS < len(prompt):
        return None, (
            f"Keep the prompt to {GENERATION_PROMPT_MAX_CHARS} characters "
            f"(it has {len(prompt)})."
        )
    return {"prompt": prompt}, ""


def has_ended(record: dict) -> bool:
    """Tell whether a generation or a run has reached its last status."""
    return record.get("status") in ENDED_STATUSES


def generation_status_text(generation: dict, execution: dict | None) -> str:
    """Return the generation dialog's one-line status.

    It reads the API's fields only: the generation's status and the
    fields it has saved so far, then its test run's status and rows.
    """
    status = generation.get("status")
    if "failed" == status:
        return f"Failed: {generation.get('error') or 'unknown error'}"
    if "succeeded" == status:
        return _test_run_text(generation, execution)
    if "running" == status:
        return _running_text(generation)
    return "Waiting for a worker…"


def _running_text(generation: dict) -> str:
    """Name the step a running generation is on, from what it saved."""
    if generation.get("result_version_id"):
        return "Starting the test run…"
    if generation.get("filtered_requests"):
        return "Writing instructions…"
    return "Recording the browser session…"


def _test_run_text(generation: dict, execution: dict | None) -> str:
    """Describe a succeeded generation's test run, as far as known."""
    if not generation.get("test_execution_id"):
        return "Instructions written."
    if None is execution:
        return "Test run pending…"
    if not has_ended(execution):
        return f"Test run {execution['status']}…"
    validation = execution.get("validation")
    if not validation:
        return f"Test run {execution['status']}"
    return f"Test run {execution['status']}: {validation['rows_checked']} rows"


USER_ROLES = ("user", "admin", "viewer")


def build_user_payload(
    form: dict, role: str, *, is_new: bool
) -> tuple[dict | None, str]:
    """Return a user body from the dialog, or an error.

    A new account takes an email and a temporary password (Keycloak asks
    the user for a new one at their first login); the API starts it as
    `user`, so `role` is only sent on edits. An edit keeps the password
    unless one is typed, also temporary. The API checks the email and
    password rules.
    """
    email = form.get("email", "").strip()
    password = form.get("password", "")
    if not email:
        return None, "Set the email."
    if is_new:
        if not password.strip():
            return None, "Set a temporary password."
        return {"email": email, "password": password}, ""
    payload = {"email": email, "role": role}
    if password.strip():
        payload["password"] = password
    return payload, ""
