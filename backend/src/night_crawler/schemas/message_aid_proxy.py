"""Request and response models for pooled proxies."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageAidProxyBase(BaseModel):
    """Fields shared by proxy models."""

    url: str = Field(min_length=1, max_length=2048)
    user: str | None = None
    headers: dict[str, Any] = {}
    rate_limit_id: str | None = None


class MessageAidProxyCreate(MessageAidProxyBase):
    """Body for adding a proxy, including its password."""

    password: str


class MessageAidProxyUpdate(BaseModel):
    """Body for a partial proxy update; unset fields stay unchanged."""

    url: str | None = Field(default=None, min_length=1, max_length=2048)
    user: str | None = None
    password: str | None = None
    headers: dict[str, Any] | None = None
    rate_limit_id: str | None = None


class MessageAidProxyOut(MessageAidProxyBase):
    """A proxy as returned by the API, never with its password."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
