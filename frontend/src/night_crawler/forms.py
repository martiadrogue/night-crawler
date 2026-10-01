"""Pure helpers turning form input into API payloads, and back.

No Reflex and no I/O here, so every rule is unit-testable.
"""

import json
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


def context_rows(values: dict) -> list[dict]:
    """Return the Context as `{key, value_text, is_secret}`, by key.

    `value_text` is the value as JSON, or a mask for a secret key.
    """
    return [
        {
            "key": key,
            "value_text": (
                MASKED_VALUE
                if is_secret_key(key)
                else json.dumps(values[key], ensure_ascii=False)
            ),
            "is_secret": is_secret_key(key),
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
