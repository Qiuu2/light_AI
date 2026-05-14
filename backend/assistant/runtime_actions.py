"""Runtime-domain assistant actions (削减版：仅保留核心播放控制)."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._compat import api_public

ActionResult = Tuple[str, Dict[str, Any], List[dict]]


def _module():
    return api_public()


def apply_play_task_intent(text: str, slots: dict) -> ActionResult:
    module = _module()
    return module._apply_runtime_task_state_change(
        "play_task",
        text,
        slots,
        state_value=1,
        action_name="play_task",
        action_text="执行",
        check_terminal_status=True,
    )


def apply_stop_task_intent(text: str, slots: dict) -> ActionResult:
    module = _module()
    return module._apply_runtime_task_state_change(
        "stop_task",
        text,
        slots,
        state_value=0,
        action_name="stop_task",
        action_text="停止",
    )


def apply_play_media_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_play_media_intent(text, slots)


def apply_stop_media_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_stop_media_intent(text, slots)


__all__ = [
    "apply_play_media_intent",
    "apply_play_task_intent",
    "apply_stop_media_intent",
    "apply_stop_task_intent",
]
