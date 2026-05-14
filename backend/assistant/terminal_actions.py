"""Terminal-domain assistant actions."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fastapi import HTTPException

from ._compat import api_public

ActionResult = Tuple[str, Dict[str, Any], List[dict]]


def _module():
    return api_public()


def _result(reply: str, *, action: str, details: dict | None = None) -> ActionResult:
    module = _module()
    return (
        reply,
        {"missing_slots": []},
        [
            module._build_action_log(
                action,
                "",
                [],
                mode="runtime",
                details=details or {},
            )
        ],
    )


def _remote_guard(action_text: str) -> ActionResult | None:
    if not _module()._remote_enabled():
        return (f"未配置远端服务,无法执行{action_text}。", {"missing_slots": []}, [])
    return None


def apply_query_terminal_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_query_terminal_intent(text, slots)


def _apply_terminal_state_change(*, enabled: bool, action_name: str, slots: dict) -> ActionResult:
    module = _module()
    if enabled:
        return module._apply_enable_terminal_intent("", slots)
    return module._apply_disable_terminal_intent("", slots)


def apply_enable_terminal_intent(text: str, slots: dict) -> ActionResult:
    return _apply_terminal_state_change(enabled=True, action_name="enable_terminal", slots=slots)


def apply_disable_terminal_intent(text: str, slots: dict) -> ActionResult:
    return _apply_terminal_state_change(enabled=False, action_name="disable_terminal", slots=slots)


def apply_sync_terminal_time_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_sync_terminal_time_intent(text, slots)


def apply_check_terminal_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_check_terminal_intent(text, slots)


def apply_create_zone_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_create_zone_intent(text, slots)


def apply_delete_zone_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_delete_zone_intent(text, slots)


def _apply_add_remove_terminal_to_zone_intent(text: str, slots: dict, *, add: bool, action_name: str) -> ActionResult:
    return _module()._apply_add_remove_terminal_to_zone_intent(
        text,
        slots,
        add=add,
        action_name=action_name,
    )


def apply_add_terminal_to_zone_intent(text: str, slots: dict) -> ActionResult:
    return _apply_add_remove_terminal_to_zone_intent(text, slots, add=True, action_name="add_terminal_to_zone")


def apply_remove_terminal_from_zone_intent(text: str, slots: dict) -> ActionResult:
    return _apply_add_remove_terminal_to_zone_intent(text, slots, add=False, action_name="remove_terminal_from_zone")


def apply_add_terminal_to_task_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_add_remove_terminal_to_task_intent(text, slots, add=True, action_name="add_terminal_to_task")


def apply_remove_terminal_from_task_intent(text: str, slots: dict) -> ActionResult:
    return _module()._apply_add_remove_terminal_to_task_intent(
        text,
        slots,
        add=False,
        action_name="remove_terminal_from_task",
    )


__all__ = [
    "apply_add_terminal_to_task_intent",
    "apply_add_terminal_to_zone_intent",
    "apply_check_terminal_intent",
    "apply_create_zone_intent",
    "apply_delete_zone_intent",
    "apply_disable_terminal_intent",
    "apply_enable_terminal_intent",
    "apply_query_terminal_intent",
    "apply_remove_terminal_from_task_intent",
    "apply_remove_terminal_from_zone_intent",
    "apply_sync_terminal_time_intent",
]
