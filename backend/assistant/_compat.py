"""Shared lazy import helpers for assistant wrappers."""
from __future__ import annotations

from functools import lru_cache
from types import ModuleType


@lru_cache(maxsize=1)
def api_public() -> ModuleType:
    from backend import api_public as module

    return module
