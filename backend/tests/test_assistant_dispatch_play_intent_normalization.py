from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_apply_action_play_task_uses_media_name_as_task_fallback(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [
            {"taskid": "1", "taskname": "prep_bell", "taskstate": 0, "status": "stopped"},
            {"taskid": "2", "taskname": "anthem", "taskstate": 0, "status": "stopped"},
        ],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    result = {
        "intent": "play_task",
        "status": "success",
        "slots": {"media_name": "prep_bell"},
    }
    reply, state, logs = api_public._apply_action("play prep_bell", result)

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "play_task"
    assert logs[0]["task_ids"] == ["1"]
    assert result["intent"] == "play_task"
    assert result["slots"]["task_name"] == "prep_bell"
    assert committed["payload"]["broadcasts"][0]["taskstate"] == 1
    assert committed["payload"]["broadcasts"][1]["taskstate"] == 0


def test_apply_action_play_media_without_media_signals_falls_back_to_play_task(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "1", "taskname": "prep_bell", "taskstate": 0, "status": "stopped"}],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    result = {
        "intent": "play_media",
        "status": "success",
        "slots": {"media_name": "prep_bell"},
    }
    reply, state, logs = api_public._apply_action("play prep_bell", result)

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "play_task"
    assert logs[0]["task_ids"] == ["1"]
    assert result["intent"] == "play_task"
    assert result["slots"]["task_name"] == "prep_bell"
    assert committed["payload"]["broadcasts"][0]["taskstate"] == 1


def test_apply_action_play_task_with_media_target_falls_forward_to_play_media(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_safe_media_map", lambda: {"prep_bell": "11"})
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    result = {
        "intent": "play_task",
        "status": "success",
        "slots": {"task_name": "prep_bell", "terminal_id": "101"},
    }
    reply, state, logs = api_public._apply_action("terminal 101 play prep_bell", result)

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "play_media"
    assert logs[0]["task_ids"] == ["998"]
    assert result["intent"] == "play_media"
    assert result["slots"]["media_name"] == "prep_bell"
    assert captured["media_ids"] == ["11"]
    assert captured["terminal_ids"] == ["101"]
