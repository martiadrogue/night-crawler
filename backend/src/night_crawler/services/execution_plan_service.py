"""Use cases for loading what a run executes."""

from night_crawler.domain.bundles.execution_plan import ExecutionPlan, ScheduledCrawler
from night_crawler.domain.model.entities import (
    Crawler,
    CrawlerExecution,
    CrawlerVersion,
    MessageAid,
    MessageAidProxy,
    MessageAidRateLimit,
    MessageSelector,
    MessageTemplate,
)
from night_crawler.domain.ports.repository_sets import AbstractReadRepositories
from night_crawler.domain.rules.template_ordering import order_message_templates
from night_crawler.services import crawler_execution_service


async def get_scheduled_crawlers(
    read_repositories: AbstractReadRepositories,
) -> list[ScheduledCrawler]:
    """Return every scheduled Crawler with a published version.

    A schedule always runs; a Crawler with nothing published is skipped
    until a draft is published.
    """
    scheduled: list[ScheduledCrawler] = []
    for crawler in await read_repositories.crawlers.get_all():
        if not crawler.schedule:
            continue
        published = (
            await read_repositories.crawler_versions.get_published_by_crawler_id(
                crawler.id
            )
        )
        if None is not published:
            scheduled.append(ScheduledCrawler(crawler, published))
    return scheduled


async def build_execution_plan(
    read_repositories: AbstractReadRepositories, execution_id: str
) -> ExecutionPlan | None:
    """Load an execution's version tree, in run order, with its Context.

    Returns:
        The plan, or `None` if the execution, its Crawler, its version,
        or its Dataset no longer exists.

    Raises:
        ValidationException: templates depend on each other in a cycle
            (409).
    """
    loaded = await _load_run(read_repositories, execution_id)
    if None is loaded:
        return None
    execution, crawler, version = loaded

    templates = await read_repositories.message_templates.get_all_by_crawler_version_id(
        version.id
    )
    dataset = await read_repositories.datasets.get_by_id(crawler.dataset_id)
    if None is dataset:
        return None
    selectors = await _get_selectors(read_repositories, templates)
    aids = await _get_aids(read_repositories, [template.id for template in templates])
    proxies = await _get_proxies(read_repositories, aids)
    return ExecutionPlan(
        execution=execution,
        crawler=crawler,
        version=version,
        dataset=dataset,
        ordered_templates=order_message_templates(templates, selectors),
        selectors_by_template_id=selectors,
        aids_by_template_id=aids,
        proxies_by_id=proxies,
        context=await crawler_execution_service.get_context(
            read_repositories, execution.id
        ),
        rate_limits_by_id=await _get_rate_limits(read_repositories, aids, proxies),
    )


async def _load_run(
    read_repositories: AbstractReadRepositories, execution_id: str
) -> tuple[CrawlerExecution, Crawler, CrawlerVersion] | None:
    """Return the execution, its Crawler and version, if all exist."""
    execution = await read_repositories.crawler_executions.get_by_id(execution_id)
    if None is execution:
        return None
    crawler = await read_repositories.crawlers.get_by_id(execution.crawler_id)
    version = await read_repositories.crawler_versions.get_by_id(
        execution.crawler_version_id
    )
    if None is crawler or None is version:
        return None
    return execution, crawler, version


async def _get_selectors(
    read_repositories: AbstractReadRepositories, templates: list[MessageTemplate]
) -> dict[str, list[MessageSelector]]:
    """Return each template's selectors, by template id."""
    return {
        template.id: await read_repositories.message_selectors.get_all_by_message_template_id(
            template.id
        )
        for template in templates
    }


async def _get_aids(
    read_repositories: AbstractReadRepositories, template_ids: list[str]
) -> dict[str, MessageAid]:
    """Return the Message Aid of each template that has one."""
    aids: dict[str, MessageAid] = {}
    for template_id in template_ids:
        aid = await read_repositories.message_aids.get_by_message_template_id(
            template_id
        )
        if None is not aid:
            aids[template_id] = aid
    return aids


async def _get_proxies(
    read_repositories: AbstractReadRepositories, aids: dict[str, MessageAid]
) -> dict[str, MessageAidProxy]:
    """Return the proxies the aids select, by id."""
    proxies: dict[str, MessageAidProxy] = {}
    for proxy_id in {aid.selected_proxy_id for aid in aids.values()} - {None}:
        proxy = await read_repositories.message_aid_proxies.get_by_id(proxy_id)
        if None is not proxy:
            proxies[proxy_id] = proxy
    return proxies


async def _get_rate_limits(
    read_repositories: AbstractReadRepositories,
    aids: dict[str, MessageAid],
    proxies: dict[str, MessageAidProxy],
) -> dict[str, MessageAidRateLimit]:
    """Return the rate limits the aids and proxies use, by id."""
    rate_limit_ids = {aid.rate_limit_id for aid in aids.values()} | {
        proxy.rate_limit_id for proxy in proxies.values()
    }
    rate_limits: dict[str, MessageAidRateLimit] = {}
    for rate_limit_id in rate_limit_ids - {None}:
        rate_limit = await read_repositories.message_aid_rate_limits.get_by_id(
            rate_limit_id
        )
        if None is not rate_limit:
            rate_limits[rate_limit_id] = rate_limit
    return rate_limits
