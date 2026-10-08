"""Browser Use's agent history mapped onto an `AgentRecording`'s parts.

Each history item is one agent step: the model's chosen action, what
running it returned, and the browser's state when the step started.
The recorder lets the agent take one action per step, so a history
item maps onto one `AgentStep`.
"""

import json
from typing import Any

from browser_use.agent.views import AgentHistory, AgentHistoryList
from night_crawler.domain.ports.browser_agent_recorder import (
    AgentFinalResult,
    AgentStep,
)


def map_steps(
    history: AgentHistoryList, final_url: str | None
) -> tuple[AgentStep, ...]:
    """Return the agent's steps, in order.

    An item's state holds the URL from before its step, so the URL
    after a step is the next item's.

    Args:
        history: The agent's history, one item per step.
        final_url: The page's URL once the run ended, the URL after
            the last step; `None` when it could not be read.
    """
    items = history.history
    if not items:
        return ()
    urls_after = [item.state.url for item in items[1:]] + [final_url]
    return tuple(
        _to_step(index, item, url_after)
        for index, (item, url_after) in enumerate(zip(items, urls_after, strict=True))
    )


def get_step_start_times(history: AgentHistoryList) -> list[float]:
    """Return when each step started, as epoch seconds.

    A step without metadata (one that failed before it was timed) is
    taken to start when the step before it did.
    """
    start_times: list[float] = []
    for item in history.history:
        previous = start_times[-1] if start_times else 0.0
        metadata = item.metadata
        start_times.append(previous if None is metadata else metadata.step_start_time)
    return start_times


def map_final_result(history: AgentHistoryList) -> AgentFinalResult:
    """Return what the agent answered with, parsed when it is JSON."""
    answer = history.final_result() if history.is_done() else None
    return AgentFinalResult(
        data=_parse(answer), is_success=True is history.is_successful()
    )


def get_stop_error(history: AgentHistoryList) -> str | None:
    """Return the error that ended an unfinished run, if one did.

    A run that answered, or that only ran out of steps, has none: the
    agent's model or its browser failing shows as an error on the last
    step, after Browser Use's own retries.
    """
    if history.is_done() or not history.history:
        return None
    return history.errors()[-1]


def _to_step(index: int, item: AgentHistory, url_after: str | None) -> AgentStep:
    """Map one history item onto a step."""
    action_name, params = _first_action(item)
    error = next((result.error for result in item.result if result.error), None)
    return AgentStep(
        index=index,
        action=action_name,
        params=params,
        target_xpath=_target_xpath(item),
        url=url_after,
        is_success=None is error,
        error=error,
    )


def _first_action(item: AgentHistory) -> tuple[str | None, dict[str, Any]]:
    """Return the item's action name and arguments, if it has one."""
    if None is item.model_output or not item.model_output.action:
        return None, {}
    dumped = item.model_output.action[0].model_dump(exclude_none=True, mode="json")
    [(action_name, params)] = dumped.items()
    return action_name, params or {}


def _target_xpath(item: AgentHistory) -> str | None:
    """Return the XPath of the element the action used, if any."""
    elements = item.state.interacted_element or [None]
    element = elements[0]
    return None if None is element else element.x_path


def _parse(answer: str | None) -> Any:
    """Return the answer as JSON values, or as text if not JSON."""
    if None is answer:
        return None
    try:
        return json.loads(answer)
    except json.JSONDecodeError:
        return answer
