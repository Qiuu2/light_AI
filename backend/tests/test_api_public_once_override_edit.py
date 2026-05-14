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


def _session_headers() -> dict[str, str]:
    session = api_public._create_local_session("once-override-test-token", "tester", "test")
    return {"X-Token": session["token"]}


def _migrate_override_payload() -> dict:
    return {
        "overrides": [
            {
                "id": "override-migrate",
                "action": "migrate",
                "mode": "once",
                "schedule_name": "夏季作息",
                "execution_state": "scheduled",
                "active": True,
                "remote_synced": True,
                "cleanup_state": "pending",
                "time_start": "2026-04-23 07:50:00",
                "time_end": "2026-04-23 08:00:00",
                "task_ids": ["81291"],
                "conflict_task_ids": ["90001"],
                "commands": [{"type": "sechetask", "phase": "create_once_task", "taskid": "93001"}],
                "once_task_ids": ["93001"],
                "shadow_task_ids": ["93001"],
                "once_schedule_name": "夏季作息(AI迁移版)",
                "once_task_specs": [
                    {
                        "taskid": "93001",
                        "taskname": "早读开始铃",
                        "schedule_name": "夏季作息",
                        "once_schedule_name": "夏季作息(AI迁移版)",
                        "source_task_id": "81291",
                        "source_task_name": "早读开始铃",
                        "startdate": "2026-04-26",
                        "starttime": "07:50:00",
                        "timelength": "20",
                        "timelengthtype": "1",
                        "duration_seconds": 20,
                        "mediaid": "7",
                        "medianame": "旧提示铃",
                        "volume": 80,
                        "terminalids": ["50"],
                        "terminalnames": ["定压备份功放"],
                        "liveterminalid": "50",
                        "liveterminalname": "定压备份功放",
                        "location": [["无分区终端", "定压备份功放"]],
                        "once_action": "migrate",
                    }
                ],
                "enable_once_commands": [],
            }
        ]
    }


def _swap_override_payload() -> dict:
    return {
        "overrides": [
            {
                "id": "override-swap",
                "action": "swap",
                "mode": "once",
                "schedule_name": "夏季作息",
                "execution_state": "scheduled",
                "active": True,
                "remote_synced": True,
                "cleanup_state": "pending",
                "source_time_start": "2026-04-23 07:50:00",
                "source_time_end": "2026-04-23 08:00:00",
                "target_time_start": "2026-04-23 14:25:00",
                "target_time_end": "2026-04-23 14:35:00",
                "source_task_ids": ["81291"],
                "target_task_ids": ["81311"],
                "commands": [{"type": "sechetask", "phase": "create_once_task_from_source", "taskid": "93021"}],
                "source_once_task_ids": ["93021"],
                "target_once_task_ids": ["93022"],
                "once_task_ids": ["93021", "93022"],
                "shadow_task_ids": ["93021", "93022"],
                "once_schedule_name": "夏季作息(AI互换版)",
                "once_task_specs": [
                    {
                        "taskid": "93021",
                        "taskname": "早读开始铃",
                        "schedule_name": "夏季作息",
                        "once_schedule_name": "夏季作息(AI互换版)",
                        "source_task_id": "81291",
                        "source_task_name": "早读开始铃",
                        "startdate": "2026-04-23",
                        "starttime": "14:25:00",
                        "timelength": "20",
                        "timelengthtype": "1",
                        "duration_seconds": 20,
                        "mediaid": "7",
                        "medianame": "旧提示铃",
                        "volume": 80,
                        "terminalids": ["50"],
                        "terminalnames": ["定压备份功放"],
                        "liveterminalid": "50",
                        "liveterminalname": "定压备份功放",
                        "location": [["无分区终端", "定压备份功放"]],
                        "once_action": "swap",
                        "role": "source_to_target",
                    },
                    {
                        "taskid": "93022",
                        "taskname": "下午第一节课上课",
                        "schedule_name": "夏季作息",
                        "once_schedule_name": "夏季作息(AI互换版)",
                        "source_task_id": "81311",
                        "source_task_name": "下午第一节课上课",
                        "startdate": "2026-04-23",
                        "starttime": "07:50:00",
                        "timelength": "20",
                        "timelengthtype": "1",
                        "duration_seconds": 20,
                        "mediaid": "8",
                        "medianame": "下午铃声",
                        "volume": 80,
                        "terminalids": ["52"],
                        "terminalnames": ["操场音箱"],
                        "liveterminalid": "52",
                        "liveterminalname": "操场音箱",
                        "location": [["操场", "操场音箱"]],
                        "once_action": "swap",
                        "role": "target_to_source",
                    },
                ],
                "enable_once_commands": [],
            }
        ]
    }


@pytest.fixture(autouse=True)
def _isolate_once_override_routes(monkeypatch):
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_ensure_once_overrides_cleaned", lambda: None)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_save_schedules_payload", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("broadcast_schedules should not be saved")))
    monkeypatch.setattr(api_public, "_save_schedules_payload_local", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("broadcast_schedules should not be saved locally")))
    monkeypatch.setattr(api_public, "_touch_generated_at", lambda payload: payload)

    def _fake_dispatch_enabletask_phase(commands, phase, task_ids, enstate, start_dt, **kwargs):
        del kwargs
        commands.append(
            {
                "type": "enabletask",
                "phase": phase,
                "payload": {
                    "taskid": ",".join(str(item) for item in task_ids),
                    "enstate": str(enstate),
                    "starttime": start_dt.strftime("%H:%M:%S"),
                },
            }
        )

    monkeypatch.setattr(api_public, "_dispatch_enabletask_phase", _fake_dispatch_enabletask_phase)


def test_put_once_override_task_updates_remote_payload_and_override(monkeypatch) -> None:
    payload = _migrate_override_payload()
    saved: dict = {}
    remote_update: dict = {}
    remote_snapshot = {
        "taskid": "93001",
        "taskname": "早读开始铃",
        "medianame": "旧提示铃",
        "mediaid": "7",
        "startdate": "2026-04-26",
        "starttime": "07:50:00",
        "timelength": "20",
        "timelengthtype": "1",
        "terminalids": ["50"],
        "terminalnames": ["定压备份功放"],
        "liveterminalid": "50",
        "liveterminalname": "定压备份功放",
        "location": [["无分区终端", "定压备份功放"]],
    }

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"payload": deepcopy(data)}))
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [deepcopy(remote_snapshot)] if schedule_name == "夏季作息(AI迁移版)" else [],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {"9": "临时提示铃"})
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {"9": "临时提示铃"})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"101": {"name": "教学楼终端A"}})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "教学楼终端A"}})

    def _capture_remote_update(task_id, schedule_name, task, media_map, terminal_map, remote_fallback):
        remote_update.update(
            {
                "task_id": task_id,
                "schedule_name": schedule_name,
                "task": deepcopy(task),
                "media_map": deepcopy(media_map),
                "terminal_map": deepcopy(terminal_map),
                "remote_fallback": deepcopy(remote_fallback),
            }
        )

    monkeypatch.setattr(api_public, "_remote_update_task", _capture_remote_update)

    with TestClient(api_public.app) as client:
        response = client.put(
            "/data/task_overrides/once/override-migrate/tasks/93001",
            json={
                "taskname": "临时早读提醒",
                "mediaid": "9",
                "medianame": "临时提示铃",
                "startdate": "2026-04-27",
                "starttime": "08:10:00",
                "timelength": "45",
                "timelengthtype": "1",
                "volume": 65,
                "terminalids": ["101"],
                "terminalnames": ["教学楼终端A"],
                "liveterminalid": "101",
                "liveterminalname": "教学楼终端A",
                "location": [["教学楼", "终端A"]],
            },
            headers=_session_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert remote_update["task_id"] == "93001"
    assert remote_update["schedule_name"] == "夏季作息(AI迁移版)"
    assert remote_update["task"]["taskname"] == "临时早读提醒"
    assert remote_update["task"]["mediaid"] == "9"
    assert remote_update["task"]["medianame"] == "临时提示铃"
    assert remote_update["task"]["startdate"] == "2026-04-27"
    assert remote_update["task"]["starttime"] == "08:10:00"
    assert remote_update["task"]["terminalids"] == ["101"]
    assert remote_update["task"]["location"] == [["教学楼", "终端A"]]
    saved_entry = saved["payload"]["overrides"][0]
    saved_spec = saved_entry["once_task_specs"][0]
    assert saved_spec["taskname"] == "临时早读提醒"
    assert saved_spec["schedule_name"] == "夏季作息"
    assert saved_spec["once_schedule_name"] == "夏季作息(AI迁移版)"
    assert saved_spec["source_task_id"] == "81291"
    assert saved_spec["source_task_name"] == "早读开始铃"
    assert saved_spec["mediaid"] == "9"
    assert saved_spec["medianame"] == "临时提示铃"
    assert saved_spec["startdate"] == "2026-04-27"
    assert saved_spec["starttime"] == "08:10:00"
    assert saved_entry["enable_once_commands"]
    assert saved_entry["new_time_start"] == "2026-04-27 08:10:00"
    assert body["once_task_spec"]["terminalids"] == ["101"]


def test_put_legacy_once_override_keeps_remote_task_hidden_marker(monkeypatch) -> None:
    payload = {
        "overrides": [
            {
                "id": "legacy-migrate",
                "action": "migrate",
                "mode": "once",
                "schedule_name": "LegacyPlan",
                "execution_state": "scheduled",
                "active": True,
                "remote_synced": True,
                "cleanup_state": "pending",
                "time_start": "2026-04-23 07:50:00",
                "time_end": "2026-04-23 08:00:00",
                "task_ids": ["81291"],
                "commands": [{"type": "sechetask", "phase": "create_once_task", "taskid": "93001"}],
                "once_task_ids": ["93001"],
                "shadow_task_ids": ["93001"],
                "once_task_specs": [
                    {
                        "taskid": "93001",
                        "taskname": "Legacy Bell",
                        "schedule_name": "LegacyPlan",
                        "source_task_id": "81291",
                        "source_task_name": "Legacy Bell",
                        "startdate": "2026-04-26",
                        "starttime": "07:50:00",
                        "timelength": "20",
                        "timelengthtype": "1",
                        "duration_seconds": 20,
                        "mediaid": "7",
                        "medianame": "old.mp3",
                        "volume": 80,
                        "terminalids": ["50"],
                        "terminalnames": ["Terminal A"],
                        "liveterminalid": "50",
                        "liveterminalname": "Terminal A",
                        "location": [["Zone", "Terminal A"]],
                        "once_action": "migrate",
                    }
                ],
                "enable_once_commands": [],
            }
        ]
    }
    saved: dict = {}
    remote_update: dict = {}
    remote_snapshot = {
        "taskid": "93001",
        "taskname": "Legacy Bell_once_81291_20260426075000",
        "medianame": "old.mp3",
        "mediaid": "7",
        "startdate": "2026-04-26",
        "starttime": "07:50:00",
        "timelength": "20",
        "timelengthtype": "1",
        "terminalids": ["50"],
        "terminalnames": ["Terminal A"],
        "liveterminalid": "50",
        "liveterminalname": "Terminal A",
        "location": [["Zone", "Terminal A"]],
    }

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"payload": deepcopy(data)}))
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [deepcopy(remote_snapshot)] if schedule_name == "LegacyPlan" else [],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {"9": "new.mp3"})
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {"9": "new.mp3"})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"101": {"name": "Terminal B"}})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "Terminal B"}})

    def _capture_remote_update(task_id, schedule_name, task, media_map, terminal_map, remote_fallback):
        remote_update.update(
            {
                "task_id": task_id,
                "schedule_name": schedule_name,
                "task": deepcopy(task),
                "remote_fallback": deepcopy(remote_fallback),
            }
        )

    monkeypatch.setattr(api_public, "_remote_update_task", _capture_remote_update)

    with TestClient(api_public.app) as client:
        response = client.put(
            "/data/task_overrides/once/legacy-migrate/tasks/93001",
            json={
                "taskname": "User Friendly Bell",
                "mediaid": "9",
                "medianame": "new.mp3",
                "startdate": "2026-04-27",
                "starttime": "08:10:00",
                "timelength": "45",
                "timelengthtype": "1",
                "volume": 65,
                "terminalids": ["101"],
                "terminalnames": ["Terminal B"],
                "liveterminalid": "101",
                "liveterminalname": "Terminal B",
                "location": [["Zone", "Terminal B"]],
            },
            headers=_session_headers(),
        )

    assert response.status_code == 200
    assert remote_update["schedule_name"] == "LegacyPlan"
    assert "_once_" in remote_update["task"]["taskname"]
    assert api_public._filter_once_ephemeral_schedule_tasks([remote_update["task"]]) == []
    saved_spec = saved["payload"]["overrides"][0]["once_task_specs"][0]
    assert saved_spec["taskname"] == "User Friendly Bell"
    assert "_once_" in saved_spec["remote_taskname"]
    assert "once_schedule_name" not in saved_spec


def test_put_once_override_task_preserves_swap_roles(monkeypatch) -> None:
    payload = _swap_override_payload()
    saved: dict = {}

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"payload": deepcopy(data)}))
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [deepcopy(item) for item in payload["overrides"][0]["once_task_specs"]]
        if schedule_name == "夏季作息(AI互换版)" else [],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {"9": "互换后提示铃"})
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {"9": "互换后提示铃"})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"52": {"name": "操场音箱"}})
    monkeypatch.setattr(api_public, "_remote_update_task", lambda *args, **kwargs: None)

    with TestClient(api_public.app) as client:
        response = client.put(
            "/data/task_overrides/once/override-swap/tasks/93021",
            json={
                "taskname": "互换后的早读提醒",
                "mediaid": "9",
                "medianame": "互换后提示铃",
                "startdate": "2026-04-23",
                "starttime": "14:30:00",
                "timelength": "30",
                "timelengthtype": "1",
                "volume": 70,
                "terminalids": ["52"],
                "terminalnames": ["操场音箱"],
                "liveterminalid": "52",
                "liveterminalname": "操场音箱",
                "location": [["操场", "操场音箱"]],
            },
            headers=_session_headers(),
        )

    assert response.status_code == 200
    saved_specs = saved["payload"]["overrides"][0]["once_task_specs"]
    assert [item["role"] for item in saved_specs] == ["source_to_target", "target_to_source"]
    assert saved_specs[0]["taskname"] == "互换后的早读提醒"
    assert saved_specs[0]["once_schedule_name"] == "夏季作息(AI互换版)"
    assert saved_specs[1]["taskname"] == "下午第一节课上课"


def test_put_once_override_task_remote_failure_does_not_persist(monkeypatch) -> None:
    payload = _migrate_override_payload()
    saved_calls: list[dict] = []

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved_calls.append(deepcopy(data)))
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [{"taskid": "93001"}] if schedule_name == "夏季作息(AI迁移版)" else [],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "教学楼终端A"}})
    monkeypatch.setattr(
        api_public,
        "_remote_update_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="remote failed")),
    )

    with TestClient(api_public.app) as client:
        response = client.put(
            "/data/task_overrides/once/override-migrate/tasks/93001",
            json={
                "taskname": "临时早读提醒",
                "mediaid": "9",
                "medianame": "临时提示铃",
                "startdate": "2026-04-27",
                "starttime": "08:10:00",
                "timelength": "45",
                "timelengthtype": "1",
                "volume": 65,
                "terminalids": ["101"],
                "terminalnames": ["教学楼终端A"],
                "liveterminalid": "101",
                "liveterminalname": "教学楼终端A",
                "location": [["教学楼", "终端A"]],
            },
            headers=_session_headers(),
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "remote failed"
    assert saved_calls == []


def test_delete_once_override_task_removes_remote_task_and_cleans_empty_override(monkeypatch) -> None:
    payload = _migrate_override_payload()
    saved: dict = {}
    deleted: list[str] = []
    deleted_schedules: list[str] = []

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"payload": deepcopy(data)}))
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: deleted.append(str(task_id)))
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(api_public, "_remote_delete_schedule_entry", lambda schedule_name: deleted_schedules.append(str(schedule_name)))

    with TestClient(api_public.app) as client:
        response = client.delete(
            "/data/task_overrides/once/override-migrate/tasks/93001",
            headers=_session_headers(),
        )

    assert response.status_code == 200
    assert deleted == ["93001"]
    assert deleted_schedules == ["夏季作息(AI迁移版)"]
    saved_entry = saved["payload"]["overrides"][0]
    assert saved_entry["once_task_specs"] == []
    assert saved_entry["once_task_ids"] == []
    assert saved_entry["shadow_task_ids"] == []
    assert saved_entry["active"] is False
    assert saved_entry["execution_state"] == "cleaned"
    assert saved_entry["cleanup_state"] == "cleaned"
    assert saved_entry["enable_once_commands"] == []


def test_delete_once_override_task_requires_remote_sync(monkeypatch) -> None:
    payload = _migrate_override_payload()
    saved_calls: list[dict] = []

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved_calls.append(deepcopy(data)))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: (_ for _ in ()).throw(AssertionError(f"unexpected remote delete: {task_id}")))

    with TestClient(api_public.app) as client:
        response = client.delete(
            "/data/task_overrides/once/override-migrate/tasks/93001",
            headers=_session_headers(),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Remote sync is required for once task deletion."
    assert saved_calls == []


def test_delete_once_override_task_remote_failure_does_not_persist(monkeypatch) -> None:
    payload = _migrate_override_payload()
    saved_calls: list[dict] = []

    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved_calls.append(deepcopy(data)))
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail=f"delete failed: {task_id}")),
    )

    with TestClient(api_public.app) as client:
        response = client.delete(
            "/data/task_overrides/once/override-migrate/tasks/93001",
            headers=_session_headers(),
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "delete failed: 93001"
    assert saved_calls == []
