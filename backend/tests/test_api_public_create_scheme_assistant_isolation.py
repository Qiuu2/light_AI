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


def _phase1_media_library(
    items: list[dict],
    *,
    source: str = "local",
    remote_expected: bool = False,
    remote_fetch_ok: bool = False,
    fallback_used: bool = False,
) -> dict:
    return {
        "items": deepcopy(items),
        "source": source,
        "remote_expected": remote_expected,
        "remote_fetch_ok": remote_fetch_ok,
        "fallback_used": fallback_used,
    }


@pytest.fixture(autouse=True)
def _default_phase1_template_media_library(monkeypatch):
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library([{"mediaid": "911", "name": "prep-bell"}]),
    )


def _template_schedule() -> dict:
    return {
        "schedule_name": "template",
        "tasks": [
            {
                "taskname": "prep-bell",
                "medianame": "prep-bell",
                "audio": "prep-bell",
                "mediaid": "911",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                "terminalids": ["9"],
                "terminalnames": ["speaker-a"],
                "liveterminalid": "9",
                "liveterminalname": "speaker-a",
                "location": [["zone-a", "speaker-a"]],
                "taskterminal": [
                    {
                        "terminalid": "9",
                        "terminalname": "speaker-a",
                        "groupid": 1,
                        "groupid_present": True,
                    }
                ],
            }
        ],
    }


def _playback_terminal_items() -> list[dict]:
    return [
        {"id": 46, "type": 11, "name": "speaker-a", "zone": 0},
        {"id": 25, "type": 24, "name": "amp-a", "zone": 0},
    ]


def _fake_engine(intent: str, slots: dict):
    class FakeEngine:
        def __init__(self) -> None:
            self.session = type("Session", (), {})()

        def infer(self, text: str) -> dict:
            return {
                "intent": intent,
                "intent_confidence": 0.98,
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


def test_debug_test_phase1_intent_create_schedule_stays_on_shared_path(monkeypatch) -> None:
    committed: dict = {}

    monkeypatch.setattr(api_public, "_load_default_schedule_kind", lambda: "primary")
    monkeypatch.setattr(api_public, "_load_default_schedule_season", lambda: "夏季")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        lambda text, schedule_kind, schedule_season: (
            "primary",
            "夏季",
            {"local_template_file": "school_summer_default.json"},
        ),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(_template_schedule()))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_store_terminalinfo_items", _playback_terminal_items)
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda new_schedule, *, sync_remote: committed.update(
            {"schedule": deepcopy(new_schedule), "sync_remote": sync_remote}
        )
        or deepcopy(new_schedule),
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/debug/test_phase1_intent",
            json={
                "intent": "create_schedule",
                "text": "create spring-schedule",
                "slots": {"schedule_name": "spring-schedule"},
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    saved_task = committed["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["9"]
    assert saved_task["liveterminalid"] == "9"


def test_debug_apply_action_create_schedule_stays_on_shared_path(monkeypatch) -> None:
    committed: dict = {}

    monkeypatch.setattr(api_public, "_load_default_schedule_kind", lambda: "primary")
    monkeypatch.setattr(api_public, "_load_default_schedule_season", lambda: "夏季")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        lambda text, schedule_kind, schedule_season: (
            "primary",
            "夏季",
            {"local_template_file": "school_summer_default.json"},
        ),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(_template_schedule()))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_store_terminalinfo_items", _playback_terminal_items)
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda new_schedule, *, sync_remote: committed.update(
            {"schedule": deepcopy(new_schedule), "sync_remote": sync_remote}
        )
        or deepcopy(new_schedule),
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/debug/apply_action",
            json={
                "intent": "create_schedule",
                "text": "create spring-schedule",
                "status": "success",
                "slots": {"schedule_name": "spring-schedule"},
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is True
    saved_task = committed["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["9"]
    assert saved_task["liveterminalid"] == "9"


def test_assistant_chat_create_schedule_uses_assistant_scope(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "ENGINE", _fake_engine("create_schedule", {"schedule_name": "spring-schedule"}))
    monkeypatch.setattr(api_public, "_append_assistant_command_log", lambda **kwargs: None)

    def fake_apply_create_scheme_intent(text: str, slots: dict, *, assistant_terminal_scope: str = ""):
        captured["text"] = text
        captured["slots"] = deepcopy(slots)
        captured["assistant_terminal_scope"] = assistant_terminal_scope
        return "created", {"missing_slots": []}, [{"action": "create_schedule"}]

    monkeypatch.setattr(api_public, "_apply_create_scheme_intent", fake_apply_create_scheme_intent)

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "create spring-schedule"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "created"
    assert body["action_log"][0]["action"] == "create_schedule"
    assert captured["text"] == "create spring-schedule"
    assert captured["slots"] == {"schedule_name": "spring-schedule"}
    assert (
        captured["assistant_terminal_scope"]
        == api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS
    )
