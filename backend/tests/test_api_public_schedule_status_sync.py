from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_status_from_remote_prefers_projectstate_over_state() -> None:
    item = {"state": 0, "projectstate": 1}

    assert api_public._status_from_remote(item) == "停用"


def test_adapt_remote_schedules_preserves_disabled_status_for_task_rows() -> None:
    raw = {
        "data": [
            {
                "sechename": "summer",
                "taskid": "72645",
                "taskname": "ring1",
                "starttime": "08:20:00",
                "projectstate": 1,
                "state": 0,
            },
            {
                "sechename": "summer",
                "taskid": "72646",
                "taskname": "ring2",
                "starttime": "08:50:00",
                "projectstate": 1,
                "state": 0,
            },
        ]
    }

    payload = api_public._adapt_remote_schedules(raw)

    assert len(payload["schedules"]) == 1
    assert payload["schedules"][0]["schedule_name"] == "summer"
    assert payload["schedules"][0]["status"] == "停用"
    assert len(payload["schedules"][0]["tasks"]) == 2


def test_adapt_remote_schedules_ignores_task_rows_without_schedule_name() -> None:
    raw = {
        "data": [
            {
                "taskid": "72644",
                "taskname": "ghost",
                "starttime": "07:50:00",
            },
            {
                "sechename": "summer",
                "taskid": "72645",
                "taskname": "ring1",
                "starttime": "08:20:00",
            },
        ]
    }

    payload = api_public._adapt_remote_schedules(raw)

    assert [item["schedule_name"] for item in payload["schedules"]] == ["summer"]
    assert payload["ignored_unnamed_schedules"] == 1


def test_adapt_remote_schedules_skips_known_reset_rows_without_schedule_name() -> None:
    raw = {
        "data": [
            {
                "taskid": "7000",
                "taskname": "reset",
                "starttime": "04:00:00",
            },
            {
                "sechename": "summer",
                "taskid": "72645",
                "taskname": "ring1",
                "starttime": "08:20:00",
            },
        ]
    }

    payload = api_public._adapt_remote_schedules(raw)

    assert [item["schedule_name"] for item in payload["schedules"]] == ["summer"]
    assert "ignored_unnamed_schedules" not in payload


def test_adapt_remote_schedules_skips_reset_only_payload_without_unnamed_count() -> None:
    raw = {
        "data": [
            {
                "taskid": "7000",
                "taskname": "reset",
                "starttime": "04:00:00",
            }
        ]
    }

    payload = api_public._adapt_remote_schedules(raw)

    assert payload["schedules"] == []
    assert "ignored_unnamed_schedules" not in payload


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("taskname", "reset"),
        ("name", "reset"),
        ("customName", "reset"),
        ("audio", "reset"),
        ("title", "reset"),
        ("taskname", "重启"),
    ],
)
def test_adapt_remote_schedules_skips_reset_alias_rows_without_schedule_name(
    field_name: str,
    field_value: str,
) -> None:
    raw = {
        "data": [
            {
                "taskid": "7000",
                field_name: field_value,
                "starttime": "04:00:00",
            },
            {
                "sechename": "summer",
                "taskid": "72645",
                "taskname": "ring1",
                "starttime": "08:20:00",
            },
        ]
    }

    payload = api_public._adapt_remote_schedules(raw)

    assert [item["schedule_name"] for item in payload["schedules"]] == ["summer"]
    assert "ignored_unnamed_schedules" not in payload


def test_adapt_remote_schedules_keeps_named_schedule_with_reset_task_name() -> None:
    raw = {
        "data": [
            {
                "sechename": "reset",
                "taskid": "7000",
                "taskname": "reset",
                "starttime": "04:00:00",
            }
        ]
    }

    payload = api_public._adapt_remote_schedules(raw)

    assert [item["schedule_name"] for item in payload["schedules"]] == ["reset"]
    assert len(payload["schedules"][0]["tasks"]) == 1
    assert payload["schedules"][0]["tasks"][0]["taskname"] == "reset"
    assert "ignored_unnamed_schedules" not in payload


def test_fetch_remote_schedule_summary_preserves_disabled_status_for_task_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_sources",
        lambda force=False: [
            {
                "data": [
                    {
                        "sechename": "summer",
                        "taskid": "72645",
                        "taskname": "ring1",
                        "starttime": "08:20:00",
                        "projectstate": 1,
                        "state": 0,
                    }
                ]
            }
        ],
    )

    payload = api_public._fetch_remote_schedule_summary()

    assert payload["schedules"] == [
        {
            "schedule_name": "summer",
            "status": "停用",
            "tasks": [],
            "tasks_loaded": False,
            "task_count": 1,
        }
    ]


def test_fetch_remote_schedule_summary_ignores_rows_without_schedule_name(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_sources",
        lambda force=False: [
            {
                "data": [
                    {
                        "taskid": "70001",
                        "taskname": "ghost",
                        "starttime": "07:40:00",
                    },
                    {
                        "sechename": "summer",
                        "taskid": "70002",
                        "taskname": "ring1",
                        "starttime": "08:20:00",
                    },
                ]
            }
        ],
    )

    payload = api_public._fetch_remote_schedule_summary()

    assert payload["schedules"] == [
        {
            "schedule_name": "summer",
            "status": "启用",
            "tasks": [],
            "tasks_loaded": False,
            "task_count": 1,
        }
    ]
    assert payload["ignored_unnamed_schedules"] == 1


def test_fetch_remote_schedule_summary_skips_known_reset_rows_without_schedule_name(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_sources",
        lambda force=False: [
            {
                "data": [
                    {
                        "taskid": "7000",
                        "taskname": "reset",
                        "starttime": "04:00:00",
                    },
                    {
                        "sechename": "summer",
                        "taskid": "70002",
                        "taskname": "ring1",
                        "starttime": "08:20:00",
                    },
                ]
            }
        ],
    )

    payload = api_public._fetch_remote_schedule_summary()

    assert payload["schedules"] == [
        {
            "schedule_name": "summer",
            "status": "启用",
            "tasks": [],
            "tasks_loaded": False,
            "task_count": 1,
        }
    ]
    assert "ignored_unnamed_schedules" not in payload


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("taskname", "reset"),
        ("name", "reset"),
        ("customName", "reset"),
        ("audio", "reset"),
        ("title", "reset"),
        ("taskname", "重启"),
    ],
)
def test_fetch_remote_schedule_summary_skips_reset_alias_rows_without_schedule_name(
    monkeypatch,
    field_name: str,
    field_value: str,
) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_sources",
        lambda force=False: [
            {
                "data": [
                    {
                        "taskid": "7000",
                        field_name: field_value,
                        "starttime": "04:00:00",
                    },
                    {
                        "sechename": "summer",
                        "taskid": "70002",
                        "taskname": "ring1",
                        "starttime": "08:20:00",
                    },
                ]
            }
        ],
    )

    payload = api_public._fetch_remote_schedule_summary()

    assert [item["schedule_name"] for item in payload["schedules"]] == ["summer"]
    assert payload["schedules"][0]["task_count"] == 1
    assert payload["schedules"][0]["tasks_loaded"] is False
    assert "ignored_unnamed_schedules" not in payload


def test_merge_schedule_payloads_preserves_precise_ignored_unnamed_count() -> None:
    merged = api_public._merge_schedule_payloads(
        [
            {
                "schedules": [{"schedule_name": "summer", "tasks": []}],
                "ignored_unnamed_schedules": 4,
                "ignored_unnamed_schedule_samples": [{"index": 0, "task_id": "1", "task_name": "ghost-1", "raw_name": ""}],
            },
            {
                "schedules": [{"schedule_name": "winter", "tasks": []}],
                "ignored_unnamed_schedules": 3,
                "ignored_unnamed_schedule_samples": [{"index": 1, "task_id": "2", "task_name": "ghost-2", "raw_name": ""}],
            },
        ]
    )

    assert [item["schedule_name"] for item in merged["schedules"]] == ["summer", "winter"]
    assert merged["ignored_unnamed_schedules"] == 7
    assert merged["ignored_unnamed_schedule_samples"] == [
        {"index": 0, "task_id": "1", "task_name": "ghost-1", "raw_name": ""},
        {"index": 1, "task_id": "2", "task_name": "ghost-2", "raw_name": ""},
    ]


def test_sync_remote_schedules_targeted_sets_status_after_task_changes(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda *args, **kwargs: {"data": [{"sechename": "new-plan", "state": 0}]},
    )
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(api_public, "_remote_ensure_schedule", lambda schedule_name: calls.append("ensure"))
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(
        api_public,
        "_remote_add_task",
        lambda schedule_name, task, media_map, terminal_map, **kwargs: calls.append("add"),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_set_schedule_status",
        lambda schedule_name, enabled: calls.append("status"),
    )

    payload = {
        "schedules": [
            {
                "schedule_name": "new-plan",
                "status": "disabled",
                "tasks": [{"taskname": "first-ring", "starttime": "08:20:00", "id": "draft-1"}],
            }
        ]
    }

    api_public._sync_remote_schedules_targeted(payload, ["new-plan"])

    assert calls == ["add", "status"]


def test_sync_remote_schedules_targeted_splits_update_create_delete(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda *args, **kwargs: {"data": [{"sechename": "summer", "state": 0}]},
    )
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {"taskid": "70170", "taskname": "old", "starttime": "08:00:00", "terminalids": ["8"]},
            {"taskid": "70171", "taskname": "remove-me", "starttime": "09:00:00", "terminalids": ["9"]},
        ],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "old"})
    monkeypatch.setattr(api_public, "_remote_task_changed", lambda desired, remote, payload: True)
    monkeypatch.setattr(
        api_public,
        "_remote_update_task",
        lambda task_id, schedule_name, task, media_map, terminal_map, remote_fallback: calls.append(("update", str(task_id))),
    )

    def fake_add(schedule_name, task, media_map, terminal_map, **kwargs):
        calls.append(("create", str(task.get("id") or task.get("taskid") or "")))
        task["taskid"] = "80001"
        task["id"] = "80001"

    monkeypatch.setattr(api_public, "_remote_add_task", fake_add)
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: calls.append(("delete", str(task_id))),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_set_schedule_status",
        lambda schedule_name, enabled: calls.append(("status", str(int(bool(enabled))))),
    )

    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "status": "enabled",
                "tasks": [
                    {"id": "client-1", "taskid": "70170", "taskname": "old", "starttime": "08:10:00", "terminalids": ["8"]},
                    {"id": "draft-1", "taskid": "", "taskname": "new", "starttime": "10:00:00", "terminalids": ["29"]},
                ],
            }
        ]
    }

    api_public._sync_remote_schedules_targeted(payload, ["summer"])

    assert calls == [
        ("update", "70170"),
        ("create", "draft-1"),
        ("delete", "70171"),
        ("status", "1"),
    ]
    assert payload["schedules"][0]["tasks"][1]["taskid"] == "80001"


def test_sync_remote_schedules_targeted_does_not_delete_and_recreate_when_update_fails(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda *args, **kwargs: {"data": [{"sechename": "summer", "state": 0}]},
    )
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [{"taskid": "70170", "taskname": "old", "starttime": "08:00:00", "terminalids": ["8"]}],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "old"})
    monkeypatch.setattr(api_public, "_remote_task_changed", lambda desired, remote, payload: True)

    def failing_update(*args, **kwargs):
        calls.append(("update", "70170"))
        raise api_public.HTTPException(status_code=502, detail="remote update failed")

    monkeypatch.setattr(api_public, "_remote_update_task", failing_update)
    monkeypatch.setattr(
        api_public,
        "_remote_add_task",
        lambda *args, **kwargs: calls.append(("create", "unexpected")),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: calls.append(("delete", str(task_id))),
    )

    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "status": "enabled",
                "tasks": [
                    {"id": "client-1", "taskid": "70170", "taskname": "old", "starttime": "08:10:00", "terminalids": ["8"]},
                ],
            }
        ]
    }

    try:
        api_public._sync_remote_schedules_targeted(payload, ["summer"])
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 502

    assert calls == [("update", "70170")]
