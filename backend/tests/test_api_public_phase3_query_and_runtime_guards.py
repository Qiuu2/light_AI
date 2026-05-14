from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_query_task_without_time_returns_all_matching_tasks(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {"taskid": "1", "taskname": "morning_reading", "starttime": "07:00:00", "taskstate": 0},
                    {"taskid": "2", "taskname": "morning_reading", "starttime": "08:00:00", "taskstate": 1},
                    {"taskid": "3", "taskname": "morning_reading", "starttime": "09:00:00", "taskstate": 2},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent("query morning_reading", {"task_name": "morning_reading"})

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 3
    assert {item["task_id"] for item in details["tasks"]} == {"1", "2", "3"}


def test_query_task_without_time_excludes_broadcasts_and_livecasts(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [{"taskid": "1", "taskname": "schedule_only", "starttime": "08:00:00", "taskstate": 0}],
            }
        ],
        "broadcasts": [{"taskid": "21", "taskname": "file_broadcast", "starttime": "00:00:00", "taskstate": 0}],
        "livecasts": [{"taskid": "31", "taskname": "livecast_task", "starttime": "16:32:00", "taskstate": 0}],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent("query all tasks", {})

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]
    assert all(item["kind"] == "schedule" for item in details["tasks"])


def test_query_task_without_schedule_name_excludes_disabled_schedules(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "status": "启用",
                "tasks": [{"taskid": "1", "taskname": "anthem", "starttime": "08:00:00"}],
            },
            {
                "schedule_name": "summer_schedule",
                "status": "停用",
                "tasks": [{"taskid": "2", "taskname": "anthem", "starttime": "08:00:00"}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent("query anthem", {"task_name": "anthem"})

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]
    assert details["tasks"][0]["schedule_name"] == "spring_schedule"


def test_query_task_without_schedule_name_reports_when_no_enabled_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "status": "停用",
                "tasks": [{"taskid": "1", "taskname": "anthem", "starttime": "08:00:00"}],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent("query anthem", {"task_name": "anthem"})

    assert "当前没有启用中的作息方案" in reply
    assert state["missing_slots"] == ["schedule_name"]
    assert logs == []


def test_query_task_source_time_alias_filters_schedule_tasks_only(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "afternoon_bell",
                        "starttime": "16:15:00",
                        "startdate": "2026-03-23",
                        "enddate": "2026-03-23",
                    },
                    {
                        "taskid": "2",
                        "taskname": "afternoon_break",
                        "starttime": "15:05:00",
                        "startdate": "2026-03-23",
                        "enddate": "2026-03-23",
                    },
                ],
            }
        ],
        "broadcasts": [{"taskid": "21", "taskname": "file_broadcast", "starttime": "16:15:00", "taskstate": 0}],
        "livecasts": [{"taskid": "31", "taskname": "livecast_task", "starttime": "16:15:00", "taskstate": 0}],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query task at a point in time",
        {"source_time": "2026-03-23 16:15"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]
    assert details["time_range_start"] == "2026-03-23 16:15"
    assert details["time_range_end"] == ""


def test_query_task_source_time_and_end_time_alias_filter_range(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "early_reading",
                        "starttime": "07:50:00",
                        "startdate": "2026-03-23",
                        "enddate": "2026-03-23",
                    },
                    {
                        "taskid": "2",
                        "taskname": "first_class",
                        "starttime": "08:20:00",
                        "startdate": "2026-03-23",
                        "enddate": "2026-03-23",
                    },
                    {
                        "taskid": "3",
                        "taskname": "school_end",
                        "starttime": "16:15:00",
                        "startdate": "2026-03-23",
                        "enddate": "2026-03-23",
                    },
                    {
                        "taskid": "4",
                        "taskname": "late_task",
                        "starttime": "17:30:00",
                        "startdate": "2026-03-23",
                        "enddate": "2026-03-23",
                    },
                ],
            }
        ],
        "broadcasts": [{"taskid": "21", "taskname": "file_broadcast", "starttime": "16:32:00", "taskstate": 0}],
        "livecasts": [{"taskid": "31", "taskname": "livecast_task", "starttime": "11:14:00", "taskstate": 0}],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query task by time range",
        {"source_time": "2026-03-23 08:00", "end_time": "2026-03-23 17:00"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 2
    assert [item["task_id"] for item in details["tasks"]] == ["2", "3"]
    assert details["time_range_start"] == "2026-03-23 08:00"
    assert details["time_range_end"] == "2026-03-23 17:00"


def test_query_task_time_window_matches_tasks_across_midnight(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "night_schedule",
                "tasks": [
                    {"taskid": "1", "taskname": "night_watch", "starttime": "23:55:00", "taskstate": 1},
                    {"taskid": "2", "taskname": "night_watch", "starttime": "00:05:00", "taskstate": 1},
                    {"taskid": "3", "taskname": "night_watch", "starttime": "22:30:00", "taskstate": 1},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query cross-midnight tasks",
        {"task_name": "night_watch", "time_range_start": "23:50", "time_range_end": "00:10"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 2
    assert {item["task_id"] for item in details["tasks"]} == {"1", "2"}


def test_query_task_date_window_respects_task_date_span_and_weekdays(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "weekly_schedule",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "flag_raise",
                        "starttime": "08:00:00",
                        "timelength": 10,
                        "timelengthtype": 1,
                        "startdate": "2026-03-01",
                        "enddate": "2026-03-31",
                        "weekdays": ["周一"],
                        "taskstate": 1,
                    },
                    {
                        "taskid": "2",
                        "taskname": "flag_raise",
                        "starttime": "08:00:00",
                        "timelength": 10,
                        "timelengthtype": 1,
                        "startdate": "2026-03-01",
                        "enddate": "2026-03-31",
                        "weekdays": ["周二"],
                        "taskstate": 1,
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query monday flag raise",
        {
            "task_name": "flag_raise",
            "time_range_start": "2026-03-23 07:55",
            "time_range_end": "2026-03-23 08:05",
        },
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]


def test_query_task_dated_window_matches_previous_day_cross_midnight_occurrence(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "night_schedule",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "night_watch",
                        "starttime": "23:55:00",
                        "timelength": 600,
                        "timelengthtype": 1,
                        "startdate": "2026-03-22",
                        "enddate": "2026-03-22",
                        "taskstate": 1,
                    },
                    {
                        "taskid": "2",
                        "taskname": "night_watch",
                        "starttime": "23:40:00",
                        "timelength": 300,
                        "timelengthtype": 1,
                        "startdate": "2026-03-23",
                        "enddate": "2026-03-23",
                        "taskstate": 1,
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query dated cross-midnight night_watch",
        {
            "task_name": "night_watch",
            "time_range_start": "2026-03-23 00:00",
            "time_range_end": "2026-03-23 00:04",
        },
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]


def test_query_task_ambiguous_name_returns_pending_action(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [{"taskid": "11", "taskname": "anthem_alpha", "starttime": "07:00:00", "taskstate": 0}],
            },
            {
                "schedule_name": "summer_schedule",
                "tasks": [{"taskid": "12", "taskname": "anthem_beta", "starttime": "08:00:00", "taskstate": 0}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    api_public._clear_pending_action()

    reply, state, logs = api_public._apply_query_task_intent("query anthem", {"task_name": "anthem"})

    assert "请确认" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert isinstance(api_public.PENDING_ACTION, dict)
    assert api_public.PENDING_ACTION.get("kind") == "target_disambiguation"
    assert api_public.PENDING_ACTION.get("target_type") == "task"
    api_public._clear_pending_action()


def test_check_terminal_without_netstate_reports_unknown(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: ([], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [{"id": "1", "name": "教学楼"}, {"id": "2", "name": "操场"}],
    )
    monkeypatch.setattr(
        api_public,
        "_check_terminal_online_status",
        lambda terminal_ids: (_ for _ in ()).throw(AssertionError("should not use fallback status probe")),
    )

    reply, state, logs = api_public._apply_check_terminal_intent("做一次终端自检", {})

    assert state["missing_slots"] == []
    assert "未知 2 个" in reply
    assert logs[0]["details"]["unknown_names"] == ["教学楼", "操场"]
    assert logs[0]["details"]["offline_names"] == []


def test_remote_write_ack_requires_non_empty_positive_payload() -> None:
    assert api_public._remote_write_ack_ok({"status": "ok"}) is True
    assert api_public._remote_write_ack_ok({"raw": "OK"}) is True
    assert api_public._remote_write_ack_ok({"data": [{"accepted": True}]}) is True
    assert api_public._remote_write_ack_ok({}) is False
    assert api_public._remote_write_ack_ok(None) is False
    assert api_public._remote_write_ack_ok({"message": "failure"}) is False


def test_post_remote_eventid_rejects_unacknowledged_payload(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {})

    with pytest.raises(api_public.HTTPException) as exc_info:
        api_public._post_remote_eventid("/terminal/syncntp", ["101"])

    assert exc_info.value.status_code == 502
    assert "not acknowledged" in str(exc_info.value.detail)


def test_play_task_rejects_non_numeric_task_id_without_mutating_payload(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [
            {
                "taskid": "abc",
                "taskname": "anthem",
                "starttime": "07:00:00",
                "taskstate": 0,
                "terminalids": ["11"],
            }
        ],
        "livecasts": [],
    }
    remote_calls: list[tuple[str, int]] = []
    saved_payloads: list[dict] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_remote_set_task_state",
        lambda task_id, state: remote_calls.append((str(task_id), int(state))),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: saved_payloads.append(deepcopy(new_payload)),
    )

    reply, state, logs = api_public._apply_play_task_intent("play anthem", {"task_name": "anthem"})

    assert isinstance(reply, str)
    assert "\u5931\u8d25" in reply
    assert "\u65e0\u6548 task_id" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert remote_calls == []
    assert saved_payloads == []


def test_remove_terminal_from_task_rejects_non_numeric_task_id_without_mutating_payload(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {
                        "taskid": "abc",
                        "taskname": "morning_reading",
                        "starttime": "07:00:00",
                        "taskstate": 0,
                        "terminalids": ["11"],
                        "liveterminalid": "11",
                        "liveterminalname": "terminal_one",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    remote_calls: list[tuple[str, tuple[str, ...]]] = []
    saved_payloads: list[dict] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_remote_remove_taskterminals",
        lambda task_id, terminal_ids, **kwargs: remote_calls.append(
            (str(task_id), tuple(str(item) for item in terminal_ids))
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: saved_payloads.append(deepcopy(new_payload)),
    )

    reply, state, logs = api_public._apply_remove_terminal_from_task_intent(
        "remove morning_reading terminal",
        {"schedule_name": "spring_schedule", "task_name": "morning_reading", "terminal_id": "11"},
    )

    assert isinstance(reply, str)
    assert "\u5931\u8d25" in reply or "\u65e0\u6548 task_id" in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert remote_calls == []
    assert saved_payloads == []


def test_query_terminal_without_netstate_reports_unknown_consistently(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: (["1"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [{"id": "1", "name": "terminal_one"}],
    )

    reply, state, logs = api_public._apply_query_terminal_intent("query terminal", {"terminal_id": "1"})

    assert state["missing_slots"] == []
    assert "未知 1 个" in reply
    assert logs[0]["details"]["unknown"] == 1
    assert logs[0]["details"]["unknown_names"] == ["terminal_one"]


def test_query_task_end_only_date_filter_is_respected(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "anthem",
                        "starttime": "08:00:00",
                        "timelength": 10,
                        "timelengthtype": 1,
                        "startdate": "2026-03-21",
                        "enddate": "2026-03-21",
                    },
                    {
                        "taskid": "2",
                        "taskname": "anthem",
                        "starttime": "08:00:00",
                        "timelength": 10,
                        "timelengthtype": 1,
                        "startdate": "2026-03-22",
                        "enddate": "2026-03-22",
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query anthem by end only",
        {"task_name": "anthem", "time_range_end": "2026-03-21"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]


def test_query_task_schedule_name_limits_results_to_that_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "tasks": [{"taskid": "1", "taskname": "anthem", "starttime": "08:00:00"}],
            },
            {
                "schedule_name": "summer_schedule",
                "tasks": [{"taskid": "2", "taskname": "anthem", "starttime": "09:00:00"}],
            },
        ],
        "broadcasts": [{"taskid": "21", "taskname": "anthem", "starttime": "10:00:00"}],
        "livecasts": [{"taskid": "31", "taskname": "anthem", "starttime": "11:00:00"}],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query spring anthem",
        {"schedule_name": "spring_schedule", "task_name": "anthem"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]
    assert details["schedule_name"] == "spring_schedule"


def test_query_task_schedule_name_still_queries_disabled_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "status": "停用",
                "tasks": [{"taskid": "1", "taskname": "anthem", "starttime": "08:00:00"}],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query disabled spring anthem",
        {"schedule_name": "spring_schedule", "task_name": "anthem"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    details = logs[0]["details"]
    assert details["count"] == 1
    assert [item["task_id"] for item in details["tasks"]] == ["1"]
    assert details["schedule_name"] == "spring_schedule"


def test_query_task_preview_includes_schedule_name_when_multiple_enabled_schedules_match(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "status": "启用",
                "tasks": [{"taskid": "1", "taskname": "anthem", "starttime": "08:00:00"}],
            },
            {
                "schedule_name": "summer_schedule",
                "status": "启用",
                "tasks": [{"taskid": "2", "taskname": "anthem", "starttime": "08:00:00"}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent("query anthem", {"task_name": "anthem"})

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert "spring_schedule/anthem(08:00)" in reply
    assert "summer_schedule/anthem(08:00)" in reply


def test_remote_write_ack_requires_explicit_positive_signal() -> None:
    assert api_public._remote_write_ack_ok({"status": "ok"}) is True
    assert api_public._remote_write_ack_ok({"raw": "OK"}) is True
    assert api_public._remote_write_ack_ok({"data": [{"accepted": True}]}) is True
    assert api_public._remote_write_ack_ok({"message": "queued"}) is False
    assert api_public._remote_write_ack_ok({"raw": "accepted"}) is False
