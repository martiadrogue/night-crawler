from unittest.mock import create_autospec

import pytest
from browser_use import ChatGoogle
from night_crawler.core import di
from night_crawler.domain.exceptions import ConfigurationException
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.infrastructure.external.rate_limited_gemini_model import (
    RateLimitedGeminiModel,
)
from pydantic import SecretStr


def _use_settings(monkeypatch, **values) -> None:
    monkeypatch.setattr(di, "_settings", di._settings.model_copy(update=values))


def _rate_limiter():
    return create_autospec(AbstractRateLimiter, instance=True)


def test_the_gemini_chat_model_needs_a_key(monkeypatch):
    _use_settings(monkeypatch, gemini_api_key=SecretStr(""))

    with pytest.raises(ConfigurationException) as exc_info:
        di.create_gemini_chat_model(_rate_limiter())

    assert "GEMINI_API_KEY must be set." == exc_info.value.message


def test_the_gemini_chat_model_uses_the_set_model(monkeypatch):
    _use_settings(
        monkeypatch,
        gemini_api_key=SecretStr("test-key"),
        gemini_model="gemini-2.5-flash",
    )

    chat_model = di.create_gemini_chat_model(_rate_limiter())

    assert isinstance(chat_model.chat_model, ChatGoogle)
    assert "gemini-2.5-flash" == chat_model.model


def test_every_gemini_chat_model_shares_the_task_rate_limiter(monkeypatch):
    _use_settings(
        monkeypatch,
        gemini_api_key=SecretStr("test-key"),
        gemini_model="gemini-2.5-flash",
        gemini_requests_per_minute=10,
        gemini_requests_per_day=500,
        gemini_tokens_per_minute=250_000,
        gemini_max_retry_attempts=4,
    )
    rate_limiter = _rate_limiter()

    recorder_model = di.create_gemini_chat_model(rate_limiter)
    synthesizer_model = di.create_gemini_chat_model(rate_limiter)

    assert isinstance(recorder_model, RateLimitedGeminiModel)
    assert isinstance(synthesizer_model, RateLimitedGeminiModel)
    assert recorder_model.rate_limiter is synthesizer_model.rate_limiter
    assert "gemini-2.5-flash" == recorder_model.model
    # Gemini's 429s are left to the wrapper, which shares the budget.
    assert 429 not in recorder_model.chat_model.retryable_status_codes
