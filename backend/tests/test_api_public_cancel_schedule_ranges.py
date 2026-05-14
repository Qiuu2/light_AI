from __future__ import annotations

from copy import deepcopy
from datetime import datetime as real_datetime
from importlib import import_module
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public

engine_module = import_module("src.engine")


def _patch_now(monkeypatch, year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> None:
    class FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day, hour, minute, second, tzinfo=tz)

    monkeypatch.setattr(api_public, "datetime", FixedDateTime)
    monkeypatch.setattr(engine_module, "datetime", FixedDateTime)


def _summer_schedule_payload(date_text: str) -> dict:
    return {
        "schedules": [
            {
                "schedule_name": "夏季作息",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "78483",
                        "taskname": "第一节课上课铃",
                        "starttime": "08:20:00",
                        "startdate": date_text,
                        "enddate": date_text,
                    },
                    {
                        "taskid": "78485",
                        "taskname": "第一节课下课铃",
                        "starttime": "09:00:00",
                        "startdate": date_text,
                        "enddate": date_text,
                    },
                    {
                        "taskid": "78487",
                        "taskname": "第二节课上课铃",
                        "starttime": "09:10:00",
                        "startdate": date_text,
                        "enddate": date_text,
                    },
                    {
                        "taskid": "78489",
                        "taskname": "大课间",
                        "starttime": "09:50:00",
                        "startdate": date_text,
                        "enddate": date_text,
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }


def test_apply_cancel_schedule_with_date_range_cancels_all_matching_tasks(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "status": "启用",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "晨读",
                        "starttime": "07:00:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-07",
                        "weekdays": ["周三"],
                    },
                    {
                        "taskid": "2",
                        "taskname": "广播体操",
                        "starttime": "07:30:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-07",
                        "weekdays": ["周五"],
                    },
                ],
            }
        ],
        "broadcasts": [],
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

    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "永久取消春季作息中10月1日到10月7日的所有任务执行",
        {"schedule_name": "春季作息", "source_time": "10月1日", "end_time": "10月7日"},
    )

    assert "已永久删除 2 条任务" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "cancel_schedule"
    assert logs[0]["mode"] == "permanent"
    assert committed["payload"]["schedules"][0]["tasks"] == []


def test_apply_cancel_schedule_without_schedule_name_uses_unique_enabled_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "status": "启用",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "晨读",
                        "starttime": "07:00:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-07",
                    }
                ],
            },
            {
                "schedule_name": "冬季作息",
                "status": "停用",
                "tasks": [
                    {
                        "taskid": "2",
                        "taskname": "广播体操",
                        "starttime": "07:30:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-07",
                    }
                ],
            },
        ],
        "broadcasts": [],
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

    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "永久取消10月1日到10月7日的所有任务",
        {"source_time": "10月1日", "end_time": "10月7日"},
    )

    assert "已永久删除 1 条任务" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["schedule_name"] == "春季作息"
    assert committed["payload"]["schedules"][0]["tasks"] == []
    assert len(committed["payload"]["schedules"][1]["tasks"]) == 1


def _legacy_apply_cancel_schedule_without_schedule_name_prompts_when_active_schedule_is_ambiguous_or_missing(
    monkeypatch,
) -> None:
    cases = [
        (
            [
                {"schedule_name": "春季作息", "status": "启用", "tasks": []},
                {"schedule_name": "夏季作息", "status": "启用", "tasks": []},
            ],
            "当前有多个启用中的作息方案",
        ),
        (
            [
                {"schedule_name": "春季作息", "status": "停用", "tasks": []},
                {"schedule_name": "夏季作息", "status": "停用", "tasks": []},
            ],
            "当前没有启用中的作息方案",
        ),
    ]

    for schedules, expected_fragment in cases:
        monkeypatch.setattr(
            api_public,
            "_load_schedules_payload",
            lambda schedules=deepcopy(schedules): {"schedules": deepcopy(schedules), "broadcasts": [], "livecasts": []},
        )

        reply, state, logs = api_public._apply_cancel_schedule_intent(
            "永久取消10月1日到10月7日的所有任务",
            {"source_time": "10月1日", "end_time": "10月7日"},
        )

        assert expected_fragment in reply
        assert state["missing_slots"] == ["schedule_name"]
        assert logs == []


def test_apply_cancel_schedule_without_schedule_name_shows_enabled_schedule_choices_or_missing_prompt(
    monkeypatch,
) -> None:
    ambiguous_payload = {
        "schedules": [
            {"schedule_name": "spring", "status": "0", "tasks": []},
            {"schedule_name": "summer", "status": "0", "tasks": []},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    missing_payload = {
        "schedules": [
            {"schedule_name": "spring", "status": "1", "tasks": []},
            {"schedule_name": "summer", "status": "1", "tasks": []},
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(ambiguous_payload))
    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "cancel 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "end_time": "2026-10-02"},
    )

    assert "当前启用方案" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["kind"] == "target_disambiguation"
    labels = [str(item.get("label") or "") for item in (api_public.PENDING_ACTION.get("choices") or [])]
    assert labels == ["spring", "summer", "全部"]

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(missing_payload))
    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "cancel 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "end_time": "2026-10-02"},
    )

    assert "未指定作息方案，且当前没有启用中的作息方案" in reply
    assert state["missing_slots"] == ["schedule_name"]
    assert logs == []


def test_apply_move_schedule_without_schedule_name_uses_unique_enabled_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "morning-read",
                        "starttime": "07:00:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-01",
                    }
                ],
            },
            {
                "schedule_name": "winter",
                "status": "1",
                "tasks": [],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    api_public.PENDING_ACTION = None

    reply, state, logs = api_public._apply_move_schedule_intent(
        "move 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )

    assert "\u8bf7\u786e\u8ba4\u8981\u4e00\u6b21\u6027\u6267\u884c\u8fd8\u662f\u6c38\u4e45\u751f\u6548" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["schedule_name"] == "spring"
    api_public.PENDING_ACTION = None


def test_apply_swap_schedule_without_schedule_name_uses_unique_enabled_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "morning-read",
                        "starttime": "07:00:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-01",
                    },
                    {
                        "taskid": "2",
                        "taskname": "exercise",
                        "starttime": "07:30:00",
                        "startdate": "2026-10-02",
                        "enddate": "2026-10-02",
                    },
                ],
            },
            {
                "schedule_name": "winter",
                "status": "1",
                "tasks": [],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    api_public.PENDING_ACTION = None

    reply, state, logs = api_public._apply_swap_schedule_intent(
        "swap 2026-10-01 and 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )

    assert "\u8bf7\u786e\u8ba4\u8981\u4e00\u6b21\u6027\u6267\u884c\u8fd8\u662f\u6c38\u4e45\u751f\u6548" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["schedule_name"] == "spring"
    api_public.PENDING_ACTION = None


def test_move_and_swap_without_schedule_name_show_enabled_schedule_choices_or_missing_prompt(
    monkeypatch,
) -> None:
    ambiguous_payload = {
        "schedules": [
            {"schedule_name": "spring", "status": "0", "tasks": [{"taskid": "1", "starttime": "07:00:00", "startdate": "2026-10-01", "enddate": "2026-10-01"}]},
            {"schedule_name": "summer", "status": "0", "tasks": [{"taskid": "2", "starttime": "07:00:00", "startdate": "2026-10-01", "enddate": "2026-10-01"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    missing_payload = {
        "schedules": [
            {"schedule_name": "spring", "status": "1", "tasks": []},
            {"schedule_name": "summer", "status": "1", "tasks": []},
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(ambiguous_payload))
    api_public.PENDING_ACTION = None
    move_reply, move_state, move_logs = api_public._apply_move_schedule_intent(
        "move 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )
    assert "当前启用方案" in move_reply
    assert move_state["missing_slots"] == []
    assert move_logs == []
    assert api_public.PENDING_ACTION is not None
    assert [str(item.get("label") or "") for item in (api_public.PENDING_ACTION.get("choices") or [])] == ["spring", "summer", "全部"]

    api_public.PENDING_ACTION = None
    swap_reply, swap_state, swap_logs = api_public._apply_swap_schedule_intent(
        "swap 2026-10-01 and 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )
    assert "当前启用方案" in swap_reply
    assert swap_state["missing_slots"] == []
    assert swap_logs == []
    assert api_public.PENDING_ACTION is not None
    assert [str(item.get("label") or "") for item in (api_public.PENDING_ACTION.get("choices") or [])] == ["spring", "summer", "全部"]

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(missing_payload))
    api_public.PENDING_ACTION = None
    move_reply, move_state, move_logs = api_public._apply_move_schedule_intent(
        "move 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )
    assert "未指定作息方案，且当前没有启用中的作息方案" in move_reply
    assert move_state["missing_slots"] == ["schedule_name"]
    assert move_logs == []

    swap_reply, swap_state, swap_logs = api_public._apply_swap_schedule_intent(
        "swap 2026-10-01 and 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )
    assert "未指定作息方案，且当前没有启用中的作息方案" in swap_reply
    assert swap_state["missing_slots"] == ["schedule_name"]
    assert swap_logs == []


def test_select_all_enabled_schedules_builds_multi_schedule_pending_actions_for_move_and_swap(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "status": "0",
                "tasks": [
                    {"taskid": "1", "starttime": "07:00:00", "startdate": "2026-10-01", "enddate": "2026-10-01"},
                    {"taskid": "2", "starttime": "07:30:00", "startdate": "2026-10-02", "enddate": "2026-10-02"},
                ],
            },
            {
                "schedule_name": "summer",
                "status": "0",
                "tasks": [
                    {"taskid": "11", "starttime": "07:00:00", "startdate": "2026-10-01", "enddate": "2026-10-01"},
                    {"taskid": "12", "starttime": "07:30:00", "startdate": "2026-10-02", "enddate": "2026-10-02"},
                ],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    api_public.PENDING_ACTION = None
    api_public._apply_move_schedule_intent(
        "move 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )
    reply, state, logs = api_public._handle_pending_action("3")
    assert "请确认要一次性执行还是永久生效" in reply
    assert "我先帮您定位到这些内容" not in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["schedule_scope"] == "enabled_all"
    assert len(api_public.PENDING_ACTION["task_groups"]) == 2

    api_public.PENDING_ACTION = None
    api_public._apply_swap_schedule_intent(
        "swap 2026-10-01 and 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )
    reply, state, logs = api_public._handle_pending_action("3")
    assert "请确认要一次性执行还是永久生效" in reply
    assert "我先帮您定位到这些内容" not in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["schedule_scope"] == "enabled_all"
    assert len(api_public.PENDING_ACTION["task_groups"]) == 2


def test_move_schedule_enabled_all_ambiguity_requires_schedule_then_task_confirmation(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "status": "0",
                "tasks": [
                    {"taskid": "1", "taskname": "read", "starttime": "07:00:00", "startdate": "2026-10-01", "enddate": "2026-10-01"},
                ],
            },
            {
                "schedule_name": "summer",
                "status": "0",
                "tasks": [
                    {"taskid": "11", "taskname": "read", "starttime": "08:30:00", "startdate": "2026-10-01", "enddate": "2026-10-01"},
                    {"taskid": "12", "taskname": "read", "starttime": "09:30:00", "startdate": "2026-10-01", "enddate": "2026-10-01"},
                ],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    api_public.PENDING_ACTION = None
    api_public._apply_move_schedule_intent(
        "move read 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02", "task_name": "read"},
    )
    reply, state, logs = api_public._handle_pending_action("3")

    assert "作息方案" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["kind"] == "target_disambiguation"
    assert api_public.PENDING_ACTION["target_type"] == "schedule"
    schedule_choices = api_public.PENDING_ACTION.get("choices") or []
    assert [str(item.get("label") or "") for item in schedule_choices] == ["spring", "summer"]
    assert any("07:00:00 read" in str(item.get("description") or "") for item in schedule_choices)
    assert any("08:30:00 read" in str(item.get("description") or "") for item in schedule_choices)
    assert all((item.get("slot_updates") or {}).get("schedule_scope", "") == "" for item in schedule_choices)
    assert all((item.get("slot_updates") or {}).get("schedule_names", []) == [] for item in schedule_choices)

    reply, state, logs = api_public._handle_pending_action("summer")

    assert "任务" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["kind"] == "target_disambiguation"
    assert api_public.PENDING_ACTION["target_type"] == "task"
    task_choices = api_public.PENDING_ACTION.get("choices") or []
    assert len(task_choices) == 2
    assert any("08:30" in str(item.get("description") or "") for item in task_choices)
    assert any("09:30" in str(item.get("description") or "") for item in task_choices)

    reply, state, logs = api_public._handle_pending_action("11")

    assert "08:30:00 read" in reply
    assert "09:30:00 read" not in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION.get("intent") == "move_schedule"
    assert api_public.PENDING_ACTION.get("schedule_name") == "summer"
    assert api_public.PENDING_ACTION.get("task_id") == "11"
    assert api_public.PENDING_ACTION.get("task_ids") == ["11"]


def test_select_all_enabled_schedules_can_permanently_cancel_across_multiple_schedules(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "status": "0",
                "tasks": [
                    {"taskid": "1", "taskname": "read", "starttime": "07:00:00", "startdate": "2026-10-01", "enddate": "2026-10-01"},
                ],
            },
            {
                "schedule_name": "summer",
                "status": "0",
                "tasks": [
                    {"taskid": "2", "taskname": "read", "starttime": "07:00:00", "startdate": "2026-10-01", "enddate": "2026-10-01"},
                ],
            },
        ],
        "broadcasts": [],
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

    api_public.PENDING_ACTION = None
    api_public._apply_cancel_schedule_intent(
        "cancel 2026-10-01 to 2026-10-01",
        {"source_time": "2026-10-01", "end_time": "2026-10-01"},
    )
    reply, state, logs = api_public._handle_pending_action("3")
    assert "请确认要一次性执行还是永久生效" in reply
    assert state["missing_slots"] == []
    assert logs == []
    reply, state, logs = api_public._handle_pending_action("永久")

    assert "已在 2 个启用中的作息方案中永久删除 2 条任务" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 2
    assert committed["payload"]["schedules"][0]["tasks"] == []
    assert committed["payload"]["schedules"][1]["tasks"] == []


def test_apply_cancel_schedule_does_not_route_cancel_execute_text_to_once(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "status": "启用",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "晨读",
                        "starttime": "07:00:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-07",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    called = {"count": 0}

    def fake_once(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("_execute_once_cancel_action should not be called")

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_execute_once_cancel_action", fake_once)

    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "取消执行春季作息中10月1日到10月7日的所有任务",
        {"schedule_name": "春季作息", "source_time": "10月1日", "end_time": "10月7日"},
    )

    assert called["count"] == 0
    assert state["missing_slots"] == []
    assert logs == []
    assert "请确认" in reply


def test_handle_pending_cancel_schedule_permanent_fails_when_remote_task_id_cannot_be_resolved(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "status": "启用",
                "tasks": [
                    {
                        "taskid": "local-1",
                        "taskname": "晨读",
                        "starttime": "07:00:00",
                        "startdate": "2026-03-18",
                        "enddate": "2026-03-18",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    saved = {"called": False}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_resolve_remote_delete_task_ids",
        lambda schedule_name, tasks: ([], ["晨读"]),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda *args, **kwargs: saved.update({"called": True}),
    )

    api_public._set_pending_action(
        {
            "intent": "cancel_schedule",
            "schedule_name": "春季作息",
            "task_ids": ["local-1"],
            "task_name": "晨读",
            "time_start": "2026-03-18 07:00:00",
            "time_end": "2026-03-18 08:00:00",
            "date_specific": True,
            "confirm_prompt": "请确认一次性还是永久生效",
        }
    )

    reply, state, logs = api_public._handle_pending_action("永久")

    assert "无法确定远端任务ID" in reply
    assert "已取消本地保存" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert saved["called"] is False


def test_cancel_schedule_enabled_all_then_once_keeps_cancel_intent(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "夏季作息",
                "status": "0",
                "tasks": [
                    {"taskid": "1", "taskname": "晨读", "starttime": "07:00:00", "startdate": "2026-04-03", "enddate": "2026-04-03"},
                ],
            },
            {
                "schedule_name": "冬季作息",
                "status": "0",
                "tasks": [
                    {"taskid": "11", "taskname": "晨读", "starttime": "07:10:00", "startdate": "2026-04-03", "enddate": "2026-04-03"},
                ],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_execute_once_cancel_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": f"cancel-{action['schedule_name']}"},
            "已设置一次性取消,任务执行后将自动恢复。",
        ),
    )

    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "取消这周五的任务",
        {"source_time": "2026-04-03"},
    )

    assert "当前启用方案" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["kind"] == "target_disambiguation"

    reply, state, logs = api_public._handle_pending_action("全部")
    assert "请确认要一次性执行还是永久生效" in reply
    assert state["intent"] == "cancel_schedule"
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["schedule_scope"] == "enabled_all"

    reply, state, logs = api_public._handle_pending_action("一次性")
    assert reply == "已对 2 个启用中的作息方案执行一次性取消,共 2 条任务。"
    assert state["intent"] == "cancel_schedule"
    assert state["missing_slots"] == []
    assert len(logs) == 2


def test_cancel_schedule_rejects_expired_explicit_today_range(monkeypatch) -> None:
    _patch_now(monkeypatch, 2026, 4, 7, 20, 30, 0)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_summer_schedule_payload("2026-04-07")))

    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "取消今天夏季作息早上8点到10点的任务",
        {"schedule_name": "夏季作息", "source_time": "早上8点", "end_time": "10点"},
    )

    assert reply == "该时间段已结束，请改说明天或未来的具体日期。"
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is None


def test_cancel_schedule_once_keeps_explicit_today_range_on_same_day(monkeypatch) -> None:
    _patch_now(monkeypatch, 2026, 4, 7, 9, 0, 0)
    captured: dict = {}

    def fake_once(action, schedule, dry_run=False, diagnostics=None, diagnostic_id=""):
        del schedule, dry_run, diagnostics, diagnostic_id
        captured["action"] = deepcopy(action)
        return {"id": "cancel-1"}, "已设置一次性取消,任务执行后将自动恢复。"

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_summer_schedule_payload("2026-04-07")))
    monkeypatch.setattr(api_public, "_execute_once_cancel_action", fake_once)

    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "取消今天夏季作息早上8点到10点的任务",
        {"schedule_name": "夏季作息", "source_time": "早上8点", "end_time": "10点"},
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["time_start"] == "2026-04-07 08:00:00"
    assert api_public.PENDING_ACTION["time_end"] == "2026-04-07 10:00:00"

    reply, state, logs = api_public._handle_pending_action("一次性")

    assert reply == "已设置一次性取消,任务执行后将自动恢复。"
    assert state["intent"] == "cancel_schedule"
    assert captured["action"]["time_start"] == "2026-04-07 08:00:00"
    assert captured["action"]["time_end"] == "2026-04-07 10:00:00"
    assert logs[0]["time_range"]["start"] == "2026-04-07 08:00:00"
    assert logs[0]["time_range"]["end"] == "2026-04-07 10:00:00"


def test_cancel_schedule_once_keeps_explicit_tomorrow_range(monkeypatch) -> None:
    _patch_now(monkeypatch, 2026, 4, 7, 20, 30, 0)
    captured: dict = {}

    def fake_once(action, schedule, dry_run=False, diagnostics=None, diagnostic_id=""):
        del schedule, dry_run, diagnostics, diagnostic_id
        captured["action"] = deepcopy(action)
        return {"id": "cancel-2"}, "已设置一次性取消,任务执行后将自动恢复。"

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_summer_schedule_payload("2026-04-08")))
    monkeypatch.setattr(api_public, "_execute_once_cancel_action", fake_once)

    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "取消明天夏季作息早上8点到10点的任务",
        {"schedule_name": "夏季作息", "source_time": "早上8点", "end_time": "10点"},
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["time_start"] == "2026-04-08 08:00:00"
    assert api_public.PENDING_ACTION["time_end"] == "2026-04-08 10:00:00"

    reply, state, logs = api_public._handle_pending_action("一次性")

    assert reply == "已设置一次性取消,任务执行后将自动恢复。"
    assert captured["action"]["time_start"] == "2026-04-08 08:00:00"
    assert captured["action"]["time_end"] == "2026-04-08 10:00:00"
    assert logs[0]["time_range"]["start"] == "2026-04-08 08:00:00"
    assert logs[0]["time_range"]["end"] == "2026-04-08 10:00:00"


def test_cancel_schedule_without_explicit_date_keeps_next_day_rollover(monkeypatch) -> None:
    _patch_now(monkeypatch, 2026, 4, 7, 20, 30, 0)
    captured: dict = {}

    def fake_once(action, schedule, dry_run=False, diagnostics=None, diagnostic_id=""):
        del schedule, dry_run, diagnostics, diagnostic_id
        captured["action"] = deepcopy(action)
        return {"id": "cancel-3"}, "已设置一次性取消,任务执行后将自动恢复。"

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_summer_schedule_payload("2026-04-08")))
    monkeypatch.setattr(api_public, "_execute_once_cancel_action", fake_once)

    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "取消夏季作息早上8点到10点的任务",
        {"schedule_name": "夏季作息", "source_time": "早上8点", "end_time": "10点"},
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["time_start"] == "2026-04-08 08:00:00"
    assert api_public.PENDING_ACTION["time_end"] == "2026-04-08 10:00:00"

    reply, state, logs = api_public._handle_pending_action("一次性")

    assert reply == "已设置一次性取消,任务执行后将自动恢复。"
    assert captured["action"]["time_start"] == "2026-04-08 08:00:00"
    assert captured["action"]["time_end"] == "2026-04-08 10:00:00"
    assert logs[0]["time_range"]["start"] == "2026-04-08 08:00:00"
    assert logs[0]["time_range"]["end"] == "2026-04-08 10:00:00"


def test_cancel_schedule_followup_reuses_initial_absolute_time_range(monkeypatch) -> None:
    captured: dict = {}

    def fake_once(action, schedule, dry_run=False, diagnostics=None, diagnostic_id=""):
        del schedule, dry_run, diagnostics, diagnostic_id
        captured["action"] = deepcopy(action)
        return {"id": "cancel-4"}, "已设置一次性取消,任务执行后将自动恢复。"

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_summer_schedule_payload("2026-04-08")))
    monkeypatch.setattr(api_public, "_execute_once_cancel_action", fake_once)

    _patch_now(monkeypatch, 2026, 4, 7, 20, 30, 0)
    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_cancel_schedule_intent(
        "取消明天夏季作息早上8点到10点的任务",
        {"schedule_name": "夏季作息", "source_time": "早上8点", "end_time": "10点"},
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert api_public.PENDING_ACTION is not None
    assert api_public.PENDING_ACTION["time_start"] == "2026-04-08 08:00:00"
    assert api_public.PENDING_ACTION["time_end"] == "2026-04-08 10:00:00"

    _patch_now(monkeypatch, 2026, 4, 8, 20, 30, 0)
    reply, state, logs = api_public._handle_pending_action("一次性")

    assert reply == "已设置一次性取消,任务执行后将自动恢复。"
    assert state["intent"] == "cancel_schedule"
    assert captured["action"]["time_start"] == "2026-04-08 08:00:00"
    assert captured["action"]["time_end"] == "2026-04-08 10:00:00"
    assert logs[0]["time_range"]["start"] == "2026-04-08 08:00:00"
    assert logs[0]["time_range"]["end"] == "2026-04-08 10:00:00"
