"""
Caching layer: in-memory caches with TTL support.
"""
from __future__ import annotations

import time
import threading
from typing import Any, Dict, Optional, Tuple

from backend.config import REMOTE_CACHE_SECONDS

REMOTE_CACHE: Dict[str, Tuple[float, object]] = {}
TTL_CACHE: Dict[str, Tuple[float, float, object]] = {}
DATA_STORE_LOCK = threading.Lock()


def cache_get(key: str) -> Optional[object]:
    if REMOTE_CACHE_SECONDS <= 0:
        return None
    cached = REMOTE_CACHE.get(key)
    if not cached:
        return None
    ts, payload = cached
    if time.time() - ts > REMOTE_CACHE_SECONDS:
        return None
    return payload


def cache_set(key: str, payload: object) -> None:
    if REMOTE_CACHE_SECONDS <= 0:
        return
    REMOTE_CACHE[key] = (time.time(), payload)


def ttl_cache_get(key: str) -> Optional[object]:
    cached = TTL_CACHE.get(key)
    if not cached:
        return None
    ts, ttl_seconds, payload = cached
    if ttl_seconds <= 0:
        return payload
    if time.time() - ts > ttl_seconds:
        return None
    return payload


def ttl_cache_set(key: str, payload: object, ttl_seconds: float) -> None:
    TTL_CACHE[key] = (time.time(), ttl_seconds, payload)
