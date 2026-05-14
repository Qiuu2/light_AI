from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def _auth_headers() -> dict[str, str]:
    session = api_public._create_local_session("remote-test-token", "tester", "test")
    return {"X-Token": session["token"]}


def test_apply_move_anchor_to_task_shifts_weekday_time_only_once() -> None:
    task = {
        "taskid": "1",
        "starttime": "03:30:00",
        "weekdays": ["周五"],
        "execmode": 2,
        "startdate": "2026-03-20",
        "enddate": "2026-03-20",
    }
    source_anchor = {
        "kind": "weekday",
        "weekday": "周五",
        "time_start_minutes": 180,
        "time_end_minutes": 420,
    }
    target_anchor = {
        "kind": "weekday",
        "weekday": "周六",
        "time_start_minutes": 240,
        "time_end_minutes": 300,
    }

    moved = api_public._apply_move_anchor_to_task(task, source_anchor, target_anchor)

    assert moved is not None
    assert moved["starttime"] == "04:30:00"
    assert moved["weekdays"] == ["周六"]


def test_move_schedule_date_specific_recurring_task_respects_real_weekday(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "晨读",
                        "starttime": "07:00:00",
                        "startdate": "2026-03-18",
                        "enddate": "2026-03-25",
                        "weekdays": ["周三"],
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_move_schedule_intent(
        "把春季作息中2026-03-20的任务挪到2026-03-21",
        {"schedule_name": "春季作息", "source_time": "2026-03-20", "target_time": "2026-03-21"},
    )

    assert "未找到匹配" in reply
    assert state["missing_slots"] == []
    assert logs == []


def test_swap_schedule_date_specific_recurring_task_respects_real_weekday(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "晨读",
                        "starttime": "07:00:00",
                        "startdate": "2026-03-18",
                        "enddate": "2026-03-25",
                        "weekdays": ["周三"],
                    },
                    {
                        "taskid": "2",
                        "taskname": "午休",
                        "starttime": "12:00:00",
                        "startdate": "2026-03-18",
                        "enddate": "2026-03-25",
                        "weekdays": ["周六"],
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_swap_schedule_intent(
        "把春季作息中2026-03-20和2026-03-21的任务对调",
        {"schedule_name": "春季作息", "source_time": "2026-03-20", "target_time": "2026-03-21"},
    )

    assert "未找到可对调" in reply
    assert state["missing_slots"] == []
    assert logs == []


def test_parse_weekday_disambig_choices_supports_separate_source_and_target() -> None:
    ambiguous_items = [
        {
            "anchor_key": "source_anchor",
            "label": "源时间",
            "weekday": "周五",
            "this_week_date": api_public.date(2026, 3, 20),
            "next_week_date": api_public.date(2026, 3, 27),
        },
        {
            "anchor_key": "target_anchor",
            "label": "目标时间",
            "weekday": "周六",
            "this_week_date": api_public.date(2026, 3, 21),
            "next_week_date": api_public.date(2026, 3, 28),
        },
    ]

    choices = api_public._parse_weekday_disambig_choices("源时间这周，目标时间下周", ambiguous_items)

    assert choices == {"source_anchor": "this", "target_anchor": "next"}


def test_debug_apply_action_returns_structured_pending_action_for_ambiguous_delete_schedule(
    monkeypatch,
) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "春季作息一班", "tasks": [{"taskid": "1"}]},
            {"schedule_name": "春季作息二班", "tasks": [{"taskid": "2"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    saved_payloads: list[dict] = []

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_clear_pending_action", lambda: None)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: saved_payloads.append(deepcopy(new_payload)),
    )
    monkeypatch.setattr(api_public, "PENDING_ACTION", None)

    with TestClient(api_public.app) as client:
        response = client.post(
            "/debug/apply_action",
            json={
                "intent": "delete_schedule",
                "text": "删除春季作息",
                "slots": {"schedule_name": "春季作息"},
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    pending = data["pending_action"]
    assert data["applied"] is True
    assert pending is not None
    assert pending["kind"] == "target_disambiguation"
    assert pending["intent"] == "delete_schedule"
    assert pending["target_type"] == "schedule"
    assert "候选项" in str(pending.get("confirm_prompt") or "")
    choices = pending.get("choices") or pending.get("candidates") or []
    assert len(choices) == 2
    labels = [
        str(item.get("label") or item.get("name") or item.get("text") or "")
        for item in choices
        if isinstance(item, dict)
    ]
    assert any("春季作息一班" in label for label in labels)
    assert any("春季作息二班" in label for label in labels)
    assert all(isinstance(item, dict) and item.get("slot_updates") is not None for item in choices)
    assert saved_payloads == []


def test_parse_phase1_time_anchor_supports_single_point_time_expressions() -> None:
    weekday_anchor = api_public._parse_phase1_time_anchor("周一8点30")
    clock_anchor = api_public._parse_phase1_time_anchor("周二 08:30")
    afternoon_anchor = api_public._parse_phase1_time_anchor("下午3点")
    range_anchor = api_public._parse_phase1_time_anchor("周一8点到9点")

    assert weekday_anchor is not None
    assert weekday_anchor["kind"] == "weekday"
    assert weekday_anchor["time_start_minutes"] == 8 * 60 + 30
    assert weekday_anchor["time_end_minutes"] == 8 * 60 + 30

    assert clock_anchor is not None
    assert clock_anchor["kind"] == "weekday"
    assert clock_anchor["time_start_minutes"] == 8 * 60 + 30
    assert clock_anchor["time_end_minutes"] == 8 * 60 + 30

    assert afternoon_anchor is not None
    assert afternoon_anchor["kind"] == "date"
    assert afternoon_anchor["time_start_minutes"] == 15 * 60
    assert afternoon_anchor["time_end_minutes"] == 15 * 60

    assert range_anchor is not None
    assert range_anchor["time_start_minutes"] == 8 * 60
    assert range_anchor["time_end_minutes"] == 9 * 60


def test_move_schedule_filters_by_task_name_with_weekday_anchor(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {"taskid": "1", "taskname": "flag-ceremony", "starttime": "08:30:00", "startdate": "2026-03-23", "enddate": "2026-03-23", "weekdays": ["周一"]},
                    {"taskid": "2", "taskname": "evening-study", "starttime": "19:00:00", "startdate": "2026-03-23", "enddate": "2026-03-23", "weekdays": ["周一"]},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    api_public.PENDING_ACTION = None

    reply, state, logs = api_public._apply_move_schedule_intent(
        "把夏季作息里周一的flag-ceremony改到周二",
        {"schedule_name": "summer", "source_time": "周一", "target_time": "周二", "task_name": "flag-ceremony"},
    )

    assert "08:30:00 flag-ceremony" in reply
    assert "19:00:00 evening-study" not in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["task_ids"] == ["1"]
    assert api_public.PENDING_ACTION["task_name"] == "flag-ceremony"
    api_public.PENDING_ACTION = None


def test_move_schedule_filters_precise_time_when_task_names_repeat(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {"taskid": "1", "taskname": "flag-ceremony", "starttime": "08:30:00", "startdate": "2026-03-23", "enddate": "2026-03-23", "weekdays": ["周一"]},
                    {"taskid": "2", "taskname": "flag-ceremony", "starttime": "19:00:00", "startdate": "2026-03-23", "enddate": "2026-03-23", "weekdays": ["周一"]},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    api_public.PENDING_ACTION = None

    reply, state, logs = api_public._apply_move_schedule_intent(
        "把夏季作息里周一8点30的flag-ceremony改到周二8点30",
        {"schedule_name": "summer", "source_time": "周一8点30", "target_time": "周二8点30", "task_name": "flag-ceremony"},
    )

    assert "08:30:00 flag-ceremony" in reply
    assert "19:00:00 flag-ceremony" not in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["task_ids"] == ["1"]
    api_public.PENDING_ACTION = None


def test_move_schedule_prompts_for_ambiguous_duplicate_task_names(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {"taskid": "1", "taskname": "flag-ceremony", "starttime": "08:30:00", "startdate": "2026-03-23", "enddate": "2026-03-23", "weekdays": ["周一"]},
                    {"taskid": "2", "taskname": "flag-ceremony", "starttime": "09:30:00", "startdate": "2026-03-23", "enddate": "2026-03-23", "weekdays": ["周一"]},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    api_public.PENDING_ACTION = None

    reply, state, logs = api_public._apply_move_schedule_intent(
        "把夏季作息里周一的flag-ceremony改到周二",
        {"schedule_name": "summer", "source_time": "周一", "target_time": "周二", "task_name": "flag-ceremony"},
    )

    assert "多个可能的任务" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["kind"] == "target_disambiguation"
    assert api_public.PENDING_ACTION["target_type"] == "task"
    choices = api_public.PENDING_ACTION.get("choices") or []
    assert len(choices) == 2
    descriptions = [str(item.get("description") or "") for item in choices if isinstance(item, dict)]
    assert any("08:30" in description for description in descriptions)
    assert any("09:30" in description for description in descriptions)
    assert all((item.get("slot_updates") or {}).get("task_id") for item in choices if isinstance(item, dict))
    api_public.PENDING_ACTION = None
