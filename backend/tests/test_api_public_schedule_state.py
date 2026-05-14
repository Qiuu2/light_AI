from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_set_schedule_state_updates_local_payload_and_remote(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "春季作息", "status": "停用", "tasks": []},
            {"schedule_name": "夏季作息", "status": "启用", "tasks": []},
        ],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    saved = {}
    remote_calls = []

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: payload)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_remote_set_schedule_status",
        lambda schedule_name, enabled: remote_calls.append((schedule_name, enabled)),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda next_payload, **kwargs: saved.update({"payload": next_payload, "kwargs": kwargs}),
    )

    result = api_public.set_schedule_state(
        api_public.ScheduleStateRequest(schedule_names=["春季作息"], state=0)
    )

    assert result["status"] == "ok"
    assert result["updated_names"] == ["春季作息"]
    assert result["display_status"] == "启用"
    assert remote_calls == [("春季作息", True)]
    assert saved["kwargs"] == {
        "sync_schedules": False,
        "sync_broadcasts": False,
        "sync_livecasts": False,
    }
    assert saved["payload"]["schedules"][0]["status"] == "启用"
    assert saved["payload"]["schedules"][1]["status"] == "启用"


def test_set_schedule_state_returns_missing_names(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "春季作息", "status": "启用", "tasks": []},
        ],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: payload)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_save_schedules_payload", lambda next_payload, **kwargs: None)

    result = api_public.set_schedule_state(
        api_public.ScheduleStateRequest(schedule_names=["春季作息", "不存在方案"], status="停用")
    )

    assert result["updated_names"] == ["春季作息"]
    assert result["missing_names"] == ["不存在方案"]
    assert result["display_status"] == "停用"


def test_set_schedule_state_rejects_empty_request() -> None:
    with pytest.raises(api_public.HTTPException) as excinfo:
        api_public.set_schedule_state(api_public.ScheduleStateRequest(schedule_names=[], state=0))

    assert excinfo.value.status_code == 400
