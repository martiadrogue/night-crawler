"""Validation of Context values supplied by users."""

from typing import Any

ITERATOR_KEY_SUFFIX = "[]"
RESERVED_KEY_PREFIX = "_"


def validate_seed_context(context: dict[str, Any]) -> list[str]:
    """Return every problem with a caller-supplied Context, in order.

    Args:
        context: Keys and values to seed the execution with.

    Returns:
        Human-readable errors; empty when the Context is valid.
    """
    return [error for key, value in context.items() for error in _check(key, value)]


def _check(key: str, value: Any) -> list[str]:
    """Return the problems with one Context entry."""
    if not key.strip():
        return ["Context keys can't be empty."]
    if key.startswith(RESERVED_KEY_PREFIX):
        return [f"Context key '{key}' is reserved for the system."]
    if key.endswith(ITERATOR_KEY_SUFFIX):
        return _check_list(key, value)
    if not _is_primitive(value):
        return [f"Context key '{key}' takes a string, number, boolean, or null."]
    return []


def _check_list(key: str, value: Any) -> list[str]:
    """Return the problems with a `name[]` entry's list."""
    if not isinstance(value, list):
        return [f"Context key '{key}' ends in '[]', so its value must be a list."]
    if not all(_is_primitive(item) for item in value):
        return [f"Context key '{key}' takes a list of primitive values."]
    return []


def _is_primitive(value: Any) -> bool:
    """Tell whether `value` is a string, number, boolean, or `None`."""
    return None is value or isinstance(value, str | int | float | bool)
