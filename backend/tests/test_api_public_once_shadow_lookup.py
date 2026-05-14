from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def _extract_post_payload(kwargs: dict) -> dict:
    body = kwargs.get("json_body")
    if body is None:
        body = kwargs.get("form_body")
    return deepcopy(body or {})


def _make_task(
    task_id: str,
    start_time: str,
    start_date: str,
    *,
    taskname: str = "task",
    mediaid: str = "11",
    terminalids: list[str] | None = None,
    liveterminalid: str = "21",
) -> dict:
    return {
        "taskid": str(task_id),
        "id": str(task_id),
        "tasktype": "2",
        "taskname": taskname,
        "starttime": start_time,
        "startdate": start_date,
        "enddate": start_date,
        "timelength": 60,
        "timelengthtype": 1,
        "mediaid": mediaid,
        "terminalids": list(terminalids or []),
        "liveterminalid": liveterminalid,
    }


def test_build_once_shadow_task_uses_unique_taskname() -> None:
    shadow = api_public._build_once_shadow_task(
        {
            "taskid": "72132",
            "taskname": "早读开始铃",
            "starttime": "07:50:00",
            "startdate": "2026-03-21",
        },
        api_public.datetime(2026, 3, 22, 7, 50, 0),
    )

    assert shadow["taskname"] == "早读开始铃_once_72132_20260322075000"
    assert shadow["startdate"] == "2026-03-22"
    assert shadow["starttime"] == "07:50:00"
    assert shadow["execmode"] == 0
    assert shadow["tasktype"] == api_public._coerce_int(api_public.REMOTE_BROADCAST_TASK_TYPE, 2)


def test_build_once_shadow_task_overrides_legacy_source_tasktype() -> None:
    shadow = api_public._build_once_shadow_task(
        {
            "taskid": "72132",
            "taskname": "legacy-task",
            "tasktype": "1",
            "starttime": "07:50:00",
            "startdate": "2026-03-21",
        },
        api_public.datetime(2026, 3, 22, 7, 50, 0),
    )

    assert shadow["tasktype"] == api_public._coerce_int(api_public.REMOTE_BROADCAST_TASK_TYPE, 2)


def test_build_once_schedule_task_prefers_local_snapshot_fields_without_remote_lookup(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_task_media_ids",
        lambda task_id: (_ for _ in ()).throw(AssertionError("media fallback should not run")),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_task_terminal_ids",
        lambda task_id: (_ for _ in ()).throw(AssertionError("terminal fallback should not run")),
    )

    once_task = api_public._build_once_schedule_task(
        {
            "taskid": "72132",
            "taskname": "鏃╄寮€濮嬮搩",
            "customName": "鏃╄寮€濮嬮搩",
            "starttime": "07:50:00",
            "startdate": "2026-03-21",
            "enddate": "2026-03-21",
            "mediaid": "1127",
            "terminalids": ["50", "52"],
            "liveterminalid": "50",
            "location": [["鎿嶅満", "鍙充竴缁堢"]],
            "terminalnames": ["鍙充竴缁堢", "鍙充簩缁堢"],
            "timelength": 20,
            "timelengthtype": 1,
            "volume": 80,
            "priority": 7,
            "datasendmodel": 3,
            "prepower": 1,
            "level": 2,
            "israndomplay": 1,
            "cmd": 6,
            "cmdargs": "9",
            "bandrate": 4,
            "samplerate": 5,
            "caiboprepower": 6,
            "weekdays": ["鍛ㄤ竴", "鍛ㄤ簩"],
            "projectstate": 1,
            "taskstate": 1,
            "state": 1,
            "enablestate": 1,
        },
        api_public.datetime(2026, 3, 22, 8, 10, 0),
    )

    assert once_task["taskname"] == "鏃╄寮€濮嬮搩_once_72132_20260322081000"
    assert once_task["customName"] == "鏃╄寮€濮嬮搩_once_72132_20260322081000"
    assert once_task["name"] == "鏃╄寮€濮嬮搩_once_72132_20260322081000"
    assert once_task["startdate"] == "2026-03-22"
    assert once_task["enddate"] == "2026-03-22"
    assert once_task["starttime"] == "08:10:00"
    assert once_task["execmode"] == 127
    assert once_task["tasktype"] == 1
    assert once_task["mediaid"] == "1127"
    assert once_task["terminalids"] == ["50", "52"]
    assert once_task["liveterminalid"] == "50"
    assert once_task["location"] == [["鎿嶅満", "鍙充竴缁堢"]]
    assert once_task["terminalnames"] == ["鍙充竴缁堢", "鍙充簩缁堢"]
    assert once_task["timelength"] == 20
    assert once_task["timelengthtype"] == 1
    assert once_task["volume"] == 80
    assert once_task["priority"] == 7
    assert once_task["datasendmodel"] == 3
    assert once_task["prepower"] == 1
    assert once_task["level"] == 2
    assert once_task["israndomplay"] == 1
    assert once_task["cmd"] == 6
    assert once_task["cmdargs"] == "9"
    assert once_task["bandrate"] == 4
    assert once_task["samplerate"] == 5
    assert once_task["caiboprepower"] == 6
    assert once_task["weekdays"] == ["鍛ㄤ竴", "鍛ㄤ簩"]
    assert "projectstate" not in once_task
    assert "taskstate" not in once_task
    assert "state" not in once_task
    assert "enablestate" not in once_task
    assert "isinstancy" not in once_task


def test_build_once_schedule_task_falls_back_to_remote_bindings_when_local_snapshot_missing(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_task_media_ids", lambda task_id: ["9001"])
    monkeypatch.setattr(api_public, "_remote_task_terminal_ids", lambda task_id: ["31", "32"])

    once_task = api_public._build_once_schedule_task(
        {
            "taskid": "72132",
            "taskname": "legacy-task",
            "starttime": "07:50:00",
            "startdate": "2026-03-21",
            "enddate": "2026-03-21",
            "liveterminalid": "0",
        },
        api_public.datetime(2026, 3, 22, 9, 0, 0),
    )

    assert once_task["mediaid"] == "9001"
    assert once_task["terminalids"] == ["31", "32"]
    assert once_task["liveterminalid"] == "31"


def test_build_once_task_spec_includes_media_and_second_duration(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    spec = api_public._build_once_task_spec(
        schedule_name="S",
        source_task={
            "taskid": "72132",
            "taskname": "morning-bell",
            "audio": "上课铃.mp3",
            "mediaid": "1127",
            "volume": 80,
            "timelength": "20",
            "timelengthtype": "1",
            "terminalids": ["31", "32"],
            "terminalnames": ["教学区终端", "操场终端"],
            "liveterminalid": "31",
            "liveterminalname": "教学区终端",
            "location": [["教学区", "教学区终端"], ["操场", "操场终端"]],
        },
        once_task={
            "taskname": "morning-bell_once_72132_20260322075000",
            "startdate": "2026-03-22",
            "starttime": "07:50:00",
            "medianame": "fallback-media.mp3",
            "mediaid": "1127",
            "volume": 81,
            "terminalids": ["31", "32"],
            "terminalnames": ["教学区终端", "操场终端"],
            "liveterminalid": "31",
            "liveterminalname": "教学区终端",
            "location": [["教学区", "教学区终端"], ["操场", "操场终端"]],
        },
        once_task_id="93001",
        role="migrate_target",
        once_action="migrate",
    )

    assert spec["taskid"] == "93001"
    assert spec["taskname"] == "morning-bell"
    assert spec["remote_taskname"] == "morning-bell_once_72132_20260322075000"
    assert spec["mediaid"] == "1127"
    assert spec["medianame"] == "上课铃.mp3"
    assert spec["volume"] == 81
    assert spec["timelength"] == "20"
    assert spec["timelengthtype"] == "1"
    assert spec["duration_seconds"] == 20
    assert spec["terminalids"] == ["31", "32"]
    assert spec["terminalnames"] == ["教学区终端", "操场终端"]
    assert spec["liveterminalid"] == "31"
    assert spec["liveterminalname"] == "教学区终端"
    assert spec["location"] == [["教学区", "教学区终端"], ["操场", "操场终端"]]


def test_remote_add_taskinfo_success_response_extracts_taskid_without_lookup(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "shadow-task",
                "tasktype": 2,
                "startdate": "2026-03-22",
                "starttime": "08:20:00",
            },
            ["9"],
            "911",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)
    monkeypatch.setattr(api_public, "_remote_taskinfo_items", lambda task_type: (_ for _ in ()).throw(AssertionError("lookup should not run")))
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: {"data": [{"state": 0, "taskid": 73986}]}
        if method == "POST" and path == "/task/taskinfo"
        else (_ for _ in ()).throw(AssertionError(f"unexpected request: {method} {path}")),
    )

    diagnostics: dict = {}
    task_id = api_public._remote_add_taskinfo("broadcast", {"taskname": "shadow-task"}, {}, {}, diagnostics=diagnostics)

    assert task_id == "73986"
    assert diagnostics.get("response_body") == {"data": [{"state": 0, "taskid": 73986}]}
    assert diagnostics.get("lookup_attempts") == []


def test_remote_add_taskinfo_lookup_retry_recovers_after_delayed_visibility(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "早读开始铃_once_72132_20260322075000",
                "tasktype": 2,
                "startdate": "2026-03-22",
                "starttime": "07:50:00",
                "sechename": "S",
                "mediaid": 911,
                "liveterminalid": 9,
            },
            ["9"],
            "911",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)

    call_state = {"count": 0}

    def fake_remote_taskinfo_items(task_type):
        call_state["count"] += 1
        if call_state["count"] == 1:
            return []
        return [
            {
                "taskid": "93002",
                "taskname": "早读开始铃_once_72132_20260322075000",
                "tasktype": 2,
                "startdate": "2026-03-22",
                "starttime": "07:50:00",
                "mediaid": 911,
                "liveterminalid": 9,
            }
        ]

    monkeypatch.setattr(api_public, "_remote_taskinfo_items", fake_remote_taskinfo_items)
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: {"data": [{"state": 0, "taskid": 0}]}
        if method == "POST" and path == "/task/taskinfo"
        else (_ for _ in ()).throw(AssertionError(f"unexpected request: {method} {path}")),
    )

    diagnostics: dict = {}
    task_id = api_public._remote_add_taskinfo("broadcast", {"taskname": "shadow-task"}, {}, {}, diagnostics=diagnostics)

    assert task_id == "93002"
    assert diagnostics.get("failure_code", "") == ""
    attempts = diagnostics.get("lookup_attempts") or []
    assert len(attempts) == 2
    assert attempts[0]["match_count"] == 0
    assert attempts[1]["match_count"] == 1


def test_remote_add_taskinfo_lookup_ambiguous_sets_failure_code(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "早读开始铃_once_72132_20260322075000",
                "tasktype": 2,
                "startdate": "2026-03-22",
                "starttime": "07:50:00",
            },
            ["9"],
            "911",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)
    monkeypatch.setattr(
        api_public,
        "_remote_taskinfo_items",
        lambda task_type: [
            {"taskid": "93002", "taskname": "早读开始铃_once_72132_20260322075000", "tasktype": 2, "startdate": "2026-03-22", "starttime": "07:50:00"},
            {"taskid": "93003", "taskname": "早读开始铃_once_72132_20260322075000", "tasktype": 2, "startdate": "2026-03-22", "starttime": "07:50:00"},
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: {"data": [{"state": 0, "taskid": 0}]}
        if method == "POST" and path == "/task/taskinfo"
        else (_ for _ in ()).throw(AssertionError(f"unexpected request: {method} {path}")),
    )

    diagnostics: dict = {}
    task_id = api_public._remote_add_taskinfo("broadcast", {"taskname": "shadow-task"}, {}, {}, diagnostics=diagnostics)

    assert task_id is None
    assert diagnostics["failure_code"] == "taskinfo_lookup_ambiguous"
    assert diagnostics["match_ids"] == ["93002", "93003"]
    assert "multiple candidate" in diagnostics["reason"]


def test_remote_add_taskinfo_rejected_state_marks_remote_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "shadow-task",
                "tasktype": 2,
                "startdate": "2026-03-22",
                "starttime": "08:20:00",
            },
            ["9"],
            "911",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: {"data": [{"state": 15, "taskid": 0}]}
        if method == "POST" and path == "/task/taskinfo"
        else (_ for _ in ()).throw(AssertionError(f"unexpected request: {method} {path}")),
    )
    monkeypatch.setattr(api_public, "_remote_taskinfo_items", lambda task_type: (_ for _ in ()).throw(AssertionError("lookup should not run")))

    diagnostics: dict = {}
    task_id = api_public._remote_add_taskinfo("broadcast", {"taskname": "shadow-task"}, {}, {}, diagnostics=diagnostics)

    assert task_id is None
    assert diagnostics["failure_code"] == "taskinfo_remote_rejected"
    assert "state=15" in diagnostics["reason"]
    assert diagnostics.get("lookup_attempts") == []
    assert diagnostics.get("response_body") == {"data": [{"state": 15, "taskid": 0}]}


def test_once_swap_shadow_names_are_unique(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            _make_task("1001", "07:00:00", "2026-03-21", taskname="早读开始铃", mediaid="11", terminalids=["21"], liveterminalid="21"),
            _make_task("1002", "14:00:00", "2026-03-21", taskname="放学铃", mediaid="12", terminalids=["22"], liveterminalid="22"),
        ],
    }
    action = {
        "schedule_name": "S",
        "source_task_ids": ["1001"],
        "target_task_ids": ["1002"],
        "source_time_start": "2026-03-21 07:00:00",
        "source_time_end": "2026-03-21 08:00:00",
        "target_time_start": "2026-03-21 14:00:00",
        "target_time_end": "2026-03-21 15:00:00",
    }
    created_names: list[str] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: None)
    monkeypatch.setattr(
        api_public,
        "_remote_add_task",
        lambda schedule_name, task, media_map, terminal_map, **kwargs: created_names.append(str(task.get("taskname") or "")) or f"99{len(created_names)}",
    )
    monkeypatch.setattr(api_public, "_remote_schedule_enabletask", lambda *args, **kwargs: [])

    entry, _ = api_public._execute_once_swap_action(action, schedule, dry_run=False)

    assert entry["execution_state"] == "scheduled"
    assert len(created_names) == 2
    assert created_names[0] != created_names[1]
    assert entry["once_task_specs"][0]["role"] == "source_to_target"
    assert entry["once_task_specs"][1]["role"] == "target_to_source"
    assert entry["once_task_specs"][0]["terminalids"] == ["21"]
    assert entry["once_task_specs"][1]["terminalids"] == ["22"]
    assert created_names[0].startswith("早读开始铃_once_1001_")
    assert created_names[1].startswith("放学铃_once_1002_")
