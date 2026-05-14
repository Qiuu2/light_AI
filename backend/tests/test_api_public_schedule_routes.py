from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_normalize_schedules_payload_fills_missing_top_level_lists() -> None:
    normalized = api_public._normalize_schedules_payload({"version": "1.0"})

    assert normalized["schedules"] == []
    assert normalized["broadcasts"] == []
    assert normalized["livecasts"] == []
    assert normalized["directories"] == []


def test_delete_schedule_route_uses_strict_remote_cleanup(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "broken", "tasks": [{"taskid": "1"}, {"taskid": "1"}]},
            {"schedule_name": "healthy", "tasks": [{"taskid": "2"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    overrides = {
        "overrides": [
            {
                "id": "once-migrate",
                "mode": "once",
                "schedule_name": "broken",
                "action": "migrate",
                "once_task_ids": ["93001"],
                "once_task_specs": [{"taskid": "93001", "once_schedule_name": "broken(AI迁移版)"}],
            },
            {
                "id": "once-swap",
                "mode": "once",
                "schedule_name": "broken",
                "action": "swap",
                "source_once_task_ids": ["93002"],
                "target_once_task_ids": ["93003"],
                "once_task_specs": [
                    {"taskid": "93002", "once_schedule_name": "broken(AI互换版)"},
                    {"taskid": "93003", "once_schedule_name": "broken(AI互换版)"},
                ],
            },
            {"id": "once-cancel", "mode": "once", "schedule_name": "broken", "action": "cancel"},
            {"id": "manual-keep", "mode": "manual", "schedule_name": "broken"},
            {"id": "once-keep", "mode": "once", "schedule_name": "healthy", "action": "migrate"},
        ]
    }
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(overrides))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_delete_remote_schedule_tasks_strict",
        lambda schedule_name, tasks: captured.update(
            {"delete": (schedule_name, [str(task.get("taskid")) for task in tasks if isinstance(task, dict)])}
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: captured.update(
            {"payload": deepcopy(new_payload), "kwargs": kwargs}
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: captured.update({"overrides": deepcopy(new_payload)}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: captured.setdefault("once_task_ids", []).append(str(task_id)),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_schedule_entry",
        lambda schedule_name: captured.setdefault("once_schedule_names", []).append(str(schedule_name)),
    )

    result = api_public.delete_schedule("broken")

    assert result["count"] == 1
    assert captured["delete"] == ("broken", ["1", "1"])
    assert captured["once_task_ids"] == ["93001", "93002", "93003"]
    assert captured["once_schedule_names"] == ["broken(AI迁移版)", "broken(AI互换版)"]
    assert captured["kwargs"]["sync_schedules"] is False
    remaining_override_ids = [item.get("id") for item in captured["overrides"]["overrides"]]
    assert remaining_override_ids == ["manual-keep", "once-keep"]


def test_delete_schedule_route_remote_failure_does_not_persist_local(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "broken", "tasks": [{"taskid": "1"}]},
            {"schedule_name": "healthy", "tasks": [{"taskid": "2"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    overrides = {
        "overrides": [
            {"id": "once-broken", "mode": "once", "schedule_name": "broken", "action": "migrate"},
            {"id": "once-healthy", "mode": "once", "schedule_name": "healthy", "action": "swap"},
        ]
    }
    called = {"schedule_saved": False, "override_saved": False}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(overrides))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_delete_remote_schedule_tasks_strict",
        lambda schedule_name, tasks: (_ for _ in ()).throw(
            api_public.HTTPException(status_code=502, detail="boom")
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: called.update({"schedule_saved": True}),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: called.update({"override_saved": True}),
    )

    try:
        api_public.delete_schedule("broken")
        raise AssertionError("expected delete_schedule to fail")
    except api_public.HTTPException as exc:
        assert exc.status_code == 502
        assert "boom" in str(exc.detail)

    assert called["schedule_saved"] is False
    assert called["override_saved"] is False


def test_delete_schedule_route_once_remote_failure_does_not_persist_local(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "broken", "tasks": [{"taskid": "1"}]},
            {"schedule_name": "healthy", "tasks": [{"taskid": "2"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    overrides = {
        "overrides": [
            {
                "id": "once-broken",
                "mode": "once",
                "schedule_name": "broken",
                "action": "migrate",
                "once_task_ids": ["93001"],
                "once_task_specs": [{"taskid": "93001", "once_schedule_name": "broken(AI迁移版)"}],
            },
            {"id": "once-healthy", "mode": "once", "schedule_name": "healthy", "action": "swap"},
        ]
    }
    called = {"schedule_saved": False, "override_saved": False}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(overrides))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_delete_remote_schedule_tasks_strict", lambda schedule_name, tasks: None)
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail=f"once delete failed: {task_id}")),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: called.update({"schedule_saved": True}),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: called.update({"override_saved": True}),
    )

    try:
        api_public.delete_schedule("broken")
        raise AssertionError("expected delete_schedule to fail")
    except api_public.HTTPException as exc:
        assert exc.status_code == 502
        assert "once delete failed: 93001" in str(exc.detail)

    assert called["schedule_saved"] is False
    assert called["override_saved"] is False


def test_delete_schedule_route_reports_override_cleanup_failure_without_schedule_rollback(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "broken", "tasks": [{"taskid": "1"}]},
            {"schedule_name": "healthy", "tasks": [{"taskid": "2"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    overrides = {
        "overrides": [
            {"id": "once-broken", "mode": "once", "schedule_name": "broken", "action": "migrate"},
            {"id": "once-healthy", "mode": "once", "schedule_name": "healthy", "action": "swap"},
        ]
    }
    captured = {"schedule_saves": [], "override_saves": []}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(overrides))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)

    def save_schedules(new_payload, **kwargs):
        captured["schedule_saves"].append(
            {"payload": deepcopy(new_payload), "kwargs": deepcopy(kwargs)}
        )

    def save_overrides(new_payload):
        captured["override_saves"].append(deepcopy(new_payload))
        if len(captured["override_saves"]) == 1:
            raise RuntimeError("disk failed")

    monkeypatch.setattr(api_public, "_save_schedules_payload", save_schedules)
    monkeypatch.setattr(api_public, "_save_overrides_payload", save_overrides)

    try:
        api_public.delete_schedule("broken")
        raise AssertionError("expected delete_schedule to fail")
    except api_public.HTTPException as exc:
        assert exc.status_code == 500
        assert "delete_schedule override cleanup failed" in str(exc.detail)

    assert len(captured["schedule_saves"]) == 1
    assert len(captured["override_saves"]) == 1
    first_remaining = [item.get("schedule_name") for item in captured["schedule_saves"][0]["payload"]["schedules"]]
    attempted_override_ids = [item.get("id") for item in captured["override_saves"][0]["overrides"]]
    assert first_remaining == ["healthy"]
    assert attempted_override_ids == ["once-healthy"]


def test_delete_remote_schedule_tasks_uses_remote_query_results(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {"taskid": "70170", "sechename": schedule_name},
            {"taskid": "70171", "sechename": schedule_name},
            {"taskid": "0", "sechename": schedule_name},
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_batch_delete_parallel",
        lambda task_ids, delete_fn, label="batch_delete": captured.update(
            {"task_ids": list(task_ids), "label": label}
        ),
    )

    api_public._delete_remote_schedule_tasks("legacy", ["1", "2", "2"])

    assert captured["task_ids"] == ["70170", "70171"]
    assert captured["label"] == "delete_schedule_legacy"


def test_put_broadcast_schedules_preserves_directories_when_omitted(monkeypatch) -> None:
    existing = {
        "version": "1.0",
        "schedules": [{"schedule_name": "official", "tasks": []}],
        "broadcasts": [{"id": "b-1"}],
        "livecasts": [{"id": "l-1"}],
        "directories": [{"name": "media-root"}],
    }
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda new_payload, snapshot_payload, **kwargs: captured.update(
            {
                "payload": deepcopy(new_payload),
                "snapshot": deepcopy(snapshot_payload),
                "kwargs": kwargs,
            }
        ),
    )

    api_public.put_broadcast_schedules(
        {
            "version": "1.0",
            "schedules": [{"schedule_name": "draft", "tasks": []}],
            "broadcasts": [{"id": "b-2"}],
        }
    )

    assert captured["payload"]["directories"] == existing["directories"]
    assert captured["payload"]["livecasts"] == existing["livecasts"]
    assert captured["snapshot"] == existing
    assert captured["kwargs"]["sync_schedules"] is True
    assert captured["kwargs"]["sync_broadcasts"] is True
    assert captured["kwargs"]["sync_livecasts"] is False


def test_put_broadcast_schedules_cleans_removed_schedule_once_overrides(monkeypatch) -> None:
    existing = {
        "version": "1.0",
        "schedules": [
            {"schedule_name": "winter", "tasks": []},
            {"schedule_name": "summer", "tasks": []},
        ],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    overrides = {
        "overrides": [
            {"id": "once-cancel", "mode": "once", "schedule_name": "winter", "action": "cancel"},
            {
                "id": "once-migrate",
                "mode": "once",
                "schedule_name": "winter",
                "action": "migrate",
                "once_task_ids": ["93011"],
                "once_task_specs": [{"taskid": "93011", "once_schedule_name": "winter(AI迁移版)"}],
            },
            {
                "id": "once-swap",
                "mode": "once",
                "schedule_name": "winter",
                "action": "swap",
                "source_once_task_ids": ["93012"],
                "target_once_task_ids": ["93013"],
                "once_task_specs": [
                    {"taskid": "93012", "once_schedule_name": "winter(AI互换版)"},
                    {"taskid": "93013", "once_schedule_name": "winter(AI互换版)"},
                ],
            },
            {"id": "manual-keep", "mode": "manual", "schedule_name": "winter"},
            {"id": "once-keep", "mode": "once", "schedule_name": "summer", "action": "migrate"},
        ]
    }
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(overrides))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda new_payload, snapshot_payload, **kwargs: captured.update(
            {
                "payload": deepcopy(new_payload),
                "snapshot": deepcopy(snapshot_payload),
                "kwargs": kwargs,
            }
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: captured.update({"overrides": deepcopy(new_payload)}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: captured.setdefault("once_task_ids", []).append(str(task_id)),
    )
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(
        api_public,
        "_remote_delete_schedule_entry",
        lambda schedule_name: captured.setdefault("once_schedule_names", []).append(str(schedule_name)),
    )

    result = api_public.put_broadcast_schedules(
        {
            "version": "1.0",
            "schedules": [{"schedule_name": "summer", "tasks": []}],
            "broadcasts": [],
            "livecasts": [],
        }
    )

    assert result == {"status": "ok"}
    assert [item["schedule_name"] for item in captured["payload"]["schedules"]] == ["summer"]
    assert captured["once_task_ids"] == ["93011", "93012", "93013"]
    assert captured["once_schedule_names"] == ["winter(AI迁移版)", "winter(AI互换版)"]
    assert [item["id"] for item in captured["overrides"]["overrides"]] == ["manual-keep", "once-keep"]


def test_put_broadcast_schedules_keeps_once_overrides_when_schedule_names_unchanged(monkeypatch) -> None:
    existing = {
        "version": "1.0",
        "schedules": [{"schedule_name": "winter", "tasks": [{"taskid": "1", "taskname": "晨读"}]}],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    called = {"override_saved": False}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_load_overrides_payload",
        lambda: {"overrides": [{"id": "once-keep", "mode": "once", "schedule_name": "winter", "action": "migrate"}]},
    )
    monkeypatch.setattr(api_public, "_commit_payload_with_rollback", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: called.update({"override_saved": True}),
    )

    result = api_public.put_broadcast_schedules(
        {
            "version": "1.0",
            "schedules": [{"schedule_name": "winter", "tasks": [{"taskid": "1", "taskname": "早读"}]}],
            "broadcasts": [],
            "livecasts": [],
        }
    )

    assert result == {"status": "ok"}
    assert called["override_saved"] is False


def test_put_broadcast_schedules_rename_cleans_old_schedule_once_overrides(monkeypatch) -> None:
    existing = {
        "version": "1.0",
        "schedules": [{"schedule_name": "winter", "tasks": []}],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_load_overrides_payload",
        lambda: {
            "overrides": [
                {
                    "id": "once-old",
                    "mode": "once",
                    "schedule_name": "winter",
                    "action": "migrate",
                    "once_task_ids": ["93021"],
                    "once_task_specs": [{"taskid": "93021", "once_schedule_name": "winter(AI迁移版)"}],
                }
            ]
        },
    )
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_commit_payload_with_rollback", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: captured.update({"overrides": deepcopy(new_payload)}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: captured.setdefault("once_task_ids", []).append(str(task_id)),
    )
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(
        api_public,
        "_remote_delete_schedule_entry",
        lambda schedule_name: captured.setdefault("once_schedule_names", []).append(str(schedule_name)),
    )

    result = api_public.put_broadcast_schedules(
        {
            "version": "1.0",
            "schedules": [{"schedule_name": "winter-v2", "tasks": []}],
            "broadcasts": [],
            "livecasts": [],
        }
    )

    assert result == {"status": "ok"}
    assert captured["once_task_ids"] == ["93021"]
    assert captured["once_schedule_names"] == ["winter(AI迁移版)"]
    assert captured["overrides"]["overrides"] == []


def test_put_broadcast_schedules_cleans_cancel_only_override_without_remote_delete(monkeypatch) -> None:
    existing = {
        "version": "1.0",
        "schedules": [{"schedule_name": "winter", "tasks": []}],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_load_overrides_payload",
        lambda: {"overrides": [{"id": "once-cancel", "mode": "once", "schedule_name": "winter", "action": "cancel"}]},
    )
    monkeypatch.setattr(api_public, "_commit_payload_with_rollback", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: captured.update({"overrides": deepcopy(new_payload)}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: (_ for _ in ()).throw(AssertionError(f"unexpected remote delete: {task_id}")),
    )

    result = api_public.put_broadcast_schedules(
        {
            "version": "1.0",
            "schedules": [],
            "broadcasts": [],
            "livecasts": [],
        }
    )

    assert result == {"status": "ok"}
    assert captured["overrides"]["overrides"] == []


def test_put_broadcast_schedules_once_remote_failure_does_not_persist(monkeypatch) -> None:
    existing = {
        "version": "1.0",
        "schedules": [{"schedule_name": "winter", "tasks": []}],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    called = {"schedule_saved": False, "override_saved": False}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_load_overrides_payload",
        lambda: {
            "overrides": [
                {
                    "id": "once-old",
                    "mode": "once",
                    "schedule_name": "winter",
                    "action": "migrate",
                    "once_task_ids": ["93031"],
                    "once_task_specs": [{"taskid": "93031", "once_schedule_name": "winter(AI迁移版)"}],
                }
            ]
        },
    )
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail=f"once delete failed: {task_id}")),
    )
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda *args, **kwargs: called.update({"schedule_saved": True}),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: called.update({"override_saved": True}),
    )

    try:
        api_public.put_broadcast_schedules(
            {
                "version": "1.0",
                "schedules": [],
                "broadcasts": [],
                "livecasts": [],
            }
        )
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 502
        assert "once delete failed: 93031" in str(exc.detail)

    assert called["schedule_saved"] is False
    assert called["override_saved"] is False


def test_put_broadcast_schedules_reports_override_cleanup_failure(monkeypatch) -> None:
    existing = {
        "version": "1.0",
        "schedules": [{"schedule_name": "winter", "tasks": []}],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    captured = {"schedule_saved": False}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_load_overrides_payload",
        lambda: {"overrides": [{"id": "once-old", "mode": "once", "schedule_name": "winter", "action": "cancel"}]},
    )
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda *args, **kwargs: captured.update({"schedule_saved": True}),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda new_payload: (_ for _ in ()).throw(api_public.HTTPException(status_code=500, detail="override disk failed")),
    )

    try:
        api_public.put_broadcast_schedules(
            {
                "version": "1.0",
                "schedules": [],
                "broadcasts": [],
                "livecasts": [],
            }
        )
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 500
        assert "put_broadcast_schedules override cleanup failed" in str(exc.detail)
        assert "override disk failed" in str(exc.detail)

    assert captured["schedule_saved"] is True


def test_put_broadcast_schedules_rejects_unnamed_schedule_entries(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": [], "broadcasts": [], "livecasts": [], "directories": []})

    try:
        api_public.put_broadcast_schedules(
            {
                "version": "1.0",
                "schedules": [{"schedule_name": "", "tasks": []}],
            }
        )
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 400
        assert "schedule_name is required for every schedule entry" in str(exc.detail)


def test_add_schedule_uses_commit_wrapper_with_targeted_schedule_name(monkeypatch) -> None:
    existing = {"schedules": [], "broadcasts": [], "livecasts": [], "directories": []}
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda new_payload, snapshot_payload, **kwargs: captured.update(
            {
                "payload": deepcopy(new_payload),
                "snapshot": deepcopy(snapshot_payload),
                "kwargs": kwargs,
            }
        ),
    )

    result = api_public.add_schedule({"schedule_name": "summer", "tasks": []})

    assert result == {"schedule_name": "summer", "count": 1}
    assert captured["snapshot"] == existing
    assert captured["payload"]["schedules"][0]["schedule_name"] == "summer"
    assert captured["kwargs"]["target_schedule_names"] == ["summer"]
    assert captured["kwargs"]["sync_broadcasts"] is False
    assert captured["kwargs"]["sync_livecasts"] is False


def test_put_all_task_scope_broadcasts_preserves_explicit_location(monkeypatch) -> None:
    stored: dict = {}
    schedules_payload = {"schedules": [], "broadcasts": [], "livecasts": [], "directories": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_store_media_lookup", lambda: {})
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: {"broadcast_schedules": deepcopy(schedules_payload)}.get(key),
    )
    monkeypatch.setattr(api_public, "_write_cache_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)
    monkeypatch.setattr(
        api_public,
        "_store_set",
        lambda key, payload: stored.__setitem__(key, deepcopy(payload)),
    )

    payload = {
        "data": [
            {
                "id": "501",
                "taskid": "501",
                "tasktype": api_public._coerce_int(api_public.REMOTE_BROADCAST_TASK_TYPE, 2),
                "name": "afternoon-bell",
                "taskname": "afternoon-bell",
                "audio": "bell",
                "medianame": "bell",
                "liveterminalid": "9",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "location": [["zone-a", "right-1"]],
            }
        ]
    }

    api_public.put_all_task(payload, scope="broadcasts")

    assert stored["all_task"]["data"][0]["location"] == [["zone-a", "right-1"]]
    assert stored["broadcast_schedules"]["broadcasts"][0]["location"] == [["zone-a", "right-1"]]


def test_put_all_task_scope_all_persists_when_livecast_sync_fails(monkeypatch) -> None:
    stored: dict = {}
    schedules_payload = {"schedules": [], "broadcasts": [], "livecasts": [], "directories": []}
    sync_calls: list[tuple[str, list]] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: {"broadcast_schedules": deepcopy(schedules_payload)}.get(key),
    )
    monkeypatch.setattr(api_public, "_write_cache_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)
    monkeypatch.setattr(
        api_public,
        "_store_set",
        lambda key, payload: stored.__setitem__(key, deepcopy(payload)),
    )

    def fake_sync_remote_taskinfo(kind, task_type, desired_tasks):
        sync_calls.append((kind, deepcopy(desired_tasks)))
        if kind == "livecast":
            raise api_public.HTTPException(status_code=400, detail="Missing mediaid for livecast task '后采集器'.")

    monkeypatch.setattr(api_public, "_sync_remote_taskinfo", fake_sync_remote_taskinfo)

    payload = {
        "data": [
            {"taskid": "501", "id": "501", "tasktype": api_public._coerce_int(api_public.REMOTE_BROADCAST_TASK_TYPE, 2), "taskname": "bell", "medianame": "bell", "audio": "bell"},
            {"taskid": "601", "id": "601", "tasktype": api_public._coerce_int(api_public.REMOTE_LIVECAST_TASK_TYPE, 3), "taskname": "后采集器", "medianame": "后采集器", "audio": ""},
        ]
    }

    api_public.put_all_task(payload, scope="all")

    assert any(kind == "broadcast" for kind, _ in sync_calls)
    assert any(kind == "livecast" for kind, _ in sync_calls)
    assert len(stored["all_task"]["data"]) == 2
    assert stored["broadcast_schedules"]["livecasts"][0]["taskname"] == "后采集器"


def test_put_all_task_scope_livecasts_still_raises_on_livecast_sync_failure(monkeypatch) -> None:
    stored = {"called": False}
    schedules_payload = {"schedules": [], "broadcasts": [], "livecasts": [], "directories": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: {"broadcast_schedules": deepcopy(schedules_payload)}.get(key),
    )
    monkeypatch.setattr(
        api_public,
        "_sync_remote_taskinfo",
        lambda kind, task_type, desired_tasks: (_ for _ in ()).throw(
            api_public.HTTPException(status_code=400, detail="Missing mediaid for livecast task '后采集器'.")
        ),
    )
    monkeypatch.setattr(api_public, "_store_set", lambda key, payload: stored.update({"called": True}))

    payload = {
        "data": [
            {"taskid": "601", "id": "601", "tasktype": api_public._coerce_int(api_public.REMOTE_LIVECAST_TASK_TYPE, 3), "taskname": "后采集器", "medianame": "后采集器", "audio": ""},
        ]
    }

    try:
        api_public.put_all_task(payload, scope="livecasts")
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 400

    assert stored["called"] is False


def test_update_schedule_uses_commit_wrapper_with_targeted_schedule_name(monkeypatch) -> None:
    existing = {
        "schedules": [{"schedule_name": "summer", "tasks": [{"taskid": "7001"}]}],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(existing))
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda new_payload, snapshot_payload, **kwargs: captured.update(
            {
                "payload": deepcopy(new_payload),
                "snapshot": deepcopy(snapshot_payload),
                "kwargs": kwargs,
            }
        ),
    )

    result = api_public.update_schedule("summer", {"tasks": [], "status": "enabled"})

    assert result["schedule_name"] == "summer"
    assert captured["snapshot"] == existing
    assert captured["payload"]["schedules"][0]["schedule_name"] == "summer"
    assert captured["kwargs"]["target_schedule_names"] == ["summer"]
    assert captured["kwargs"]["sync_broadcasts"] is False
    assert captured["kwargs"]["sync_livecasts"] is False


def test_sync_remote_schedules_removes_remote_only_schedule_entries_without_catalog_delete(monkeypatch) -> None:
    payload = {
        "schedules": [{"schedule_name": "keep", "status": "enabled", "tasks": []}],
        "broadcasts": [],
        "livecasts": [],
    }
    remote_payload = {
        "schedules": [
            {"schedule_name": "keep", "status": "enabled", "tasks": []},
            {"schedule_name": "drop", "status": "disabled", "tasks": [{"taskid": "9001"}]},
        ]
    }
    captured = {"deleted_ids": []}

    monkeypatch.setattr(api_public, "_remote_fetch_schedule_source", lambda: deepcopy(remote_payload))
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["keep", "drop"])
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(api_public, "_remote_set_schedule_status", lambda schedule_name, enabled: None)
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: captured["deleted_ids"].append(str(task_id)),
    )

    api_public._sync_remote_schedules(payload)

    assert captured["deleted_ids"] == ["9001"]
