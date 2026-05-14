from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


@pytest.fixture(autouse=True)
def _isolate_assistant_state(monkeypatch):
    original_entry = deepcopy(api_public.DATA_STORE["assistant_command_logs"])
    api_public._store_set(
        "assistant_command_logs",
        api_public._normalize_assistant_command_logs_payload({"items": []}),
    )
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)
    yield
    api_public.DATA_STORE["assistant_command_logs"] = original_entry


def _fake_engine(intent: str, slots: dict):
    class FakeEngine:
        def __init__(self) -> None:
            self.session = type("Session", (), {})()

        def infer(self, text: str) -> dict:
            return {
                "intent": intent,
                "intent_confidence": 0.93,
                "slots": dict(slots),
                "missing_slots": [],
                "entities": {},
                "tokens": [],
                "tag_ids": [],
            }

    return FakeEngine()


def _auth_headers() -> dict[str, str]:
    session = api_public._create_local_session("remote-test-token", "tester", "test")
    return {"X-Token": session["token"]}


def test_assistant_chat_delete_zone_delegates_to_api_public_helper(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "ENGINE", _fake_engine("delete_zone", {"zone_name": "zone-a"}))
    monkeypatch.setattr(
        api_public,
        "_apply_delete_zone_intent",
        lambda text, slots: (
            "delegated delete zone",
            {"missing_slots": []},
            [api_public._build_action_log("delete_zone", "", [], mode="runtime", details={"delegated": True})],
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "删除 zone-a"}, headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "delegated delete zone"
    assert body["action_log"][0]["action"] == "delete_zone"
    assert body["action_log"][0]["details"]["delegated"] is True


def test_assistant_chat_remove_terminal_from_zone_delegates_to_api_public_helper(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "ENGINE",
        _fake_engine("remove_terminal_from_zone", {"zone_name": "zone-a", "terminal_id": "9"}),
    )
    monkeypatch.setattr(
        api_public,
        "_apply_add_remove_terminal_to_zone_intent",
        lambda text, slots, *, add, action_name: (
            f"delegated {action_name}",
            {"missing_slots": []},
            [
                api_public._build_action_log(
                    action_name,
                    "",
                    [],
                    mode="runtime",
                    details={"delegated": True, "add": add},
                )
            ],
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "把 9 从 zone-a 移除"}, headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "delegated remove_terminal_from_zone"
    assert body["action_log"][0]["action"] == "remove_terminal_from_zone"
    assert body["action_log"][0]["details"] == {"delegated": True, "add": False}
