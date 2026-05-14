from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_enable_schedule_with_schedule_and_task_scopes_inside_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [
                    {"taskid": "1", "taskname": "class_bell", "taskstate": 0, "status": "停止"},
                    {"taskid": "2", "taskname": "exercise", "taskstate": 0, "status": "停止"},
                ],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "3", "taskname": "class_bell", "taskstate": 0, "status": "停止"}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    def fake_save(new_payload, **kwargs):
        committed["payload"] = deepcopy(new_payload)
        committed["sync_flags"] = kwargs

    monkeypatch.setattr(api_public, "_save_schedules_payload", fake_save)

    reply, state, logs = api_public._apply_enable_schedule_intent(
        "enable spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "enable_schedule"
    assert logs[0]["task_ids"] == ["1"]

    updated = committed["payload"]
    spring_task = updated["schedules"][0]["tasks"][0]
    spring_other = updated["schedules"][0]["tasks"][1]
    winter_task = updated["schedules"][1]["tasks"][0]

    assert spring_task["taskstate"] == 1
    assert spring_task["status"] == "执行中"
    assert spring_other["taskstate"] == 0
    assert winter_task["taskstate"] == 0


def test_disable_schedule_without_task_updates_schedule_status(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "spring-2026", "status": "启用", "tasks": [{"taskid": "1", "taskname": "class_bell"}]}
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

    reply, state, logs = api_public._apply_disable_schedule_intent(
        "disable spring-2026",
        {"schedule_name": "spring-2026"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "disable_schedule"
    assert committed["payload"]["schedules"][0]["status"] == "停用"


def test_shift_schedule_later_creates_new_schedule_with_shifted_time(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [
                    {
                        "taskid": "10",
                        "id": "10",
                        "taskname": "class_bell",
                        "starttime": "23:50:00",
                        "time": "23:50",
                        "weekdays": ["周一"],
                        "execmode": 1,
                        "startdate": "2026-02-10",
                        "enddate": "2026-02-10",
                        "sechename": "spring",
                    }
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
        "_save_schedules_payload_local",
        lambda new_payload: committed.update({"payload": deepcopy(new_payload)}),
    )

    reply, state, logs = api_public._apply_shift_schedule_later_intent(
        "copy spring later by 20 minutes",
        {
            "schedule_name": "spring",
            "time_offset": "20分钟",
            "new_schedule_name": "winter",
        },
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "shift_schedule_later"

    created = [item for item in committed["payload"]["schedules"] if item.get("schedule_name") == "winter"][0]
    shifted_task = created["tasks"][0]
    assert shifted_task["starttime"] == "00:10:00"
    assert shifted_task["time"] == "00:10"
    assert shifted_task["weekdays"] == ["周二"]
    assert shifted_task["startdate"] == "2026-02-11"
    assert shifted_task["enddate"] == "2026-02-11"


def test_delete_schedule_removes_target_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "spring", "tasks": [{"taskid": "1"}]},
            {"schedule_name": "winter", "tasks": [{"taskid": "2"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    overrides = {
        "overrides": [
            {"id": "once-1", "mode": "once", "schedule_name": "spring", "action": "migrate"},
            {"id": "once-2", "mode": "once", "schedule_name": "winter", "action": "swap"},
            {"id": "manual-1", "mode": "manual", "schedule_name": "spring"},
        ]
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(overrides))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload_local",
        lambda new_payload: committed.update({"payload": deepcopy(new_payload)}),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: committed.update({"overrides": deepcopy(new_payload)}),
    )

    reply, state, logs = api_public._apply_delete_schedule_intent("delete spring", {"schedule_name": "spring"})

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "delete_schedule"
    remaining = [item.get("schedule_name") for item in committed["payload"]["schedules"]]
    assert remaining == ["winter"]
    remaining_override_ids = [item.get("id") for item in committed["overrides"]["overrides"]]
    assert remaining_override_ids == ["once-2", "manual-1"]


def test_replace_media_in_task_only_changes_target_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [{"taskid": "1", "mediaid": "101", "medianame": "bell_a", "audio": "bell_a"}],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "2", "mediaid": "101", "medianame": "bell_a", "audio": "bell_a"}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_media_map_for_replace", lambda: {"bell_a": "101", "bell_b": "202"})
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda new_payload, snapshot_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_replace_media_in_task_intent(
        "replace spring bell",
        {"schedule_name": "spring", "media_name": "bell_a", "new_media_name": "bell_b"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "replace_media_in_task"
    assert logs[0]["details"]["count"] == 1

    spring_task = committed["payload"]["schedules"][0]["tasks"][0]
    winter_task = committed["payload"]["schedules"][1]["tasks"][0]
    assert spring_task["mediaid"] == 202
    assert spring_task["medianame"] == "bell_b"
    assert spring_task["audio"] == "bell_b"
    assert winter_task["mediaid"] == "101"


def test_query_terminal_returns_online_offline_summary(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_resolve_terminal_ids_from_slots",
        lambda slots: (["101", "102"], {"terminal_name": ["missing-terminal"]}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [
            {"id": "101", "name": "room-101", "netstate": 1, "devicestate": 1, "taskstate": 0},
            {"id": "102", "name": "room-102", "netstate": 0, "devicestate": 1, "taskstate": 1},
        ],
    )

    reply, state, logs = api_public._apply_query_terminal_intent("query terminals", {"zone_name": "grade-3"})

    assert isinstance(reply, str)
    assert "在线 1 个" in reply
    assert "离线 1 个" in reply
    assert "没有匹配上" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "query_terminal"
    assert logs[0]["details"]["count"] == 2


def test_disable_terminal_is_explicitly_unsupported() -> None:
    reply, state, logs = api_public._apply_disable_terminal_intent("disable right one", {"terminal_name": "右一终端"})

    assert "暂不支持停用终端" in reply
    assert state["missing_slots"] == []
    assert logs == [{"action": "disable_terminal", "mode": "runtime", "status": "unsupported"}]


def test_enable_terminal_is_explicitly_unsupported() -> None:
    reply, state, logs = api_public._apply_enable_terminal_intent("enable right one", {"terminal_name": "右一终端"})

    assert "暂不支持启用终端" in reply
    assert state["missing_slots"] == []
    assert logs == [{"action": "enable_terminal", "mode": "runtime", "status": "unsupported"}]


def test_enable_disable_terminal_ignore_legacy_resolution_paths() -> None:
    reply, state, logs = api_public._apply_disable_terminal_intent("disable right one", {"terminal_name": "右一终端"})

    assert "暂不支持停用终端" in reply
    assert state["missing_slots"] == []
    assert logs[0]["status"] == "unsupported"


def test_remote_event_state_value_supports_nested_payloads() -> None:
    assert api_public._remote_event_state_value({"data": [{"id": "1", "state": 0}]}) == 0
    assert api_public._remote_event_state_value({"result": {"id": "1", "state": 95}}) == 95
    assert api_public._remote_event_state_value({"item": {"id": "1", "state": 7}}) == 7
    assert api_public._remote_event_state_value({"obj": {"id": "1", "state": 8}}) == 8


def test_sync_terminal_time_is_explicitly_unsupported() -> None:
    reply, state, logs = api_public._apply_sync_terminal_time_intent("sync time", {"terminal_name": "右一终端"})

    assert "暂不支持终端校时" in reply
    assert state["missing_slots"] == []
    assert logs == [{"action": "sync_terminal_time", "mode": "runtime", "status": "unsupported"}]


def test_sync_terminal_time_no_longer_exposes_legacy_failure_details() -> None:
    reply, state, logs = api_public._apply_sync_terminal_time_intent("sync time", {"terminal_name": "右一终端"})

    assert "暂不支持终端校时" in reply
    assert "diagnostics" not in state
    assert logs[0]["status"] == "unsupported"


def test_play_task_invalid_target_sets_retryable_false(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "abc", "taskname": "anthem", "taskstate": 0, "status": "停止"}],
        "livecasts": [],
    }
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_play_task_intent("play anthem", {"task_name": "anthem"})

    assert "有效编号" in reply or "目标" in reply
    assert state["diagnostics"][0]["user_reason"] == "目标任务缺少有效编号"
    assert state["diagnostics"][0]["retryable"] is False
    assert logs[0]["details"]["failure_reason"] == "invalid_targets=1"
    assert logs[0]["details"]["retryable"] is False


def test_enable_schedule_task_invalid_target_sets_retryable_false(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "spring", "tasks": [{"taskid": "abc", "taskname": "class_bell", "taskstate": 0, "status": "停止"}]}
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_enable_schedule_intent(
        "enable spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell"},
    )

    assert "有效编号" in reply or "目标" in reply
    assert state["diagnostics"][0]["user_reason"] == "目标任务缺少有效编号"
    assert state["diagnostics"][0]["retryable"] is False
    assert logs[0]["details"]["failure_reason"] == "invalid_targets=1"
    assert logs[0]["details"]["retryable"] is False


def test_shift_schedule_remote_failure_returns_structured_details(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [
                    {
                        "taskid": "10",
                        "id": "10",
                        "taskname": "class_bell",
                        "starttime": "08:00:00",
                        "time": "08:00",
                        "weekdays": ["周一"],
                        "execmode": 1,
                        "startdate": "2026-02-10",
                        "enddate": "2026-02-10",
                        "sechename": "spring",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_schedules_payload_local", lambda new_payload: None)
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_targeted",
        lambda payload, names: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="sync down")),
    )
    monkeypatch.setattr(api_public, "_cleanup_remote_created_schedule", lambda name: "remote residue")

    reply, state, logs = api_public._apply_shift_schedule_later_intent(
        "copy spring later by 20 minutes",
        {"schedule_name": "spring", "time_offset": "20分钟", "new_schedule_name": "winter"},
    )

    assert "方案位移" in reply
    assert "sync down" not in reply
    assert state["diagnostics"][0]["failure_reason"] == "sync down"
    assert "remote residue" in state["diagnostics"][0]["cleanup_error"]
    assert logs[0]["details"]["failure_reason"] == "sync down"
    assert "remote residue" in logs[0]["details"]["cleanup_error"]


def test_delete_zone_failure_returns_structured_details(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_strict_resolve_zone_ids", lambda *args, **kwargs: (["1"], [], None))
    monkeypatch.setattr(
        api_public,
        "_delete_zone_remote_checked",
        lambda zone_ids: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="delete down")),
    )

    reply, state, logs = api_public._apply_delete_zone_intent("delete zone", {"zone_name": "教学楼"})

    assert "删除" in reply
    assert "delete down" not in reply
    assert state["diagnostics"][0]["failure_reason"] == "delete down"
    assert state["diagnostics"][0]["user_reason"] == "分区删除没有完成"
    assert logs[0]["details"]["failure_reason"] == "delete down"


def test_add_terminal_to_zone_failure_returns_structured_details(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_strict_resolve_zone_ids", lambda *args, **kwargs: (["1"], [], None))
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots, expand_zones=False: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_update_zone_terminal_membership_remote_checked",
        lambda *args, **kwargs: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="zone update down")),
    )

    reply, state, logs = api_public._apply_add_terminal_to_zone_intent(
        "add terminal to zone",
        {"zone_name": "教学楼", "terminal_id": "101"},
    )

    assert "调整" in reply
    assert "zone update down" not in reply
    assert state["diagnostics"][0]["failure_reason"] == "zone update down"
    assert state["diagnostics"][0]["user_reason"] == "分区终端调整没有完成"
    assert logs[0]["details"]["failure_reason"] == "zone update down"


def test_add_terminal_to_task_remote_failure_returns_structured_details(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "1", "taskname": "anthem", "terminalids": ["2"], "liveterminalid": 2}],
        "livecasts": [],
    }
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: (["9"], {}))
    monkeypatch.setattr(api_public, "_terminal_lookup_for_actions", lambda: {})
    monkeypatch.setattr(api_public, "_remote_task_terminal_ids_checked", lambda task_id: (["2"], True))
    monkeypatch.setattr(
        api_public,
        "_remote_add_taskterminal",
        lambda task_id, tid: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="bind down")),
    )

    reply, state, logs = api_public._apply_add_terminal_to_task_intent(
        "add terminal to anthem",
        {"task_name": "anthem", "terminal_id": "9"},
    )

    assert "暂未生效" in reply
    assert "bind down" not in reply
    assert state["diagnostics"][0]["failure_reason"] == "anthem: bind down"
    assert state["diagnostics"][0]["user_reason"] == "终端调整暂未生效"
    assert logs[0]["details"]["failure_reason"] == "anthem: bind down"

def test_add_terminal_to_task_scopes_to_named_task_in_named_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [
                    {"taskid": "1", "taskname": "class_bell", "terminalids": ["1"], "liveterminalid": 1},
                    {"taskid": "2", "taskname": "exercise", "terminalids": ["3"], "liveterminalid": 3},
                ],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "3", "taskname": "class_bell", "terminalids": ["9"], "liveterminalid": 9}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: (["2"], {}))
    monkeypatch.setattr(
        api_public,
        "_terminal_lookup_for_actions",
        lambda: {
            "1": {"name": "terminal-1", "zone": 1},
            "2": {"name": "terminal-2", "zone": 1},
            "9": {"name": "terminal-9", "zone": 2},
        },
    )
    monkeypatch.setattr(api_public, "_location_paths_from_terminals", lambda ids, lookup: [["grade-1", "terminal-2"]])
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_add_terminal_to_task_intent(
        "add terminal to spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell", "terminal_id": "2"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "add_terminal_to_task"
    assert logs[0]["task_ids"] == ["1"]

    updated = committed["payload"]
    spring_target = updated["schedules"][0]["tasks"][0]
    spring_other = updated["schedules"][0]["tasks"][1]
    winter_target = updated["schedules"][1]["tasks"][0]

    assert spring_target["terminalids"] == ["1", "2"]
    assert spring_other["terminalids"] == ["3"]
    assert winter_target["terminalids"] == ["9"]


def test_remove_terminal_from_schedule_all_tasks_when_task_name_missing(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [
                    {"taskid": "1", "taskname": "class_bell", "terminalids": ["1", "2"], "liveterminalid": 1},
                    {"taskid": "2", "taskname": "exercise", "terminalids": ["2", "3"], "liveterminalid": 2},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: (["2"], {}))
    monkeypatch.setattr(api_public, "_terminal_lookup_for_actions", lambda: {"1": {"name": "terminal-1", "zone": 1}})
    monkeypatch.setattr(api_public, "_location_paths_from_terminals", lambda ids, lookup: [])
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_remove_terminal_from_task_intent(
        "remove terminal 2 from spring",
        {"schedule_name": "spring", "terminal_id": "2"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "remove_terminal_from_task"

    updated = committed["payload"]["schedules"][0]["tasks"]
    assert updated[0]["terminalids"] == ["1"]
    assert updated[1]["terminalids"] == ["3"]


def test_query_task_with_schedule_and_task_filters_within_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [{"taskid": "1", "taskname": "class_bell", "starttime": "07:00:00", "taskstate": 1}],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "2", "taskname": "class_bell", "starttime": "08:00:00", "taskstate": 1}],
            },
        ],
        "broadcasts": [{"taskid": "3", "taskname": "class_bell", "starttime": "09:00:00", "taskstate": 1}],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent(
        "query spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "query_task"
    assert logs[0]["details"]["count"] == 1
    task = logs[0]["details"]["tasks"][0]
    assert task["task_id"] == "1"
    assert task["schedule_name"] == "spring"


def test_play_task_with_schedule_and_task_filters_within_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [{"taskid": "1", "taskname": "class_bell", "taskstate": 0, "status": "停止", "terminalids": ["11"]}],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "2", "taskname": "class_bell", "taskstate": 0, "status": "停止", "terminalids": ["12"]}],
            },
        ],
        "broadcasts": [{"taskid": "3", "taskname": "class_bell", "taskstate": 0, "status": "停止", "terminalids": ["13"]}],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_play_task_intent(
        "play spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "play_task"
    assert logs[0]["task_ids"] == ["1"]

    updated = committed["payload"]
    assert updated["schedules"][0]["tasks"][0]["taskstate"] == 1
    assert updated["schedules"][1]["tasks"][0]["taskstate"] == 0
    assert updated["broadcasts"][0]["taskstate"] == 0


def test_stop_task_with_schedule_and_task_filters_within_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [{"taskid": "1", "taskname": "class_bell", "taskstate": 1, "status": "执行中"}],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "2", "taskname": "class_bell", "taskstate": 1, "status": "执行中"}],
            },
        ],
        "broadcasts": [{"taskid": "3", "taskname": "class_bell", "taskstate": 1, "status": "执行中"}],
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

    reply, state, logs = api_public._apply_stop_task_intent(
        "stop spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "stop_task"
    assert logs[0]["task_ids"] == ["1"]

    updated = committed["payload"]
    assert updated["schedules"][0]["tasks"][0]["taskstate"] == 0
    assert updated["schedules"][1]["tasks"][0]["taskstate"] == 1
    assert updated["broadcasts"][0]["taskstate"] == 1


def test_stop_task_requires_task_name() -> None:
    reply, state, logs = api_public._apply_stop_task_intent("stop task", {"schedule_name": "spring"})

    assert isinstance(reply, str)
    assert state["missing_slots"] == ["task_name"]
    assert logs == []


def test_apply_action_stop_task_uses_task_name_slot(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [
            {"taskid": "1", "taskname": "class_bell", "taskstate": 1, "status": "执行中"},
            {"taskid": "2", "taskname": "exercise", "taskstate": 1, "status": "执行中"},
        ],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "PENDING_ACTION", None)
    api_public.PENDING_ACTIONS_BY_SCOPE.clear()
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    result = {
        "intent": "stop_task",
        "status": "success",
        "slots": {"task_name": "class_bell"},
    }
    reply, state, logs = api_public._apply_action("stop class_bell", result)

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "stop_task"
    assert logs[0]["task_ids"] == ["1"]
    assert committed["payload"]["broadcasts"][0]["taskstate"] == 0
    assert committed["payload"]["broadcasts"][1]["taskstate"] == 1


def test_pause_task_with_schedule_and_task_filters_within_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [{"taskid": "1", "taskname": "class_bell", "taskstate": 1, "status": "执行中"}],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "2", "taskname": "class_bell", "taskstate": 1, "status": "执行中"}],
            },
        ],
        "broadcasts": [{"taskid": "3", "taskname": "class_bell", "taskstate": 1, "status": "执行中"}],
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

    reply, state, logs = api_public._apply_task_pause_intent(
        "pause spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "task_pause"
    assert logs[0]["task_ids"] == ["1"]
    updated = committed["payload"]
    assert updated["schedules"][0]["tasks"][0]["taskstate"] == 2
    assert updated["schedules"][1]["tasks"][0]["taskstate"] == 1
    assert updated["broadcasts"][0]["taskstate"] == 1


def test_resume_task_with_schedule_and_task_filters_within_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "tasks": [{"taskid": "1", "taskname": "class_bell", "taskstate": 2, "status": "暂停"}],
            },
            {
                "schedule_name": "winter",
                "tasks": [{"taskid": "2", "taskname": "class_bell", "taskstate": 2, "status": "暂停"}],
            },
        ],
        "broadcasts": [{"taskid": "3", "taskname": "class_bell", "taskstate": 2, "status": "暂停"}],
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

    reply, state, logs = api_public._apply_task_resume_intent(
        "resume spring class_bell",
        {"schedule_name": "spring", "task_name": "class_bell"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "task_resume"
    assert logs[0]["task_ids"] == ["1"]
    updated = committed["payload"]
    assert updated["schedules"][0]["tasks"][0]["taskstate"] == 3
    assert updated["schedules"][0]["tasks"][0]["status"] == "执行中"
    assert updated["schedules"][1]["tasks"][0]["taskstate"] == 2
    assert updated["broadcasts"][0]["taskstate"] == 2


def test_apply_action_pause_task_alias_uses_task_name_slot(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [
            {"taskid": "1", "taskname": "class_bell", "taskstate": 1, "status": "执行中"},
            {"taskid": "2", "taskname": "exercise", "taskstate": 1, "status": "执行中"},
        ],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "PENDING_ACTION", None)
    api_public.PENDING_ACTIONS_BY_SCOPE.clear()
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    result = {
        "intent": "pause_task",
        "status": "success",
        "slots": {"task_name": "class_bell"},
    }
    reply, state, logs = api_public._apply_action("pause class_bell", result)

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "task_pause"
    assert logs[0]["task_ids"] == ["1"]
    assert committed["payload"]["broadcasts"][0]["taskstate"] == 2
    assert committed["payload"]["broadcasts"][1]["taskstate"] == 1


def test_remote_schedule_enabletask_chunks_by_90(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/task/enabletask"
        payload = kwargs.get("form_body") or kwargs.get("json_body") or {}
        calls.append(payload)
        return {}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    ids = [str(i) for i in range(1, 206)]
    payloads = api_public._remote_schedule_enabletask(ids, 0, datetime(2026, 2, 11, 10, 0, 0), dry_run=False)

    assert len(payloads) == 3
    assert len(calls) == 3
    assert [len(str(item["taskid"]).split(",")) for item in payloads] == [90, 90, 25]
    assert all(item["enstate"].split(",")[0] == "0" for item in payloads)
    assert all("yuantaskid" not in item for item in payloads)
    assert all("yuantaskid" not in item for item in calls)


def test_handle_pending_task_cancel_once_sends_disable_and_restore(monkeypatch) -> None:
    payload = {
        "schedules": [{"schedule_name": "S", "tasks": [{"taskid": "1"}, {"taskid": "2"}]}],
        "broadcasts": [],
        "livecasts": [],
    }
    sent_payloads: list[dict] = []
    saved: dict = {}

    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/task/enabletask"
        sent_payloads.append(kwargs.get("form_body") or kwargs.get("json_body") or {})
        return {}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "PENDING_ACTION",
        {
            "intent": "cancel_schedule",
            "schedule_name": "S",
            "task_ids": ["1", "2"],
            "time_start": "2026-02-11 10:00:00",
            "time_end": "2026-02-11 10:30:00",
            "date_specific": True,
            "created_at": api_public._now_str(),
        },
    )

    reply, state, logs = api_public._handle_pending_action("once")

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "cancel_schedule"
    assert logs[0]["mode"] == "once"
    assert len(sent_payloads) == 2
    assert sent_payloads[0]["taskid"] == "1,2"
    assert sent_payloads[0]["enstate"] == "1,1"
    assert sent_payloads[0]["starttime"] == "09:59:55"
    assert sent_payloads[1]["taskid"] == "1,2"
    assert sent_payloads[1]["enstate"] == "0,0"
    assert sent_payloads[1]["starttime"] == "10:30:00"
    assert saved["data"]["overrides"][0]["action"] == "cancel"


def test_execute_once_migrate_records_source_and_conflict_windows(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            {
                "taskid": "1",
                "tasktype": "2",
                "starttime": "10:00:00",
                "startdate": "2026-02-11",
                "enddate": "2026-02-11",
            },
            {
                "taskid": "2",
                "tasktype": "2",
                "starttime": "11:05:00",
                "startdate": "2026-02-12",
                "enddate": "2026-02-12",
            },
        ],
    }
    action = {
        "schedule_name": "S",
        "task_ids": ["1"],
        "time_start": "2026-02-11 10:00:00",
        "time_end": "2026-02-11 10:10:00",
        "new_time_start": "2026-02-12 11:00:00",
        "new_time_end": "2026-02-12 11:10:00",
    }
    saved: dict = {}

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))

    entry, reply = api_public._execute_once_migrate_action(action, schedule, dry_run=True)

    assert isinstance(reply, str)
    assert entry["action"] == "migrate"
    assert entry["shadow_task_ids"] == ["dryrun-once-1"]
    assert entry["conflict_task_ids"] == ["2"]
    enable_cmds = [item for item in entry["commands"] if item.get("type") == "enabletask"]
    assert len(enable_cmds) == 5
    assert enable_cmds[0]["payload"]["taskid"] == "dryrun-once-1"
    assert enable_cmds[0]["payload"]["enstate"] == "0"
    assert enable_cmds[1]["payload"]["taskid"] == "1"
    assert enable_cmds[3]["payload"]["taskid"] == "2"
    assert saved["data"]["overrides"][0]["action"] == "migrate"


def test_apply_swap_schedule_intent_once_routes_to_once_executor(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "S",
                "tasks": [
                    {
                        "taskid": "10",
                        "tasktype": "2",
                        "starttime": "10:00:00",
                        "startdate": "2026-02-11",
                        "enddate": "2026-02-11",
                    },
                    {
                        "taskid": "20",
                        "tasktype": "2",
                        "starttime": "10:00:00",
                        "startdate": "2026-02-12",
                        "enddate": "2026-02-12",
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    saved: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))
    monkeypatch.setattr(api_public, "PENDING_ACTION", None)

    reply, state, logs = api_public._apply_swap_schedule_intent(
        "once swap these tasks",
        {"schedule_name": "S", "source_time": "2026-02-11", "target_time": "2026-02-12"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "swap_schedule"
    assert logs[0]["mode"] == "once"
    overrides = saved["data"]["overrides"]
    assert len(overrides) == 1
    assert overrides[0]["action"] == "swap"
    assert len(overrides[0]["shadow_task_ids"]) == 2


def test_normalize_intent_label_maps_phase3_aliases() -> None:
    assert api_public._normalize_intent_label("cancel_task") == "cancel_task"
    assert api_public._normalize_intent_label("move_task") == "move_task"
    assert api_public._normalize_intent_label("swap_task") == "swap_schedule"
    assert api_public._normalize_intent_label("task_pause") == "pause_task"
    assert api_public._normalize_intent_label("task_resume") == "resume_task"
    assert api_public._normalize_intent_label("pause_task") == "pause_task"
    assert api_public._normalize_intent_label("resume_task") == "resume_task"


def test_remote_extract_taskid_supports_common_response_shapes() -> None:
    assert api_public._remote_extract_taskid({"data": {"id": 12345}}) == "12345"
    assert api_public._remote_extract_taskid({"data": 67890}) == "67890"
    assert api_public._remote_extract_taskid({"result": {"taskid": "24680"}}) == "24680"
