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

RunOutcome = Literal["success", "verification_failed", "failed", "in_progress"]
"""Mirrors the domain's `RUN_OUTCOMES`."""


class CrawlerExecutionMetricsOut(BaseModel):
    """A run's counters (DOMAIN_MODEL §4.9)."""

    request_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    records_skipped: int = 0


class CrawlerExecutionValidationOut(BaseModel):
    """What validating a run's dataset rows found (DOMAIN_MODEL §5.4).

    Parsing is `parsed` only when `is_valid`. `completeness_rate` is
    `None` for reports saved before it existed.
    """

    rows_checked: int
    rows_dropped_missing_required: int
    rows_dropped_duplicate: int
    type_mismatches: dict[str, int]
    pattern_mismatches: dict[str, int]
    empty_columns: list[str]
    is_valid: bool
    completeness_rate: float | None = None


class CrawlerExecutionImportMetricsOut(BaseModel):
    """A run dataset's import counters (DOMAIN_MODEL §4.12)."""

    records_inserted: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    rows_rejected: int = 0


class CrawlerExecutionDatasetOut(BaseModel):
    """What a run's dataset holds: rows extracted and rows imported."""

    row_count: int
    import_metrics: CrawlerExecutionImportMetricsOut


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
    outcome: RunOutcome
    queue: str
    started_at: datetime | None
    finished_at: datetime | None
    resume_count: int
    metrics: CrawlerExecutionMetricsOut
    context_keys: list[str]
    created_at: datetime
    updated_at: datetime
    validation: CrawlerExecutionValidationOut | None = None
    dataset: CrawlerExecutionDatasetOut | None = None


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


class CrawlerExecutionHistoryQuery(BaseModel):
    """Filters and page for one Crawler's runs.

    Without `queue` it covers every queue but `testing`, so test runs
    of the Crawler's versions stay out. It paginates even when
    filtered, within the same bounds as every Crawler's runs.
    """

    status: ExecutionStatus | None = None
    queue: ExecutionQueue | None = None
    limit: int = Field(default=50, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=250)


class CrawlerExecutionSummaryOut(BaseModel):
    """One Crawler's run history in numbers (DOMAIN_MODEL §4.9).

    A run is successful when it `succeeded` and its dataset is
    `parsed`. Pending and running runs never count. Without a queue,
    test runs are left out.

    Attributes:
        consecutive_successful_runs: Successful runs since the newest
            other ended run, over the whole history.
        avg_completion_seconds: Mean duration of the last 30
            successful runs; `None` without any.
        success_rate: Share of the last 30 ended runs that were
            successful, 0 to 1; `None` before any run ended.
        recent_run_count: Ended runs `success_rate` covers (≤ 30).
        last_success_at: When the newest successful run finished.
        last_verification_failure_at: When the newest run that
            succeeded without being parsed finished.
        last_failure_at: When the newest failed or cancelled run
            finished.
        avg_completeness_rate: Mean completeness rate of the last 30
            successful runs that have one, 0 to 1.
    """

    consecutive_successful_runs: int
    avg_completion_seconds: float | None
    success_rate: float | None
    recent_run_count: int
    last_success_at: datetime | None
    last_verification_failure_at: datetime | None
    last_failure_at: datetime | None
    avg_completeness_rate: float | None


class CrawlerExecutionWindowQuery(BaseModel):
    """The window of one Crawler's runs: the last `days` days.

    Without `queue` it covers every queue but `testing`.
    """

    days: int = Field(default=30, ge=1, le=90)
    queue: ExecutionQueue | None = None


class CrawlerExecutionOutcomeCountsOut(BaseModel):
    """How many runs of a window came to each outcome."""

    all: int
    success: int
    verification_failed: int
    failed: int
    in_progress: int


class CrawlerExecutionHistoryOut(BaseModel):
    """One Crawler's runs created in a window, newest first.

    `runs` stops at the cap (`is_truncated`); `counts` covers every run
    of the window. Window bounds are naive UTC.
    """

    runs: list[CrawlerExecutionOut]
    counts: CrawlerExecutionOutcomeCountsOut
    is_truncated: bool
    window_start: datetime
    window_end: datetime


class CrawlerExecutionsPageOut(BaseModel):
    """One page of runs, newest first: every Crawler's, or one's.

    `has_more` follows the pagination cap, so it is `False` at the cap
    even if more runs exist. A filtered page of every Crawler's runs
    never has a next page: `has_more` then means the cap cut the
    result short. One Crawler's runs page even when filtered.
    """

    items: list[CrawlerExecutionOut]
    limit: int
    offset: int
    has_more: bool


class CrawlerExecutionCsvOut(BaseModel):
    """A run's dataset CSV and the file name to download it as."""

    filename: str
    csv_content: str
