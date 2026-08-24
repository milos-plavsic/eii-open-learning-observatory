"""Thread-safety decorator for shared WeatherStore connections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

T = TypeVar("T")


class LockOwner(Protocol):
    _lock: Any


def synchronized(method: Callable[..., T]) -> Callable[..., T]:
    """Serialize access to one explicitly cross-thread SQLite connection."""

    def locked(self: LockOwner, *args: Any, **kwargs: Any) -> T:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(Callable[..., T], locked)
