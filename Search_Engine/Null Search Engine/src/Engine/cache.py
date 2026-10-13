"""Small thread-safe TTL + LRU cache and a circuit breaker."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional


class TTLCache:
    """LRU cache whose entries expire after ``ttl`` seconds. ``ttl <= 0`` disables caching."""

    def __init__(self, maxsize: int = 256, ttl: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.maxsize = max(1, maxsize)
        self.ttl = ttl
        self._clock = clock
        self._data: "OrderedDict[Any, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any, default: Any = None) -> Any:
        if self.ttl <= 0:
            return default
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return default
            expires, value = item
            if expires < self._clock():
                del self._data[key]
                self.misses += 1
                return default
            self._data.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: Any, value: Any, ttl: Optional[float] = None) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            self._data[key] = (self._clock() + (self.ttl if ttl is None else ttl), value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures and stays open for ``cooldown`` seconds.

    Used so that being offline costs one slow attempt, not one per keystroke.
    """

    def __init__(self, threshold: int = 3, cooldown: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.threshold = threshold
        self.cooldown = cooldown
        self._clock = clock
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._clock() < self._open_until

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold:
                self._open_until = self._clock() + self.cooldown
