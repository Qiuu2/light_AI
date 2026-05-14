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


def _schedule_payload(tasks: list[dict]) -> dict:
    return {
        "schedules": [
            {
                "schedule_name": "夏季作息",
                "status": "0",
                "tasks": deepcopy(tasks),
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }


def _infer_result(intent: str, slots: dict) -> dict:
    return {
        "intent": intent,
        "intent_confidence": 0.99,
        "slots": deepcopy(slots),
        "missing_slots": [],
        "entities": {},
        "tokens": [],
        "tag_ids": [],
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
    monkeypatch.setattr(api_public, "_write_cache_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    yield
    api_public.DATA_STORE["assistant_command_logs"] = original_logs
    api_public._clear_pending_action()


def test_chat_api_move_friday_flag_ceremony_to_saturday_with_weekdays(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "升旗仪式",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周五"],
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _infer_result(
            "move_schedule",
            {
                "schedule_name": "夏季作息",
                "source_time": "周五",
                "end_time": "周六",
                "task_name": "升旗仪式",
            },
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "把夏季作息里周五的升旗仪式改到周六"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "move_schedule"
    assert "请确认要一次性执行还是永久生效" in data["reply"]
    assert data["pending_action"]["intent"] == "move_schedule"
    assert data["pending_action"]["task_ids"] == ["1"]


def test_chat_api_move_friday_flag_ceremony_to_saturday_with_execmode_only(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "升旗仪式",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "execmode": api_public._execmode_from_weekdays(["周五"]),
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _infer_result(
            "move_schedule",
            {
                "schedule_name": "夏季作息",
                "source_time": "周五",
                "end_time": "周六",
                "task_name": "升旗仪式",
            },
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "把夏季作息里周五的升旗仪式改到周六"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "move_schedule"
    assert "请确认要一次性执行还是永久生效" in data["reply"]
    assert data["pending_action"]["intent"] == "move_schedule"
    assert data["pending_action"]["task_ids"] == ["1"]


def test_chat_api_move_friday_hits_time_but_misses_task_name(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "晨间体操",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周五"],
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _infer_result(
            "move_schedule",
            {
                "schedule_name": "夏季作息",
                "source_time": "周五",
                "end_time": "周六",
                "task_name": "升旗仪式",
            },
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "把夏季作息里周五的升旗仪式改到周六"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "move_schedule"
    assert data["reply"] == "在“夏季作息”的“周五”任务中未找到名称匹配“升旗仪式”的任务。"
    assert data["diagnostics"][0]["anchor_kind"] == "weekday"
    assert data["diagnostics"][0]["anchor_weekday"] == "周五"
    assert data["diagnostics"][0]["candidate_count_after_time_match"] == 1
    assert data["diagnostics"][0]["candidate_count_after_task_name_match"] == 0
    assert data["diagnostics"][0]["missing_recurrence_metadata_count"] == 0


def test_chat_api_move_friday_reports_missing_recurrence_metadata(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "升旗仪式",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _infer_result(
            "move_schedule",
            {
                "schedule_name": "夏季作息",
                "source_time": "周五",
                "end_time": "周六",
                "task_name": "升旗仪式",
            },
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "把夏季作息里周五的升旗仪式改到周六"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "move_schedule"
    assert data["reply"] == "“夏季作息”中的任务缺少星期信息，无法按“周五”定位。"
    assert data["diagnostics"][0]["anchor_kind"] == "weekday"
    assert data["diagnostics"][0]["anchor_weekday"] == "周五"
    assert data["diagnostics"][0]["candidate_count_after_time_match"] == 0
    assert data["diagnostics"][0]["candidate_count_after_task_name_match"] == 0
    assert data["diagnostics"][0]["missing_recurrence_metadata_count"] == 1
