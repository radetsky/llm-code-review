import time


class Cache:
    """A small in-memory cache."""

    def __init__(self):
        self._items = {}

    def set(self, key, value, ttl_ms: int = 60_000):
        self._items[key] = (value, time.monotonic() * 1000 + ttl_ms)

    def get(self, key):
        item = self._items.get(key)
        if item is None:
            return None
        value, expires = item
        if time.monotonic() * 1000 > expires:
            del self._items[key]
            return None
        return value
