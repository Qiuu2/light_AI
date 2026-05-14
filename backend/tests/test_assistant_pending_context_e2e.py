from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public
from backend.assistant.dispatch import apply_action


def _auth_session(name: str = "tester") -> dict[str, str]:
    return api_public._create_local_session("remote-test-token", name, "test")


def _set_scoped_pending(action: dict, session_token: str) -> None:
    api_public._set_pending_action_for_scope(deepcopy(action), session_token)


def _with_pending_scope(session_token: str, func):
    reset_scope = api_public._set_current_pending_scope(session_token)
    try:
        return func()
    finally:
        api_public._reset_current_pending_scope(reset_scope)


def _apply_action_as_session(text: str, result: dict, session_token: str):
    return _with_pending_scope(session_token, lambda: apply_action(text, deepcopy(result)))


def _schedule_payload() -> dict:
    return {
        "schedules": [
            {
                "schedule_name": "S",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "morning-read",
                        "starttime": "08:00:00",
                        "startdate": "2026-03-21",
                        "enddate": "2026-03-21",
                    },
                    {
                        "taskid": "2",
                        "taskname": "exercise",
                        "starttime": "08:30:00",
                        "startdate": "2026-03-22",
                        "enddate": "2026-03-22",
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }


def _stale_followup_result() -> dict:
    return {
        "intent": "sync_terminal_time",
        "intent_confidence": 0.62,
        "slots": {"play_count": "一"},
        "missing_slots": [],
        "entities": {"play_count": ["一"]},
        "tokens": ["一", "次", "性"],
        "tag_ids": [9, 0, 0],
        "status": "success",
    }


def test_assistant_dispatch_pending_cancel_once_cleans_stale_metadata(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(
        api_public,
        "_execute_once_cancel_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": "cancel-1"},
            "已设置一次性取消，任务执行后将自动恢复。",
        ),
    )

    session = _auth_session("cancel-clean")
    _set_scoped_pending(
        {
            "intent": "cancel_schedule",
            "schedule_name": "S",
            "task_ids": ["1"],
            "time_start": "2026-03-21 08:00:00",
            "time_end": "2026-03-21 08:10:00",
            "date_specific": True,
            "slots": {"schedule_name": "S", "source_time": "2026-03-21"},
        },
        session["token"],
    )

    reply, overrides, action_log = _apply_action_as_session("一次性", _stale_followup_result(), session["token"])

    assert reply == "已设置一次性取消，任务执行后将自动恢复。"
    assert overrides["intent"] == "cancel_schedule"
    assert overrides["confidence"] == 1.0
    assert overrides["slots"] == {"schedule_name": "S", "source_time": "2026-03-21"}
    assert overrides["raw_entities"] == {}
    assert overrides["tokens"] == []
    assert overrides["tags"] == []
    assert action_log[0]["action"] == "cancel_schedule"


def test_assistant_dispatch_pending_move_once_overrides_wrong_fresh_intent(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(
        api_public,
        "_execute_once_migrate_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": "move-1", "shadow_task_ids": []},
            "已设置一次性挪动，原任务会在原时段静音并在目标时段播放临时任务。",
        ),
    )

    session = _auth_session("move-clean")
    _set_scoped_pending(
        {
            "intent": "move_schedule",
            "schedule_name": "S",
            "task_ids": ["1"],
            "date_specific": True,
            "source_text": "2026-03-21",
            "target_text": "2026-03-22",
            "source_anchor": {"kind": "date", "date": api_public.date(2026, 3, 21)},
            "target_anchor": {"kind": "date", "date": api_public.date(2026, 3, 22)},
            "slots": {"schedule_name": "S", "source_time": "2026-03-21", "target_time": "2026-03-22"},
        },
        session["token"],
    )

    reply, overrides, action_log = _apply_action_as_session("一次性", _stale_followup_result(), session["token"])

    assert reply == "已设置一次性挪动，原任务会在原时段静音并在目标时段播放临时任务。"
    assert overrides["intent"] == "move_schedule"
    assert overrides["confidence"] == 1.0
    assert overrides["slots"] == {"schedule_name": "S", "source_time": "2026-03-21", "target_time": "2026-03-22"}
    assert overrides["raw_entities"] == {}
    assert overrides["tokens"] == []
    assert overrides["tags"] == []
    assert action_log[0]["action"] == "move_schedule"


def test_assistant_dispatch_pending_swap_once_overrides_wrong_fresh_intent(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(
        api_public,
        "_execute_once_swap_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": "swap-1", "shadow_task_ids": []},
            "已设置一次性对调，原任务会在对调时段临时互换。",
        ),
    )

    session = _auth_session("swap-clean")
    _set_scoped_pending(
        {
            "intent": "swap_schedule",
            "schedule_name": "S",
            "task_ids_a": ["1"],
            "task_ids_b": ["2"],
            "date_specific": True,
            "source_text": "2026-03-21",
            "target_text": "2026-03-22",
            "anchor_a": {"kind": "date", "date": api_public.date(2026, 3, 21)},
            "anchor_b": {"kind": "date", "date": api_public.date(2026, 3, 22)},
            "slots": {"schedule_name": "S", "source_time": "2026-03-21", "target_time": "2026-03-22"},
        },
        session["token"],
    )

    reply, overrides, action_log = _apply_action_as_session("一次性", _stale_followup_result(), session["token"])

    assert reply == "已设置一次性对调，原任务会在对调时段临时互换。"
    assert overrides["intent"] == "swap_schedule"
    assert overrides["confidence"] == 1.0
    assert overrides["slots"] == {"schedule_name": "S", "source_time": "2026-03-21", "target_time": "2026-03-22"}
    assert overrides["raw_entities"] == {}
    assert overrides["tokens"] == []
    assert overrides["tags"] == []
    assert action_log[0]["action"] == "swap_schedule"


def test_assistant_dispatch_cancel_ambiguity_chain_all_then_once_keeps_pending_context(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "夏季作息",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "晨读",
                        "starttime": "07:00:00",
                        "startdate": "2026-04-03",
                        "enddate": "2026-04-03",
                    }
                ],
            },
            {
                "schedule_name": "冬季作息",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "11",
                        "taskname": "晨读",
                        "starttime": "07:10:00",
                        "startdate": "2026-04-03",
                        "enddate": "2026-04-03",
                    }
                ],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    initial_result = {
        "intent": "cancel_schedule",
        "intent_confidence": 0.98,
        "slots": {"source_time": "2026-04-03"},
        "missing_slots": [],
        "entities": {"source_time": ["2026-04-03"]},
        "tokens": ["取消", "这周五", "任务"],
        "tag_ids": [1, 2, 3],
        "status": "success",
    }

    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_execute_once_cancel_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": f"cancel-{action['schedule_name']}"},
            "已设置一次性取消，任务执行后将自动恢复。",
        ),
    )

    session = _auth_session("cancel-chain")

    first_reply, first_overrides, _ = _apply_action_as_session("取消这周五的任务", initial_result, session["token"])
    assert "当前启用方案" in first_reply
    assert first_overrides["intent"] == "cancel_schedule"
    assert api_public._snapshot_pending_action(session["token"]) is not None

    second_reply, second_overrides, _ = _apply_action_as_session("全部", _stale_followup_result(), session["token"])
    assert "一次性执行还是永久生效" in second_reply
    assert second_overrides["intent"] == "cancel_schedule"
    assert second_overrides["confidence"] == 1.0
    assert second_overrides["raw_entities"] == {}
    assert second_overrides["tokens"] == []
    assert second_overrides["tags"] == []

    third_reply, third_overrides, third_log = _apply_action_as_session("一次性", _stale_followup_result(), session["token"])
    assert "一次性取消" in third_reply
    assert third_overrides["intent"] == "cancel_schedule"
    assert third_overrides["confidence"] == 1.0
    assert third_overrides["raw_entities"] == {}
    assert third_overrides["tokens"] == []
    assert third_overrides["tags"] == []
    assert len(third_log) == 2
    assert {item["schedule_name"] for item in third_log} == {"夏季作息", "冬季作息"}


def test_assistant_dispatch_move_weekday_disambiguation_can_continue_once(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    recurring_payload = deepcopy(_schedule_payload())
    recurring_payload["schedules"][0]["tasks"][0]["startdate"] = "0-00-00"
    recurring_payload["schedules"][0]["tasks"][0]["enddate"] = "0-00-00"
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(recurring_payload))

    def fake_once(action, schedule, dry_run=False, diagnostics=None, diagnostic_id=""):
        del schedule, dry_run, diagnostics, diagnostic_id
        captured["action"] = deepcopy(action)
        return {"id": "move-weekday", "shadow_task_ids": []}, "已设置一次性挪动，原任务会在原时段静音并在目标时段播放临时任务。"

    monkeypatch.setattr(api_public, "_execute_once_migrate_action", fake_once)

    session = _auth_session("weekday-move")
    _set_scoped_pending(
        {
            "intent": "move_schedule",
            "schedule_name": "S",
            "task_ids": ["1"],
            "task_groups": [{"schedule_name": "S", "task_ids": ["1"], "count": 1}],
            "schedule_scope": "single",
            "source_text": "周五",
            "target_text": "周六",
            "source_anchor": {"kind": "date", "date": api_public.date(2026, 4, 3)},
            "target_anchor": {"kind": "date", "date": api_public.date(2026, 4, 4)},
            "date_specific": False,
            "weekday_disambiguation": True,
            "ambiguous_items": [
                {
                    "anchor_key": "source_anchor",
                    "label": "源时间",
                    "weekday": "周五",
                    "this_week_date": api_public.date(2026, 4, 3),
                    "next_week_date": api_public.date(2026, 4, 10),
                }
            ],
            "slots": {"schedule_name": "S", "source_time": "周五", "target_time": "周六"},
        },
        session["token"],
    )

    reply, overrides, action_log = _apply_action_as_session("下周", _stale_followup_result(), session["token"])

    assert reply.startswith("已设置一次性挪动")
    assert overrides["intent"] == "move_schedule"
    assert overrides["confidence"] == 1.0
    assert overrides["raw_entities"] == {}
    assert overrides["tokens"] == []
    assert overrides["tags"] == []
    assert action_log[0]["action"] == "move_schedule"
    assert captured["action"]["time_start"].startswith("2026-04-10 ")
    assert captured["action"]["new_time_start"].startswith("2026-04-04 ")
