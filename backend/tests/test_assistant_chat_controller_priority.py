from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public

assistant_chat = importlib.import_module("backend.assistant.chat")


class _FakeEngine:
    def __init__(self) -> None:
        self.call_count = 0
        self.session = type("Session", (), {})()
        self.session.last_intent = "play_media"
        self.session.last_dialog_state = "ask"
        self.session.pending_slots = {"__missing": ["media_name"]}
        self.session.last_update = time.time()
        self.session.interrupt_candidate = {}

    def infer(self, text: str) -> dict:
        self.call_count += 1
        return {
            "intent": "play_media",
            "intent_confidence": 0.93,
            "slots": {},
            "entities": {},
            "tokens": list(text),
            "tag_ids": [0] * len(text),
            "missing_slots": ["media_name"],
            "output_speech": "请补充媒体名称。",
            "dialog_state": "ask",
            "dialog_state_detail": "ask_missing_slot",
        }


class _InterruptConfirmEngine:
    def __init__(self) -> None:
        self.call_count = 0
        self.session = type("Session", (), {})()
        self.session.last_intent = "play_media"
        self.session.last_dialog_state = "interrupt_confirm"
        self.session.pending_slots = {"__missing": ["media_name"]}
        self.session.last_update = time.time()
        self.session.interrupt_candidate = {
            "text": "把高三一班音量调到30",
            "intent": "adjust_volume",
            "slots": {"zone_name": "高三一班", "volume": "30"},
            "created_at": time.time(),
        }

    def infer(self, text: str) -> dict:
        self.call_count += 1
        return {
            "intent": "adjust_volume",
            "intent_confidence": 0.0,
            "slots": {"zone_name": "高三一班", "volume": "30"},
            "entities": {},
            "tokens": [],
            "tag_ids": [],
            "missing_slots": [],
            "output_speech": "上一个问题我还在等您补充。您是要继续补上一个，还是改执行新指令？",
            "dialog_state": "interrupt_confirm",
            "dialog_state_detail": "confirm_interrupt_switch",
            "status": "interrupt_confirm",
        }


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


def test_chat_pending_action_wins_over_nlu_followup(monkeypatch) -> None:
    engine = _FakeEngine()

    def _handle_pending(text: str, scope: str | None = None):
        del text, scope
        return (
            "请确认按一次性还是永久执行。",
            {"intent": "move_schedule", "slots": {"schedule_name": "夏季作息"}},
            [],
        )

    monkeypatch.setattr(api_public, "ENGINE", engine)
    monkeypatch.setattr(api_public, "_handle_pending_action_for_scope", _handle_pending)

    with TestClient(api_public.app) as client:
        headers = _auth_headers()
        api_public._set_pending_action_for_scope(
            {"intent": "move_schedule", "schedule_name": "夏季作息", "created_at": "2026-04-04 10:00:00"},
            headers["X-Token"],
        )
        response = client.post("/assistant/chat", json={"text": "国歌"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["dialog_state_detail"] == "pending_action_followup"
    assert body["intent"] == "move_schedule"
    assert engine.call_count == 0
    assert engine.session.last_dialog_state is None
    assert body["pending_action"] is not None


def test_chat_interrupt_confirm_blocks_pending_action_takeover(monkeypatch) -> None:
    engine = _InterruptConfirmEngine()

    def _should_not_run(*args, **kwargs):
        raise AssertionError("pending_action handler should not run during interrupt_confirm")

    monkeypatch.setattr(api_public, "ENGINE", engine)
    monkeypatch.setattr(api_public, "_handle_pending_action_for_scope", _should_not_run)

    with TestClient(api_public.app) as client:
        headers = _auth_headers()
        api_public._set_pending_action_for_scope(
            {"intent": "move_schedule", "schedule_name": "夏季作息", "created_at": "2026-04-04 10:00:00"},
            headers["X-Token"],
        )
        response = client.post("/assistant/chat", json={"text": "执行新的"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["dialog_state_detail"] == "confirm_interrupt_switch"
    assert body["intent"] == "adjust_volume"
    assert engine.call_count == 1
    assert body["pending_action"] is None
