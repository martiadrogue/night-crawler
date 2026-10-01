"""Request and response models for Crawlers."""

from datetime import datetime
from typing import Literal

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator

CrawlerQueue = Literal["discovery", "priority", "real-time"]
"""Mirrors the domain's `CRAWLER_QUEUES`; `testing` is for test runs."""

SortField = Literal["created_at", "updated_at"]
SortOrder = Literal["asc", "desc"]


def _validate_cron_schedule(value: str | None) -> str | None:
    """Reject a malformed cron expression when it is written.

    Otherwise it would only fail later in the scheduler, where the error
    is logged and never reaches whoever set it.

    Raises:
        ValueError: `value` is not a valid cron expression; Pydantic
            turns it into a 422.
    """
    if None is value or croniter.is_valid(value):
        return value
    raise ValueError(f"Invalid cron expression: {value!r}")


class CrawlerBase(BaseModel):
    """Fields shared by Crawler models.

    `fields` are the Dataset fields each execution downloads, in CSV
    order.
    """

    title: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    fields: list[str] = Field(min_length=1)
    schedule: str | None = None
    queue: CrawlerQueue = "discovery"

    _validate_schedule = field_validator("schedule")(_validate_cron_schedule)


class CrawlerCreate(CrawlerBase):
    """Body for creating a Crawler; its fields are checked (DM-17)."""


class CrawlerUpdate(BaseModel):
    """Body for a partial Crawler update; unset fields stay unchanged.

    Changing `dataset_id` or `fields` re-checks them together.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    source_id: str | None = Field(default=None, min_length=1)
    dataset_id: str | None = Field(default=None, min_length=1)
    fields: list[str] | None = Field(default=None, min_length=1)
    schedule: str | None = None
    queue: CrawlerQueue | None = None

    _validate_schedule = field_validator("schedule")(_validate_cron_schedule)


class CrawlerOut(CrawlerBase):
    """A Crawler as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
