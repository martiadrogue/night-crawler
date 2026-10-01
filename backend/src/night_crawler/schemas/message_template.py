"""Request and response models for Message Templates."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TemplateAction = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "CLICK"]
"""The actions a template can take; mirrors the collection validator."""


class MessageTemplateBase(BaseModel):
    """Fields shared by template models."""

    action: TemplateAction
    url: str = Field(max_length=2048)
    body: str | None = None
    headers: dict[str, Any] = {}


class MessageTemplateCreate(MessageTemplateBase):
    """Body for adding a template to a version."""


class MessageTemplateUpdate(BaseModel):
    """Body for a partial template update; unset fields stay as is."""

    action: TemplateAction | None = None
    url: str | None = Field(default=None, max_length=2048)
    body: str | None = None
    headers: dict[str, Any] | None = None


class MessageTemplateOut(MessageTemplateBase):
    """A template as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    crawler_version_id: str
    created_at: datetime
    updated_at: datetime
