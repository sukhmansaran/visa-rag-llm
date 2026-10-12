"""
Per-event-loop storage for async resources.

Async clients (httpx, redis.asyncio, asyncpg pools) are bound to the event loop they were
created on. A module-level singleton reused from another loop fails with
"Event loop is closed" / "attached to a different loop". This happens whenever code runs a
fresh loop per job (Celery tasks via asyncio.run) or per test (pytest-asyncio).

LoopLocal keeps one instance per running loop and forgets it when that loop is garbage-collected.
"""

import asyncio
import weakref
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class LoopLocal(Generic[T]):
    def __init__(self) -> None:
        self._items: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, T]" = weakref.WeakKeyDictionary()

    def get(self) -> Optional[T]:
        """The instance for the running loop, or None if none has been created yet."""
        return self._items.get(asyncio.get_running_loop())

    def get_or_create(self, factory: Callable[[], T]) -> T:
        loop = asyncio.get_running_loop()
        item = self._items.get(loop)
        if item is None or getattr(item, "is_closed", False):
            item = factory()
            self._items[loop] = item
        return item

    def set(self, value: Optional[T]) -> None:
        loop = asyncio.get_running_loop()
        if value is None:
            self._items.pop(loop, None)
        else:
            self._items[loop] = value

    def pop(self) -> Optional[T]:
        """Remove and return the running loop's instance (for closing it)."""
        return self._items.pop(asyncio.get_running_loop(), None)
