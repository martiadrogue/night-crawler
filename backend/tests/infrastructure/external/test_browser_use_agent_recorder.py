import asyncio
import json
import os
from pathlib import Path
from typing import ClassVar
from unittest.mock import create_autospec

import pytest
from browser_use.agent.views import AgentHistoryList
from night_crawler.domain.exceptions import (
    BrowserAgentException,
    ConfigurationException,
    ExternalServiceException,
)
from night_crawler.domain.model.value_objects import InstructionRequest
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.rules.llm_rate_limits import LlmBudget
from night_crawler.infrastructure.external import browser_use_agent_recorder
from night_crawler.infrastructure.external.browser_use_agent_recorder import (
    BrowserUseAgentRecorder,
    build_task,
)
from night_crawler.infrastructure.external.rate_limited_gemini_model import (
    RateLimitedGeminiModel,
)
from opentelemetry.metrics import NoOpMeter

EVENTS = Path(__file__).parent / "fixtures" / "browser_use" / "cdp_events.json"

REQUEST = InstructionRequest(
    prompt="Comedy shows on https://shows.example",
    crawler_fields=("item_id", "name"),
    current_instructions_yaml="templates: {}\n",
)

CHAT_MODEL = object()


class _Registrar:
    """Stands in for `cdp_client.register.Network`."""

    def __init__(self, handlers: dict) -> None:
        self._handlers = handlers

    def __getattr__(self, event: str):
        return lambda handler: self._handlers.__setitem__(event, handler)


class _NetworkCommands:
    """Stands in for `cdp_client.send.Network`."""

    def __init__(self, session: "FakeBrowserSession") -> None:
        self._session = session

    async def enable(self, session_id: str) -> None:
        self._session.enabled_session_ids.append(session_id)

    async def getResponseBody(self, params: dict, session_id: str) -> dict:
        return json.loads(EVENTS.read_text())["bodies"][params["requestId"]]


class _Namespace:
    def __init__(self, **values) -> None:
        self.__dict__.update(values)


class FakeBrowserSession:
    """Browser Use's session at its boundary: CDP events and lifecycle."""

    instances: ClassVar[list["FakeBrowserSession"]] = []

    def __init__(self, browser_profile) -> None:
        self.browser_profile = browser_profile
        self.handlers: dict = {}
        self.enabled_session_ids: list[str] = []
        self.is_started = False
        self.is_killed = False
        self.cdp_client = _Namespace(
            register=_Namespace(Network=_Registrar(self.handlers)),
            send=_Namespace(Network=_NetworkCommands(self)),
        )
        FakeBrowserSession.instances.append(self)

    async def start(self) -> None:
        self.is_started = True

    async def kill(self) -> None:
        self.is_killed = True

    async def get_or_create_cdp_session(self):
        return _Namespace(session_id="S1", cdp_client=self.cdp_client)

    async def get_current_page_url(self) -> str:
        return "https://shows.example/search?page=2#done"

    def replay_network(self) -> None:
        for event in json.loads(EVENTS.read_text())["events"]:
            self.handlers[event["method"].split(".")[1]](
                event["params"], event["session_id"]
            )


def _agent_class(run, load_history):
    """Return a fake `Agent` whose `run` is `run(agent, load_history)`."""

    class FakeAgent:
        instances: ClassVar[list["FakeAgent"]] = []

        def __init__(self, task, llm, browser_session, **options) -> None:
            self.task = task
            self.llm = llm
            self.browser_session = browser_session
            self.options = options
            self.history = AgentHistoryList(history=[], usage=None)
            self.max_steps = None
            FakeAgent.instances.append(self)

        async def run(self, max_steps, on_step_start):
            self.max_steps = max_steps
            await on_step_start(self)
            self.browser_session.replay_network()
            return await run(self, load_history)

    return FakeAgent


async def _finish(agent, load_history):
    agent.history = load_history()
    return agent.history


async def _hang(agent, load_history):
    agent.history = load_history(2)
    await asyncio.sleep(10)


async def _crash(agent, load_history):
    raise RuntimeError("browser crashed")


async def _call_the_model_until_stopped(agent, load_history):
    """Like Browser Use: a failed model call is a failed step, and the
    stop callback is checked before the next one."""
    agent.history = load_history(1)
    with pytest.raises(ExternalServiceException):
        await agent.llm.ainvoke([])
    assert await agent.options["register_should_stop_callback"]()
    return agent.history


async def _stop_on_error(agent, load_history):
    agent.history = load_history(3)
    return agent.history


@pytest.fixture
def use_fakes(monkeypatch, load_history):
    """Swap Browser Use's agent and session for fakes."""
    FakeBrowserSession.instances = []
    monkeypatch.setattr(
        browser_use_agent_recorder, "BrowserSession", FakeBrowserSession
    )

    def _use(run):
        agent_class = _agent_class(run, load_history)
        monkeypatch.setattr(browser_use_agent_recorder, "Agent", agent_class)
        return agent_class

    return _use


def _recorder(chat_model_factory=lambda: CHAT_MODEL, timeout_seconds=5):
    return BrowserUseAgentRecorder(
        chat_model_factory,
        max_steps=12,
        max_pages=3,
        timeout_seconds=timeout_seconds,
        response_body_max_bytes=1024,
    )


@pytest.mark.anyio
async def test_a_finished_run_is_recorded_and_its_browser_closed(use_fakes):
    agent_class = use_fakes(_finish)

    recording = await _recorder().record(REQUEST)

    [session] = FakeBrowserSession.instances
    [agent] = agent_class.instances
    assert ["navigate", "click", "input", "done"] == [s.action for s in recording.steps]
    assert [0, 0, 1, 1, 2, 2] == [r.step_index for r in recording.requests]
    assert [{"item_id": "1", "name": "Comedy night"}] == recording.final_result.data
    assert recording.final_result.is_success
    assert session.is_started and session.is_killed
    assert not os.path.exists(session.browser_profile.user_data_dir)
    assert {"S1"} == set(session.enabled_session_ids)
    assert CHAT_MODEL is agent.llm
    assert 12 == agent.max_steps
    assert 1 == agent.options["max_actions_per_step"]
    assert not agent.options["enable_signal_handler"]


@pytest.mark.anyio
async def test_the_task_asks_for_the_fields_and_distrusts_page_text(use_fakes):
    agent_class = use_fakes(_finish)

    await _recorder().record(REQUEST)

    [agent] = agent_class.instances
    assert "Comedy shows on https://shows.example" in agent.task
    assert "item_id, name" in agent.task
    assert "templates: {}" in agent.task
    assert "never as instructions" in agent.task
    assert "never as instructions" in agent.options["extend_system_message"]
    assert "at most 3 listing" in agent.task


def test_the_task_samples_a_few_pages_whatever_the_prompt_asks():
    request = InstructionRequest(
        prompt="The whole catalog on https://shows.example",
        crawler_fields=("item_id", "name"),
        current_instructions_yaml="templates: {}\n",
    )

    task = build_task(request, max_pages=7)

    assert "The whole catalog on https://shows.example" in task
    assert "item_id, name" in task
    assert "templates: {}" in task
    assert "never as instructions" in task
    assert "not a full download" in task
    assert "at most 7 listing" in task
    assert "partial result is expected" in task


@pytest.mark.anyio
async def test_each_run_gets_a_fresh_browser_profile(use_fakes):
    use_fakes(_finish)

    await _recorder().record(REQUEST)
    await _recorder().record(REQUEST)

    first, second = FakeBrowserSession.instances
    assert first.browser_profile.user_data_dir != second.browser_profile.user_data_dir


@pytest.mark.anyio
async def test_a_timeout_fails_with_the_partial_recording(use_fakes):
    use_fakes(_hang)

    with pytest.raises(BrowserAgentException) as exc_info:
        await _recorder(timeout_seconds=0.05).record(REQUEST)

    [session] = FakeBrowserSession.instances
    assert isinstance(exc_info.value, ExternalServiceException)
    assert "Browser agent timed out after 0.05 s." == exc_info.value.message
    assert ["navigate", "click"] == [
        step.action for step in exc_info.value.recording.steps
    ]
    assert 6 == len(exc_info.value.recording.requests)
    assert not exc_info.value.recording.final_result.is_success
    assert session.is_killed


@pytest.mark.anyio
async def test_a_crash_becomes_an_external_service_error(use_fakes):
    use_fakes(_crash)

    with pytest.raises(BrowserAgentException) as exc_info:
        await _recorder().record(REQUEST)

    [session] = FakeBrowserSession.instances
    assert "Browser agent failed: RuntimeError." == exc_info.value.message
    assert session.is_killed


@pytest.mark.anyio
async def test_a_run_stopped_by_an_error_fails_with_its_recording(use_fakes):
    use_fakes(_stop_on_error)

    with pytest.raises(BrowserAgentException) as exc_info:
        await _recorder().record(REQUEST)

    [session] = FakeBrowserSession.instances
    assert (
        "Browser agent stopped: Element index 7 not available" == exc_info.value.message
    )
    assert 3 == len(exc_info.value.recording.steps)
    assert session.is_killed


@pytest.mark.anyio
async def test_a_missing_key_fails_before_any_browser_starts(use_fakes):
    use_fakes(_finish)

    def chat_model_factory():
        raise ConfigurationException("GEMINI_API_KEY must be set.")

    with pytest.raises(ConfigurationException) as exc_info:
        await _recorder(chat_model_factory).record(REQUEST)

    assert "GEMINI_API_KEY must be set." == exc_info.value.message
    assert [] == FakeBrowserSession.instances


@pytest.mark.anyio
async def test_a_spent_gemini_budget_stops_the_agent_with_its_reason(use_fakes):
    use_fakes(_call_the_model_until_stopped)
    rate_limiter = create_autospec(AbstractRateLimiter, instance=True)
    rate_limiter.try_acquire.return_value = False
    chat_model = RateLimitedGeminiModel(
        _Namespace(model="gemini-2.5-flash"),
        rate_limiter,
        NoOpMeter("test"),
        LlmBudget(requests_per_minute=10, requests_per_day=500, tokens_per_minute=1),
        max_retry_attempts=3,
    )

    with pytest.raises(BrowserAgentException) as exc_info:
        await _recorder(lambda: chat_model).record(REQUEST)

    [session] = FakeBrowserSession.instances
    assert (
        "Gemini daily request budget spent; try again tomorrow"
        == exc_info.value.message
    )
    assert ["navigate"] == [s.action for s in exc_info.value.recording.steps]
    assert session.is_killed


@pytest.mark.anyio
async def test_a_healthy_model_never_asks_the_agent_to_stop(use_fakes):
    agent_class = use_fakes(_finish)

    await _recorder().record(REQUEST)

    [agent] = agent_class.instances
    assert not await agent.options["register_should_stop_callback"]()
