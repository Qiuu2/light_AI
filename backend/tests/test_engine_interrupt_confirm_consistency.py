from __future__ import annotations

from pathlib import Path
import sys

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


def test_interrupt_confirm_waiting_reply_does_not_leak_current_turn_nlu_fields() -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "把高三一班音量调到30": ("adjust_volume", 0.97, {"zone_name": ["高三一班"], "volume": ["30"]}),
            "嗯": ("none", 0.99, {}),
        }
    )

    engine.infer("播放")
    engine.infer("把高三一班音量调到30")
    result = engine.infer("嗯")

    assert result["dialog_state_detail"] == "confirm_interrupt_switch"
    assert result["intent"] == "adjust_volume"
    assert result["intent_confidence"] == 0.0
    assert result["entities"] == {}
    assert result["tokens"] == []
    assert result["tag_ids"] == []
