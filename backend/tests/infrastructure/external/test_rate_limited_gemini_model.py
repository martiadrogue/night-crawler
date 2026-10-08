import pytest
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.model.value_objects import RateLimitTarget
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.rules.llm_rate_limits import LlmBudget
from night_crawler.infrastructure.external import rate_limited_gemini_model
from night_crawler.infrastructure.external.rate_limited_gemini_model import (
    RateLimitedGeminiModel,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

MODEL = "gemini-2.5-flash"
MINUTE, DAY, TOKENS = (f"llm:{MODEL}:{name}" for name in ("minute", "day", "tokens"))
BUDGET = LlmBudget(
    requests_per_minute=10, requests_per_day=500, tokens_per_minute=250_000
)
MESSAGES = [UserMessage(content="Which shows are on?")]

MINUTE_QUOTA_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded "
    "your current quota.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaValue': "
    "'10'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', "
    "'retryDelay': '37s'}]}}"
)
DAY_QUOTA_429 = MINUTE_QUOTA_429.replace("PerMinute", "PerDay").replace("37s", "52000s")
BARE_429 = "429 Resource has been exhausted (e.g. check quota)."


def _completion(total_tokens: int | None = 120) -> ChatInvokeCompletion:
    usage = None
    if None is not total_tokens:
        usage = ChatInvokeUsage(
            prompt_tokens=total_tokens - 20,
            prompt_cached_tokens=None,
            prompt_cache_creation_tokens=None,
            prompt_image_tokens=None,
            completion_tokens=20,
            total_tokens=total_tokens,
        )
    return ChatInvokeCompletion(completion="Comedy night", usage=usage)


def _rate_limited(message: str = MINUTE_QUOTA_429) -> ModelProviderError:
    """What `ChatGoogle` raises for a 429 it does not retry itself."""
    return ModelProviderError(message=message, status_code=429, model=MODEL)


class FakeRateLimiter(AbstractRateLimiter):
    """One shared budget: records calls; `day_slots` free daily slots."""

    def __init__(self, day_slots=500, minute_wait=0.0, usage_wait=0.0) -> None:
        self.calls: list[tuple] = []
        self.day_slots = day_slots
        self.minute_wait = minute_wait
        self.usage_wait = usage_wait

    async def acquire(self, target: RateLimitTarget) -> float:
        self.calls.append(("acquire", target.key))
        return self.minute_wait

    async def try_acquire(self, target: RateLimitTarget) -> bool:
        self.calls.append(("try_acquire", target.key))
        if 0 == self.day_slots:
            return False
        self.day_slots -= 1
        return True

    async def wait_for_usage(self, target: RateLimitTarget) -> float:
        self.calls.append(("wait_for_usage", target.key))
        return self.usage_wait

    async def record_usage(self, target: RateLimitTarget, amount: int) -> None:
        self.calls.append(("usage", target.key, amount))

    async def record_block(self, target: RateLimitTarget) -> None:
        self.calls.append(("block", target.key))

    async def record_success(self, target: RateLimitTarget) -> None:
        self.calls.append(("success", target.key))

    async def aclose(self) -> None:
        self.calls.append(("aclose",))


class FakeChatModel:
    """Browser Use's chat model at its boundary: scripted answers."""

    model = MODEL
    provider = "google"
    name = MODEL
    _verified_api_keys = False

    def __init__(self, *answers) -> None:
        self.answers = list(answers) or [_completion()]
        self.calls: list[list] = []

    @property
    def model_name(self) -> str:
        return self.model

    async def ainvoke(self, messages, output_format=None, **kwargs):
        self.calls.append(messages)
        answer = self.answers.pop(0) if 1 < len(self.answers) else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def sleeps(monkeypatch):
    """Record the decorator's retry waits instead of sleeping."""
    recorded: list[float] = []

    async def record(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(rate_limited_gemini_model, "sleep", record)
    return recorded


@pytest.fixture
def metric_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def meter(metric_reader):
    return MeterProvider(metric_readers=[metric_reader]).get_meter("test")


def _points(metric_reader, name):
    data = metric_reader.get_metrics_data()
    return [
        (dict(point.attributes), point.value)
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if name == metric.name
        for point in metric.data.data_points
    ]


def _wrap(chat_model, rate_limiter, meter, max_retry_attempts=3):
    return RateLimitedGeminiModel(
        chat_model, rate_limiter, meter, BUDGET, max_retry_attempts
    )


@pytest.mark.anyio
async def test_each_call_waits_on_the_day_and_minute_keys_first(meter, sleeps):
    rate_limiter, chat_model = FakeRateLimiter(), FakeChatModel()

    completion = await _wrap(chat_model, rate_limiter, meter).ainvoke(MESSAGES)

    assert "Comedy night" == completion.completion
    assert [MESSAGES] == chat_model.calls
    assert [
        ("try_acquire", DAY),
        ("wait_for_usage", TOKENS),
        ("acquire", MINUTE),
        ("success", MINUTE),
        ("usage", TOKENS, 120),
    ] == rate_limiter.calls
    assert [] == sleeps


@pytest.mark.anyio
async def test_a_completion_without_usage_counts_no_tokens(meter, sleeps):
    rate_limiter = FakeRateLimiter()

    await _wrap(FakeChatModel(_completion(None)), rate_limiter, meter).ainvoke(MESSAGES)

    assert [] == [call for call in rate_limiter.calls if "usage" == call[0]]


@pytest.mark.anyio
async def test_a_429_with_a_retry_delay_is_honoured_then_succeeds(meter, sleeps):
    rate_limiter = FakeRateLimiter()
    chat_model = FakeChatModel(_rate_limited(), _completion())

    completion = await _wrap(chat_model, rate_limiter, meter).ainvoke(MESSAGES)

    assert "Comedy night" == completion.completion
    assert [37.0] == sleeps
    assert 2 == len(chat_model.calls)
    assert [("block", MINUTE), ("success", MINUTE)] == [
        call for call in rate_limiter.calls if call[0] in ("block", "success")
    ]
    assert 2 == rate_limiter.calls.count(("acquire", MINUTE))
    assert 2 == rate_limiter.calls.count(("try_acquire", DAY))


@pytest.mark.anyio
async def test_a_429_without_a_delay_backs_off_like_crawl_retries(meter, sleeps):
    chat_model = FakeChatModel(
        _rate_limited(BARE_429), _rate_limited(BARE_429), _completion()
    )

    await _wrap(chat_model, FakeRateLimiter(), meter).ainvoke(MESSAGES)

    assert [1.0, 2.0] == sleeps


@pytest.mark.anyio
async def test_gives_up_after_the_retry_attempts(meter, sleeps):
    rate_limiter = FakeRateLimiter()
    chat_model = FakeChatModel(_rate_limited())
    model = _wrap(chat_model, rate_limiter, meter, max_retry_attempts=2)

    with pytest.raises(ExternalServiceException) as exc_info:
        await model.ainvoke(MESSAGES)

    assert "Gemini rate limit exhausted" == exc_info.value.message
    assert 3 == len(chat_model.calls)
    assert [37.0, 37.0] == sleeps
    assert 3 == rate_limiter.calls.count(("block", MINUTE))
    assert exc_info.value is model.failure


@pytest.mark.anyio
async def test_a_spent_day_fails_fast_without_calling_the_model(meter, sleeps):
    rate_limiter = FakeRateLimiter(day_slots=0)
    chat_model = FakeChatModel()
    model = _wrap(chat_model, rate_limiter, meter)

    with pytest.raises(ExternalServiceException) as first:
        await model.ainvoke(MESSAGES)
    with pytest.raises(ExternalServiceException) as second:
        await model.ainvoke(MESSAGES)

    assert "Gemini daily request budget spent; try again tomorrow" == (
        first.value.message
    )
    assert first.value is second.value
    assert [] == chat_model.calls
    assert [("try_acquire", DAY)] == rate_limiter.calls
    assert [] == sleeps


@pytest.mark.anyio
async def test_googles_own_daily_quota_also_fails_fast(meter, sleeps):
    chat_model = FakeChatModel(_rate_limited(DAY_QUOTA_429))

    with pytest.raises(ExternalServiceException) as exc_info:
        await _wrap(chat_model, FakeRateLimiter(), meter).ainvoke(MESSAGES)

    assert "Gemini daily request budget spent; try again tomorrow" == (
        exc_info.value.message
    )
    assert 1 == len(chat_model.calls)
    assert [] == sleeps


@pytest.mark.anyio
async def test_other_model_errors_pass_through_untouched(meter, sleeps):
    rate_limiter = FakeRateLimiter()
    error = ModelProviderError(message="500 INTERNAL", status_code=500, model=MODEL)

    with pytest.raises(ModelProviderError) as exc_info:
        await _wrap(FakeChatModel(error), rate_limiter, meter).ainvoke(MESSAGES)

    assert error is exc_info.value
    assert [] == [call for call in rate_limiter.calls if "block" == call[0]]
    assert [] == sleeps


@pytest.mark.anyio
async def test_recorder_and_synthesizer_models_share_one_budget(meter, sleeps):
    rate_limiter = FakeRateLimiter(day_slots=1)
    recorder_model = _wrap(FakeChatModel(), rate_limiter, meter)
    synthesizer_model = _wrap(FakeChatModel(), rate_limiter, meter)

    await recorder_model.ainvoke(MESSAGES)
    with pytest.raises(ExternalServiceException) as exc_info:
        await synthesizer_model.ainvoke(MESSAGES)

    assert "Gemini daily request budget spent" in exc_info.value.message
    assert [DAY, DAY] == [
        call[1] for call in rate_limiter.calls if "try_acquire" == call[0]
    ]


@pytest.mark.anyio
async def test_waits_and_blocks_are_measured_by_model_key(meter, metric_reader, sleeps):
    rate_limiter = FakeRateLimiter(minute_wait=1.5, usage_wait=0.5)
    chat_model = FakeChatModel(_rate_limited(), _completion())

    await _wrap(chat_model, rate_limiter, meter).ainvoke(MESSAGES)

    key = {"key": f"llm:{MODEL}"}
    assert [(key, 2 * (1.5 + 0.5) + 37.0)] == _points(
        metric_reader, "llm.rate_limit.wait"
    )
    assert [(key, 1)] == _points(metric_reader, "llm.rate_limit.blocks")


def test_it_passes_for_the_model_it_wraps(meter):
    model = _wrap(FakeChatModel(), FakeRateLimiter(), meter)
    model._verified_api_keys = True

    assert isinstance(model, BaseChatModel)
    assert (MODEL, "google", MODEL, MODEL) == (
        model.model,
        model.provider,
        model.name,
        model.model_name,
    )
    assert None is model.failure
