"""Async-safe in-memory TTL cache.

Used for caching expensive Avito API responses that don't change often
(e.g. fees of completed reports).

Usage:
    from app.cache import cache

    val = await cache.get("k")
    if val is None:
        val = await expensive_fetch()
        await cache.set("k", val, ttl_seconds=3600)
"""

import asyncio
import time
from typing import Any


class TTLCache:
    """Simple async-safe TTL cache backed by a dict.

    Entries are lazily evicted on read/write. There is no background sweeper,
    so memory grows until explicit cleanup or process restart — fine for the
    expected key cardinality (one entry per Avito report).
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        """Return cached value, or None if missing or expired."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at <= time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store value with a relative TTL."""
        if ttl_seconds <= 0:
            return
        async with self._lock:
            self._store[key] = (value, time.monotonic() + ttl_seconds)

    async def invalidate(self, key: str) -> None:
        """Remove a single key (no error if missing)."""
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        """Drop all entries."""
        async with self._lock:
            self._store.clear()

    async def size(self) -> int:
        """Return current number of stored entries (incl. expired-but-not-evicted)."""
        async with self._lock:
            return len(self._store)


# Module-level shared instance
cache = TTLCache()
