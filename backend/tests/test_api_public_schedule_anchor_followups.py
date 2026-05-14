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


def test_apply_swap_schedule_weekday_anchor_filters_by_task_name(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "升旗仪式",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周三"],
            },
            {
                "taskid": "2",
                "taskname": "晨间体操",
                "starttime": "09:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周三"],
            },
            {
                "taskid": "3",
                "taskname": "升旗仪式",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周六"],
            },
            {
                "taskid": "4",
                "taskname": "晨间体操",
                "starttime": "09:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周六"],
            },
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_swap_schedule_intent(
        "把夏季作息里周三和周六的升旗仪式对调",
        {
            "schedule_name": "夏季作息",
            "source_time": "周三",
            "target_time": "周六",
            "task_name": "升旗仪式",
        },
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert state["missing_slots"] == []
    assert logs == []
    pending = api_public._get_pending_action()
    assert pending is not None
    assert pending["intent"] == "swap_schedule"
    assert pending["task_name"] == "升旗仪式"
    assert pending["task_ids_a"] == ["1"]
    assert pending["task_ids_b"] == ["3"]


def test_apply_swap_schedule_weekday_anchor_reports_task_name_mismatch(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "晨间体操",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周三"],
            },
            {
                "taskid": "2",
                "taskname": "晨间体操",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周六"],
            },
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_swap_schedule_intent(
        "把夏季作息里周三和周六的升旗仪式对调",
        {
            "schedule_name": "夏季作息",
            "source_time": "周三",
            "target_time": "周六",
            "task_name": "升旗仪式",
        },
    )

    assert "升旗仪式" in reply
    assert "名称匹配" in reply
    assert logs == []
    assert state["diagnostics"][0]["candidate_count_after_time_match"] == 1
    assert state["diagnostics"][0]["candidate_count_after_task_name_match"] == 0


def test_apply_move_schedule_diagnostics_ignore_unrelated_missing_recurrence(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "晨间体操",
                "starttime": "08:00:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
            },
            {
                "taskid": "2",
                "taskname": "国歌",
                "starttime": "08:30:00",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周四"],
            },
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_move_schedule_intent(
        "将夏季作息里周三的升旗仪式挪到周六去",
        {
            "schedule_name": "夏季作息",
            "source_time": "周三",
            "target_time": "周六",
            "task_name": "升旗仪式",
        },
    )

    assert "缺少星期信息" not in reply
    assert "匹配" in reply
    assert logs == []
    assert state["diagnostics"][0]["missing_recurrence_metadata_count"] == 0


def test_chat_api_cancel_weekday_anchor_once_executes_without_time_range_prompt(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "1",
                "taskname": "升旗仪式",
                "starttime": "08:00:00",
                "timelength": "600",
                "timelengthtype": "1",
                "startdate": "2026-03-01",
                "enddate": "2026-06-30",
                "weekdays": ["周三"],
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    def _infer(text: str) -> dict:
        if "取消" in text:
            return _infer_result(
                "cancel_schedule",
                {
                    "schedule_name": "夏季作息",
                    "source_time": "周三",
                    "task_name": "升旗仪式",
                },
            )
        return _infer_result("sync_terminal_time", {"play_count": "一"})

    monkeypatch.setattr(api_public.ENGINE, "infer", _infer)

    headers = _auth_headers()
    with TestClient(api_public.app) as client:
        first = client.post("/assistant/chat", json={"text": "取消夏季作息周三的升旗仪式"}, headers=headers)
        second = client.post("/assistant/chat", json={"text": "一次性"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()
    second_data = second.json()
    assert first_data["pending_action"]["intent"] == "cancel_schedule"
    assert "具体时间段" not in second_data["reply"]
    assert second_data["intent"] == "cancel_schedule"
    assert second_data["pending_action"] is None
    assert len(second_data["action_log"]) == 1
