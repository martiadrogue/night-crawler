"""Request and response models for Datasets."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FieldType = Literal["string", "boolean", "integer", "float"]
"""Mirrors the domain's `SCHEMA_FIELD_TYPES`."""


class DatasetFieldSchema(BaseModel):
    """One field a Dataset holds, and the rules its values follow.

    A Crawler picks which fields its executions download; every
    Crawler lists a required field, and `pattern` is a regex the value
    should match.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=255)
    type: FieldType = "string"
    is_required: bool = False
    is_unique: bool = False
    pattern: str | None = None


class DatasetBase(BaseModel):
    """Fields shared by Dataset models."""

    name: str = Field(min_length=1, max_length=255)
    fields: list[DatasetFieldSchema] = Field(min_length=1)


class DatasetCreate(DatasetBase):
    """Body for creating a Dataset; its definition is checked."""


class DatasetUpdate(BaseModel):
    """Body for a partial Dataset update; unset fields stay unchanged.

    `fields` replaces the whole list. The merged definition is checked,
    and so is every linked Crawler's `fields` against it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    fields: list[DatasetFieldSchema] | None = Field(default=None, min_length=1)


class DatasetOut(DatasetBase):
    """A Dataset as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
