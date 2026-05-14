from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.session_manager import SessionState, resolve_with_session


def _ask_session(*, missing: list[str] | None = None, slots: dict | None = None) -> SessionState:
    session = SessionState()
    session.last_intent = "play_media"
    session.last_dialog_state = "ask"
    session.pending_slots = dict(slots or {})
    session.pending_slots["__missing"] = list(missing or ["media_name"])
    session.last_update = time.time()
    return session


def _interrupt_session() -> SessionState:
    session = _ask_session()
    session.last_dialog_state = "interrupt_confirm"
    session.interrupt_candidate = {
        "text": "把高三一班音量调到30",
        "intent": "adjust_volume",
        "slots": {"zone_name": "高三一班", "volume": "30"},
        "missing_slots": None,
        "created_at": time.time(),
    }
    return session


def test_ask_short_followup_fills_missing_slot() -> None:
    session = _ask_session()

    resolution = resolve_with_session(session, "none", {}, "国歌", None)

    assert resolution is not None
    assert resolution.kind == "followup"
    assert resolution.intent == "play_media"
    assert resolution.slots == {"media_name": "国歌"}
    assert resolution.dialog_state_detail == "ask_missing_slot"


def test_ask_new_command_enters_interrupt_confirm() -> None:
    session = _ask_session()

    resolution = resolve_with_session(
        session,
        "adjust_volume",
        {"zone_name": "高三一班", "volume": "30"},
        "把高三一班音量调到30",
        None,
    )

    assert resolution is not None
    assert resolution.kind == "interrupt_confirm"
    assert resolution.dialog_state_detail == "confirm_interrupt_switch"
    assert session.last_dialog_state == "interrupt_confirm"
    assert session.pending_slots == {"__missing": ["media_name"]}
    assert session.interrupt_candidate["intent"] == "adjust_volume"
    assert session.interrupt_candidate["slots"] == {"zone_name": "高三一班", "volume": "30"}


def test_cancel_returns_terminal_resolution_only_during_ask() -> None:
    session = _ask_session()

    resolution = resolve_with_session(session, "cancel_schedule", {}, "算了", None)

    assert resolution is not None
    assert resolution.kind == "cancel"
    assert resolution.intent == "none"
    assert resolution.dialog_state_detail == "complete"


def test_interrupt_confirm_can_resume_previous_question() -> None:
    session = _interrupt_session()

    resolution = resolve_with_session(session, "none", {}, "继续上一个", None)

    assert resolution is not None
    assert resolution.kind == "continue_previous"
    assert resolution.intent == "play_media"
    assert resolution.missing_slots == ["media_name"]
    assert session.last_dialog_state == "ask"
    assert session.interrupt_candidate == {}


def test_interrupt_confirm_waiting_reply_keeps_original_candidate() -> None:
    session = _interrupt_session()

    resolution = resolve_with_session(session, "none", {}, "嗯", None)

    assert resolution is not None
    assert resolution.kind == "interrupt_confirm"
    assert resolution.intent == "adjust_volume"
    assert resolution.slots == {"zone_name": "高三一班", "volume": "30"}
    assert session.interrupt_candidate["text"] == "把高三一班音量调到30"


def test_interrupt_confirm_only_replaces_candidate_with_new_command() -> None:
    session = _interrupt_session()

    resolution = resolve_with_session(
        session,
        "play_task",
        {"task_name": "运动会广播"},
        "播放运动会广播",
        None,
    )

    assert resolution is not None
    assert resolution.kind == "interrupt_confirm"
    assert session.interrupt_candidate["intent"] == "play_task"
    assert session.interrupt_candidate["slots"] == {"task_name": "运动会广播"}


def test_slot_value_with_business_nouns_stays_followup() -> None:
    session = _ask_session()

    resolution = resolve_with_session(session, "none", {}, "广播体操", None)

    assert resolution is not None
    assert resolution.kind == "followup"
    assert resolution.slots == {"media_name": "广播体操"}


def test_composite_missing_reply_without_extraction_is_not_forced() -> None:
    session = _ask_session(missing=["zone_name/terminal_id/terminal_name"])

    resolution = resolve_with_session(session, "none", {}, "高三终端", None)

    assert resolution is not None
    assert resolution.kind == "followup"
    assert resolution.slots == {}


def test_ask_timeout_drops_stale_pending_state() -> None:
    session = _ask_session()
    session.last_update = time.time() - 120

    resolution = resolve_with_session(session, "adjust_volume", {"volume": "30"}, "音量30", None)

    assert resolution is None
    assert session.last_dialog_state is None
    assert session.pending_slots == {}
