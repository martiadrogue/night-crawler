"""Request and response models for Message Aids."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RenderMode = Literal["none", "playwright", "stealth"]
"""Mirrors the domain's `RENDER_MODES`.

Duplicated rather than imported so `schemas/` stays self-contained.
"""


class MessageAidBase(BaseModel):
    """Fields shared by Message Aid models.

    Every `None` falls back to a global default (DOMAIN_MODEL DM-13).
    """

    selected_proxy_id: str | None = None
    retry_codes: list[str] | None = None
    success_codes: list[str] | None = None
    ttl: int | None = Field(default=None, gt=0)
    render_mode: RenderMode = "none"
    rate_limit_id: str | None = None
    max_retry_attempts: int | None = Field(default=None, ge=0)


class MessageAidCreate(MessageAidBase):
    """Body for creating or replacing a template's Message Aid.

    A template has at most one aid, so writing it is a full replace.
    """


class MessageAidOut(MessageAidBase):
    """A Message Aid as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    message_template_id: str
    created_at: datetime
    updated_at: datetime
