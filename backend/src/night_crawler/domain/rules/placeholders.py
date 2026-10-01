"""`{{placeholder}}` extraction and substitution."""

import json
import re
from collections.abc import Iterable
from typing import Any

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def extract_placeholders(texts: Iterable[str]) -> set[str]:
    """Return every distinct placeholder name used in `texts`."""
    return {name for text in texts for name in PLACEHOLDER_PATTERN.findall(text)}


def render_placeholders(text: str, values: dict[str, str]) -> str:
    """Substitute known placeholders; leave unknown ones as written."""
    return PLACEHOLDER_PATTERN.sub(
        lambda match: values.get(match.group(1), match.group(0)), text
    )


def stringify(value: Any) -> str:
    """Return `value` as placeholder text.

    Strings stay as they are; objects and lists become JSON, so a
    harvested object can be pasted into a JSON body.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
