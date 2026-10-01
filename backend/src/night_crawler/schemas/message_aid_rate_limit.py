"""Request and response models for rate-limit rules."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageAidRateLimitBase(BaseModel):
    """Fields shared by rate-limit models."""

    name: str | None = None
    rate_limit_string: str
    penalty_step_seconds: int = Field(default=0, ge=0)
    max_penalty_seconds: int = Field(default=0, ge=0)
    decay_after_successes: int = Field(default=1, gt=0)
    decay_step_seconds: int = Field(default=0, ge=0)


class MessageAidRateLimitCreate(MessageAidRateLimitBase):
    """Body for creating a rate-limit rule."""


class MessageAidRateLimitUpdate(BaseModel):
    """Body for a partial rule update; unset fields stay unchanged."""

    name: str | None = None
    rate_limit_string: str | None = None
    penalty_step_seconds: int | None = Field(default=None, ge=0)
    max_penalty_seconds: int | None = Field(default=None, ge=0)
    decay_after_successes: int | None = Field(default=None, gt=0)
    decay_step_seconds: int | None = Field(default=None, ge=0)


class MessageAidRateLimitOut(MessageAidRateLimitBase):
    """A rate-limit rule as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
