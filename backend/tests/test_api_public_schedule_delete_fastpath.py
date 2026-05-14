from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_sync_remote_schedules_removed_prefers_catalog_delete_when_verified(monkeypatch) -> None:
    deleted_entries: list[str] = []
    deleted_tasks: list[str] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_delete_schedule_entry", lambda name: deleted_entries.append(name))
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(
        api_public,
        "_delete_remote_schedule_tasks",
        lambda schedule_name, local_task_ids: deleted_tasks.append(f"{schedule_name}:{list(local_task_ids)}"),
    )

    api_public._sync_remote_schedules_removed(["drop"])

    assert deleted_entries == ["drop"]
    assert deleted_tasks == []


def test_sync_remote_schedules_removed_falls_back_to_task_delete_when_catalog_delete_not_verified(monkeypatch) -> None:
    deleted_entries: list[str] = []
    deleted_tasks: list[str] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_delete_schedule_entry", lambda name: deleted_entries.append(name))
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["drop"])
    monkeypatch.setattr(
        api_public,
        "_delete_remote_schedule_tasks",
        lambda schedule_name, local_task_ids: deleted_tasks.append(f"{schedule_name}:{list(local_task_ids)}"),
    )

    api_public._sync_remote_schedules_removed(["drop"])

    assert deleted_entries == ["drop", "drop"]
    assert deleted_tasks == ["drop:[]"]
