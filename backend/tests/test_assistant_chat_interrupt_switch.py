from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public
from src import engine as engine_module
from src.response_manager import ResponseManager
from src.session_manager import SessionState

assistant_chat = importlib.import_module("backend.assistant.chat")


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


def _auth_headers() -> dict[str, str]:
    session = api_public._create_local_session("remote-test-token", "tester", "test")
    return {"X-Token": session["token"]}


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch):
    original_logs = deepcopy(api_public.DATA_STORE["assistant_command_logs"])
    api_public._store_set(
        "assistant_command_logs",
        api_public._normalize_assistant_command_logs_payload({"items": []}),
    )
    api_public._clear_pending_action()
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)
    yield
    api_public.DATA_STORE["assistant_command_logs"] = original_logs
    api_public._clear_pending_action()


def test_chat_confirms_before_switching_to_new_command(monkeypatch) -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "把高三一班音量调到30": ("adjust_volume", 0.97, {"zone_name": ["高三一班"], "volume": ["30"]}),
        }
    )

    def _apply_action(text: str, result: dict):
        if result["intent"] == "play_media":
            return ("请补充媒体名称。如果不继续这个问题，可以说“取消”或“算了”。", {"missing_slots": ["media_name"]}, [])
        if result["intent"] == "adjust_volume":
            return ("已调整音量。", {"missing_slots": []}, [{"action": "adjust_volume"}])
        return None

    monkeypatch.setattr(api_public, "ENGINE", engine)
    monkeypatch.setattr(assistant_chat, "apply_action", _apply_action)

    with TestClient(api_public.app) as client:
        headers = _auth_headers()
        first = client.post("/assistant/chat", json={"text": "播放"}, headers=headers)
        second = client.post("/assistant/chat", json={"text": "把高三一班音量调到30"}, headers=headers)

    assert first.status_code == 200
    assert first.json()["missing_slots"] == ["media_name"]
    assert first.json()["dialog_state_detail"] == "ask_missing_slot"
    assert "取消" in first.json()["reply"]
    assert second.status_code == 200
    assert second.json()["dialog_state_detail"] == "confirm_interrupt_switch"
    assert second.json()["reply"].count("继续上一个") == 1
    assert second.json()["action_log"] == []


def test_chat_execute_new_reuses_cached_candidate_without_retyping(monkeypatch) -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "把高三一班音量调到30": ("adjust_volume", 0.97, {"zone_name": ["高三一班"], "volume": ["30"]}),
            "嗯": ("none", 0.99, {}),
            "执行新的": ("none", 0.99, {}),
        }
    )

    def _apply_action(text: str, result: dict):
        if result["intent"] == "play_media":
            return ("请补充媒体名称。如果不继续这个问题，可以说“取消”或“算了”。", {"missing_slots": ["media_name"]}, [])
        if result["intent"] == "adjust_volume":
            return ("已调整音量。", {"missing_slots": []}, [{"action": "adjust_volume", "text": text}])
        return None

    monkeypatch.setattr(api_public, "ENGINE", engine)
    monkeypatch.setattr(assistant_chat, "apply_action", _apply_action)

    with TestClient(api_public.app) as client:
        headers = _auth_headers()
        client.post("/assistant/chat", json={"text": "播放"}, headers=headers)
        client.post("/assistant/chat", json={"text": "把高三一班音量调到30"}, headers=headers)
        waiting = client.post("/assistant/chat", json={"text": "嗯"}, headers=headers)
        third = client.post("/assistant/chat", json={"text": "执行新的"}, headers=headers)

    assert waiting.status_code == 200
    assert waiting.json()["dialog_state_detail"] == "confirm_interrupt_switch"
    assert third.status_code == 200
    body = third.json()
    assert body["reply"] == "已调整音量。"
    assert body["intent"] == "adjust_volume"
    assert body["dialog_state_detail"] == "complete"
    assert body["slots"] == {"zone_name": "高三一班", "volume": "30"}
    assert body["action_log"] == [{"action": "adjust_volume", "text": "执行新的"}]


def test_chat_continue_previous_returns_to_original_ask(monkeypatch) -> None:
    engine = _build_engine(
        {
            "播放": ("play_media", 0.96, {}),
            "把高三一班音量调到30": ("adjust_volume", 0.97, {"zone_name": ["高三一班"], "volume": ["30"]}),
            "继续上一个": ("none", 0.99, {}),
        }
    )

    def _apply_action(text: str, result: dict):
        if result["intent"] == "play_media":
            return ("请补充媒体名称。如果不继续这个问题，可以说“取消”或“算了”。", {"missing_slots": ["media_name"]}, [])
        if result["intent"] == "adjust_volume":
            return ("已调整音量。", {"missing_slots": []}, [{"action": "adjust_volume"}])
        return None

    monkeypatch.setattr(api_public, "ENGINE", engine)
    monkeypatch.setattr(assistant_chat, "apply_action", _apply_action)

    with TestClient(api_public.app) as client:
        headers = _auth_headers()
        client.post("/assistant/chat", json={"text": "播放"}, headers=headers)
        client.post("/assistant/chat", json={"text": "把高三一班音量调到30"}, headers=headers)
        third = client.post("/assistant/chat", json={"text": "继续上一个"}, headers=headers)

    assert third.status_code == 200
    body = third.json()
    assert body["intent"] == "play_media"
    assert body["missing_slots"] == ["media_name"]
    assert body["dialog_state_detail"] == "ask_missing_slot"
    assert "取消" in body["reply"]
    assert body["action_log"] == []


def test_chat_backend_followup_sync_uses_session_update(monkeypatch) -> None:
    engine = _build_engine(
        {
            "同步任务": ("query_task", 0.95, {}),
            "运动会广播": ("none", 0.99, {}),
        }
    )
    before = engine.session.last_update

    def _apply_action(text: str, result: dict):
        if text == "同步任务":
            return (
                "请补充任务名称。如果不继续这个问题，可以说“取消”或“算了”。",
                {"missing_slots": ["task_name"], "dialog_state_detail": "ask_missing_slot"},
                [],
            )
        return None

    monkeypatch.setattr(api_public, "ENGINE", engine)
    monkeypatch.setattr(assistant_chat, "apply_action", _apply_action)

    with TestClient(api_public.app) as client:
        headers = _auth_headers()
        first = client.post("/assistant/chat", json={"text": "同步任务"}, headers=headers)

    body = first.json()
    assert body["dialog_state_detail"] == "ask_missing_slot"
    assert engine.session.last_dialog_state == "ask"
    assert engine.session.pending_slots["__missing"] == ["task_name"]
    assert engine.session.last_update >= before


def test_chat_successful_runtime_play_clears_stale_ask_state(monkeypatch) -> None:
    engine = _build_engine(
        {
            "播放喜羊羊": ("play_task", 0.99, {"media_name": ["喜羊羊"]}),
            "停止喜羊羊": ("stop_task", 0.99, {"task_name": ["喜羊羊"]}),
        }
    )

    def _check_missing(intent: str, slots: dict) -> list[str]:
        if intent == "play_task" and not slots.get("task_name"):
            return ["task_name"]
        return []

    def _apply_action(text: str, result: dict):
        if result["intent"] == "play_task":
            return (
                "任务“喜羊羊”现在是开始播放状态。",
                {
                    "intent": "play_task",
                    "slots": {"media_name": "喜羊羊", "task_name": "喜羊羊"},
                    "missing_slots": [],
                },
                [{"action": "play_task"}],
            )
        if result["intent"] == "stop_task":
            return (
                "任务“喜羊羊”现在是停止状态。",
                {"slots": {"task_name": "喜羊羊"}, "missing_slots": []},
                [{"action": "stop_task"}],
            )
        return None

    engine._check_missing_slots = _check_missing
    monkeypatch.setattr(api_public, "ENGINE", engine)
    monkeypatch.setattr(assistant_chat, "apply_action", _apply_action)

    with TestClient(api_public.app) as client:
        headers = _auth_headers()
        first = client.post("/assistant/chat", json={"text": "播放喜羊羊"}, headers=headers)
        second = client.post("/assistant/chat", json={"text": "停止喜羊羊"}, headers=headers)

    first_body = first.json()
    assert first.status_code == 200
    assert first_body["intent"] == "play_task"
    assert first_body["slots"] == {"media_name": "喜羊羊", "task_name": "喜羊羊"}
    assert first_body["missing_slots"] == []
    assert first_body["dialog_state_detail"] == "complete"
    assert engine.session.last_dialog_state is None
    assert engine.session.pending_slots == {}

    second_body = second.json()
    assert second.status_code == 200
    assert second_body["intent"] == "stop_task"
    assert second_body["missing_slots"] == []
    assert second_body["dialog_state_detail"] == "complete"
    assert second_body["action_log"] == [{"action": "stop_task"}]
    assert "继续上一个" not in second_body["reply"]
