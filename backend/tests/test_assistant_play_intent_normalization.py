from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public
from backend.assistant import dispatch as assistant_dispatch


def _patch_play_handlers(monkeypatch, captured: dict) -> None:
    monkeypatch.setitem(
        assistant_dispatch.PHASE1_INTENT_DISPATCH,
        "play_task",
        lambda text, slots: captured.update({"route": "play_task", "text": text, "slots": deepcopy(slots)})
        or ("task", {"missing_slots": []}, [{"action": "play_task"}]),
    )
    monkeypatch.setitem(
        assistant_dispatch.PHASE1_INTENT_DISPATCH,
        "play_media",
        lambda text, slots: captured.update({"route": "play_media", "text": text, "slots": deepcopy(slots)})
        or ("media", {"missing_slots": []}, [{"action": "play_media"}]),
    )


def test_apply_action_play_task_with_media_name_only_stays_play_task(monkeypatch) -> None:
    captured: dict = {}
    _patch_play_handlers(monkeypatch, captured)

    result = {
        "intent": "play_task",
        "status": "success",
        "slots": {"media_name": "anthem"},
    }
    reply, state, logs = api_public._apply_action("play anthem", result)

    assert reply == "task"
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "play_task"
    assert captured["route"] == "play_task"
    assert captured["slots"]["media_name"] == "anthem"
    assert captured["slots"]["task_name"] == "anthem"
    assert result["intent"] == "play_task"
    assert result["slots"]["task_name"] == "anthem"


def test_apply_action_play_media_with_media_name_only_falls_back_to_play_task(monkeypatch) -> None:
    captured: dict = {}
    _patch_play_handlers(monkeypatch, captured)

    result = {
        "intent": "play_media",
        "status": "success",
        "slots": {"media_name": "anthem"},
    }
    reply, state, logs = api_public._apply_action("play anthem", result)

    assert reply == "task"
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "play_task"
    assert captured["route"] == "play_task"
    assert captured["slots"]["task_name"] == "anthem"
    assert result["intent"] == "play_task"
    assert result["slots"]["task_name"] == "anthem"


def test_apply_action_play_task_with_zone_signal_routes_to_play_media(monkeypatch) -> None:
    captured: dict = {}
    _patch_play_handlers(monkeypatch, captured)

    result = {
        "intent": "play_task",
        "status": "success",
        "slots": {"task_name": "anthem", "zone_name": "zone_a"},
    }
    reply, state, logs = api_public._apply_action("play anthem in zone_a", result)

    assert reply == "media"
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "play_media"
    assert captured["route"] == "play_media"
    assert captured["slots"]["task_name"] == "anthem"
    assert captured["slots"]["media_name"] == "anthem"
    assert captured["slots"]["zone_name"] == "zone_a"
    assert result["intent"] == "play_media"
    assert result["slots"]["media_name"] == "anthem"


def test_apply_action_play_media_with_count_signal_stays_play_media(monkeypatch) -> None:
    captured: dict = {}
    _patch_play_handlers(monkeypatch, captured)

    result = {
        "intent": "play_media",
        "status": "success",
        "slots": {"media_name": "anthem", "play_count": "3"},
    }
    reply, state, logs = api_public._apply_action("play anthem three times", result)

    assert reply == "media"
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "play_media"
    assert captured["route"] == "play_media"
    assert captured["slots"]["media_name"] == "anthem"
    assert result["intent"] == "play_media"


def test_apply_action_play_task_with_volume_signal_routes_to_play_media(monkeypatch) -> None:
    captured: dict = {}
    _patch_play_handlers(monkeypatch, captured)

    result = {
        "intent": "play_task",
        "status": "success",
        "slots": {"task_name": "anthem", "volume": "20"},
    }
    reply, state, logs = api_public._apply_action("play anthem at volume 20", result)

    assert reply == "media"
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "play_media"
    assert captured["route"] == "play_media"
    assert captured["slots"]["media_name"] == "anthem"
    assert captured["slots"]["volume"] == "20"
    assert result["intent"] == "play_media"


def test_apply_action_play_task_with_duration_signal_routes_to_play_media(monkeypatch) -> None:
    captured: dict = {}
    _patch_play_handlers(monkeypatch, captured)

    result = {
        "intent": "play_task",
        "status": "success",
        "slots": {"task_name": "anthem", "play_duration": "10"},
    }
    reply, state, logs = api_public._apply_action("play anthem for 10 minutes", result)

    assert reply == "media"
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "play_media"
    assert captured["route"] == "play_media"
    assert captured["slots"]["media_name"] == "anthem"
    assert captured["slots"]["play_duration"] == "10"
    assert result["intent"] == "play_media"


def test_apply_action_play_media_with_both_names_and_no_media_signal_prefers_play_task(monkeypatch) -> None:
    captured: dict = {}
    _patch_play_handlers(monkeypatch, captured)

    result = {
        "intent": "play_media",
        "status": "success",
        "slots": {"task_name": "anthem", "media_name": "anthem"},
    }
    reply, state, logs = api_public._apply_action("play anthem", result)

    assert reply == "task"
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "play_task"
    assert captured["route"] == "play_task"
    assert result["intent"] == "play_task"
