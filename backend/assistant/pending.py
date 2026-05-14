"""Pending-action assistant wrapper.

The source of truth for pending orchestration lives in ``backend.api_public``.
Keep the assistant entrypoint as a thin wrapper so the production assistant
route, debug helpers, and legacy compatibility paths share exactly one pending
implementation.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ._compat import api_public

ActionResult = Tuple[str, Dict[str, object], List[dict]]


def handle_pending_action(text: str) -> Optional[ActionResult]:
    module = api_public()
    return module._handle_pending_action(text)


__all__ = ["handle_pending_action"]
