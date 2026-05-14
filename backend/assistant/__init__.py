"""Assistant-layer compatibility wrappers for api_public split."""
from __future__ import annotations

from .chat import chat, chat_api, infer, infer_api
from .dispatch import (
    ACTION_DISPATCH,
    PHASE1_INTENT_DISPATCH,
    apply_action,
    apply_action_for_assistant,
    apply_phase1_intent,
    apply_phase1_intent_for_assistant,
)
from .pending import handle_pending_action
from .reply import build_reply, compute_missing

__all__ = [
    "ACTION_DISPATCH",
    "PHASE1_INTENT_DISPATCH",
    "apply_action",
    "apply_action_for_assistant",
    "apply_phase1_intent",
    "apply_phase1_intent_for_assistant",
    "build_reply",
    "chat",
    "chat_api",
    "compute_missing",
    "handle_pending_action",
    "infer",
    "infer_api",
]
