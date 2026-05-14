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
def _isolate_remote_sync_meta(monkeypatch):
    original_entry = deepcopy(api_public.DATA_STORE["remote_sync_meta"])
    original_overrides = deepcopy(api_public.DATA_STORE.get("task_overrides"))
    original_flag = api_public.REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY
    api_public._store_set(
        "remote_sync_meta",
        api_public._normalize_remote_sync_meta_payload({}),
    )
    api_public._store_set("task_overrides", {"overrides": []})
    monkeypatch.setattr(api_public, "_write_cache_json", lambda path, payload: None)
    yield
    api_public.DATA_STORE["remote_sync_meta"] = original_entry
    if original_overrides is None:
        api_public.DATA_STORE.pop("task_overrides", None)
    else:
        api_public.DATA_STORE["task_overrides"] = original_overrides
    api_public.REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY = original_flag


def test_remote_delete_schedule_entry_skips_delete_when_disabled(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_remote_request(method: str, path: str, **kwargs):
        del kwargs
        calls.append((method, path))
        return {}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    api_public.REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY = False
    api_public._remote_delete_schedule_entry("ghost")

    assert calls == []
    assert api_public._is_schedule_tombstoned("ghost") is True


def test_remote_delete_schedule_entry_downgrades_capability_on_405(monkeypatch) -> None:
    def fake_remote_request(method: str, path: str, **kwargs):
        del method, path, kwargs
        raise api_public.HTTPException(status_code=405, detail="Method Not Allowed")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    api_public.REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY = True
    api_public._remote_delete_schedule_entry("ghost")

    meta = api_public._load_remote_sync_meta_payload()
    assert meta["schedule_delete_supported"] is False
    assert meta["schedule_delete_checked"] is True
    assert api_public._is_schedule_tombstoned("ghost") is True


def test_delete_schedule_route_tombstones_without_remote_catalog_delete(monkeypatch) -> None:
    payload = {
        "schedules": [
            {"schedule_name": "drop", "tasks": [{"taskid": "9"}, {"taskid": "10"}]},
            {"schedule_name": "keep", "tasks": [{"taskid": "11"}]},
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    captured: dict = {}

    def fail_remote_request(method: str, path: str, **kwargs):
        del kwargs
        raise AssertionError(f"unexpected remote call: {method} {path}")

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_resolve_remote_delete_task_ids",
        lambda schedule_name, tasks: (
            [str(task.get("taskid")) for task in tasks if isinstance(task, dict)],
            [],
        ),
    )
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: captured.setdefault("task_ids", []).append(task_id))
    monkeypatch.setattr(api_public, "_remote_schedule_delete_supported", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: captured.update(
            {"payload": deepcopy(new_payload), "kwargs": kwargs}
        ),
    )
    monkeypatch.setattr(api_public, "_remote_request", fail_remote_request)

    api_public.REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY = False
    result = api_public.delete_schedule("drop")

    assert result["count"] == 1
    assert captured["task_ids"] == ["9", "10"]
    assert captured["kwargs"]["sync_schedules"] is False
    assert api_public._is_schedule_tombstoned("drop") is True


def test_fetch_remote_schedule_payload_skips_tombstoned_empty_schedule(monkeypatch) -> None:
    api_public._add_schedule_tombstone("ghost")

    monkeypatch.setattr(api_public, "_remote_fetch_schedule_sources", lambda force=False: [{"data": []}])
    monkeypatch.setattr(
        api_public,
        "_adapt_remote_schedules",
        lambda raw: {
            "version": "remote",
            "generated_at": "",
            "schedules": [],
            "broadcasts": [],
            "livecasts": [],
        },
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["ghost", "keep"])
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_fetch_remote_taskinfo_list", lambda kind, task_type: [])
    monkeypatch.setattr(api_public, "_load_local_broadcasts", lambda: {"broadcasts": [], "livecasts": []})

    payload = api_public._fetch_remote_schedule_payload()

    assert [item["schedule_name"] for item in payload["schedules"]] == ["keep"]


def test_fetch_remote_schedule_payload_hides_ai_once_schedules(monkeypatch) -> None:
    ai_name = api_public._once_remote_schedule_name("keep", "migrate")
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_sources", lambda force=False: [{"data": []}])
    monkeypatch.setattr(
        api_public,
        "_adapt_remote_schedules",
        lambda raw: {
            "version": "remote",
            "generated_at": "",
            "schedules": [
                {"schedule_name": "keep", "status": "启用", "tasks": []},
                {"schedule_name": ai_name, "status": "启用", "tasks": []},
            ],
            "broadcasts": [],
            "livecasts": [],
        },
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["keep", ai_name])
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: {
            "overrides": [
                {
                    "mode": "once",
                    "active": True,
                    "cleanup_state": "pending",
                    "once_schedule_name": ai_name,
                }
            ]
        } if key == "task_overrides" else None,
    )
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_fetch_remote_taskinfo_list", lambda kind, task_type: [])
    monkeypatch.setattr(api_public, "_load_local_broadcasts", lambda: {"broadcasts": [], "livecasts": []})

    payload = api_public._fetch_remote_schedule_payload()

    assert [item["schedule_name"] for item in payload["schedules"]] == ["keep"]


def test_fetch_remote_schedule_payload_keeps_unreferenced_ai_suffix_schedule(monkeypatch) -> None:
    ai_name = api_public._once_remote_schedule_name("keep", "migrate")
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_sources", lambda force=False: [{"data": []}])
    monkeypatch.setattr(
        api_public,
        "_adapt_remote_schedules",
        lambda raw: {
            "version": "remote",
            "generated_at": "",
            "schedules": [
                {"schedule_name": "keep", "status": "启用", "tasks": []},
                {"schedule_name": ai_name, "status": "启用", "tasks": []},
            ],
            "broadcasts": [],
            "livecasts": [],
        },
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["keep", ai_name])
    monkeypatch.setattr(api_public, "_store_get", lambda key: {"overrides": []} if key == "task_overrides" else None)
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_fetch_remote_taskinfo_list", lambda kind, task_type: [])
    monkeypatch.setattr(api_public, "_load_local_broadcasts", lambda: {"broadcasts": [], "livecasts": []})

    payload = api_public._fetch_remote_schedule_payload()

    assert [item["schedule_name"] for item in payload["schedules"]] == ["keep", ai_name]


def test_sync_remote_schedules_tombstones_remote_only_schedule_without_catalog_delete(monkeypatch) -> None:
    payload = {
        "schedules": [{"schedule_name": "keep", "status": "启用", "tasks": []}],
        "broadcasts": [],
        "livecasts": [],
    }
    remote_payload = {
        "schedules": [
            {"schedule_name": "keep", "status": "启用", "tasks": []},
            {"schedule_name": "drop", "status": "停用", "tasks": [{"taskid": "9001"}]},
        ]
    }
    deleted_ids: list[str] = []

    def fail_remote_request(method: str, path: str, **kwargs):
        del kwargs
        raise AssertionError(f"unexpected remote call: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_fetch_schedule_source", lambda: deepcopy(remote_payload))
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["keep", "drop"])
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(api_public, "_remote_set_schedule_status", lambda schedule_name, enabled: None)
    monkeypatch.setattr(
        api_public,
        "_batch_delete_parallel",
        lambda task_ids, delete_fn, label="batch_delete": deleted_ids.extend(list(task_ids)),
    )
    monkeypatch.setattr(api_public, "_remote_request", fail_remote_request)

    api_public.REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY = False
    api_public._sync_remote_schedules(payload)

    assert deleted_ids == ["9001"]
    assert api_public._is_schedule_tombstoned("drop") is True


def test_sync_remote_schedules_keeps_remote_only_ai_once_schedule(monkeypatch) -> None:
    ai_name = api_public._once_remote_schedule_name("keep", "migrate")
    payload = {
        "schedules": [{"schedule_name": "keep", "status": "启用", "tasks": []}],
        "broadcasts": [],
        "livecasts": [],
    }
    remote_payload = {
        "schedules": [
            {"schedule_name": "keep", "status": "启用", "tasks": []},
            {"schedule_name": ai_name, "status": "启用", "tasks": [{"taskid": "9002"}]},
        ]
    }
    deleted_ids: list[str] = []

    monkeypatch.setattr(api_public, "_remote_fetch_schedule_source", lambda: deepcopy(remote_payload))
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["keep", ai_name])
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: {
            "overrides": [
                {
                    "mode": "once",
                    "active": True,
                    "cleanup_state": "pending",
                    "once_schedule_name": ai_name,
                }
            ]
        } if key == "task_overrides" else None,
    )
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(api_public, "_remote_set_schedule_status", lambda schedule_name, enabled: None)
    monkeypatch.setattr(
        api_public,
        "_batch_delete_parallel",
        lambda task_ids, delete_fn, label="batch_delete": deleted_ids.extend(list(task_ids)),
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda method, path, **kwargs: {})

    api_public._sync_remote_schedules(payload)

    assert deleted_ids == []
    assert api_public._is_schedule_tombstoned(ai_name) is False


def test_save_schedules_payload_clears_tombstone_for_recreated_schedule(monkeypatch) -> None:
    api_public._add_schedule_tombstone("returning")

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_normalize_schedule_task_terminals",
        lambda schedules, force_terminal_lookup=True: None,
    )
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda payload: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda payload: None)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)
    monkeypatch.setattr(api_public, "_build_all_task_payload", lambda payload: {"data": []})

    api_public._save_schedules_payload(
        {
            "schedules": [{"schedule_name": "returning", "tasks": []}],
            "broadcasts": [],
            "livecasts": [],
        }
    )

    assert api_public._is_schedule_tombstoned("returning") is False
