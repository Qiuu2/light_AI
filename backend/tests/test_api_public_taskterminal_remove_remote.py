from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_remote_remove_taskterminal_uses_swagger_body(monkeypatch) -> None:
    calls = []

    def fake_remote_request(method, path, **kwargs):
        calls.append({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"9": {"zone": "3", "name": "右一终端"}})

    api_public._remote_remove_taskterminal("71791", "9")

    assert len(calls) == 1
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["path"] == "/task/taskterminal"
    assert calls[0]["json_body"] == {"data": [{"id": 9, "taskid": 71791, "groupid": 3}]}


def test_remote_remove_taskterminals_batches_all_terminals(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {
            "9": {"zone": "1", "name": "终端9"},
            "10": {"zone": "2", "name": "终端10"},
        },
    )

    api_public._remote_remove_taskterminals("71791", ["9", "10"])

    assert captured["method"] == "DELETE"
    assert captured["path"] == "/task/taskterminal"
    assert captured["json_body"] == {
        "data": [
            {"id": 9, "taskid": 71791, "groupid": 1},
            {"id": 10, "taskid": 71791, "groupid": 2},
        ]
    }


def test_remote_remove_taskterminal_prefers_location_zone_id_over_terminal_zone(monkeypatch) -> None:
    calls = []

    def fake_remote_request(method, path, **kwargs):
        calls.append({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"9": {"zone": "0", "name": "右一终端"}})
    monkeypatch.setattr(
        api_public,
        "_remote_terzone_cached",
        lambda force=False: {
            "data": [
                {
                    "id": 1,
                    "name": "A区",
                    "terminal": [{"id": 9, "name": "右一终端", "zone": 0}],
                }
            ]
        },
    )

    api_public._remote_remove_taskterminals("71791", ["9"], task={"location": [["A区", "右一终端"]]})

    assert calls[0]["json_body"] == {"data": [{"id": 9, "taskid": 71791, "groupid": 1}]}


def test_apply_remove_terminal_from_task_remote_sync_updates_local_payload(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring schedule",
                "tasks": [
                    {"taskid": "1", "taskname": "class bell", "terminalids": ["1", "2"], "liveterminalid": 1},
                    {"taskid": "2", "taskname": "exercise", "terminalids": ["2", "3"], "liveterminalid": 2},
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    committed = {}
    removed_calls = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: (["2"], {}))
    monkeypatch.setattr(api_public, "_terminal_lookup_for_actions", lambda: {"1": {"name": "terminal-1"}, "3": {"name": "terminal-3"}})
    monkeypatch.setattr(api_public, "_location_paths_from_terminals", lambda ids, lookup: [])
    monkeypatch.setattr(api_public, "_remote_task_terminal_ids", lambda task_id: ["1", "2"] if str(task_id) == "1" else ["2", "3"])
    monkeypatch.setattr(
        api_public,
        "_remote_remove_taskterminal",
        lambda task_id, terminal_id: removed_calls.append((str(task_id), str(terminal_id))),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_remove_terminal_from_task_intent(
        "remove terminal 2 from spring schedule",
        {"schedule_name": "spring schedule", "terminal_id": "2"},
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "remove_terminal_from_task"
    assert removed_calls == [("1", "2"), ("2", "2")]

    updated_tasks = committed["payload"]["schedules"][0]["tasks"]
    assert updated_tasks[0]["terminalids"] == ["1"]
    assert updated_tasks[0]["liveterminalid"] == 1
    assert updated_tasks[1]["terminalids"] == ["3"]
    assert updated_tasks[1]["liveterminalid"] == 3
