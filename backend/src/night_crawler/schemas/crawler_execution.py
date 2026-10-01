"""Response models for Crawler Executions."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
"""Mirrors the domain's `EXECUTION_STATUSES`."""

ParsingStatus = Literal["pending", "parsing", "parsed", "failed"]
"""Mirrors the domain's `PARSING_STATUSES`."""

ExecutionQueue = Literal["discovery", "priority", "real-time", "testing"]
"""Mirrors the domain's `EXECUTION_QUEUES`."""


class CrawlerExecutionMetricsOut(BaseModel):
    """A run's counters (DOMAIN_MODEL §4.9)."""

    request_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    records_skipped: int = 0


class CrawlerExecutionValidationOut(BaseModel):
    """What validating a run's dataset rows found (DOMAIN_MODEL §5.4).

    Parsing is `parsed` only when `is_valid`.
    """

    rows_checked: int
    rows_dropped_missing_required: int
    rows_dropped_duplicate: int
    type_mismatches: dict[str, int]
    pattern_mismatches: dict[str, int]
    empty_columns: list[str]
    is_valid: bool


class CrawlerExecutionCreate(BaseModel):
    """Optional body for starting a run.

    `context` seeds the run's Context, e.g. `{"parish[]": [...]}` for a
    template to fan out over, or an API key a template header uses.
    Keys starting with `_` are reserved; `[]` keys take lists.
    """

    context: dict[str, Any] = {}


class CrawlerExecutionOut(BaseModel):
    """A Crawler Execution as returned by the API.

    Only the Context keys are returned, never the values: a seeded
    value may be a secret such as an API key. The status belongs to
    the worker.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    crawler_id: str
    crawler_title: str
    crawler_version_id: str
    status: str
    parsing_status: str
    queue: str
    started_at: datetime | None
    finished_at: datetime | None
    resume_count: int
    metrics: CrawlerExecutionMetricsOut
    context_keys: list[str]
    created_at: datetime
    updated_at: datetime
    validation: CrawlerExecutionValidationOut | None = None


class CrawlerExecutionQuery(BaseModel):
    """Filters and page for every Crawler's runs.

    `crawler_title` keeps runs whose Crawler's title contains it, in any
    case. With a filter the listing is one capped page and
    `limit`/`offset` are ignored; without one it paginates.
    """

    status: ExecutionStatus | None = None
    parsing_status: ParsingStatus | None = None
    queue: ExecutionQueue | None = None
    crawler_title: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=50, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=250)


class CrawlerExecutionsPageOut(BaseModel):
    """One page of runs across every Crawler, newest first.

    `has_more` follows the pagination cap, so it is `False` at the cap
    even if more runs exist. A filtered page never has a next page:
    `has_more` then means the cap cut the result short.
    """

    items: list[CrawlerExecutionOut]
    limit: int
    offset: int
    has_more: bool


class CrawlerExecutionCsvOut(BaseModel):
    """A run's dataset CSV and the file name to download it as."""

    filename: str
    csv_content: str
