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
def _isolate_chat_query_task_state(monkeypatch):
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


def _fake_query_infer_result(slots: dict) -> dict:
    return {
        "intent": "query_task",
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


def test_chat_api_query_task_for_relative_day_excludes_runtime_scopes(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [{"taskid": "1", "taskname": "schedule_only", "starttime": "08:00:00", "startdate": "2026-03-24", "enddate": "2026-03-24"}],
            }
        ],
        "broadcasts": [{"taskid": "21", "taskname": "file_broadcast", "starttime": "00:00:00", "taskstate": 0}],
        "livecasts": [{"taskid": "31", "taskname": "livecast_task", "starttime": "16:32:00", "taskstate": 0}],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _fake_query_infer_result({"source_time": "2026-03-24"}),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "看看后天的任务"}, headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "query_task"
    assert "1 条" in data["reply"]
    assert len(data["action_log"]) == 1
    details = data["action_log"][0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]
    assert all(item["kind"] == "schedule" for item in details["tasks"])


def test_chat_api_query_task_point_in_time_uses_source_time_alias(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {"taskid": "1", "taskname": "school_end", "starttime": "16:15:00", "startdate": "2026-03-23", "enddate": "2026-03-23"},
                    {"taskid": "2", "taskname": "afternoon_break", "starttime": "15:05:00", "startdate": "2026-03-23", "enddate": "2026-03-23"},
                ],
            }
        ],
        "broadcasts": [{"taskid": "21", "taskname": "file_broadcast", "starttime": "16:15:00", "taskstate": 0}],
        "livecasts": [{"taskid": "31", "taskname": "livecast_task", "starttime": "16:15:00", "taskstate": 0}],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _fake_query_infer_result({"source_time": "2026-03-23 16:15"}),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "查看3月23日下午4点的任务"}, headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "query_task"
    assert "1 条" in data["reply"]
    assert data["slots"] == {"source_time": "2026-03-23 16:15"}
    details = data["action_log"][0]["details"]
    assert details["time_range_start"] == "2026-03-23 16:15"
    assert details["time_range_end"] == ""
    assert [item["task_id"] for item in details["tasks"]] == ["1"]


def test_chat_api_query_task_time_range_uses_source_time_and_end_time_aliases(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {"taskid": "1", "taskname": "early_reading", "starttime": "07:50:00", "startdate": "2026-03-23", "enddate": "2026-03-23"},
                    {"taskid": "2", "taskname": "first_class", "starttime": "08:20:00", "startdate": "2026-03-23", "enddate": "2026-03-23"},
                    {"taskid": "3", "taskname": "school_end", "starttime": "16:15:00", "startdate": "2026-03-23", "enddate": "2026-03-23"},
                    {"taskid": "4", "taskname": "late_task", "starttime": "17:30:00", "startdate": "2026-03-23", "enddate": "2026-03-23"},
                ],
            }
        ],
        "broadcasts": [{"taskid": "21", "taskname": "file_broadcast", "starttime": "16:32:00", "taskstate": 0}],
        "livecasts": [{"taskid": "31", "taskname": "livecast_task", "starttime": "11:14:00", "taskstate": 0}],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _fake_query_infer_result(
            {"source_time": "2026-03-23 08:00", "end_time": "2026-03-23 17:00"}
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "查看3月23日上午8点到下午5点的任务"}, headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "query_task"
    assert "2 条任务" in data["reply"]
    assert data["slots"] == {"source_time": "2026-03-23 08:00", "end_time": "2026-03-23 17:00"}
    details = data["action_log"][0]["details"]
    assert details["time_range_start"] == "2026-03-23 08:00"
    assert details["time_range_end"] == "2026-03-23 17:00"
    assert [item["task_id"] for item in details["tasks"]] == ["2", "3"]
    assert all(item["kind"] == "schedule" for item in details["tasks"])


def test_chat_api_query_task_afternoon_window_repairs_truncated_source_time(monkeypatch) -> None:
    today = api_public.date.today().isoformat()
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {"taskid": "1", "taskname": "morning_reading", "starttime": "07:50:00", "startdate": today, "enddate": today},
                    {"taskid": "2", "taskname": "lunch_break", "starttime": "12:30:00", "startdate": today, "enddate": today},
                    {"taskid": "3", "taskname": "afternoon_class", "starttime": "15:05:00", "startdate": today, "enddate": today},
                    {"taskid": "4", "taskname": "night_study", "starttime": "18:30:00", "startdate": today, "enddate": today},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _fake_query_infer_result({"source_time": "今天下"}),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "查看今天下午的任务"}, headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "query_task"
    assert data["slots"]["source_time"] == "今天下午"
    assert "2" in str(data["reply"])
    details = data["action_log"][0]["details"]
    assert details["time_range_start"] == "今天下午"
    assert details["time_range_end"] == ""
    assert [item["task_id"] for item in details["tasks"]] == ["2", "3"]
