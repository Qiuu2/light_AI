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

assistant_chat = importlib.import_module("backend.assistant.chat")


@pytest.fixture(autouse=True)
def _isolate_assistant_command_logs(monkeypatch):
    original_entry = deepcopy(api_public.DATA_STORE["assistant_command_logs"])
    api_public._store_set(
        "assistant_command_logs",
        api_public._normalize_assistant_command_logs_payload({"items": []}),
    )
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)
    yield
    api_public.DATA_STORE["assistant_command_logs"] = original_entry


def _fake_infer_result(intent: str = "play_media", slots: dict | None = None) -> dict:
    return {
        "intent": intent,
        "intent_confidence": 0.93,
        "slots": slots or {"media_name": "国歌"},
        "missing_slots": [],
        "entities": {},
        "tokens": [],
        "tag_ids": [],
    }


def _action_log() -> list[dict]:
    return [
        api_public._build_action_log(
            "play_now",
            "校园广播",
            ["1001"],
            details={"audio": "国歌"},
        )
    ]


def _auth_headers() -> dict[str, str]:
    session = api_public._create_local_session("remote-test-token", "tester", "test")
    return {"X-Token": session["token"]}


def test_chat_api_persists_successful_command_log(monkeypatch) -> None:
    writes: dict = {}

    class FakeEngine:
        def __init__(self) -> None:
            self.session = type("Session", (), {})()

        def infer(self, text: str) -> dict:
            assert text == "播放国歌"
            return _fake_infer_result()

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())
    monkeypatch.setattr(
        assistant_chat,
        "apply_action",
        lambda text, result: ("已播放国歌。", {}, _action_log()),
    )
    monkeypatch.setattr(
        api_public,
        "_write_json",
        lambda path, payload: writes.update({"path": path, "payload": deepcopy(payload)}),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "播放国歌"}, headers=_auth_headers())

    assert response.status_code == 200
    stored = api_public._load_assistant_command_logs_payload()
    assert len(stored["items"]) == 1
    entry = stored["items"][0]
    assert writes["path"] == api_public.ASSISTANT_COMMAND_LOGS_PATH
    assert entry == {"text": "播放国歌", "reply": "已播放国歌。"}


def test_chat_api_skips_log_when_action_log_is_empty(monkeypatch) -> None:
    write_calls = {"count": 0}

    class FakeEngine:
        def __init__(self) -> None:
            self.session = type("Session", (), {})()

        def infer(self, text: str) -> dict:
            assert text == "帮我改一下"
            return _fake_infer_result(intent="move_schedule", slots={"schedule_name": "春季作息"})

    def _count_write(path, payload) -> None:
        del path, payload
        write_calls["count"] += 1

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())
    monkeypatch.setattr(
        assistant_chat,
        "apply_action",
        lambda text, result: ("我需要补充时间。", {"missing_slots": ["source_time"]}, []),
    )
    monkeypatch.setattr(api_public, "_write_json", _count_write)

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "帮我改一下"}, headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["missing_slots"] == ["source_time"]
    assert api_public._load_assistant_command_logs_payload()["items"] == []
    assert write_calls["count"] == 0


def test_chat_api_skips_log_when_action_raises(monkeypatch) -> None:
    write_calls = {"count": 0}

    class FakeEngine:
        def __init__(self) -> None:
            self.session = type("Session", (), {})()

        def infer(self, text: str) -> dict:
            assert text == "执行失败"
            return _fake_infer_result(intent="cancel_schedule", slots={"schedule_name": "夏季作息"})

    def _count_write(path, payload) -> None:
        del path, payload
        write_calls["count"] += 1

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())
    monkeypatch.setattr(
        assistant_chat,
        "apply_action",
        lambda text, result: (_ for _ in ()).throw(api_public.HTTPException(status_code=503, detail="boom")),
    )
    monkeypatch.setattr(api_public, "_write_json", _count_write)

    with TestClient(api_public.app, raise_server_exceptions=False) as client:
        response = client.post("/assistant/chat", json={"text": "执行失败"}, headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == assistant_chat.ASSISTANT_UNAVAILABLE_REPLY
    assert data["output_speech"] == assistant_chat.ASSISTANT_UNAVAILABLE_REPLY
    assert data["action_log"] == []
    assert api_public._load_assistant_command_logs_payload()["items"] == []
    assert write_calls["count"] == 0


def test_append_assistant_command_log_keeps_latest_limit(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)

    overflow = 5
    total = api_public.ASSISTANT_COMMAND_LOG_LIMIT + overflow
    for index in range(total):
        api_public._append_assistant_command_log(
            text=f"cmd-{index}",
            reply=f"reply-{index}",
            action_log=_action_log(),
        )

    stored = api_public._load_assistant_command_logs_payload()["items"]
    assert len(stored) == api_public.ASSISTANT_COMMAND_LOG_LIMIT
    assert stored[0]["text"] == f"cmd-{overflow}"
    assert stored[-1]["text"] == f"cmd-{total - 1}"


def test_get_assistant_command_logs_returns_latest_first_and_enforces_limit(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    api_public._store_set(
        "assistant_command_logs",
        api_public._normalize_assistant_command_logs_payload(
            {
                "items": [
                    {
                        "text": "old",
                        "reply": "old-reply",
                    },
                    {
                        "text": "mid",
                        "reply": "mid-reply",
                    },
                    {
                        "text": "new",
                        "reply": "new-reply",
                        "intent": "play_media",
                        "confidence": 0.3,
                        "slots": {},
                        "action_log": _action_log(),
                    },
                ]
            }
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.get("/data/assistant_command_logs", params={"limit": 2}, headers=_auth_headers())
        invalid = client.get(
            "/data/assistant_command_logs",
            params={"limit": api_public.ASSISTANT_COMMAND_LOG_LIMIT + 1},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["limit"] == 2
    assert data["items"] == [
        {"text": "new", "reply": "new-reply"},
        {"text": "mid", "reply": "mid-reply"},
    ]
    assert invalid.status_code == 422


def test_healthz_returns_ok(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)

    with TestClient(api_public.app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-speaker-api",
    }
