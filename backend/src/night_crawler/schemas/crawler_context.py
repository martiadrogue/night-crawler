"""Request and response models for a Crawler's current Context."""

from typing import Any

from pydantic import BaseModel


class CrawlerContextOut(BaseModel):
    """The Context of a Crawler's latest execution.

    `name[]` keys hold lists; other keys a single primitive.
    """

    crawler_execution_id: str
    values: dict[str, Any]


class CrawlerContextValueUpdate(BaseModel):
    """Body setting one Context key.

    A primitive (string, number, boolean, or null), or a list of them
    for a `name[]` key; the list replaces the key's elements.
    """

    value: Any
