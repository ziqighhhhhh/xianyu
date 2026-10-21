"""Tiny in-process rate limiter for login / setup attempts."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_failures: dict[str, list[float]] = defaultdict(list)


def _prune(key: str, window: int) -> None:
    cutoff = time.monotonic() - window
    _failures[key] = [t for t in _failures.get(key, []) if t >= cutoff]


def check(key: str, limit: int = 5, window: int = 300) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    with _lock:
        _prune(key, window)
        attempts = _failures.get(key, [])
        if len(attempts) >= limit:
            retry = int(window - (time.monotonic() - attempts[0])) + 1
            return False, max(retry, 1)
        return True, 0


def failure(key: str) -> None:
    with _lock:
        _failures.setdefault(key, []).append(time.monotonic())


def reset(key: str) -> None:
    with _lock:
        _failures.pop(key, None)


def size() -> int:
    with _lock:
        return sum(len(v) for v in _failures.values())
