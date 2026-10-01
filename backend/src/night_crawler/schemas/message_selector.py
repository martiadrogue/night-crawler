"""Request and response models for Message Selectors."""

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SelectorType = Literal["value", "iterator", "boolean", "click", "select", "pagination"]
"""The selector types; mirrors the collection validator."""

SelectorSource = Literal["content", "headers", "url", "context"]
"""What a selector reads; mirrors the domain's `SELECTOR_SOURCES`.

A `context` selector's `path` is a placeholder name: it reads that
placeholder's value in the template's run.
"""


LIST_KEY_SUFFIX = "[]"
"""Mirrors the domain's `ITERATOR_KEY_SUFFIX`: it marks a list key."""


def _reject_list_suffix(title: str | None) -> str | None:
    """Refuse a title ending in `[]`: lists are named automatically.

    A selector under an iterator, click, or select harvests into
    `title[]` in the Context on its own.

    Raises:
        ValueError: `title` ends in `[]`; Pydantic turns it into a 422.
    """
    if None is not title and title.endswith(LIST_KEY_SUFFIX):
        raise ValueError(
            "Leave `[]` out of the title: a selector under an iterator, "
            "click, or select is stored as a list in the Context on its own."
        )
    return title


def _require_regex_for_regex_sources(source: str | None, path: str | None) -> None:
    """Check a `headers`/`url` selector's path compiles as a regex.

    Raises:
        ValueError: it doesn't; Pydantic turns it into a 422.
    """
    if source not in ("headers", "url") or None is path:
        return
    try:
        re.compile(path)
    except re.error as error:
        raise ValueError(f"`path` must be a regex for {source}: {error}") from error


class PrimitiveMappingBase(BaseModel):
    """Where one pagination number lives, and how to clean it."""

    path: str = Field(min_length=1)
    regex_clean: str = r"\d+"

    @field_validator("regex_clean")
    @classmethod
    def _validate_regex(cls, value: str) -> str:
        """Reject a pattern that doesn't compile.

        Raises:
            ValueError: `value` is not a valid regex; Pydantic turns it
                into a 422.
        """
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"Invalid regex_clean pattern: {error}") from error
        return value


class PaginationPrimitivesBase(BaseModel):
    """The numbers a pagination selector extracts."""

    total_items: PrimitiveMappingBase
    page_size: PrimitiveMappingBase | None = None
    current_page: PrimitiveMappingBase | None = None


class CircuitBreakerBase(BaseModel):
    """Limits that stop a discovered page range from running away."""

    max_limit_cap: int = Field(ge=1)
    fallback_page_size: int = Field(default=20, ge=1)


class PaginationConfigBase(BaseModel):
    """A `pagination` selector's configuration (DOMAIN_MODEL §5.7).

    The selector's own `path` finds the metadata container; each
    primitive's `path` is relative to it. The result is stored in the
    Context under `output_key`, and later templates fan out over the
    pages through the `{{range_key}}` placeholder.
    """

    output_key: Literal["_pagination"] = "_pagination"
    range_key: str = Field(default="page", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    primitive_mappings: PaginationPrimitivesBase
    circuit_breaker: CircuitBreakerBase


class MessageSelectorBase(BaseModel):
    """Fields shared by selector models."""

    path: str = Field(min_length=1)
    type: SelectorType
    target: str = "__text"
    parent_selector_id: str | None = None
    title: str | None = None
    config: PaginationConfigBase | None = None
    source: SelectorSource = "content"

    _validate_title = field_validator("title")(_reject_list_suffix)


class MessageSelectorCreate(MessageSelectorBase):
    """Body for adding a selector to a template.

    A `pagination` selector requires `config`; every other type must
    leave it unset.
    """

    @model_validator(mode="after")
    def _require_config_for_pagination(self) -> Self:
        """Check that `config` is set exactly for `pagination`.

        Raises:
            ValueError: `config` is missing on a `pagination` selector
                or set on any other type.
        """
        if ("pagination" == self.type) != (None is not self.config):
            raise ValueError("`config` is required for, and only for, pagination.")
        _require_regex_for_regex_sources(self.source, self.path)
        return self


class MessageSelectorUpdate(BaseModel):
    """Body for a partial selector update; unset fields stay as is.

    The `config` rule is checked against the merged selector.
    """

    path: str | None = Field(default=None, min_length=1)
    type: SelectorType | None = None
    target: str | None = None
    parent_selector_id: str | None = None
    title: str | None = None
    config: PaginationConfigBase | None = None
    source: SelectorSource | None = None

    _validate_title = field_validator("title")(_reject_list_suffix)

    @model_validator(mode="after")
    def _check_regex(self) -> Self:
        """Check a new `headers`/`url` path compiles as a regex.

        Raises:
            ValueError: it doesn't.
        """
        _require_regex_for_regex_sources(self.source, self.path)
        return self


class MessageSelectorOut(MessageSelectorBase):
    """A selector as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    message_template_id: str
    created_at: datetime
    updated_at: datetime
