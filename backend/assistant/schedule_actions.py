"""Thin schedule-action wrappers around backend.api_public."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._compat import api_public

ActionResult = Tuple[str, Dict[str, Any], List[dict]]
_ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS = "all_playback_terminals"


def _api():
    return api_public()


def apply_cancel_schedule_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_cancel_schedule_intent(text, slots)


def apply_move_schedule_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_move_schedule_intent(text, slots)


def apply_swap_schedule_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_swap_schedule_intent(text, slots)


def apply_create_scheme_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_create_scheme_intent(text, slots)


def apply_create_scheme_intent_for_assistant(text: str, slots: dict) -> ActionResult:
    return _api()._apply_create_scheme_intent(
        text,
        slots,
        assistant_terminal_scope=_ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )


def apply_enable_schedule_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_enable_schedule_intent(text, slots)


def apply_disable_schedule_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_disable_schedule_intent(text, slots)


def apply_shift_schedule_later_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_shift_schedule_later_intent(text, slots)


def apply_shift_schedule_earlier_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_shift_schedule_earlier_intent(text, slots)


def apply_delete_schedule_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_delete_schedule_intent(text, slots)


def apply_replace_media_in_task_intent(text: str, slots: dict) -> ActionResult:
    return _api()._apply_replace_media_in_task_intent(text, slots)


__all__ = [
    "apply_cancel_schedule_intent",
    "apply_create_scheme_intent",
    "apply_create_scheme_intent_for_assistant",
    "apply_delete_schedule_intent",
    "apply_disable_schedule_intent",
    "apply_enable_schedule_intent",
    "apply_move_schedule_intent",
    "apply_replace_media_in_task_intent",
    "apply_shift_schedule_earlier_intent",
    "apply_shift_schedule_later_intent",
    "apply_swap_schedule_intent",
]
