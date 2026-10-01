"""A guard that lets a repository read but never write."""

from typing import Any

from night_crawler.domain.exceptions import ConfigurationException

READ_METHOD_PREFIXES: tuple[str, ...] = ("get_", "has_", "count_")
"""Repository reads (CONTRIBUTING R2.2.3); everything else writes."""


class ReadOnlyRepository:
    """Forward reads to a repository and refuse every other method.

    An allow-list, not a deny-list: a write method added to a
    repository later is refused without touching this class.
    """

    def __init__(self, repository: Any) -> None:
        """Wrap `repository`, built without a session."""
        self._repository = repository

    def __getattr__(self, name: str) -> Any:
        """Return the read method `name`, or a refusing stand-in.

        Raises:
            ConfigurationException: when the returned stand-in for a
                write method is called.
        """
        if name.startswith(READ_METHOD_PREFIXES):
            return getattr(self._repository, name)
        return _refuse_write(name)


def _refuse_write(name: str) -> Any:
    """Return a callable that refuses the write method `name`."""

    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise ConfigurationException(
            f"`{name}` writes, but read repositories run outside a "
            "transaction; use write repositories."
        )

    return _refuse
