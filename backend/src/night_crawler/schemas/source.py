"""Request and response models for Sources."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceBase(BaseModel):
    """Fields shared by Source models."""

    name: str = Field(min_length=1, max_length=255)
    url: str | None = Field(default=None, max_length=2048)


class SourceCreate(SourceBase):
    """Body for creating a Source; its name must be unique."""


class SourceUpdate(BaseModel):
    """Body for a partial Source update; unset fields stay unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, max_length=2048)


class SourceOut(SourceBase):
    """A Source as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
