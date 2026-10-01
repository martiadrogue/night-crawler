"""Repository ports: one abstract storage interface per entity.

Every implementation converts storage errors before they leave it: a
broken natural key or unique reference raises `ValidationException`
(409), a document the storage validator rejects raises
`ValidationException` (400), and any other storage failure raises
`ExternalServiceException` (503).
"""

from abc import ABC, abstractmethod
from typing import Any

from night_crawler.domain.model.entities import (
    Crawler,
    CrawlerExecution,
    CrawlerExecutionContext,
    CrawlerExecutionDataset,
    CrawlerVersion,
    Dataset,
    MessageAid,
    MessageAidProxy,
    MessageAidRateLimit,
    MessageSelector,
    MessageTemplate,
    Source,
    User,
)


class AbstractUserRepository(ABC):
    """Storage for user accounts."""

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this email, if any."""

    @abstractmethod
    async def get_by_id(self, user_id: str) -> User | None:
        """Return the user with this id, if any."""

    @abstractmethod
    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[User]:
        """Return users, newest first.

        Args:
            limit: Maximum users to return; `None` returns them all.
            offset: Users to skip first.
        """

    @abstractmethod
    async def count_by_role(self, role: str) -> int:
        """Return how many users hold `role`."""

    @abstractmethod
    async def save(self, user: User) -> User:
        """Insert or update a user; return a fresh copy.

        Raises:
            ValidationException: the email is already taken (409).
        """

    @abstractmethod
    async def delete(self, user_id: str) -> None:
        """Delete a user, if present."""


class AbstractCrawlerRepository(ABC):
    """Storage for Crawlers."""

    @abstractmethod
    async def get_by_id(self, crawler_id: str) -> Crawler | None:
        """Return the Crawler with this id, if any."""

    @abstractmethod
    async def get_all_by_title_containing(self, text: str) -> list[Crawler]:
        """Return the Crawlers whose title contains `text`, any case.

        `text` is matched literally, not as a pattern.
        """

    @abstractmethod
    async def get_all_by_ids(self, crawler_ids: list[str]) -> list[Crawler]:
        """Return the Crawlers with these ids, skipping missing ones."""

    @abstractmethod
    async def get_all(
        self,
        source_id: str | None = None,
        dataset_id: str | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
        limit: int | None = None,
    ) -> list[Crawler]:
        """Return Crawlers, filtered and sorted.

        Args:
            source_id: Keep only Crawlers linked to this Source.
            dataset_id: Keep only Crawlers linked to this Dataset.
            sort_by: `created_at` or `updated_at`.
            order: `asc` or `desc`.
            limit: Maximum Crawlers to return; `None` returns them all.
        """

    @abstractmethod
    async def get_all_by_user_id(self, user_id: str) -> list[Crawler]:
        """Return every Crawler a user created."""

    @abstractmethod
    async def has_any_by_source_id(self, source_id: str) -> bool:
        """Tell whether any Crawler is linked to this Source."""

    @abstractmethod
    async def get_all_by_dataset_id(self, dataset_id: str) -> list[Crawler]:
        """Return every Crawler linked to this Dataset."""

    @abstractmethod
    async def save(self, crawler: Crawler) -> Crawler:
        """Insert or update a Crawler; return a fresh copy."""

    @abstractmethod
    async def delete(self, crawler_id: str) -> None:
        """Delete a Crawler document only; children are the caller's."""


class AbstractCrawlerVersionRepository(ABC):
    """Storage for Crawler Versions."""

    @abstractmethod
    async def get_by_id(self, version_id: str) -> CrawlerVersion | None:
        """Return the version with this id, if any."""

    @abstractmethod
    async def get_all_by_crawler_id(self, crawler_id: str) -> list[CrawlerVersion]:
        """Return a Crawler's versions, oldest first."""

    @abstractmethod
    async def get_all_by_user_id(self, user_id: str) -> list[CrawlerVersion]:
        """Return every version a user owns."""

    @abstractmethod
    async def get_published_by_crawler_id(
        self, crawler_id: str
    ) -> CrawlerVersion | None:
        """Return the Crawler's published version, if any."""

    @abstractmethod
    async def get_draft_by_crawler_id(self, crawler_id: str) -> CrawlerVersion | None:
        """Return the Crawler's open draft, if any."""

    @abstractmethod
    async def save(self, version: CrawlerVersion) -> CrawlerVersion:
        """Insert or update a version; return a fresh copy.

        Raises:
            ValidationException: a second draft or published version
                (409).
        """

    @abstractmethod
    async def delete(self, version_id: str) -> None:
        """Delete a version document only; its tree is the caller's."""


class AbstractMessageTemplateRepository(ABC):
    """Storage for Message Templates."""

    @abstractmethod
    async def get_by_id(self, template_id: str) -> MessageTemplate | None:
        """Return the template with this id, if any."""

    @abstractmethod
    async def get_all_by_crawler_version_id(
        self, version_id: str
    ) -> list[MessageTemplate]:
        """Return a version's templates, oldest first."""

    @abstractmethod
    async def save(self, template: MessageTemplate) -> MessageTemplate:
        """Insert or update a template; return a fresh copy."""

    @abstractmethod
    async def delete(self, template_id: str) -> None:
        """Delete a template document; children are the caller's."""


class AbstractMessageSelectorRepository(ABC):
    """Storage for Message Selectors."""

    @abstractmethod
    async def get_by_id(self, selector_id: str) -> MessageSelector | None:
        """Return the selector with this id, if any."""

    @abstractmethod
    async def get_all_by_message_template_id(
        self, template_id: str
    ) -> list[MessageSelector]:
        """Return a template's selectors, oldest first."""

    @abstractmethod
    async def save(self, selector: MessageSelector) -> MessageSelector:
        """Insert or update a selector; return a fresh copy."""

    @abstractmethod
    async def delete_all(self, selector_ids: list[str]) -> None:
        """Delete these selectors."""

    @abstractmethod
    async def delete_by_message_template_id(self, template_id: str) -> None:
        """Delete every selector of a template."""


class AbstractMessageAidRepository(ABC):
    """Storage for Message Aids, at most one per template."""

    @abstractmethod
    async def get_by_message_template_id(self, template_id: str) -> MessageAid | None:
        """Return the template's aid, if any."""

    @abstractmethod
    async def save(self, aid: MessageAid) -> MessageAid:
        """Insert or update an aid; return a fresh copy.

        Raises:
            ValidationException: the template already has another aid
                (409).
        """

    @abstractmethod
    async def delete_by_message_template_id(self, template_id: str) -> None:
        """Delete the template's aid, if any."""

    @abstractmethod
    async def clear_selected_proxy_id(self, proxy_id: str) -> None:
        """Set `selected_proxy_id` to `None` where it is `proxy_id`."""

    @abstractmethod
    async def clear_rate_limit_id(self, rate_limit_id: str) -> None:
        """Null every `rate_limit_id` equal to `rate_limit_id`."""


class AbstractMessageAidProxyRepository(ABC):
    """Storage for the proxy pool."""

    @abstractmethod
    async def get_by_id(self, proxy_id: str) -> MessageAidProxy | None:
        """Return the proxy with this id, if any."""

    @abstractmethod
    async def get_all(self) -> list[MessageAidProxy]:
        """Return every proxy, newest first."""

    @abstractmethod
    async def save(self, proxy: MessageAidProxy) -> MessageAidProxy:
        """Insert or update a proxy; return a fresh copy."""

    @abstractmethod
    async def delete(self, proxy_id: str) -> None:
        """Delete a proxy document only; references are the caller's."""

    @abstractmethod
    async def clear_rate_limit_id(self, rate_limit_id: str) -> None:
        """Null every `rate_limit_id` equal to `rate_limit_id`."""


class AbstractDatasetRepository(ABC):
    """Storage for Datasets."""

    @abstractmethod
    async def get_by_id(self, dataset_id: str) -> Dataset | None:
        """Return the Dataset with this id, if any."""

    @abstractmethod
    async def get_by_name(self, name: str) -> Dataset | None:
        """Return the Dataset with this name, if any."""

    @abstractmethod
    async def get_all(self) -> list[Dataset]:
        """Return every Dataset, by name."""

    @abstractmethod
    async def save(self, dataset: Dataset) -> Dataset:
        """Insert or update a Dataset; return a fresh copy.

        Raises:
            ValidationException: another Dataset has this name (409).
        """

    @abstractmethod
    async def delete(self, dataset_id: str) -> None:
        """Delete a Dataset document only; crawlers are the caller's."""


class AbstractSourceRepository(ABC):
    """Storage for Sources."""

    @abstractmethod
    async def get_by_id(self, source_id: str) -> Source | None:
        """Return the Source with this id, if any."""

    @abstractmethod
    async def get_all(self) -> list[Source]:
        """Return every Source, by name."""

    @abstractmethod
    async def save(self, source: Source) -> Source:
        """Insert or update a Source; return a fresh copy.

        Raises:
            ValidationException: another Source has this name (409).
        """

    @abstractmethod
    async def delete(self, source_id: str) -> None:
        """Delete a Source document only; crawlers are the caller's."""


class AbstractMessageAidRateLimitRepository(ABC):
    """Storage for rate-limit rules."""

    @abstractmethod
    async def get_by_id(self, rate_limit_id: str) -> MessageAidRateLimit | None:
        """Return the rule with this id, if any."""

    @abstractmethod
    async def get_all(self) -> list[MessageAidRateLimit]:
        """Return every rule, newest first."""

    @abstractmethod
    async def save(self, rate_limit: MessageAidRateLimit) -> MessageAidRateLimit:
        """Insert or update a rule; return a fresh copy.

        Raises:
            ValidationException: `rate_limit_string` is not valid
                `limits` syntax, e.g. `"100/minute"` (400).
        """

    @abstractmethod
    async def delete(self, rate_limit_id: str) -> None:
        """Delete a rule document only; references are the caller's."""


class AbstractCrawlerExecutionRepository(ABC):
    """Storage for Crawler Executions."""

    @abstractmethod
    async def get_by_id(self, execution_id: str) -> CrawlerExecution | None:
        """Return the execution with this id, if any."""

    @abstractmethod
    async def get_all_by_crawler_id(
        self,
        crawler_id: str,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[CrawlerExecution]:
        """Return a Crawler's executions, newest first.

        Args:
            crawler_id: The Crawler whose runs to return.
            status: Keep only executions in this status.
            limit: Maximum executions to return; `None` returns all.
        """

    @abstractmethod
    async def get_all(
        self,
        status: str | None = None,
        parsing_status: str | None = None,
        queue: str | None = None,
        crawler_ids: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CrawlerExecution]:
        """Return every Crawler's executions, newest first.

        Args:
            status: Keep only executions in this status.
            parsing_status: Keep only executions in this parsing status.
            queue: Keep only executions sent to this queue.
            crawler_ids: Keep only these Crawlers' executions; `None`
                keeps every Crawler's.
            limit: Maximum executions to return; `None` returns all.
            offset: How many matching executions to skip first.
        """

    @abstractmethod
    async def get_latest_by_crawler_id(
        self, crawler_id: str
    ) -> CrawlerExecution | None:
        """Return the Crawler's most recent run, if any.

        Test runs (`TESTING_QUEUE`) are skipped: they never become the
        Context later runs inherit.
        """

    @abstractmethod
    async def has_any_by_crawler_version_id(self, version_id: str) -> bool:
        """Tell whether any execution ran this version."""

    @abstractmethod
    async def save(self, execution: CrawlerExecution) -> CrawlerExecution:
        """Insert or update an execution; return a fresh copy."""

    @abstractmethod
    async def delete_by_crawler_id(self, crawler_id: str) -> None:
        """Delete every execution of a Crawler."""


class AbstractCrawlerExecutionContextRepository(ABC):
    """Storage for Crawler Execution Context entries."""

    @abstractmethod
    async def get_all_by_crawler_execution_ids(
        self, execution_ids: list[str]
    ) -> list[CrawlerExecutionContext]:
        """Return the Context entries of these executions."""

    @abstractmethod
    async def save_all(
        self, contexts: list[CrawlerExecutionContext]
    ) -> list[CrawlerExecutionContext]:
        """Insert or update entries; return fresh copies.

        Raises:
            ValidationException: a scalar key, or a list key's position,
                repeats within an execution (409).
        """

    @abstractmethod
    async def delete_by_crawler_execution_id_and_key(
        self, execution_id: str, key: str
    ) -> None:
        """Delete every entry of one key in one execution."""

    @abstractmethod
    async def delete_by_crawler_execution_ids(self, execution_ids: list[str]) -> None:
        """Delete every Context entry of these executions."""


class AbstractCrawlerExecutionDatasetRepository(ABC):
    """Storage for the CSV each Crawler Execution produced."""

    @abstractmethod
    async def get_by_crawler_execution_id(
        self, execution_id: str
    ) -> CrawlerExecutionDataset | None:
        """Return the execution's dataset, if it has one."""

    @abstractmethod
    async def get_validations_by_crawler_execution_ids(
        self, execution_ids: list[str]
    ) -> dict[str, dict[str, Any] | None]:
        """Return each execution's validation report, without its CSV.

        Executions with no dataset yet are left out.
        """

    @abstractmethod
    async def save(self, dataset: CrawlerExecutionDataset) -> CrawlerExecutionDataset:
        """Insert or update a dataset; return a fresh copy.

        Raises:
            ValidationException: the execution already has another
                dataset (409).
        """

    @abstractmethod
    async def delete_by_crawler_execution_ids(self, execution_ids: list[str]) -> None:
        """Delete the datasets of these executions."""
