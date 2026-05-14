from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def _schedule_payload(names: list[str]) -> dict:
    schedules = []
    for name in names:
        schedules.append(
            {
                "schedule_name": name,
                "status": "enabled",
                "tasks": [
                    {
                        "taskid": f"{name}-ignored",
                        "taskname": f"{name}-ring",
                        "customName": f"{name}-ring",
                        "starttime": "08:00:00",
                        "startdate": "2026-03-20",
                        "enddate": "2026-03-20",
                        "mediaid": "911",
                        "volume": 80,
                        "terminalids": ["9"],
                        "location": [["A区", "右一终端"]],
                    }
                ],
            }
        )
    return {"schedules": schedules, "broadcasts": [], "livecasts": [], "directories": []}


def test_schedule_sync_delta_ignores_task_and_terminal_order_for_unchanged_schedule() -> None:
    snapshot = {
        "schedules": [
            {
                "schedule_name": "1111",
                "status": "enabled",
                "tasks": [
                    {
                        "taskid": "701",
                        "taskname": "早读开始铃",
                        "customName": "早读开始铃",
                        "starttime": "08:00:00",
                        "startdate": "2026-03-20",
                        "enddate": "2026-03-20",
                        "mediaid": "911",
                        "terminalids": ["9", "10"],
                        "location": [["A区", "右一终端"], ["B区", "右二终端"]],
                    },
                    {
                        "taskid": "702",
                        "taskname": "第一节课上课铃",
                        "customName": "第一节课上课铃",
                        "starttime": "08:20:00",
                        "startdate": "2026-03-20",
                        "enddate": "2026-03-20",
                        "mediaid": "912",
                        "terminalids": ["11"],
                        "location": [["C区", "右三终端"]],
                    },
                ],
            },
            {"schedule_name": "2222", "status": "enabled", "tasks": []},
        ]
    }
    new_payload = {
        "schedules": [
            {
                "schedule_name": "1111",
                "status": "enabled",
                "tasks": [
                    {
                        "taskid": "702",
                        "taskname": "第一节课上课铃",
                        "customName": "第一节课上课铃",
                        "starttime": "08:20:00",
                        "startdate": "2026-03-20",
                        "enddate": "2026-03-20",
                        "mediaid": "912",
                        "terminalids": ["11"],
                        "location": [["C区", "右三终端"]],
                    },
                    {
                        "taskid": "701",
                        "taskname": "早读开始铃",
                        "customName": "早读开始铃",
                        "starttime": "08:00:00",
                        "startdate": "2026-03-20",
                        "enddate": "2026-03-20",
                        "mediaid": "911",
                        "terminalids": ["10", "9", "9"],
                        "location": [["B区", "右二终端"], ["A区", "右一终端"]],
                    },
                ],
            },
            {"schedule_name": "2222", "status": "enabled", "tasks": []},
            {"schedule_name": "3333", "status": "enabled", "tasks": []},
        ]
    }

    delta = api_public._schedule_sync_delta(snapshot, new_payload)

    assert delta["changed_or_added_names"] == ["3333"]
    assert delta["removed_names"] == []
    assert delta["renamed"] == []


def test_schedule_sync_delta_detects_schedule_rename_via_origin_name() -> None:
    snapshot = _schedule_payload(["夏季作息"])
    new_payload = _schedule_payload(["秋季作息"])
    new_payload["schedules"][0]["origin_name"] = "夏季作息"

    delta = api_public._schedule_sync_delta(snapshot, new_payload)

    assert delta["changed_or_added_names"] == ["秋季作息"]
    assert delta["removed_names"] == []
    assert delta["renamed"] == [{"from": "夏季作息", "to": "秋季作息"}]


def test_commit_payload_with_rollback_only_syncs_changed_or_added_schedules(monkeypatch) -> None:
    snapshot = _schedule_payload(["1111", "2222"])
    new_payload = _schedule_payload(["1111", "2222", "3333"])
    calls: dict = {"renamed": [], "targeted": [], "removed": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_inherit_schedule_task_terminal_bindings", lambda schedules: None)
    monkeypatch.setattr(api_public, "_normalize_schedule_task_terminals", lambda schedules, force_terminal_lookup=True: None)
    monkeypatch.setattr(api_public, "_validate_schedule_task_terminal_bindings", lambda schedules: None)
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedule_renames",
        lambda pairs: calls["renamed"].append(deepcopy(pairs)) or [],
    )
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_targeted",
        lambda payload, names: calls["targeted"].append(list(names)),
    )
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_removed",
        lambda names: calls["removed"].append(list(names)),
    )
    monkeypatch.setattr(api_public, "_store_set", lambda key, payload: None)
    monkeypatch.setattr(api_public, "_write_cache_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda payload: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda payload: None)
    monkeypatch.setattr(api_public, "_build_all_task_payload", lambda payload: {"data": []})

    api_public._commit_payload_with_rollback(
        deepcopy(new_payload),
        deepcopy(snapshot),
        sync_schedules=True,
        sync_broadcasts=False,
        sync_livecasts=False,
    )

    assert calls["renamed"] == []
    assert calls["targeted"] == [["3333"]]
    assert calls["removed"] == []


def test_save_schedules_payload_renames_before_targeted_sync(monkeypatch) -> None:
    payload = _schedule_payload(["秋季作息"])
    payload["schedules"][0]["origin_name"] = "夏季作息"
    calls: dict = {"renamed": [], "targeted": [], "removed": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_inherit_schedule_task_terminal_bindings", lambda schedules: None)
    monkeypatch.setattr(api_public, "_normalize_schedule_task_terminals", lambda schedules, force_terminal_lookup=True: None)
    monkeypatch.setattr(api_public, "_validate_schedule_task_terminal_bindings", lambda schedules: None)
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedule_renames",
        lambda pairs: calls["renamed"].append(deepcopy(pairs)) or [],
    )
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_targeted",
        lambda sync_payload, names: calls["targeted"].append(list(names)),
    )
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_removed",
        lambda names: calls["removed"].append(list(names)),
    )
    monkeypatch.setattr(api_public, "_store_set", lambda key, payload: None)
    monkeypatch.setattr(api_public, "_write_cache_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda payload: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda payload: None)
    monkeypatch.setattr(api_public, "_build_all_task_payload", lambda payload: {"data": []})
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)

    api_public._save_schedules_payload(
        deepcopy(payload),
        sync_schedules=True,
        sync_broadcasts=False,
        sync_livecasts=False,
        schedule_sync_delta={
            "changed_or_added_names": ["秋季作息"],
            "removed_names": [],
            "renamed": [{"from": "夏季作息", "to": "秋季作息"}],
        },
    )

    assert calls["renamed"] == [[{"from": "夏季作息", "to": "秋季作息"}]]
    assert calls["targeted"] == [["秋季作息"]]
    assert calls["removed"] == []


def test_commit_payload_with_rollback_uses_reverse_delta_on_failure(monkeypatch) -> None:
    snapshot = _schedule_payload(["1111", "2222"])
    new_payload = _schedule_payload(["1111", "3333"])
    captured: list[dict] = []

    def fake_save(payload, **kwargs):
        captured.append(deepcopy(kwargs))
        if len(captured) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(api_public, "_save_schedules_payload", fake_save)

    try:
        api_public._commit_payload_with_rollback(
            deepcopy(new_payload),
            deepcopy(snapshot),
            sync_schedules=True,
            sync_broadcasts=False,
            sync_livecasts=False,
        )
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 500

    assert captured[0]["schedule_sync_delta"] == {
        "changed_or_added_names": ["3333"],
        "removed_names": ["2222"],
        "renamed": [],
    }
    assert captured[1]["schedule_sync_delta"] == {
        "changed_or_added_names": ["2222"],
        "removed_names": ["3333"],
        "renamed": [],
    }


def test_sync_schedule_task_set_stops_before_delete_phase_when_create_fails(monkeypatch) -> None:
    created: list[str] = []
    deleted: list[str] = []

    monkeypatch.setattr(api_public, "_remote_task_changed", lambda desired, remote, payload: False)
    monkeypatch.setattr(api_public, "_schedule_task_terminals_changed", lambda desired, remote, *args, **kwargs: False)
    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "unused"})

    def fake_remote_add_task(schedule_name, task, media_map, terminal_map, pre_create_snapshot=None):
        del schedule_name, media_map, terminal_map, pre_create_snapshot
        created.append(str(task.get("taskname")))
        if task.get("taskname") == "final-create":
            raise api_public.HTTPException(status_code=502, detail="create failed")
        task["taskid"] = "7001"
        return "7001"

    monkeypatch.setattr(api_public, "_remote_add_task", fake_remote_add_task)
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: deleted.append(str(task_id)))

    desired_tasks = [
        {"taskid": "7001", "taskname": "keep", "starttime": "08:00:00"},
        {"taskname": "final-create", "starttime": "08:10:00"},
    ]
    remote_tasks = [
        {"taskid": "7001", "taskname": "keep", "starttime": "08:00:00"},
        {"taskid": "7002", "taskname": "stale", "starttime": "08:20:00"},
    ]

    with pytest.raises(api_public.HTTPException, match="create failed"):
        api_public._sync_schedule_task_set("summer", desired_tasks, remote_tasks, {}, {})

    assert created == ["final-create"]
    assert deleted == []
    assert "taskid" not in desired_tasks[1]


def test_save_schedules_payload_mixed_livecast_sync_failure_does_not_raise(monkeypatch) -> None:
    payload = _schedule_payload(["1111"])
    payload["livecasts"] = [{"taskid": "31", "taskname": "后采集器", "medianame": "后采集器"}]
    stored: dict = {}
    sync_calls: list[tuple[str, list]] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_inherit_schedule_task_terminal_bindings", lambda schedules: None)
    monkeypatch.setattr(api_public, "_normalize_schedule_task_terminals", lambda schedules, force_terminal_lookup=True: None)
    monkeypatch.setattr(api_public, "_validate_schedule_task_terminal_bindings", lambda schedules: None)
    monkeypatch.setattr(api_public, "_sync_remote_schedules", lambda payload: sync_calls.append(("schedule", [])))

    def fake_sync_remote_taskinfo(kind, task_type, desired_tasks):
        sync_calls.append((kind, deepcopy(desired_tasks)))
        if kind == "livecast":
            raise api_public.HTTPException(status_code=400, detail="Missing mediaid for livecast task '后采集器'.")

    monkeypatch.setattr(api_public, "_sync_remote_taskinfo", fake_sync_remote_taskinfo)
    monkeypatch.setattr(api_public, "_store_set", lambda key, payload: stored.__setitem__(key, deepcopy(payload)))
    monkeypatch.setattr(api_public, "_write_cache_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda payload: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda payload: None)
    monkeypatch.setattr(api_public, "_build_all_task_payload", lambda payload: {"data": []})
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)

    api_public._save_schedules_payload(
        deepcopy(payload),
        sync_schedules=True,
        sync_broadcasts=False,
        sync_livecasts=True,
    )

    assert ("schedule", []) in sync_calls
    assert any(kind == "livecast" for kind, _ in sync_calls)
    assert stored["broadcast_schedules"]["livecasts"][0]["taskname"] == "后采集器"


def test_save_schedules_payload_livecast_only_still_raises_on_livecast_sync_failure(monkeypatch) -> None:
    payload = {"schedules": [], "broadcasts": [], "livecasts": [{"taskid": "31", "taskname": "后采集器"}], "directories": []}
    stored = {"called": False}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_inherit_schedule_task_terminal_bindings", lambda schedules: None)
    monkeypatch.setattr(api_public, "_normalize_schedule_task_terminals", lambda schedules, force_terminal_lookup=True: None)
    monkeypatch.setattr(
        api_public,
        "_sync_remote_taskinfo",
        lambda kind, task_type, desired_tasks: (_ for _ in ()).throw(
            api_public.HTTPException(status_code=400, detail="Missing mediaid for livecast task '后采集器'.")
        ),
    )
    monkeypatch.setattr(api_public, "_store_set", lambda key, payload: stored.update({"called": True}))
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)

    with pytest.raises(api_public.HTTPException) as excinfo:
        api_public._save_schedules_payload(
            deepcopy(payload),
            sync_schedules=False,
            sync_broadcasts=False,
            sync_livecasts=True,
        )

    assert excinfo.value.status_code == 400
    assert stored["called"] is False


def test_remote_task_changed_ignores_format_only_differences() -> None:
    desired_task = {"taskid": "701", "taskname": "早读开始铃"}
    remote_task = {
        "taskid": "701",
        "taskname": "早读开始铃",
        "starttime": "8:00:00",
        "startdate": "",
        "enddate": "0-00-00",
        "mediaid": "0911",
        "volume": "080",
        "priority": "010",
        "execmode": "062",
        "tasktype": "01",
        "timelength": "020",
        "timelengthtype": "01",
    }
    payload = {
        "taskid": "701",
        "sechename": "1111",
        "taskname": "早读开始铃",
        "starttime": "08:00:00",
        "startdate": "0000-00-00",
        "enddate": "",
        "mediaid": 911,
        "volume": 80,
        "priority": 10,
        "execmode": 62,
        "tasktype": 1,
        "timelength": "20",
        "timelengthtype": "1",
    }

    changed = api_public._remote_task_changed(desired_task, remote_task, payload)

    assert changed is False


def test_remote_task_changed_detects_real_semantic_difference() -> None:
    changed = api_public._remote_task_changed(
        {"taskid": "701", "taskname": "早读开始铃"},
        {
            "taskid": "701",
            "taskname": "早读开始铃",
            "starttime": "08:00:00",
            "startdate": "2026-03-20",
            "enddate": "2026-03-20",
            "mediaid": "911",
            "volume": "80",
            "priority": "10",
            "execmode": "62",
            "tasktype": "1",
            "timelength": "20",
            "timelengthtype": "1",
        },
        {
            "taskid": "701",
            "sechename": "1111",
            "taskname": "早读开始铃",
            "starttime": "08:01:00",
            "startdate": "2026-03-20",
            "enddate": "2026-03-20",
            "mediaid": 911,
            "volume": 80,
            "priority": 10,
            "execmode": 62,
            "tasktype": 1,
            "timelength": "20",
            "timelengthtype": "1",
        },
    )

    assert changed is True


def test_schedule_task_terminals_changed_ignores_binding_order_and_duplicates() -> None:
    desired_task = {
        "sechename": "1111",
        "taskid": "701",
        "taskname": "早读开始铃",
        "terminalids": ["29", "8", "8"],
    }
    remote_task = {
        "sechename": "1111",
        "taskid": "701",
        "taskterminal": [
            {"terminalid": "8", "groupid": 0},
            {"terminalid": "29", "groupid": 0},
        ],
    }

    changed = api_public._schedule_task_terminals_changed(
        desired_task,
        remote_task,
        {},
        terminal_lookup={
            "8": {"zone": 0, "name": "term-8"},
            "29": {"zone": 0, "name": "term-29"},
        },
        zone_items=[],
    )

    assert changed is False


def test_sync_schedule_task_set_logs_summary_counts(monkeypatch, caplog) -> None:
    updates: list[str] = []
    creates: list[str] = []
    deletes: list[str] = []

    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_remote_task_changed", lambda desired, remote, payload: desired.get("taskname") == "changed")
    monkeypatch.setattr(api_public, "_schedule_task_terminals_changed", lambda desired, remote, *args, **kwargs: False)
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda schedule_name, task, media_map, terminal_map, remote_fallback=None: {"taskname": task.get("taskname")},
    )
    monkeypatch.setattr(
        api_public,
        "_remote_update_task",
        lambda task_id, schedule_name, task, media_map, terminal_map, remote_fallback, task_changed=None, terminals_changed=None: updates.append(str(task_id)),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_add_task",
        lambda schedule_name, task, media_map, terminal_map, pre_create_snapshot=None: creates.append(str(task.get("taskname"))),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: deletes.append(str(task_id)),
    )

    caplog.set_level("INFO")
    stats = api_public._sync_schedule_task_set(
        "summer",
        [
            {"taskid": "701", "taskname": "changed", "starttime": "08:00:00"},
            {"taskid": "702", "taskname": "same", "starttime": "08:10:00"},
            {"taskname": "new", "starttime": "08:20:00"},
        ],
        [
            {"taskid": "701", "taskname": "changed", "starttime": "08:00:00"},
            {"taskid": "702", "taskname": "same", "starttime": "08:10:00"},
            {"taskid": "703", "taskname": "remove", "starttime": "08:30:00"},
        ],
        {},
        {},
    )

    assert stats == {
        "mutated": True,
        "unchanged_count": 1,
        "updated_count": 1,
        "created_count": 1,
        "deleted_count": 1,
        "terminal_rebind_count": 0,
    }
    assert updates == ["701"]
    assert creates == ["new"]
    assert deletes == ["703"]
    assert "schedule task sync summary | schedule=summer unchanged=1 updated=1 created=1 deleted=1 terminal_rebind=0" in caplog.text


def test_sync_schedule_task_set_does_not_delete_existing_remote_tasks_when_a_create_fails(monkeypatch) -> None:
    creates: list[str] = []
    deletes: list[str] = []

    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_remote_task_changed", lambda desired, remote, payload: False)
    monkeypatch.setattr(api_public, "_schedule_task_terminals_changed", lambda desired, remote, *args, **kwargs: False)
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda schedule_name, task, media_map, terminal_map, remote_fallback=None: {"taskname": task.get("taskname")},
    )
    monkeypatch.setattr(
        api_public,
        "_remote_update_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("update should not be called")),
    )

    def fake_remote_add_task(schedule_name, task, media_map, terminal_map, pre_create_snapshot=None):
        del pre_create_snapshot
        creates.append(str(task.get("taskname")))
        if task.get("taskname") == "new-bad":
            raise api_public.HTTPException(
                status_code=502,
                detail="Remote create schedule task could not be validated and lookup found no unique created task.",
            )
        task["taskid"] = "9001"
        return "9001"

    monkeypatch.setattr(api_public, "_remote_add_task", fake_remote_add_task)
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: deletes.append(str(task_id)),
    )

    with pytest.raises(api_public.HTTPException, match="could not be validated and lookup found no unique created task"):
        api_public._sync_schedule_task_set(
            "summer",
            [
                {"taskid": "701", "taskname": "keep-existing", "starttime": "08:00:00"},
                {"taskname": "new-good", "starttime": "08:10:00"},
                {"taskname": "new-bad", "starttime": "08:20:00"},
            ],
            [
                {"taskid": "701", "taskname": "keep-existing", "starttime": "08:00:00"},
                {"taskid": "77371", "taskname": "legacy-remove-candidate", "starttime": "08:30:00"},
            ],
            {},
            {},
        )

    assert creates == ["new-good", "new-bad"]
    assert deletes == []
