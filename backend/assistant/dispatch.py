"""Registry-based assistant dispatch wrappers (削减版：仅保留核心播放控制意图)."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from ._compat import api_public
from .pending import handle_pending_action
from .runtime_actions import (
    apply_play_media_intent,
    apply_play_task_intent,
    apply_stop_media_intent,
    apply_stop_task_intent,
)

ActionResult = Tuple[str, Dict[str, Any], List[dict]]
ActionHandler = Callable[[str, dict], ActionResult]
Phase1ActionHandler = Callable[[str, str, dict], Optional[ActionResult]]

PHASE1_INTENT_DISPATCH: Dict[str, ActionHandler] = {
    "play_task": apply_play_task_intent,
    "stop_task": apply_stop_task_intent,
    "play_media": apply_play_media_intent,
    "stop_media": apply_stop_media_intent,
    # "打开 X 分区"/"打开功放" 等口语被模型高置信度识别成 enable_terminal,
    # 而不是 play_media。复用 play_media handler 走 zone-only 临时任务分支。
    "enable_terminal": apply_play_media_intent,
    "disable_terminal": apply_stop_media_intent,
}

ASSISTANT_PHASE1_INTENT_DISPATCH: Dict[str, ActionHandler] = dict(PHASE1_INTENT_DISPATCH)

ACTION_DISPATCH = PHASE1_INTENT_DISPATCH


def apply_phase1_intent(intent: str, text: str, slots: dict) -> Optional[ActionResult]:
    handler = PHASE1_INTENT_DISPATCH.get(intent)
    if handler is None:
        return None
    return handler(text, slots)


def apply_phase1_intent_for_assistant(intent: str, text: str, slots: dict) -> Optional[ActionResult]:
    handler = ASSISTANT_PHASE1_INTENT_DISPATCH.get(intent)
    if handler is None:
        return None
    return handler(text, slots)


def _apply_action_with_phase1(text: str, result: dict, phase1_runner: Phase1ActionHandler) -> Optional[ActionResult]:
    module = api_public()
    pending_reply = handle_pending_action(text)
    if pending_reply:
        return pending_reply

    intent = module._normalize_intent_label(result.get("intent", ""))
    slots = result.get("slots") or {}
    if not isinstance(slots, dict):
        slots = {}

    result["intent"] = intent
    result["slots"] = slots

    if intent in module.PHASE1_INTENTS:
        return phase1_runner(intent, text, slots)

    return None


def apply_action(text: str, result: dict) -> Optional[ActionResult]:
    return _apply_action_with_phase1(text, result, apply_phase1_intent)


def apply_action_for_assistant(text: str, result: dict) -> Optional[ActionResult]:
    return _apply_action_with_phase1(text, result, apply_phase1_intent_for_assistant)


__all__ = [
    "ACTION_DISPATCH",
    "ASSISTANT_PHASE1_INTENT_DISPATCH",
    "ActionHandler",
    "ActionResult",
    "PHASE1_INTENT_DISPATCH",
    "Phase1ActionHandler",
    "apply_action",
    "apply_action_for_assistant",
    "apply_phase1_intent",
    "apply_phase1_intent_for_assistant",
]
