"""Chat model decorator keeping Gemini calls within the project's quota.

Gemini's quota (requests per minute and day, tokens per minute) is per
Google Cloud project and model, so every call from every worker waits
on one shared budget in the rate limiter (`llm:<model>` keys,
`domain/rules/llm_rate_limits.py`). It wraps Browser Use's chat model,
so the browser agent and the instruction synthesizer, which both get a
model from `core/di.py::create_gemini_chat_model`, share it.
"""

import re
from asyncio import sleep
from typing import Any

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.rules.llm_rate_limits import (
    LlmBudget,
    resolve_llm_rate_limit_targets,
)
from night_crawler.domain.rules.request_retries import retry_delay_seconds
from opentelemetry.metrics import Meter

RATE_LIMITED_STATUS = 429
"""Gemini's status for RESOURCE_EXHAUSTED: a quota was hit."""

RETRY_DELAY_PATTERN = re.compile(r"retryDelay['\"]?\s*:\s*['\"](\d+(?:\.\d+)?)s")
"""Gemini's `RetryInfo.retryDelay` (e.g. `'37s'`) in a 429's text."""

DAILY_QUOTA_MARKER = "PerDay"
"""In a 429's quota id when Google's daily quota, not ours, is spent."""

RATE_LIMIT_EXHAUSTED = "Gemini rate limit exhausted"
DAILY_BUDGET_SPENT = "Gemini daily request budget spent; try again tomorrow"


class RateLimitedGeminiModel(BaseChatModel):
    """Waits on the shared Gemini budget around every call it passes on.

    Before a call: a slot of the day budget, never waited for (spent
    means fail at once); the token budget, waited for once spent; then
    the minute window and its penalty. After it: its tokens are
    counted and the minute key's penalty decays. A 429 grows that
    penalty and is retried after Gemini's own delay, else the crawl
    retry backoff, up to `max_retry_attempts` times.

    Waits and blocks add up in `llm_rate_limit_wait_seconds_total` and
    `llm_rate_limit_blocks_total`, labelled `key="llm:<model>"`.

    Browser Use catches every error of a call and goes on to its next
    step, so the first quota failure is kept in `failure`, and every
    later call raises it again without waiting or calling Gemini.
    """

    def __init__(
        self,
        chat_model: BaseChatModel,
        rate_limiter: AbstractRateLimiter,
        meter: Meter,
        budget: LlmBudget,
        max_retry_attempts: int,
    ) -> None:
        """Wrap `chat_model`; its calls wait on `rate_limiter`.

        Args:
            chat_model: Browser Use's model for Gemini (`ChatGoogle`),
                left to retry server errors but not 429s.
            rate_limiter: Holds the budget every worker shares.
            meter: Where waits and blocks are measured.
            budget: The model's quota.
            max_retry_attempts: Retries of a rate-limited call after its
                first try; 0 never retries.
        """
        self._chat_model = chat_model
        self._rate_limiter = rate_limiter
        self._targets = resolve_llm_rate_limit_targets(chat_model.model, budget)
        self._max_retry_attempts = max_retry_attempts
        self._failure: ExternalServiceException | None = None
        self._verified_api_keys = False
        self._wait = meter.create_counter(
            "llm.rate_limit.wait",
            unit="s",
            description="Seconds LLM calls waited on their quota.",
        )
        self._blocks = meter.create_counter(
            "llm.rate_limit.blocks",
            description="LLM calls the provider rate-limited (HTTP 429).",
        )

    @property
    def model(self) -> str:
        """Return the wrapped model's id, e.g. `gemini-2.5-flash`."""
        return self._chat_model.model

    @property
    def provider(self) -> str:
        """Return the wrapped model's provider."""
        return self._chat_model.provider

    @property
    def name(self) -> str:
        """Return the wrapped model's name."""
        return self._chat_model.name

    @property
    def model_name(self) -> str:
        """Return the wrapped model's id (Browser Use's legacy name)."""
        return self._chat_model.model

    @property
    def chat_model(self) -> BaseChatModel:
        """Return the wrapped model."""
        return self._chat_model

    @property
    def rate_limiter(self) -> AbstractRateLimiter:
        """Return the limiter holding the shared budget."""
        return self._rate_limiter

    @property
    def failure(self) -> ExternalServiceException | None:
        """Return the quota failure that ended this model, if any."""
        return self._failure

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type | None = None,
        **kwargs: Any,
    ) -> ChatInvokeCompletion:
        """Call the model within the shared budget.

        Raises:
            ExternalServiceException: the day budget is spent (here or
                at Google), or calls were still rate-limited after every
                retry; kept in `failure` and raised by every later call.
            ModelProviderError: any other model failure, unchanged.
        """
        if None is not self._failure:
            raise self._failure
        for retry in range(self._max_retry_attempts + 1):
            await self._wait_for_turn()
            try:
                completion = await self._chat_model.ainvoke(
                    messages, output_format, **kwargs
                )
            except ModelProviderError as error:
                await self._handle_rate_limited(error, retry)
                continue
            await self._record_completion(completion)
            return completion
        raise self._fail(RATE_LIMIT_EXHAUSTED)

    async def _wait_for_turn(self) -> None:
        """Take a day slot, then wait for tokens and the minute window.

        Raises:
            ExternalServiceException: the day budget is spent.
        """
        if not await self._rate_limiter.try_acquire(self._targets.day):
            raise self._fail(DAILY_BUDGET_SPENT)
        waited = await self._rate_limiter.wait_for_usage(self._targets.tokens)
        waited += await self._rate_limiter.acquire(self._targets.minute)
        self._wait.add(waited, {"key": self._targets.key})

    async def _handle_rate_limited(self, error: ModelProviderError, retry: int) -> None:
        """Grow the penalty and wait before retrying a 429.

        Raises:
            ModelProviderError: `error`, when it is not a 429.
            ExternalServiceException: Google's daily quota is spent.
        """
        if RATE_LIMITED_STATUS != error.status_code:
            raise error
        self._blocks.add(1, {"key": self._targets.key})
        await self._rate_limiter.record_block(self._targets.minute)
        if DAILY_QUOTA_MARKER in error.message:
            raise self._fail(DAILY_BUDGET_SPENT) from error
        if retry < self._max_retry_attempts:
            delay = _parse_retry_delay(error.message) or retry_delay_seconds(retry + 1)
            await sleep(delay)
            self._wait.add(delay, {"key": self._targets.key})

    async def _record_completion(self, completion: ChatInvokeCompletion) -> None:
        """Decay the minute penalty and count the call's tokens."""
        await self._rate_limiter.record_success(self._targets.minute)
        if None is not completion.usage:
            await self._rate_limiter.record_usage(
                self._targets.tokens, completion.usage.total_tokens
            )

    def _fail(self, message: str) -> ExternalServiceException:
        """Keep a quota failure for every later call, and return it."""
        self._failure = ExternalServiceException(message, 429)
        return self._failure


def _parse_retry_delay(message: str) -> float | None:
    """Return the seconds Gemini asked to wait, if its error says."""
    match = RETRY_DELAY_PATTERN.search(message)
    return None if None is match else float(match.group(1))
