from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


@pytest.fixture(autouse=True)
def _stub_once_schedule_creation(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_ensure_schedule", lambda schedule_name, **kwargs: None)
    monkeypatch.setattr(api_public, "_cleanup_empty_once_remote_schedule", lambda schedule_name: None)


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


def test_remote_schedule_enabletask_enstate_mapping_matches_remote_contract(monkeypatch) -> None:
    sent: list[dict] = []

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/task/enabletask"
        sent.append(_extract_post_payload(kwargs))
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    disable_payloads = api_public._remote_schedule_enabletask(
        ["1", "2"], 1, api_public._parse_action_datetime("2026-03-21 08:00:00"), dry_run=False
    )
    restore_payloads = api_public._remote_schedule_enabletask(
        ["1", "2"], 0, api_public._parse_action_datetime("2026-03-21 09:00:00"), dry_run=False
    )

    assert disable_payloads[0]["enstate"] == "1,1"  # non-zero => disable
    assert restore_payloads[0]["enstate"] == "0,0"  # zero => enable
    assert sent[0]["enstate"] == "1,1"
    assert sent[1]["enstate"] == "0,0"
    assert "yuantaskid" not in disable_payloads[0]
    assert "yuantaskid" not in restore_payloads[0]
    assert "yuantaskid" not in sent[0]
    assert "yuantaskid" not in sent[1]


def test_remote_add_taskinfo_create_payload_omits_legacy_id(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "shadow-task",
                "tasktype": 2,
                "startdate": "2026-03-10",
                "starttime": "07:00:00",
                "mediaid": 8,
                "liveterminalid": 9,
            },
            ["9"],
            "8",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/taskinfo":
            captured["payload"] = _extract_post_payload(kwargs)
            return {"data": {"taskid": "93001"}}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    task = {"taskname": "shadow-task"}
    task_id = api_public._remote_add_taskinfo("broadcast", task, {}, {})

    assert task_id == "93001"
    assert "id" not in captured["payload"]
    assert "taskid" not in captured["payload"]


def test_build_remote_taskinfo_payload_includes_mediaid_and_terminalid(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_resolve_terminal_name", lambda task, remote_fallback=None: "Terminal-9")

    payload, terminal_ids, media_id = api_public._build_remote_taskinfo_payload(
        "broadcast",
        {
            "taskname": "shadow-task",
            "starttime": "07:00:00",
            "startdate": "2026-03-10",
            "enddate": "2026-03-10",
            "mediaid": "8",
            "liveterminalid": "9",
            "timelength": 20,
            "timelengthtype": 1,
            "volume": 66,
            "priority": 100,
            "datasendmodel": 0,
        },
        {},
        {},
    )

    assert media_id == "8"
    assert terminal_ids == ["9"]
    assert payload["mediaid"] == 8
    assert payload["liveterminalid"] == 9
    assert payload["tasktype"] == api_public._coerce_int(api_public.REMOTE_BROADCAST_TASK_TYPE, 2)


def test_build_remote_taskinfo_payload_resolves_mediaid_from_map(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_resolve_terminal_name", lambda task, remote_fallback=None: "Terminal-9")

    payload, terminal_ids, media_id = api_public._build_remote_taskinfo_payload(
        "broadcast",
        {
            "taskname": "璧峰簥",
            "medianame": "10.璧峰簥鍙?mp3",
            "starttime": "07:00:00",
            "startdate": "2026-03-10",
            "enddate": "2026-03-10",
            "liveterminalid": "9",
            "timelength": 20,
            "timelengthtype": 1,
        },
        {"10.璧峰簥鍙?mp3": "8"},
        {},
    )

    assert media_id == "8"
    assert terminal_ids == ["9"]
    assert payload["mediaid"] == 8
    assert payload["medianame"] == "10.璧峰簥鍙?mp3"


def test_build_remote_taskinfo_payload_prefers_unique_taskname_over_legacy_name(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_resolve_terminal_name", lambda task, remote_fallback=None: "Terminal-9")

    payload, terminal_ids, media_id = api_public._build_remote_taskinfo_payload(
        "broadcast",
        {
            "taskname": "璧峰簥_once_78987_20260417031700",
            "name": "璧峰簥",
            "medianame": "10.璧峰簥鍙?mp3",
            "starttime": "03:17:00",
            "startdate": "2026-04-17",
            "enddate": "2026-04-17",
            "mediaid": "1124",
            "liveterminalid": "8",
            "timelength": 89,
            "timelengthtype": 1,
        },
        {},
        {},
    )

    assert media_id == "1124"
    assert terminal_ids == ["8"]
    assert payload["taskname"] == "璧峰簥_once_78987_20260417031700"


def test_build_remote_taskinfo_payload_missing_mediaid_fails_before_remote_request(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_resolve_terminal_name", lambda task, remote_fallback=None: "Terminal-9")

    with pytest.raises(api_public.HTTPException) as exc_info:
        api_public._build_remote_taskinfo_payload(
            "broadcast",
            {
                "taskname": "shadow-task",
                "starttime": "07:00:00",
                "startdate": "2026-03-10",
                "enddate": "2026-03-10",
                "liveterminalid": "9",
            },
            {},
            {},
        )

    assert exc_info.value.status_code == 400
    assert "Missing mediaid" in str(exc_info.value.detail)


def test_remote_add_taskinfo_lookup_fallback_recovers_taskid(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "shadow-task",
                "tasktype": 2,
                "startdate": "2026-03-10",
                "starttime": "07:00:00",
                "sechename": "S",
                "mediaid": 8,
                "liveterminalid": 9,
            },
            ["9"],
            "8",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)
    monkeypatch.setattr(
        api_public,
        "_remote_taskinfo_items",
        lambda task_type: [
            {
                "taskid": "93002",
                "taskname": "shadow-task",
                "tasktype": 2,
                "startdate": "2026-03-10",
                "starttime": "07:00:00",
                "sechename": "S",
                "mediaid": 8,
                "liveterminalid": 9,
            }
        ],
    )

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/taskinfo":
            return {"data": True}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    diagnostics: dict = {}
    task = {"taskname": "shadow-task"}
    task_id = api_public._remote_add_taskinfo(
        "broadcast",
        task,
        {},
        {},
        diagnostics=diagnostics,
        lookup_retries=1,
        lookup_delay_seconds=0,
    )

    assert task_id == "93002"
    assert diagnostics.get("failure_code", "") == ""
    attempts = diagnostics.get("lookup_attempts") or []
    assert len(attempts) == 1
    assert attempts[0]["match_count"] == 1


def test_remote_add_taskinfo_rejected_state_skips_lookup(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "shadow-task",
                "tasktype": 2,
                "startdate": "2026-03-22",
                "starttime": "08:20:00",
                "sechename": "S",
                "mediaid": 8,
                "liveterminalid": 9,
            },
            ["9"],
            "8",
        ),
    )

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/taskinfo":
            return {"data": [{"state": 15, "taskid": 0}]}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)
    monkeypatch.setattr(api_public, "_remote_taskinfo_items", lambda task_type: (_ for _ in ()).throw(AssertionError("lookup should not run")))

    diagnostics: dict = {}
    task = {"taskname": "shadow-task"}
    task_id = api_public._remote_add_taskinfo(
        "broadcast",
        task,
        {},
        {},
        diagnostics=diagnostics,
        lookup_retries=3,
        lookup_delay_seconds=0,
    )

    assert task_id is None
    assert diagnostics["failure_code"] == "taskinfo_remote_rejected"
    assert "state=15" in diagnostics["reason"]
    assert diagnostics.get("lookup_attempts") == []
    assert diagnostics["ok"] is False
    assert "state=15" in diagnostics["error_detail"]


def test_once_migrate_lookup_not_found_fails_atomically_and_skips_enabletask(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            _make_task("72132", "07:50:00", "2026-03-21", taskname="morning-bell", mediaid="11", terminalids=["21"], liveterminalid="21")
        ],
    }
    action = {
        "schedule_name": "S",
        "task_ids": ["72132"],
        "time_start": "2026-03-21 07:50:00",
        "time_end": "2026-03-21 08:10:00",
        "new_time_start": "2026-03-22 07:50:00",
        "new_time_end": "2026-03-22 08:10:00",
    }
    saved: dict = {}
    enable_calls: list = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: saved.update({"entry": deepcopy(entry)}))
    monkeypatch.setattr(
        api_public,
        "_remote_schedule_enabletask",
        lambda task_ids, enstate, start_dt, dry_run=False, source_task_ids=None: enable_calls.append((list(task_ids), enstate)),
    )

    def fake_add(schedule_name, task, media_map, terminal_map, **kwargs):
        assert schedule_name == "S(AI迁移版)"
        assert task.get("tasktype") == 1
        assert task.get("execmode") == 127
        assert "projectstate" not in task
        assert task.get("sechename") == "S(AI迁移版)"
        assert "一次性迁移后" in str(task.get("taskname") or "")
        raise api_public.HTTPException(
            status_code=502,
            detail="Remote create schedule task could not be validated and lookup found no unique created task.",
        )

    monkeypatch.setattr(api_public, "_remote_add_task", fake_add)

    entry, reply = api_public._execute_once_migrate_action(action, schedule, dry_run=False)

    assert entry["execution_state"] == "failed"
    assert entry["failure_count"] == 1
    assert entry["remote_synced"] is False
    assert entry["once_task_failures"][0]["failure_code"] == "once_task_create_failed"
    assert "could not be validated" in entry["once_task_failures"][0]["reason"]
    assert "远端临时任务创建失败" in reply
    assert enable_calls == []
    assert saved["entry"]["execution_state"] == "failed"


def test_once_migrate_create_shadow_missing_mediaid_skips_remote_request(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            _make_task(
                "72132",
                "07:50:00",
                "2026-03-21",
                taskname="morning-bell",
                mediaid="0",
                terminalids=["21"],
                liveterminalid="21",
            )
        ],
    }
    schedule["tasks"][0].pop("mediaid", None)
    action = {
        "schedule_name": "S",
        "task_ids": ["72132"],
        "time_start": "2026-03-21 07:50:00",
        "time_end": "2026-03-21 08:10:00",
        "new_time_start": "2026-03-22 07:50:00",
        "new_time_end": "2026-03-22 08:10:00",
    }
    add_calls: list = []
    enable_calls: list = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_task_media_ids", lambda task_id: [])
    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: None)
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda *args, **kwargs: add_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_schedule_enabletask",
        lambda task_ids, enstate, start_dt, dry_run=False, source_task_ids=None, diagnostics=None, diagnostic_id="", action_name="", phase="": enable_calls.append((list(task_ids), enstate)),
    )

    entry, reply = api_public._execute_once_migrate_action(action, schedule, dry_run=False)

    assert entry["execution_state"] == "failed"
    assert entry["failure_count"] == 1
    assert entry["once_task_failures"][0]["failure_code"] == "once_task_create_failed"
    assert "Missing mediaid" in entry["once_task_failures"][0]["reason"]
    assert "mediaid" in reply
    assert add_calls == []
    assert enable_calls == []


def test_once_swap_any_shadow_failure_stops_enabletask_and_rolls_back(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            _make_task("1001", "07:00:00", "2026-03-21", taskname="source-task", mediaid="11", terminalids=["21"], liveterminalid="21"),
            _make_task("1002", "14:00:00", "2026-03-21", taskname="target-task", mediaid="12", terminalids=["22"], liveterminalid="22"),
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
    enable_calls: list = []
    deleted_once_ids: list[str] = []
    cleanup_schedules: list[str] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: None)
    monkeypatch.setattr(api_public, "_cleanup_empty_once_remote_schedule", lambda name: cleanup_schedules.append(str(name)))
    monkeypatch.setattr(
        api_public,
        "_remote_schedule_enabletask",
        lambda task_ids, enstate, start_dt, dry_run=False, source_task_ids=None: enable_calls.append((list(task_ids), enstate)),
    )
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: deleted_once_ids.append(str(task_id)))

    call_state = {"count": 0}

    def fake_add(schedule_name, task, media_map, terminal_map, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            return "99001"
        assert schedule_name == "S(AI互换版)"
        raise api_public.HTTPException(status_code=502, detail="lookup failed")

    monkeypatch.setattr(api_public, "_remote_add_task", fake_add)

    entry, reply = api_public._execute_once_swap_action(action, schedule, dry_run=False)

    assert entry["execution_state"] == "failed"
    assert entry["failure_count"] == 1
    assert deleted_once_ids == ["99001"]
    assert cleanup_schedules == ["S(AI互换版)"]
    assert enable_calls == []
    assert any(item.get("phase") == "rollback_delete_once_task" for item in entry["commands"])
    assert entry["once_task_failures"][0]["rollback_attempts"][0]["taskid"] == "99001"
    assert "远端临时任务创建失败" in reply


def test_once_migrate_terminal_strict_validation_fails_before_create(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            _make_task(
                "72132",
                "07:50:00",
                "2026-03-21",
                taskname="morning-bell",
                mediaid="11",
                terminalids=[],
                liveterminalid="0",
            )
        ],
    }
    action = {
        "schedule_name": "S",
        "task_ids": ["72132"],
        "time_start": "2026-03-21 07:50:00",
        "time_end": "2026-03-21 08:10:00",
        "new_time_start": "2026-03-22 07:50:00",
        "new_time_end": "2026-03-22 08:10:00",
    }
    add_calls: list = []
    enable_calls: list = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: None)
    monkeypatch.setattr(api_public, "_remote_task_terminal_ids_checked", lambda task_id: ([], True))
    monkeypatch.setattr(api_public, "_remote_add_task", lambda *args, **kwargs: add_calls.append(args))
    monkeypatch.setattr(
        api_public,
        "_remote_schedule_enabletask",
        lambda task_ids, enstate, start_dt, dry_run=False, source_task_ids=None: enable_calls.append((list(task_ids), enstate)),
    )

    entry, _ = api_public._execute_once_migrate_action(action, schedule, dry_run=False)

    assert entry["execution_state"] == "failed"
    assert entry["failure_count"] == 1
    failure = entry["once_task_failures"][0]
    assert failure["failure_code"] == "terminal_missing"
    assert "missing terminal binding" in failure["reason"]
    assert add_calls == []
    assert enable_calls == []


def test_once_migrate_partial_create_triggers_compensation_delete(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            _make_task("2001", "08:00:00", "2026-03-21", taskname="a", mediaid="11", terminalids=["21"], liveterminalid="21"),
            _make_task("2002", "08:10:00", "2026-03-21", taskname="b", mediaid="12", terminalids=["22"], liveterminalid="22"),
        ],
    }
    action = {
        "schedule_name": "S",
        "task_ids": ["2001", "2002"],
        "time_start": "2026-03-21 08:00:00",
        "time_end": "2026-03-21 08:20:00",
        "new_time_start": "2026-03-22 08:00:00",
        "new_time_end": "2026-03-22 08:20:00",
    }
    deleted_once_ids: list[str] = []
    enable_calls: list = []
    cleanup_schedules: list[str] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: None)
    monkeypatch.setattr(api_public, "_cleanup_empty_once_remote_schedule", lambda name: cleanup_schedules.append(str(name)))
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: deleted_once_ids.append(str(task_id)))
    monkeypatch.setattr(
        api_public,
        "_remote_schedule_enabletask",
        lambda task_ids, enstate, start_dt, dry_run=False, source_task_ids=None: enable_calls.append((list(task_ids), enstate)),
    )

    call_state = {"count": 0}

    def fake_add(schedule_name, task, media_map, terminal_map, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            return "92001"
        assert schedule_name == "S(AI迁移版)"
        raise api_public.HTTPException(status_code=502, detail="lookup failed")

    monkeypatch.setattr(api_public, "_remote_add_task", fake_add)

    entry, _ = api_public._execute_once_migrate_action(action, schedule, dry_run=False)

    assert entry["execution_state"] == "failed"
    assert deleted_once_ids == ["92001"]
    assert cleanup_schedules == ["S(AI迁移版)"]
    assert enable_calls == []
    failure = entry["once_task_failures"][0]
    assert failure["rollback_attempts"][0]["taskid"] == "92001"
    assert failure["rollback_attempts"][0]["status"] == "ok"


def test_once_migrate_preserves_relative_offsets_for_multiple_tasks(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            _make_task("2001", "08:00:00", "2026-03-21", taskname="a", mediaid="11", terminalids=["21"], liveterminalid="21"),
            _make_task("2002", "08:10:00", "2026-03-21", taskname="b", mediaid="12", terminalids=["22"], liveterminalid="22"),
        ],
    }
    action = {
        "schedule_name": "S",
        "task_ids": ["2001", "2002"],
        "time_start": "2026-03-21 08:00:00",
        "time_end": "2026-03-21 08:20:00",
        "new_time_start": "2026-03-22 09:00:00",
        "new_time_end": "2026-03-22 09:20:00",
    }

    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: None)

    entry, _ = api_public._execute_once_migrate_action(action, schedule, dry_run=True)

    specs = entry["once_task_specs"]
    assert len(specs) == 2
    assert specs[0]["source_task_id"] == "2001"
    assert specs[0]["once_schedule_name"] == "S(AI迁移版)"
    assert "一次性迁移后" in specs[0]["remote_taskname"]
    assert specs[0]["starttime"] == "09:00:00"
    assert specs[1]["source_task_id"] == "2002"
    assert specs[1]["once_schedule_name"] == "S(AI迁移版)"
    assert specs[1]["starttime"] == "09:10:00"


def test_once_migrate_restore_source_uses_second_precision_for_schedule_timelength(monkeypatch) -> None:
    schedule = {
        "schedule_name": "S",
        "tasks": [
            {
                "taskid": "2001",
                "id": "2001",
                "tasktype": "2",
                "taskname": "a",
                "starttime": "16:15:00",
                "startdate": "2026-03-21",
                "enddate": "2026-03-21",
                "timelength": "1",
                "timelengthtype": "1",
                "mediaid": "11",
                "terminalids": ["21"],
                "liveterminalid": "21",
            },
        ],
    }
    action = {
        "schedule_name": "S",
        "task_ids": ["2001"],
        "time_start": "2026-03-21 16:15:00",
        "time_end": "2026-03-21 16:15:01",
        "new_time_start": "2026-03-22 16:15:00",
        "new_time_end": "2026-03-22 16:15:01",
    }

    monkeypatch.setattr(api_public, "_save_once_override_entry", lambda entry: None)

    entry, _ = api_public._execute_once_migrate_action(action, schedule, dry_run=True)

    restore_cmd = next(item for item in entry["commands"] if item.get("phase") == "restore_source")
    assert restore_cmd["payload"]["starttime"] == "16:15:01"


def test_remote_add_taskinfo_update_path_keeps_existing_positive_ids(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "existing-task",
                "tasktype": 2,
                "startdate": "2026-03-10",
                "starttime": "07:00:00",
                "mediaid": 8,
                "liveterminalid": 9,
            },
            ["9"],
            "8",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/taskinfo":
            captured["payload"] = _extract_post_payload(kwargs)
            return {"data": {"taskid": "72134"}}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    task = {"taskid": "72134", "id": "72134", "taskname": "existing-task"}
    task_id = api_public._remote_add_taskinfo("broadcast", task, {}, {})

    assert task_id == "72134"
    assert "id" not in captured["payload"]
    assert captured["payload"]["taskid"] == "72134"


def test_cleanup_expired_once_overrides_deletes_once_tasks_and_marks_cleaned(monkeypatch) -> None:
    import datetime as dt

    payload = {
        "overrides": [
            {
                "id": "once-1",
                "action": "migrate",
                "mode": "once",
                "schedule_name": "S",
                "once_schedule_name": "S(AI迁移版)",
                "execution_state": "scheduled",
                "active": True,
                "remote_synced": True,
                "time_start": "2026-04-14 08:00:00",
                "once_task_ids": ["93001", "93002"],
                "shadow_task_ids": ["93001", "93002"],
                "cleanup_state": "pending",
                "cleanup_attempts": [],
                "cleaned_task_ids": [],
            }
        ]
    }
    saved: dict = {}
    deleted_ids: list[str] = []
    cleanup_schedules: list[str] = []

    class FakeDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 4, 15)

    monkeypatch.setattr(api_public, "date", FakeDate)
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"payload": deepcopy(data)}))
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: deleted_ids.append(str(task_id)))
    monkeypatch.setattr(api_public, "_cleanup_empty_once_remote_schedule", lambda name: cleanup_schedules.append(str(name)))

    result = api_public._cleanup_expired_once_overrides()

    assert result == {"cleaned": 1, "partial_failed": 0}
    assert deleted_ids == ["93001", "93002"]
    assert cleanup_schedules == ["S(AI迁移版)"]
    entry = saved["payload"]["overrides"][0]
    assert entry["execution_state"] == "cleaned"
    assert entry["active"] is False
    assert entry["cleanup_state"] == "cleaned"
    assert entry["once_task_ids"] == []
    assert entry["shadow_task_ids"] == []
    assert entry["cleaned_task_ids"] == ["93001", "93002"]
    assert entry["cleaned_at"]
