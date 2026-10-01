"""Value objects describing what a run executes and what it produced."""

from dataclasses import dataclass, field
from typing import Any

from night_crawler.domain.model.entities import (
    Crawler,
    CrawlerExecution,
    CrawlerVersion,
    Dataset,
    MessageAid,
    MessageAidProxy,
    MessageAidRateLimit,
    MessageSelector,
    MessageTemplate,
)
from night_crawler.domain.model.value_objects import RenderedRequest, SessionState


@dataclass(frozen=True)
class ScheduledCrawler:
    """An active, scheduled Crawler with its published version."""

    crawler: Crawler
    published_version: CrawlerVersion


@dataclass(frozen=True)
class ExecutionPlan:
    """One execution's templates in run order, with what they need.

    Attributes:
        execution: The run.
        crawler: Its Crawler (for its fields).
        version: The version it runs.
        dataset: The Crawler's Dataset (its required fields).
        ordered_templates: Templates in dependency order.
        selectors_by_template_id: Each template's selectors.
        aids_by_template_id: Each template's Message Aid, if any.
        proxies_by_id: The proxies the aids select.
        context: The Context the run starts from (seeded values).
        rate_limits_by_id: The rate limits the aids and proxies use.
    """

    execution: CrawlerExecution
    crawler: Crawler
    version: CrawlerVersion
    dataset: Dataset
    ordered_templates: list[MessageTemplate]
    selectors_by_template_id: dict[str, list[MessageSelector]]
    aids_by_template_id: dict[str, MessageAid]
    proxies_by_id: dict[str, MessageAidProxy]
    context: dict[str, Any]
    rate_limits_by_id: dict[str, MessageAidRateLimit] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateRun:
    """One fan-out run of one template."""

    template: MessageTemplate
    rendered: RenderedRequest


@dataclass(frozen=True)
class RunOutcome:
    """Where a run stands; the final one is what gets saved.

    Attributes:
        context: The Context so far, seeded and harvested values.
        sessions: Shared cookies and headers per exact host.
        request_count: Requests sent.
        error_count: Requests that failed for good, after their
            retries.
        retry_count: Retries sent, on top of `request_count`.
        failure: Why the run failed, or `None`.
        harvested_keys: Context keys this run has harvested so far.
        dataset_rows: The rows for the dataset CSV.
    """

    context: dict[str, Any]
    sessions: dict[str, SessionState] = field(default_factory=dict)
    request_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    failure: str | None = None
    harvested_keys: frozenset[str] = frozenset()
    dataset_rows: list[dict[str, Any]] = field(default_factory=list)
