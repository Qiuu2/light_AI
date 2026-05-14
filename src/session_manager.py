"""
Session state and multi-turn resolution utilities.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

PRONOUN_TRIGGERS = {"刚刚", "刚才", "上一个", "上次", "它", "这个", "那个", "正在播的"}
REPEAT_TRIGGERS = {
    "再播一次", "再放一次", "重播", "再来一遍", "重复播放", "再播一遍", "再放一遍",
    "再播一回", "再放一回", "播放一遍", "播放一次",
}
CANCEL_TRIGGERS = {"取消", "算了", "不用了", "别了", "先这样", "不用", "没事了"}
CONTINUE_PREVIOUS_TRIGGERS = {
    "继续上一个",
    "继续上个",
    "继续刚才的",
    "继续之前的",
    "继续原来的",
}
EXECUTE_NEW_TRIGGERS = {
    "执行新的",
    "执行新指令",
    "改执行新的",
    "执行这个",
    "执行当前这个",
}
WAIT_OR_REJECT_TRIGGERS = {
    "嗯",
    "嗯嗯",
    "哦",
    "好的",
    "不是",
    "不是这个",
    "等等",
    "等下",
    "先等等",
    "先想想",
    "再想想",
}
ACTION_TOKENS = {
    "播放", "停止", "暂停", "恢复", "查询", "查看", "调大", "调小", "调到", "增加", "减小",
    "创建", "新建", "删除", "替换", "对调", "挪动", "移除", "加入", "启用", "停用", "受时",
    "自检",
}
NAME_FOLLOWUP_HINTS = {"广播", "任务", "终端", "分区", "播放"}

SLOT_HINTS: Dict[str, Dict[str, object]] = {
    "source_time": {"kind": "time"},
    "end_time": {"kind": "time"},
    "time_offset": {"kind": "time_offset"},
    "play_duration": {"kind": "duration"},
    "schedule_name": {"kind": "name"},
    "media_name": {"kind": "name"},
    "new_media_name": {"kind": "name"},
    "task_name": {"kind": "name"},
    "task_type": {"kind": "name"},
    "terminal_name": {"kind": "name"},
    "zone_name": {"kind": "name"},
    "terminal_id": {"kind": "id"},
    "volume": {"kind": "volume"},
    "play_count": {"kind": "count"},
}

ASK_TTL = 60.0

_TIME_PATTERN = re.compile(
    r"\d{1,2}[:点时]\d{0,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}[日号]?|"
    r"今天|明天|后天|昨天|周[一二三四五六日天]|星期[一二三四五六日天]|上午|下午|晚上|中午|分钟|小时"
)
_EXPLICIT_ACTION_PATTERN = re.compile(
    r"(把|将|给).{0,20}(播放|停止|暂停|恢复|查询|查看|调大|调小|调到|增加|减小|创建|新建|删除|替换|对调|挪动|移除|加入|启用|停用)"
)


@dataclass
class SessionResolution:
    kind: str = "none"
    intent: Optional[str] = None
    slots: Optional[Dict[str, object]] = None
    missing_slots: Optional[List[str]] = None
    reply: str = ""
    dialog_state: Optional[str] = None
    dialog_state_detail: Optional[str] = None


@dataclass
class SessionState:
    last_intent: Optional[str] = None
    last_slots: Optional[Dict[str, object]] = None
    last_task_candidates: List[Tuple[str, str, float]] = None
    last_update: float = 0.0
    last_dialog_state: Optional[str] = None
    pending_slots: Optional[Dict[str, object]] = None
    action_history: List[Dict[str, object]] = None
    interrupt_candidate: Optional[Dict[str, object]] = None

    def __post_init__(self) -> None:
        if self.last_task_candidates is None:
            self.last_task_candidates = []
        if self.pending_slots is None:
            self.pending_slots = {}
        if self.action_history is None:
            self.action_history = []
        if self.interrupt_candidate is None:
            self.interrupt_candidate = {}

    def expired(self, ttl: float = 300.0) -> bool:
        return (time.time() - self.last_update) > ttl

    def update(
        self,
        intent: str,
        slots: Dict[str, object],
        task_candidates: List[Tuple[str, str, float]],
        dialog_state: Optional[str] = None,
        status: Optional[str] = None,
        missing_slots: Optional[List[str]] = None,
        dialog_state_detail: Optional[str] = None,
    ) -> None:
        self.last_intent = intent
        self.last_slots = slots
        self.last_task_candidates = task_candidates
        self.last_update = time.time()
        self.last_dialog_state = dialog_state
        if dialog_state == "ask":
            self.pending_slots = dict(slots) if slots else {}
            if missing_slots:
                self.pending_slots["__missing"] = list(missing_slots)
        else:
            self.pending_slots = {}
        if dialog_state != "interrupt_confirm":
            self.interrupt_candidate = {}
        if status == "success":
            self.action_history.append({"intent": intent, "slots": dict(slots)})
        if dialog_state_detail == "confirm_interrupt_switch" and self.interrupt_candidate:
            self.last_dialog_state = "interrupt_confirm"

    def clear_pending_dialog(self) -> None:
        self.last_dialog_state = None
        self.pending_slots = {}
        self.interrupt_candidate = {}

    def clear_interrupt_candidate(self) -> None:
        self.interrupt_candidate = {}
        if self.last_dialog_state == "interrupt_confirm":
            self.last_dialog_state = "ask"

    def set_interrupt_candidate(
        self,
        *,
        text: str,
        intent: str,
        slots: Dict[str, object],
        missing_slots: Optional[List[str]] = None,
    ) -> None:
        self.interrupt_candidate = {
            "text": text,
            "intent": intent,
            "slots": dict(slots or {}),
            "missing_slots": None if missing_slots is None else list(missing_slots),
            "created_at": time.time(),
        }
        self.last_dialog_state = "interrupt_confirm"
        self.last_update = time.time()


def _contains_any(text: str, phrases: set[str]) -> bool:
    if not text:
        return False
    return any(phrase and phrase in text for phrase in phrases)


def _pending_missing_keys(pending: Dict[str, object]) -> List[str]:
    missing_keys = pending.get("__missing") or []
    if isinstance(missing_keys, str):
        missing_keys = [missing_keys]
    result = [str(item).strip() for item in missing_keys if str(item).strip()]
    for key, value in pending.items():
        if key.startswith("__"):
            continue
        if not value and key not in result:
            result.append(key)
    return result


def _missing_slot_parts(missing_key: str) -> List[str]:
    return [part.strip() for part in str(missing_key or "").split("/") if part.strip()]


def _single_missing_slot(missing_keys: List[str]) -> Optional[str]:
    if len(missing_keys) != 1:
        return None
    parts = _missing_slot_parts(missing_keys[0])
    if len(parts) != 1:
        return None
    return parts[0]


def _slots_cover_missing(slots: Dict[str, object], missing_keys: List[str]) -> bool:
    if not slots:
        return False
    for missing_key in missing_keys:
        parts = _missing_slot_parts(missing_key)
        if any(slots.get(part) for part in parts):
            return True
    return False


def _looks_like_time_text(text: str) -> bool:
    return bool(_TIME_PATTERN.search(text))


def _looks_like_explicit_action_command(text: str, current_slots: Dict[str, object]) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if _EXPLICIT_ACTION_PATTERN.search(cleaned):
        return True
    if len(current_slots or {}) >= 2 and _contains_any(cleaned, ACTION_TOKENS):
        return True
    return False


def _slot_aware_short_followup(
    text: str,
    missing_keys: List[str],
    current_slots: Dict[str, object],
) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if _slots_cover_missing(current_slots, missing_keys):
        return True

    single_slot = _single_missing_slot(missing_keys)
    if not single_slot:
        return False

    slot_kind = str(SLOT_HINTS.get(single_slot, {}).get("kind") or "")
    if slot_kind == "time":
        return len(cleaned) <= 20 and _looks_like_time_text(cleaned) and not _contains_any(cleaned, ACTION_TOKENS)
    if slot_kind in {"time_offset", "duration"}:
        return len(cleaned) <= 16 and _looks_like_time_text(cleaned) and not _contains_any(cleaned, ACTION_TOKENS)
    if slot_kind == "id":
        return cleaned.isdigit() and len(cleaned) <= 12
    if slot_kind in {"volume", "count"}:
        if cleaned.isdigit():
            return True
        return len(cleaned) <= 10 and not _contains_any(cleaned, ACTION_TOKENS)
    if slot_kind == "name":
        if len(cleaned) > 20:
            return False
        if _looks_like_explicit_action_command(cleaned, current_slots):
            return False
        if _contains_any(cleaned, NAME_FOLLOWUP_HINTS):
            return True
        return not _contains_any(cleaned, ACTION_TOKENS)
    return len(cleaned) <= 12 and not _contains_any(cleaned, ACTION_TOKENS)


def _should_interrupt_ask(
    last_intent: str,
    current_intent: str,
    current_slots: Dict[str, object],
    missing_keys: List[str],
    text: str,
) -> bool:
    if not current_intent or current_intent == "none":
        return False
    if current_intent != last_intent:
        return True
    if _slot_aware_short_followup(text, missing_keys, current_slots):
        return False
    return bool(current_slots) or _contains_any(text, ACTION_TOKENS)


def _should_replace_interrupt_candidate(
    current_intent: str,
    current_slots: Dict[str, object],
    text: str,
) -> bool:
    if _contains_any(text, WAIT_OR_REJECT_TRIGGERS):
        return False
    if not current_intent or current_intent == "none":
        return False
    return bool(current_slots) or _contains_any(text, ACTION_TOKENS)


def _inject_single_slot_value(
    incoming_slots: Dict[str, object],
    text: str,
    missing_keys: List[str],
) -> Dict[str, object]:
    merged = dict(incoming_slots or {})
    single_slot = _single_missing_slot(missing_keys)
    cleaned = str(text or "").strip()
    if not single_slot or not cleaned:
        return merged
    if merged.get(single_slot):
        return merged
    if not _slot_aware_short_followup(cleaned, missing_keys, merged):
        return merged
    merged[single_slot] = cleaned
    return merged


def _merge_pending_slots(
    pending: Dict[str, object],
    incoming_slots: Dict[str, object],
    text: str,
    missing_keys: List[str],
) -> Dict[str, object]:
    merged = _inject_single_slot_value(incoming_slots, text, missing_keys)
    for key, value in pending.items():
        if key.startswith("__"):
            continue
        if key not in merged or not merged.get(key):
            merged[key] = value
    return merged


def _interrupt_confirm_reply() -> str:
    return "上一个问题还没收完。继续刚才的，回复“继续上一个”；改办新的，回复“执行新的”；不继续就说“取消”或“算了”。"


def _cancel_reply() -> str:
    return "好，这个问题先停在这里。后面直接说新的指令就行。"


def resolve_with_session(
    session: SessionState,
    intent: str,
    slots: Dict[str, object],
    text: str,
    standard_time: Optional[str],
) -> Optional[SessionResolution]:
    """Resolve multi-turn dialog by merging pending slots from previous turn."""
    del standard_time
    if session.expired():
        return None

    if session.last_dialog_state == "interrupt_confirm" and session.interrupt_candidate:
        ask_elapsed = time.time() - session.last_update
        if ask_elapsed > ASK_TTL:
            session.clear_pending_dialog()
            return None

        if _contains_any(text, CANCEL_TRIGGERS):
            session.clear_pending_dialog()
            return SessionResolution(
                kind="cancel",
                intent="none",
                slots={},
                missing_slots=[],
                reply=_cancel_reply(),
                dialog_state="complete",
                dialog_state_detail="complete",
            )

        if _contains_any(text, CONTINUE_PREVIOUS_TRIGGERS) and session.last_intent:
            pending = session.pending_slots or {}
            missing_keys = _pending_missing_keys(pending)
            session.clear_interrupt_candidate()
            session.last_dialog_state = "ask"
            session.last_update = time.time()
            return SessionResolution(
                kind="continue_previous",
                intent=session.last_intent,
                slots={k: v for k, v in pending.items() if not k.startswith("__")},
                missing_slots=missing_keys,
                dialog_state="ask",
                dialog_state_detail="ask_missing_slot",
            )

        if _contains_any(text, EXECUTE_NEW_TRIGGERS):
            candidate = dict(session.interrupt_candidate or {})
            session.clear_pending_dialog()
            return SessionResolution(
                kind="execute_interrupt_candidate",
                intent=str(candidate.get("intent") or intent or "none"),
                slots=dict(candidate.get("slots") or {}),
                missing_slots=(
                    None
                    if candidate.get("missing_slots") is None
                    else list(candidate.get("missing_slots") or [])
                ),
            )

        if _should_replace_interrupt_candidate(intent, slots, text):
            session.set_interrupt_candidate(
                text=text,
                intent=intent,
                slots=slots,
            )

        return SessionResolution(
            kind="interrupt_confirm",
            intent=str((session.interrupt_candidate or {}).get("intent") or intent or "none"),
            slots=dict((session.interrupt_candidate or {}).get("slots") or slots or {}),
            missing_slots=[],
            reply=_interrupt_confirm_reply(),
            dialog_state="interrupt_confirm",
            dialog_state_detail="confirm_interrupt_switch",
        )

    if session.last_dialog_state == "ask" and session.last_intent:
        ask_elapsed = time.time() - session.last_update
        if ask_elapsed > ASK_TTL:
            session.clear_pending_dialog()
            return None

        if _contains_any(text, CANCEL_TRIGGERS):
            return SessionResolution(
                kind="cancel",
                intent="none",
                slots={},
                missing_slots=[],
                reply=_cancel_reply(),
                dialog_state="complete",
                dialog_state_detail="complete",
            )

        pending = session.pending_slots or {}
        missing_keys = _pending_missing_keys(pending)

        if missing_keys:
            if _should_interrupt_ask(session.last_intent, intent, slots, missing_keys, text):
                session.set_interrupt_candidate(
                    text=text,
                    intent=intent,
                    slots=slots,
                )
                return SessionResolution(
                    kind="interrupt_confirm",
                    intent=intent,
                    slots=dict(slots or {}),
                    missing_slots=[],
                    reply=_interrupt_confirm_reply(),
                    dialog_state="interrupt_confirm",
                    dialog_state_detail="confirm_interrupt_switch",
                )
            return SessionResolution(
                kind="followup",
                intent=session.last_intent,
                slots=_merge_pending_slots(pending, slots, text, missing_keys),
                dialog_state="ask",
                dialog_state_detail="ask_missing_slot",
            )

        if intent and session.last_intent and intent != session.last_intent and intent != "none":
            return None

        return SessionResolution(
            kind="followup",
            intent=session.last_intent,
            slots=_merge_pending_slots(pending, slots, text, []),
            dialog_state="complete",
            dialog_state_detail="complete",
        )

    pronoun_hit = any(word in text for word in PRONOUN_TRIGGERS)
    repeat_hit = any(word in text for word in REPEAT_TRIGGERS)
    if not (pronoun_hit or repeat_hit):
        return None

    if session.last_slots and "task_name" not in slots:
        last_task = session.last_slots.get("task_name")
        if last_task:
            slots["task_name"] = last_task

    return SessionResolution(kind="pronoun", slots=slots, dialog_state_detail="complete")
