from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import engine as engine_module
from src.response_manager import ResponseManager
from src.session_manager import SessionState


def _slots_from_entities(entities: dict) -> dict:
    slots: dict = {}
    for key, values in entities.items():
        if values:
            slots[key] = values[0]
    return slots


def _build_engine(script: dict[str, tuple[str, float, dict]]) -> engine_module.JointInferenceEngine:
    engine = engine_module.JointInferenceEngine.__new__(engine_module.JointInferenceEngine)
    engine.session = SessionState()
    engine.responder = ResponseManager()

    def _run_model(text: str):
        intent, confidence, entities = script[text]
        return intent, confidence, entities, list(text), [1] * len(text)

    def _check_missing(intent: str, slots: dict) -> list[str]:
        if intent == "play_media" and not slots.get("media_name"):
            return ["media_name"]
        if intent == "adjust_volume" and not slots.get("volume"):
            return ["volume"]
        return []

    engine._run_model = _run_model
    engine._post_process_slots = lambda entities, intent: _slots_from_entities(entities)
    engine._check_missing_slots = _check_missing
    engine._intent_cmd = lambda intent: 7 if intent != "none" else -1
    return engine


def test_engine_interrupt_confirm_prevents_swallowing_new_command() -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "把高三一班音量调到30": ("adjust_volume", 0.97, {"zone_name": ["高三一班"], "volume": ["30"]}),
        }
    )

    first = engine.infer("播放")
    second = engine.infer("把高三一班音量调到30")

    assert first["intent"] == "play_media"
    assert first["missing_slots"] == ["media_name"]
    assert first["dialog_state_detail"] == "ask_missing_slot"
    assert "取消" in first["output_speech"]
    assert second["status"] == "interrupt_confirm"
    assert second["dialog_state_detail"] == "confirm_interrupt_switch"
    assert "继续上一个" in second["output_speech"]
    assert engine.session.last_dialog_state == "interrupt_confirm"
    assert engine.session.pending_slots["__missing"] == ["media_name"]


def test_engine_normalizes_play_task_media_name_before_missing_slot_check() -> None:
    engine = _build_engine(
        {
            "播放喜羊羊": ("play_task", 0.99, {"media_name": ["喜羊羊"]}),
        }
    )

    def _check_missing(intent: str, slots: dict) -> list[str]:
        if intent == "play_task" and not slots.get("task_name"):
            return ["task_name"]
        if intent == "play_media" and not slots.get("media_name"):
            return ["media_name"]
        return []

    engine._check_missing_slots = _check_missing

    result = engine.infer("播放喜羊羊")

    assert result["intent"] == "play_task"
    assert result["slots"]["media_name"] == "喜羊羊"
    assert result["slots"]["task_name"] == "喜羊羊"
    assert result.get("missing_slots", []) == []
    assert result["dialog_state_detail"] == "complete"
    assert engine.session.last_dialog_state == "complete"
    assert engine.session.pending_slots == {}


def test_engine_cancel_during_ask_does_not_execute_misclassified_intent() -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "取消": ("cancel_schedule", 0.99, {"schedule_name": ["默认作息"]}),
        }
    )

    engine.infer("播放")
    result = engine.infer("取消")

    assert result["intent"] == "none"
    assert result["status"] == "success"
    assert result["dialog_state_detail"] == "complete"
    assert result["cmd"] == -1
    assert engine.session.pending_slots == {}


def test_engine_execute_new_uses_cached_interrupt_candidate_after_waiting_reply() -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "把高三一班音量调到30": ("adjust_volume", 0.97, {"zone_name": ["高三一班"], "volume": ["30"]}),
            "嗯": ("none", 0.99, {}),
            "执行新的": ("none", 0.99, {}),
        }
    )

    engine.infer("播放")
    engine.infer("把高三一班音量调到30")
    waiting = engine.infer("嗯")
    third = engine.infer("执行新的")

    assert waiting["status"] == "interrupt_confirm"
    assert waiting["intent"] == "adjust_volume"
    assert third["intent"] == "adjust_volume"
    assert third["status"] == "success"
    assert third["slots"] == {"zone_name": "高三一班", "volume": "30"}
    assert third["dialog_state_detail"] == "complete"
    assert engine.session.last_dialog_state == "complete"
    assert engine.session.pending_slots == {}


def test_engine_continue_previous_reasks_original_missing_slot() -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "把高三一班音量调到30": ("adjust_volume", 0.97, {"zone_name": ["高三一班"], "volume": ["30"]}),
            "继续上一个": ("none", 0.99, {}),
        }
    )

    engine.infer("播放")
    engine.infer("把高三一班音量调到30")
    third = engine.infer("继续上一个")

    assert third["intent"] == "play_media"
    assert third["missing_slots"] == ["media_name"]
    assert third["dialog_state_detail"] == "ask_missing_slot"
    assert "取消" in third["output_speech"]
    assert engine.session.last_dialog_state == "ask"
    assert engine.session.pending_slots["__missing"] == ["media_name"]
