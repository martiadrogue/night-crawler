"""How a background task opens repository sets."""

from collections.abc import Callable
from dataclasses import dataclass

from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)


@dataclass(frozen=True)
class RepositorySetFactories:
    """Opens fresh read or write repositories, one use at a time.

    A run takes minutes of network I/O; a MongoDB transaction must not
    stay open that long, so a task opens short-lived sets instead of
    holding one.
    """

    open_read: Callable[[], AbstractReadRepositories]
    open_write: Callable[[], AbstractWriteRepositories]
