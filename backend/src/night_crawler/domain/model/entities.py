"""Framework-agnostic domain entities.

No FastAPI, Pydantic, or PyMongo here, so the domain works the same
behind HTTP, a queue worker, or any storage. See `docs/DOMAIN_MODEL.md`
for the full model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from night_crawler.domain.model.constants import (
    DEFAULT_EXECUTION_QUEUE,
    DEFAULT_RENDER_MODE,
    DEFAULT_SELECTOR_SOURCE,
)
from night_crawler.domain.model.value_objects import DatasetField


@dataclass
class User:
    """A registered account.

    `hashed_password` never leaves the domain and auth service; it is
    not mapped onto any API schema. `role` is `admin`, `user`, or
    `viewer`.
    """

    id: str
    email: str
    hashed_password: str
    created_at: datetime
    role: str = "user"


@dataclass
class Source:
    """A website the crawled data comes from, e.g. TheFork.

    Every Crawler is linked to exactly one; the dataset import keys
    records on it plus the item's own `item_id`, so the same ID on two
    websites never merges.
    """

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    url: str | None = None


@dataclass
class Dataset:
    """What a Crawler downloads, field by field, and how it is keyed.

    Many Crawlers can share one Dataset, each from its own Source, so
    a Dataset is fed by any number of Sources and a Source feeds any
    number of Datasets; a Crawler pairs exactly one of each.

    Attributes:
        name: Unique, e.g. `venues`.
        fields: The fields a Crawler schema picks from, in CSV order,
            each with its type, pattern, and whether it is required or
            unique. `item_id` is always required and unique; a
            Crawler's selectors harvest it like any other field.
    """

    id: str
    name: str
    fields: list[DatasetField]
    created_at: datetime
    updated_at: datetime


@dataclass
class Crawler:
    """A named crawl definition for one source and one dataset.

    Attributes:
        user_id: The creator; Crawlers are shared, not access-scoped.
        title: Display name.
        source_id: The Source its datasets come from.
        dataset_id: The Dataset its CSVs hold.
        fields: Which of its Dataset's fields each execution
            downloads, in CSV order.
        schedule: 5-field cron expression, or `None` for manual runs
            only.
        created_at: Creation time (naive UTC).
        updated_at: Last change (naive UTC).
        queue: The Celery queue every run of this Crawler goes to.
    """

    id: str
    user_id: str
    title: str
    source_id: str
    dataset_id: str
    fields: list[str]
    schedule: str | None
    created_at: datetime
    updated_at: datetime
    queue: str = DEFAULT_EXECUTION_QUEUE


@dataclass
class CrawlerVersion:
    """A snapshot of a Crawler's template tree.

    `status` is `draft`, `published`, or `archived`, and only the
    service layer changes it. Request settings (proxy, codes, retry
    budgets) live on each template's Message Aid, not here.

    Attributes:
        crawler_id: The owning Crawler.
        user_id: Whoever created this draft; never changes afterwards.
        status: Lifecycle status.
        message_template_root_id: The tree's root template.
        published_at: When it was published, if ever.
        created_at: Creation time (naive UTC).
        updated_at: Last change (naive UTC).
        is_proxy_ladder_enabled: Add the direct and cookie-harvest steps
            before IP rotation on a blocked dispatch.
        is_host_session_sharing_enabled: Let later templates reuse
            cookies, User-Agent, and proxy captured for the same host.
    """

    id: str
    crawler_id: str
    user_id: str
    status: str
    message_template_root_id: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_proxy_ladder_enabled: bool = False
    is_host_session_sharing_enabled: bool = True


@dataclass
class MessageTemplate:
    """One outbound request node in a Crawler Version's tree."""

    id: str
    crawler_version_id: str
    action: str
    url: str
    body: str | None
    headers: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class MessageSelector:
    """An extraction rule attached to a template.

    Attributes:
        message_template_id: The owning template.
        parent_selector_id: The parent selector, or `None` at top level.
        path: XPath (HTML) or JMESPath (JSON) expression.
        type: `value`, `iterator`, `boolean`, `click`, `select`, or
            `pagination`.
        target: `__text` for the element's text, or an attribute name.
        created_at: Creation time (naive UTC).
        updated_at: Last change (naive UTC).
        title: The name the harvested value is stored under: a Context
            key or a CSV field.
        config: A `pagination` selector's settings; `None` for other
            types.
        source: What the path reads: `content` (XPath or CSS for HTML,
            JMESPath for JSON), `headers` or `url` (a regex whose
            capture group is the value).
    """

    id: str
    message_template_id: str
    parent_selector_id: str | None
    path: str
    type: str
    target: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    config: dict[str, Any] | None = None
    source: str = DEFAULT_SELECTOR_SOURCE


@dataclass
class MessageAidProxy:
    """A pooled proxy credential; its password is never returned."""

    id: str
    url: str
    user: str | None
    password: str
    headers: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    rate_limit_id: str | None = None


@dataclass
class MessageAidRateLimit:
    """An admin-managed, reusable rate-limit rule.

    Referenced per domain by Message Aids and per proxy by proxies. Only
    the configuration lives here; live window and penalty state is in
    Redis.
    """

    id: str
    rate_limit_string: str
    penalty_step_seconds: int
    max_penalty_seconds: int
    decay_after_successes: int
    decay_step_seconds: int
    created_at: datetime
    updated_at: datetime
    name: str | None = None


@dataclass
class MessageAid:
    """A template's execution settings; at most one per template.

    Every `None` falls back to a global default in `constants.py`;
    `success_codes` left `None` means any status below 400 succeeds.
    """

    id: str
    message_template_id: str
    created_at: datetime
    updated_at: datetime
    selected_proxy_id: str | None = None
    render_mode: str = DEFAULT_RENDER_MODE
    ttl: int | None = None
    retry_codes: list[str] | None = None
    success_codes: list[str] | None = None
    max_retry_attempts: int | None = None
    rate_limit_id: str | None = None


def _empty_execution_metrics() -> dict[str, int]:
    """Return a fresh, all-zero execution metrics mapping."""
    return {
        "request_count": 0,
        "error_count": 0,
        "retry_count": 0,
        "records_skipped": 0,
    }


@dataclass
class CrawlerExecution:
    """One run of a Crawler Version.

    Attributes:
        crawler_id: The Crawler run.
        crawler_version_id: The exact version run; it can't be deleted
            while this exists.
        status: `pending`, `running`, `succeeded`, `failed`, or
            `cancelled`.
        parsing_status: `pending`, `parsing`, `parsed`, or `failed`.
        queue: The queue actually dispatched to.
        started_at: When a worker picked it up.
        finished_at: When it reached a terminal status.
        created_at: Creation time (naive UTC).
        updated_at: Last change (naive UTC).
        resume_count: Times it resumed from its checkpoint.
        metrics: Run counters (`request_count`, `error_count`,
            `retry_count`, `records_skipped`).
    """

    id: str
    crawler_id: str
    crawler_version_id: str
    status: str
    parsing_status: str
    queue: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    resume_count: int = 0
    metrics: dict[str, int] = field(default_factory=_empty_execution_metrics)


@dataclass
class CrawlerExecutionContext:
    """One Context key/value of a Crawler Execution.

    Harvested during the run, inherited from the Crawler's previous
    run, or supplied by a user. Values are primitives. A key without
    `[]` has one entry per run; a `name[]` key has one entry per list
    element, ordered by `position`. Keys starting with `_` are written
    by the system only.

    Attributes:
        crawler_execution_id: The run it belongs to.
        key: The Context name.
        value: A primitive: string, number, boolean, or `None`.
        created_at: Creation time (naive UTC).
        updated_at: Last change (naive UTC).
        active_value: Iterator element in flight; the resume point.
    """

    id: str
    crawler_execution_id: str
    key: str
    value: Any
    created_at: datetime
    updated_at: datetime
    active_value: Any = None
    position: int | None = None


def _empty_import_metrics() -> dict[str, int]:
    """Return fresh, all-zero dataset import counters."""
    return {
        "records_inserted": 0,
        "records_updated": 0,
        "records_unchanged": 0,
        "rows_rejected": 0,
    }


@dataclass
class CrawlerExecutionDataset:
    """The CSV one Crawler Execution produced, and its import state.

    Attributes:
        crawler_execution_id: The run; at most one dataset per run.
        fields: The CSV columns, in order.
        csv_content: The whole CSV, header included.
        row_count: Rows, header excluded.
        created_at: Creation time (naive UTC).
        updated_at: Last change (naive UTC).
        file_path: The exported copy, or `None` without export storage.
        import_status: `pending`, `importing`, `imported`, or `failed`.
        imported_at: When the import finished.
        import_error: Why the last import failed.
        import_metrics: Import counters.
        validation: What validating the rows found (a
            `DatasetValidation`, as a dict), or `None` before it ran.
    """

    id: str
    crawler_execution_id: str
    fields: list[str]
    csv_content: str
    row_count: int
    created_at: datetime
    updated_at: datetime
    file_path: str | None = None
    import_status: str = "pending"
    imported_at: datetime | None = None
    import_error: str | None = None
    import_metrics: dict[str, int] = field(default_factory=_empty_import_metrics)
    validation: dict[str, Any] | None = None
