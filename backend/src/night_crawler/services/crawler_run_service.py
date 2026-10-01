"""The use case running one execution plan's requests.

Pure orchestration over the request-executor ports: it touches no
database, since a run holds minutes of network I/O and a transaction
must not stay open that long.
"""

import logging
from asyncio import sleep
from dataclasses import replace
from typing import Any

from night_crawler.domain.bundles.execution_plan import (
    ExecutionPlan,
    RunOutcome,
    TemplateRun,
)
from night_crawler.domain.bundles.request_executors import RequestExecutors
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    MissingPlaceholderException,
)
from night_crawler.domain.model.constants import (
    DEFAULT_RENDER_MODE,
    DEFAULT_TTL_SECONDS,
)
from night_crawler.domain.model.entities import MessageAid, MessageTemplate
from night_crawler.domain.model.value_objects import RateLimitTarget, RenderedRequest
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.ports.request_executor import (
    DispatchRequest,
    DispatchResult,
)
from night_crawler.domain.rules.context_resolution import (
    resolve_repeat_run,
    resolve_template_runs,
)
from night_crawler.domain.rules.dataset_rows import project_rows
from night_crawler.domain.rules.host_session import (
    merge_session,
    resolve_request_host,
)
from night_crawler.domain.rules.rate_limits import resolve_rate_limit_targets
from night_crawler.domain.rules.request_retries import (
    RetryPolicy,
    retry_delay_seconds,
    retry_policy_for,
    should_retry,
)
from night_crawler.domain.rules.selector_tree import (
    ITERATOR_KEY_SUFFIX,
    flatten_harvest,
    merge_context_value,
    split_harvest_by_fields,
)
from night_crawler.domain.rules.template_repeats import (
    SelfFedPlaceholders,
    find_self_fed_placeholders,
    next_scalar_values,
    unrun_list_elements,
)

logger = logging.getLogger(__name__)


async def execute_plan(
    executors: RequestExecutors, rate_limiter: AbstractRateLimiter, plan: ExecutionPlan
) -> RunOutcome:
    """Run every template in order, fanning out, sharing sessions.

    Each template's runs are rendered from the Context as it stands when
    the template starts, so a template sees everything the templates it
    depends on harvested. A template that fills its own placeholders
    runs again while they change (`_run_template`). A request that
    fails for good, after its retries, stops the run, as does a missing
    placeholder; what was harvested until then is kept. Each try waits
    on its rate limits first (`_dispatch`).

    Returns:
        The final Context, sessions, counters, and any failure.
    """
    outcome = RunOutcome(context=dict(plan.context))
    try:
        for template in plan.ordered_templates:
            outcome = await _run_template(
                executors, rate_limiter, plan, outcome, template
            )
            if outcome.failure:
                break
    except MissingPlaceholderException as exception:
        return replace(outcome, failure=exception.message)
    return outcome


async def _run_template(
    executors: RequestExecutors,
    rate_limiter: AbstractRateLimiter,
    plan: ExecutionPlan,
    outcome: RunOutcome,
    template: MessageTemplate,
) -> RunOutcome:
    """Run a template's fan-out, then again for list elements it added.

    Each combination repeats on its own while the template's self-fed
    single values change. Afterwards, elements the template appended to
    a list it fans out over get their own runs, once each, until none
    are new (DOMAIN_MODEL §5.8). A failed request ends it at once.
    """
    self_fed = find_self_fed_placeholders(
        template, plan.selectors_by_template_id.get(template.id, [])
    )
    done: dict[str, list[Any]] = {name: [] for name in self_fed.lists}
    runs = resolve_template_runs(template, _seed(outcome.context, self_fed))
    while runs:
        for rendered in runs:
            outcome = await _run_combination(
                executors,
                rate_limiter,
                plan,
                outcome,
                TemplateRun(template, rendered),
                scalars=self_fed.scalars,
            )
            if outcome.failure:
                return outcome
            _mark_done(done, rendered.fanned_out_values)
        runs = _next_list_runs(template, outcome.context, self_fed, done)
    return outcome


async def _run_combination(
    executors: RequestExecutors,
    rate_limiter: AbstractRateLimiter,
    plan: ExecutionPlan,
    outcome: RunOutcome,
    run: TemplateRun,
    *,
    scalars: frozenset[str],
) -> RunOutcome:
    """Send one combination, again while its self-fed values change.

    Self-fed single values are cleared before each request, so a value
    a response didn't harvest reads as missing, never as the previous
    combination's.
    """
    used: dict[str, list[Any]] = {name: [""] for name in scalars}
    while True:
        outcome = await _dispatch(
            executors, rate_limiter, plan, _forget(outcome, scalars), run
        )
        updates = _scalar_updates(outcome, scalars, used)
        if not updates:
            return outcome
        _remember(used, updates)
        run = TemplateRun(
            run.template, resolve_repeat_run(run.template, run.rendered, updates)
        )


def _scalar_updates(
    outcome: RunOutcome, scalars: frozenset[str], used: dict[str, list[Any]]
) -> dict[str, Any]:
    """Return the self-fed values to send next; none after a failure."""
    if outcome.failure:
        return {}
    return next_scalar_values(
        {name: outcome.context.get(name) for name in scalars}, used
    )


def _remember(used: dict[str, list[Any]], updates: dict[str, Any]) -> None:
    """Record values a combination has sent, so they never repeat."""
    for name, value in updates.items():
        used[name].append(value)


def _seed(context: dict[str, Any], self_fed: SelfFedPlaceholders) -> dict[str, Any]:
    """Return the Context a self-feeding template starts from.

    Its single values start empty, whatever the previous run left, so a
    stale token is never sent; a list nothing filled yet starts as one
    empty element, so the template still runs once.
    """
    seeded = {**context, **dict.fromkeys(self_fed.scalars, "")}
    for name in self_fed.lists:
        if name not in context and f"{name}{ITERATOR_KEY_SUFFIX}" not in context:
            seeded[f"{name}{ITERATOR_KEY_SUFFIX}"] = [""]
    return seeded


def _mark_done(done: dict[str, list[Any]], fanned_out: dict[str, Any]) -> None:
    """Record the list elements a combination ran with."""
    for name, elements in done.items():
        if name in fanned_out and fanned_out[name] not in elements:
            elements.append(fanned_out[name])


def _next_list_runs(
    template: MessageTemplate,
    context: dict[str, Any],
    self_fed: SelfFedPlaceholders,
    done: dict[str, list[Any]],
) -> list[RenderedRequest]:
    """Return runs for the list elements the template added, if any."""
    unrun = unrun_list_elements(context, self_fed.lists, done)
    if not unrun:
        return []
    fresh = {
        f"{name}{ITERATOR_KEY_SUFFIX}": elements for name, elements in unrun.items()
    }
    return resolve_template_runs(template, {**_seed(context, self_fed), **fresh})


def _forget(outcome: RunOutcome, names: frozenset[str]) -> RunOutcome:
    """Return the outcome without `names` in its Context."""
    if not names:
        return outcome
    return replace(
        outcome,
        context={
            key: value for key, value in outcome.context.items() if key not in names
        },
    )


async def _dispatch(
    executors: RequestExecutors,
    rate_limiter: AbstractRateLimiter,
    plan: ExecutionPlan,
    outcome: RunOutcome,
    run: TemplateRun,
) -> RunOutcome:
    """Send one run with its engine and fold its result in.

    Every try, retries included, first waits on the rate limits of the
    request's host and proxy. A failure with a retry code is a block
    and grows their penalty; a success counts toward its decay.
    """
    aid = plan.aids_by_template_id.get(run.template.id)
    executor = executors.for_render_mode(
        aid.render_mode if None is not aid else DEFAULT_RENDER_MODE
    )
    counted = replace(outcome, request_count=outcome.request_count + 1)
    policy = retry_policy_for(aid)
    request = _build_request(plan, outcome, run)
    targets = resolve_rate_limit_targets(
        run.rendered.url, aid, request.proxy, plan.rate_limits_by_id
    )
    retries = 0
    while True:
        await _acquire(rate_limiter, plan, run, targets)
        try:
            result = await executor.execute(request)
        except ExternalServiceException as exception:
            code = getattr(exception, "failure_code", None)
            await _record_failure(rate_limiter, policy, code, targets)
            if not should_retry(policy, code, retries_done=retries):
                return _count_failure(plan, counted, run, exception, retries=retries)
            retries += 1
            await _wait_before_retry(plan, run, code, retry=retries)
            continue
        await _record_success(rate_limiter, targets)
        counted = replace(counted, retry_count=counted.retry_count + retries)
        return _record(plan, counted, run, result=result)


async def _acquire(
    rate_limiter: AbstractRateLimiter,
    plan: ExecutionPlan,
    run: TemplateRun,
    targets: tuple[RateLimitTarget, ...],
) -> None:
    """Wait on each rate limit in turn; log any wait."""
    for target in targets:
        waited = await rate_limiter.acquire(target)
        if waited:
            logger.info(
                "Rate limited: execution_id=%s, url=%s, key=%s, wait=%.1fs",
                plan.execution.id,
                run.rendered.url,
                target.key,
                waited,
            )


async def _record_success(
    rate_limiter: AbstractRateLimiter, targets: tuple[RateLimitTarget, ...]
) -> None:
    """Count a success toward each limit's penalty decay."""
    for target in targets:
        await rate_limiter.record_success(target)


async def _record_failure(
    rate_limiter: AbstractRateLimiter,
    policy: RetryPolicy,
    code: str | None,
    targets: tuple[RateLimitTarget, ...],
) -> None:
    """Count a failure with a retry code as a block on each limit."""
    if code not in policy.retry_codes:
        return
    for target in targets:
        await rate_limiter.record_block(target)


async def _wait_before_retry(
    plan: ExecutionPlan, run: TemplateRun, code: str | None, *, retry: int
) -> None:
    """Log a retried failure and wait before the next try."""
    delay = retry_delay_seconds(retry)
    logger.info(
        "Request retried: execution_id=%s, url=%s, code=%s, retry=%d, wait=%.0fs",
        plan.execution.id,
        run.rendered.url,
        code,
        retry,
        delay,
    )
    await sleep(delay)


def _count_failure(
    plan: ExecutionPlan,
    outcome: RunOutcome,
    run: TemplateRun,
    exception: ExternalServiceException,
    *,
    retries: int,
) -> RunOutcome:
    """Record a request that failed for good; it stops the run."""
    logger.warning(
        "Request failed: execution_id=%s, url=%s, retries=%d, error=%s",
        plan.execution.id,
        run.rendered.url,
        retries,
        exception.message,
    )
    return replace(
        outcome,
        error_count=outcome.error_count + 1,
        retry_count=outcome.retry_count + retries,
        failure=exception.message,
    )


def _build_request(
    plan: ExecutionPlan, outcome: RunOutcome, run: TemplateRun
) -> DispatchRequest:
    """Return the request: selectors, timeout, proxy, session, codes."""
    aid = plan.aids_by_template_id.get(run.template.id)
    host = resolve_request_host(run.rendered.url)
    session = (
        outcome.sessions.get(host)
        if plan.version.is_host_session_sharing_enabled
        else None
    )
    return DispatchRequest(
        rendered=run.rendered,
        selectors=plan.selectors_by_template_id.get(run.template.id, []),
        session=session,
        timeout_seconds=(aid.ttl if aid and aid.ttl else DEFAULT_TTL_SECONDS),
        proxy=plan.proxies_by_id.get(aid.selected_proxy_id) if aid else None,
        success_codes=_success_codes(aid),
        is_host_session_sharing_enabled=plan.version.is_host_session_sharing_enabled,
    )


def _success_codes(aid: MessageAid | None) -> tuple[str, ...] | None:
    """Return the aid's success codes, or `None` for below-400."""
    if None is aid or None is aid.success_codes:
        return None
    return tuple(aid.success_codes)


def _record(
    plan: ExecutionPlan,
    outcome: RunOutcome,
    run: TemplateRun,
    *,
    result: DispatchResult,
) -> RunOutcome:
    """Fold a result's session, Context values, and dataset rows in.

    Values for the Crawler's fields feed the dataset, never the Context.
    """
    sessions = outcome.sessions
    host = resolve_request_host(run.rendered.url)
    if plan.version.is_host_session_sharing_enabled and None is not host:
        sessions = {**sessions, host: merge_session(sessions.get(host), result.session)}

    fields = plan.crawler.fields
    context_items, _dataset_items = split_harvest_by_fields(
        flatten_harvest(result.harvest), set(fields)
    )
    rows = project_rows(result.harvest, fields) if _feeds_dataset(plan, run) else []
    return replace(
        outcome,
        context=_merge_into_context(outcome, context_items),
        harvested_keys=outcome.harvested_keys | set(context_items),
        sessions=sessions,
        dataset_rows=[*outcome.dataset_rows, *rows],
    )


def _feeds_dataset(plan: ExecutionPlan, run: TemplateRun) -> bool:
    """Tell whether a template has a selector titled after a field."""
    fields = set(plan.crawler.fields)
    return any(
        selector.title in fields
        for selector in plan.selectors_by_template_id.get(run.template.id, [])
    )


def _merge_into_context(outcome: RunOutcome, items: dict) -> dict:
    """Return the Context with one response's values merged in.

    The first harvest of a key in this run replaces what the run
    inherited; later ones extend lists.
    """
    context = dict(outcome.context)
    for key, value in items.items():
        context[key] = merge_context_value(
            context.get(key),
            value,
            key.endswith(ITERATOR_KEY_SUFFIX),
            key not in outcome.harvested_keys,
        )
    return context
