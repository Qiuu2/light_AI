from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_resolve_terminal_ids_skips_default_terminal_when_disabled() -> None:
    terminal_map = {"podium": "8", "rear-poe6": "29"}

    resolved = api_public._resolve_terminal_ids({}, terminal_map, allow_default_fallback=False)

    assert resolved == []


def test_get_task_terminal_ids_prefers_taskterminal_over_location() -> None:
    task = {
        "taskterminal": [
            {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
            {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
        ],
        "terminalids": ["8"],
        "liveterminalid": "8",
        "location": [["zone-a", "podium"], ["zone-c", "right-2"]],
    }

    resolved = api_public._get_task_terminal_ids(task, {"podium": "8", "right-2": "11"})

    assert resolved == ["11"]


def test_resolve_terminal_ids_prefers_taskterminal_over_location() -> None:
    task = {
        "taskterminal": [
            {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
            {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
        ],
        "terminalids": ["8"],
        "location": [["zone-a", "podium"]],
    }

    resolved = api_public._resolve_terminal_ids(task, {"podium": "8", "right-2": "11"})

    assert resolved == ["11"]


def test_resolve_terminal_ids_uses_legacy_fields_without_taskterminal() -> None:
    task = {
        "terminalids": ["8"],
        "location": [["zone-f", "rear-poe6"]],
    }

    resolved = api_public._resolve_terminal_ids(task, {"rear-poe6": "29", "podium": "8"})

    assert resolved == ["8", "29"]


def test_task_has_explicit_terminal_binding_rejects_legacy_terminal_fields_only() -> None:
    task = {
        "terminalids": ["11"],
        "liveterminalid": "11",
        "location": [["zone-c", "right-2"]],
    }

    assert api_public._task_has_explicit_terminal_binding(task) is False


def test_task_has_explicit_terminal_binding_requires_groupid_on_taskterminal() -> None:
    incomplete = {
        "taskterminal": [
            {"terminalid": "11", "terminalname": "right-2"},
        ]
    }
    complete = {
        "taskterminal": [
            {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
            {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
        ]
    }

    assert api_public._task_has_explicit_terminal_binding(incomplete) is False
    assert api_public._task_has_explicit_terminal_binding(complete) is True


def test_zone_label_maps_zero_to_unassigned_label() -> None:
    assert api_public._zone_label(0) == api_public._zone_label("0")
    assert api_public._zone_label("0") == api_public._zone_label("")
    assert api_public._zone_label("") == api_public._zone_label(0)
    assert api_public._zone_label(1) != api_public._zone_label(0)


def test_remote_extract_taskid_explicit_only_ignores_ack_scalars() -> None:
    assert api_public._remote_extract_taskid({"data": 1}, explicit_only=True) is None
    assert api_public._remote_extract_taskid({"success": 1}, explicit_only=True) is None
    assert api_public._remote_extract_taskid({"data": {"id": 12345}}, explicit_only=True) == "12345"


def test_resolve_created_schedule_task_id_accepts_direct_candidate_without_lookup(monkeypatch) -> None:
    fetch_calls: list[str] = []
    payload = {
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
    }

    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: fetch_calls.append(schedule_name) or [
            {
                "taskid": "1",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            }
        ],
    )

    task_id = api_public._resolve_created_schedule_task_id("summer", payload, {"data": {"id": 1}})

    assert task_id == "1"
    assert fetch_calls == []


def test_resolve_created_schedule_task_id_rejects_candidate_that_only_matches_preexisting_snapshot(
    monkeypatch,
) -> None:
    payload = {
        "taskname": "final bell",
        "starttime": "16:15:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "912",
    }
    pre_create_snapshot = [
        {
            "taskid": "7001",
            "taskname": "final bell",
            "starttime": "16:15:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "912",
        }
    ]

    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "7001",
                "taskname": "final bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            }
        ],
    )

    with pytest.raises(api_public.HTTPException, match="matched only pre-existing tasks"):
        api_public._resolve_created_schedule_task_id(
            "summer",
            payload,
            {"data": {"id": 7001}},
            pre_create_snapshot=pre_create_snapshot,
        )


def test_resolve_created_schedule_task_id_prefers_new_match_over_preexisting_duplicate(monkeypatch) -> None:
    payload = {
        "taskname": "final bell",
        "starttime": "16:15:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "912",
    }
    pre_create_snapshot = [
        {
            "taskid": "7001",
            "taskname": "final bell",
            "starttime": "16:15:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "912",
        }
    ]

    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "7001",
                "taskname": "final bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            },
            {
                "taskid": "9001",
                "taskname": "final bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            },
        ],
    )

    task_id = api_public._resolve_created_schedule_task_id(
        "summer",
        payload,
        {"data": {"id": 7001}},
        pre_create_snapshot=pre_create_snapshot,
    )

    assert task_id == "9001"


def test_resolve_created_schedule_task_id_uses_lookup_when_direct_candidate_is_missing(monkeypatch) -> None:
    fetch_calls: list[str] = []
    payload = {
        "taskname": "final bell",
        "starttime": "16:15:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "912",
    }

    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: fetch_calls.append(schedule_name) or [
            {
                "taskid": "9001",
                "taskname": "final bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            },
        ],
    )

    task_id = api_public._resolve_created_schedule_task_id("summer", payload, {"data": 1})

    assert task_id == "9001"
    assert fetch_calls == ["summer"]


def test_resolve_created_schedule_task_id_uses_lookup_when_direct_candidate_is_zero(
    monkeypatch,
) -> None:
    fetch_calls: list[str] = []
    payload = {
        "taskname": "final bell",
        "starttime": "16:15:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "912",
    }

    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: fetch_calls.append(schedule_name) or [
            {
                "taskid": "9001",
                "taskname": "final bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            }
        ],
    )

    task_id = api_public._resolve_created_schedule_task_id("summer", payload, {"data": {"id": 0}})

    assert task_id == "9001"
    assert fetch_calls == ["summer"]


def test_resolve_created_schedule_task_id_raises_when_lookup_has_no_unique_match(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "1",
                "taskname": "wrong bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            }
        ],
    )

    payload = {
        "taskname": "final bell",
        "starttime": "16:15:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "912",
    }

    with pytest.raises(api_public.HTTPException, match="lookup found no unique created task"):
        api_public._resolve_created_schedule_task_id("summer", payload, {"data": 1})


def test_resolve_created_schedule_task_id_raises_when_lookup_matches_multiple_rows(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "9001",
                "taskname": "final bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            },
            {
                "taskid": "9002",
                "taskname": "final bell",
                "starttime": "16:15:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            },
        ],
    )

    payload = {
        "taskname": "final bell",
        "starttime": "16:15:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "912",
    }

    with pytest.raises(api_public.HTTPException, match="lookup matched multiple tasks"):
        api_public._resolve_created_schedule_task_id("summer", payload, {"data": 1})


def test_remote_add_task_uses_direct_candidate_before_binding(monkeypatch) -> None:
    fetch_calls: list[str] = []
    captured: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"data": {"id": 1}})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: fetch_calls.append(schedule_name) or [
            {
                "taskid": "1",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            }
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: captured.update(
            {"task_id": str(task_id), "terminal_ids": list(terminal_ids)}
        ),
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
        "terminalids": ["8"],
    }

    task_id = api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])

    assert fetch_calls == []
    assert task_id == "1"
    assert task["taskid"] == "1"
    assert captured == {"task_id": "1", "terminal_ids": ["8"]}


def test_remote_add_task_replaces_taskterminals_with_explicit_schedule_terminals(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "test task"})

    def fake_remote_request(*args, **kwargs):
        captured.update(kwargs)
        captured["payload"] = deepcopy(kwargs.get("json_body") or kwargs.get("form_body") or {})
        return {"status": "ok"}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_resolve_created_schedule_task_id",
        lambda schedule_name, payload, response_payload, pre_create_snapshot=None: "9001",
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: captured.update(
            {"task_id": str(task_id), "terminal_ids": list(terminal_ids)}
        ),
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "location": [["zone-1", "podium"]],
    }

    task_id = api_public._remote_add_task("summer", task, {}, {"podium": "8"})

    assert task_id == "9001"
    assert task["taskid"] == "9001"
    assert task["id"] == "draft-1"
    assert captured["payload"]["taskid"] == "0"
    assert captured["form_body"] is None
    assert "id" not in captured["payload"]
    assert captured["task_id"] == "9001"
    assert captured["terminal_ids"] == ["8"]


def test_remote_add_task_logs_and_passes_explicit_desired_bindings(monkeypatch, caplog) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "test task"})
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        api_public,
        "_resolve_created_schedule_task_id",
        lambda schedule_name, payload, response_payload, pre_create_snapshot=None: "9001",
    )

    def fake_replace_taskterminals(
        task_id,
        terminal_ids,
        previous_terminal_ids=None,
        task=None,
        previous_task=None,
        desired_bindings=None,
    ):
        captured.update(
            {
                "task_id": str(task_id),
                "terminal_ids": list(terminal_ids),
                "desired_bindings": deepcopy(desired_bindings),
            }
        )

    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", fake_replace_taskterminals)

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "terminalids": ["11"],
        "location": [["zone-c", "right-2"]],
        "taskterminal": [
            {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
            {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
        ],
    }

    with caplog.at_level("INFO", logger=api_public.LOGGER.name):
        task_id = api_public._remote_add_task("summer", task, {}, {"right-2": "11"})

    assert task_id == "9001"
    assert captured == {
        "task_id": "9001",
        "terminal_ids": ["11"],
        "desired_bindings": [
            {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
            {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
        ],
    }
    assert "schedule task terminal rebind prepared | schedule=summer taskid=9001 task=test task terminal_ids=['11'] explicit_reason=covered" in caplog.text


def test_remote_add_task_skips_existing_taskterminal_fetch_for_new_task(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "test task"})
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        api_public,
        "_resolve_created_schedule_task_id",
        lambda schedule_name, payload, response_payload, pre_create_snapshot=None: "9001",
    )

    def fake_replace_taskterminals(
        task_id,
        terminal_ids,
        previous_terminal_ids=None,
        task=None,
        previous_task=None,
        desired_bindings=None,
        skip_existing_fetch=False,
    ):
        captured.update(
            {
                "task_id": str(task_id),
                "terminal_ids": list(terminal_ids),
                "skip_existing_fetch": bool(skip_existing_fetch),
                "previous_terminal_ids": list(previous_terminal_ids or []),
            }
        )

    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", fake_replace_taskterminals)

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "location": [["zone-1", "podium"]],
    }

    task_id = api_public._remote_add_task("summer", task, {}, {"podium": "8"})

    assert task_id == "9001"
    assert captured == {
        "task_id": "9001",
        "terminal_ids": ["8"],
        "skip_existing_fetch": True,
        "previous_terminal_ids": [],
    }


def test_build_remote_task_payload_prefers_first_terminalid_over_legacy_single_field() -> None:
    payload = api_public._build_remote_task_payload(
        "summer",
        {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
            "medianame": "class-bell",
            "terminalids": ["9", "10", "11"],
            "liveterminalid": "99",
        },
        {},
        {},
    )

    assert payload["liveterminalid"] == 9
    assert payload["timelength"] == "1"
    assert payload["timelengthtype"] == "1"


def test_build_remote_task_payload_keeps_cmdargs_as_string() -> None:
    payload = api_public._build_remote_task_payload(
        "summer",
        {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "912",
            "medianame": "dismiss-bell",
            "terminalids": ["9"],
            "cmdargs": 0,
        },
        {},
        {},
    )

    assert payload["cmdargs"] == "0"
    assert isinstance(payload["cmdargs"], str)


def test_build_remote_task_payload_applies_schedule_task_defaults_when_missing() -> None:
    payload = api_public._build_remote_task_payload(
        "summer",
        {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "913",
            "medianame": "exercise-bell",
            "terminalids": ["9"],
            "liveterminalid": "9",
        },
        {},
        {},
    )

    assert payload["prepower"] == 15
    assert payload["priority"] == 10
    assert payload["level"] == 10


def test_build_remote_task_payload_preserves_explicit_schedule_task_defaults() -> None:
    payload = api_public._build_remote_task_payload(
        "summer",
        {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "914",
            "medianame": "assembly-bell",
            "terminalids": ["9"],
            "liveterminalid": "9",
            "prepower": "21",
            "priority": "17",
            "level": "13",
        },
        {},
        {},
    )

    assert payload["prepower"] == 21
    assert payload["priority"] == 17
    assert payload["level"] == 13


def test_remote_add_task_deletes_new_remote_task_when_terminal_bind_fails(monkeypatch) -> None:
    cleanup: dict = {}

    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "test task"})
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        api_public,
        "_resolve_created_schedule_task_id",
        lambda schedule_name, payload, response_payload, pre_create_snapshot=None: "9001",
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: (_ for _ in ()).throw(
            api_public.HTTPException(status_code=502, detail="bind failed")
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: cleanup.update({"task_id": str(task_id)}),
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "location": [["zone-1", "podium"]],
    }

    try:
        api_public._remote_add_task("summer", task, {}, {"podium": "8"})
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 502

    assert task["id"] == "draft-1"
    assert task["taskid"] == "9001"
    assert cleanup == {"task_id": "9001"}


def test_remote_add_task_raises_when_remote_response_has_no_taskid(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "test task"})
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"data": [{"state": 0, "taskid": 0}]})
    monkeypatch.setattr(
        api_public,
        "_resolve_created_schedule_task_id",
        lambda schedule_name, payload, response_payload, pre_create_snapshot=None: (_ for _ in ()).throw(
            api_public.HTTPException(status_code=502, detail="Remote create schedule task did not return taskid and lookup found no unique created task.")
        ),
    )

    task = {"taskid": "0", "id": "draft-1", "taskname": "test task"}

    try:
        api_public._remote_add_task("summer", task, {}, {})
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 502
    assert task["taskid"] == "0"
    assert task["id"] == "draft-1"


def test_remote_add_task_uses_lookup_when_create_response_is_ack_only(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"data": 1})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "9001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            }
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: captured.update(
            {"task_id": str(task_id), "terminal_ids": list(terminal_ids)}
        ),
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
        "terminalids": ["8"],
    }

    task_id = api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])

    assert task_id == "9001"
    assert task["taskid"] == "9001"
    assert captured == {"task_id": "9001", "terminal_ids": ["8"]}


def test_remote_add_task_excludes_preexisting_duplicate_matches_from_lookup(monkeypatch) -> None:
    captured: dict = {}
    pre_create_snapshot = [
        {
            "taskid": "7001",
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        }
    ]

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"id": 7001})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "7001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            },
            {
                "taskid": "9001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            },
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: captured.update(
            {"task_id": str(task_id), "terminal_ids": list(terminal_ids)}
        ),
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
        "terminalids": ["8"],
    }

    task_id = api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=pre_create_snapshot)

    assert task_id == "9001"
    assert task["taskid"] == "9001"
    assert captured == {"task_id": "9001", "terminal_ids": ["8"]}


def test_remote_add_task_raises_when_only_preexisting_duplicate_matches_exist(monkeypatch) -> None:
    pre_create_snapshot = [
        {
            "taskid": "7001",
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        }
    ]

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"id": 7001})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "7001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            }
        ],
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
    }

    with pytest.raises(api_public.HTTPException, match="matched only pre-existing tasks"):
        api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=pre_create_snapshot)


def test_remote_add_task_accepts_direct_id_without_lookup(monkeypatch) -> None:
    captured: dict = {}
    fetch_calls: list[str] = []

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"id": 9001})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: fetch_calls.append(schedule_name) or [
            {
                "taskid": "9001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            }
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: captured.update(
            {"task_id": str(task_id), "terminal_ids": list(terminal_ids)}
        ),
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
        "terminalids": ["8"],
    }

    task_id = api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])

    assert fetch_calls == []
    assert task_id == "9001"
    assert task["taskid"] == "9001"
    assert captured == {"task_id": "9001", "terminal_ids": ["8"]}


def test_remote_add_task_uses_lookup_when_direct_id_is_zero(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"id": 0})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "9001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            },
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: captured.update(
            {"task_id": str(task_id), "terminal_ids": list(terminal_ids)}
        ),
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
        "terminalids": ["8"],
    }

    task_id = api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])

    assert task_id == "9001"
    assert task["taskid"] == "9001"
    assert captured == {"task_id": "9001", "terminal_ids": ["8"]}


def test_remote_add_task_raises_when_explicit_id_candidate_is_invalid_and_lookup_finds_no_unique_created_task(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"id": 0})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "1",
                "taskname": "other task",
                "starttime": "08:30:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            }
        ],
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
    }

    with pytest.raises(api_public.HTTPException, match="could not be validated and lookup found no unique created task"):
        api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])


def test_remote_add_task_raises_when_explicit_id_candidate_is_invalid_and_lookup_matches_multiple_tasks(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"id": 0})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "1",
                "taskname": "other task",
                "starttime": "08:30:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "912",
            },
            {
                "taskid": "9001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            },
            {
                "taskid": "9002",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            },
        ],
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
    }

    with pytest.raises(api_public.HTTPException, match="could not be validated and lookup matched multiple tasks"):
        api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])


def test_remote_add_task_raises_when_lookup_finds_no_unique_created_task(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"data": 1})
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
    }

    with pytest.raises(api_public.HTTPException, match="lookup found no unique created task"):
        api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])


def test_remote_add_task_raises_when_lookup_matches_multiple_created_tasks(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"success": 1})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "9001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            },
            {
                "taskid": "9002",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            },
        ],
    )

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
    }

    with pytest.raises(api_public.HTTPException, match="lookup matched multiple tasks"):
        api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])


def test_remote_add_task_deletes_real_task_when_lookup_resolved_bind_fails(monkeypatch) -> None:
    cleanup: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda *args, **kwargs: {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
        },
    )
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"data": 1})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "9001",
                "taskname": "test task",
                "starttime": "08:00:00",
                "startdate": "2026-03-18",
                "enddate": "2026-03-18",
                "mediaid": "911",
            }
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: (_ for _ in ()).throw(
            api_public.HTTPException(status_code=502, detail="bind failed")
        ),
    )
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: cleanup.update({"task_id": str(task_id)}))

    task = {
        "id": "draft-1",
        "taskname": "test task",
        "starttime": "08:00:00",
        "startdate": "2026-03-18",
        "enddate": "2026-03-18",
        "mediaid": "911",
        "terminalids": ["8"],
    }

    with pytest.raises(api_public.HTTPException, match="bind failed"):
        api_public._remote_add_task("summer", task, {}, {}, pre_create_snapshot=[])

    assert cleanup == {"task_id": "9001"}


def test_sync_schedule_task_set_resolves_real_taskids_for_each_created_task(monkeypatch) -> None:
    created_payloads: list[dict] = []
    bound_calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda schedule_name, task, media_map, terminal_map, remote_fallback=None: {
            "taskname": str(task.get("taskname") or ""),
            "sechename": schedule_name,
            "starttime": str(task.get("starttime") or ""),
            "startdate": str(task.get("startdate") or ""),
            "enddate": str(task.get("enddate") or ""),
            "mediaid": str(task.get("mediaid") or ""),
            "liveterminalid": str((task.get("terminalids") or [""])[0] or task.get("liveterminalid") or ""),
        },
    )

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/sechetask":
            created_payloads.append(deepcopy(kwargs.get("json_body") or {}))
            return {"data": 1}
        raise AssertionError(f"unexpected remote request: {method} {path}")

    def fake_fetch_schedule_tasks(schedule_name: str):
        assert schedule_name == "summer"
        rows = []
        for idx, payload in enumerate(created_payloads, start=9001):
            rows.append(
                {
                    "taskid": str(idx),
                    "taskname": payload.get("taskname"),
                    "starttime": payload.get("starttime"),
                    "startdate": payload.get("startdate"),
                    "enddate": payload.get("enddate"),
                    "mediaid": payload.get("mediaid"),
                }
            )
        return rows

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", fake_fetch_schedule_tasks)
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: bound_calls.append(
            (str(task_id), list(terminal_ids))
        ),
    )
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: (_ for _ in ()).throw(AssertionError("delete should not be called")))

    desired_tasks = [
        {
            "taskname": "task-1",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
            "terminalids": ["9"],
        },
        {
            "taskname": "task-2",
            "starttime": "08:10:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "912",
            "terminalids": ["9"],
        },
    ]

    stats = api_public._sync_schedule_task_set("summer", desired_tasks, [], {}, {})

    assert stats == {
        "mutated": True,
        "unchanged_count": 0,
        "updated_count": 0,
        "created_count": 2,
        "deleted_count": 0,
        "terminal_rebind_count": 0,
    }
    assert desired_tasks[0]["taskid"] == "9001"
    assert desired_tasks[1]["taskid"] == "9002"
    assert bound_calls == [("9001", ["9"]), ("9002", ["9"])]


def test_remote_add_task_posts_schedule_task_defaults_when_missing(monkeypatch) -> None:
    captured: dict = {}

    def fake_remote_request(method, path, **kwargs):
        if path != "/task/sechetask":
            return {"status": "ok"}
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = deepcopy(kwargs.get("json_body") or {})
        return {"data": 1}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_resolve_created_schedule_task_id", lambda *args, **kwargs: "9001")
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_public,
        "_remote_delete_task",
        lambda task_id: (_ for _ in ()).throw(AssertionError(f"delete should not be called for {task_id}")),
    )

    task_id = api_public._remote_add_task(
        "summer",
        {
            "taskname": "test task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "915",
            "medianame": "flag-raising",
            "terminalids": ["9"],
            "liveterminalid": "9",
        },
        {},
        {},
    )

    assert task_id == "9001"
    assert captured["method"] == "POST"
    assert captured["path"] == "/task/sechetask"
    assert captured["payload"]["prepower"] == 15
    assert captured["payload"]["priority"] == 10
    assert captured["payload"]["level"] == 10


def test_sync_schedule_task_set_rolling_snapshot_distinguishes_duplicate_creates(monkeypatch) -> None:
    created_payloads: list[dict] = []
    bound_calls: list[str] = []

    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda schedule_name, task, media_map, terminal_map, remote_fallback=None: {
            "taskname": str(task.get("taskname") or ""),
            "sechename": schedule_name,
            "starttime": str(task.get("starttime") or ""),
            "startdate": str(task.get("startdate") or ""),
            "enddate": str(task.get("enddate") or ""),
            "mediaid": str(task.get("mediaid") or ""),
        },
    )

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/sechetask":
            created_payloads.append(deepcopy(kwargs.get("json_body") or {}))
            return {"data": 1}
        raise AssertionError(f"unexpected remote request: {method} {path}")

    def fake_fetch_schedule_tasks(schedule_name: str):
        assert schedule_name == "summer"
        rows = []
        for idx, payload in enumerate(created_payloads, start=9001):
            rows.append(
                {
                    "taskid": str(idx),
                    "taskname": payload.get("taskname"),
                    "starttime": payload.get("starttime"),
                    "startdate": payload.get("startdate"),
                    "enddate": payload.get("enddate"),
                    "mediaid": payload.get("mediaid"),
                }
            )
        return rows

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", fake_fetch_schedule_tasks)
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: bound_calls.append(str(task_id)),
    )

    desired_tasks = [
        {
            "taskname": "duplicate-task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
            "terminalids": ["9"],
        },
        {
            "taskname": "duplicate-task",
            "starttime": "08:00:00",
            "startdate": "2026-03-18",
            "enddate": "2026-03-18",
            "mediaid": "911",
            "terminalids": ["9"],
        },
    ]

    stats = api_public._sync_schedule_task_set("summer", desired_tasks, [], {}, {})

    assert stats["created_count"] == 2
    assert desired_tasks[0]["taskid"] == "9001"
    assert desired_tasks[1]["taskid"] == "9002"
    assert bound_calls == ["9001", "9002"]


def test_batch_add_parallel_processes_tasks_in_input_order(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])

    monkeypatch.setattr(
        api_public,
        "_remote_add_task",
        lambda schedule_name, task, media_map, terminal_map, pre_create_snapshot=None: calls.append(
            f"{schedule_name}:{task.get('taskname')}"
        ),
    )

    api_public._batch_add_parallel(
        "summer",
        [{"taskname": "task1"}, {"taskname": "task2"}, {"taskname": "task3"}],
        {},
        {},
        label="batch_add",
    )

    assert calls == ["summer:task1", "summer:task2", "summer:task3"]


def test_remote_update_task_replaces_taskterminals_when_schedule_terminals_change(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "test task"})
    monkeypatch.setattr(api_public, "_remote_task_changed", lambda *args, **kwargs: False)
    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", lambda task_id: ([], False))
    monkeypatch.setattr(api_public, "_schedule_task_terminals_changed", lambda *args, **kwargs: True)

    def fake_remote_request(*args, **kwargs):
        captured.update(kwargs)
        captured["payload"] = deepcopy(kwargs.get("json_body") or kwargs.get("form_body") or {})
        return {"status": "ok"}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None, task=None, previous_task=None, desired_bindings=None: captured.update(
            {
                "task_id": str(task_id),
                "terminal_ids": list(terminal_ids),
                "previous_terminal_ids": list(previous_terminal_ids or []),
            }
        ),
    )

    task = {
        "taskname": "test task",
        "terminalids": ["8", "29"],
    }

    api_public._remote_update_task("9002", "summer", task, {}, {}, {"terminalids": ["8"]})

    assert captured["task_id"] == "9002"
    assert captured["terminal_ids"] == ["8", "29"]
    assert captured["previous_terminal_ids"] == ["8"]
    assert "payload" not in captured


def test_remote_update_task_puts_schedule_task_defaults_when_missing(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_task_changed", lambda *args, **kwargs: True)
    monkeypatch.setattr(api_public, "_schedule_task_terminals_changed", lambda *args, **kwargs: False)

    def fake_remote_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = deepcopy(kwargs.get("json_body") or {})
        return {"status": "ok"}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("terminal rebind should not be called")),
    )

    api_public._remote_update_task(
        "9002",
        "summer(AI迁移版)",
        {
            "taskname": "test once task",
            "starttime": "08:20:00",
            "startdate": "2026-03-19",
            "enddate": "2026-03-19",
            "mediaid": "916",
            "medianame": "class-bell",
            "terminalids": ["9"],
            "liveterminalid": "9",
        },
        {},
        {},
        {},
    )

    assert captured["method"] == "PUT"
    assert captured["path"] == "/task/sechetask"
    assert captured["payload"]["taskid"] == "9002"
    assert captured["payload"]["sechename"] == "summer(AI迁移版)"
    assert captured["payload"]["prepower"] == 15
    assert captured["payload"]["priority"] == 10
    assert captured["payload"]["level"] == 10


def test_remote_update_task_skips_terminal_rebind_when_schedule_terminals_unchanged(monkeypatch) -> None:
    captured = {"rebinds": 0}

    monkeypatch.setattr(api_public, "_build_remote_task_payload", lambda *args, **kwargs: {"taskname": "test task"})
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        api_public,
        "_remote_replace_taskterminals",
        lambda task_id, terminal_ids, previous_terminal_ids=None: captured.__setitem__("rebinds", captured["rebinds"] + 1),
    )

    task = {
        "taskname": "test task",
        "terminalids": ["8", "29"],
    }

    api_public._remote_update_task("9002", "summer", task, {}, {}, {"terminalids": ["8", "29"]})

    assert captured["rebinds"] == 0


def test_remote_replace_taskterminals_restores_old_binding_when_new_binding_fails(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", lambda task_id: ([], False))

    def fake_set(task_id, terminal_ids, task=None, bindings=None):
        source = bindings if bindings is not None else terminal_ids
        normalized = [str((value or {}).get("terminalid") if isinstance(value, dict) else value) for value in source]
        calls.append(("set", normalized))
        if normalized == ["8", "29"]:
            raise api_public.HTTPException(status_code=502, detail="terminal add failed")

    monkeypatch.setattr(api_public, "_remote_set_taskterminals", fake_set)
    monkeypatch.setattr(
        api_public,
        "_remote_remove_taskterminals",
        lambda task_id, terminal_ids, task=None, bindings=None: calls.append(
            (
                "remove",
                [
                    str((value or {}).get("terminalid") if isinstance(value, dict) else value)
                    for value in (bindings if bindings is not None else terminal_ids)
                ],
            )
        ),
    )

    try:
        api_public._remote_replace_taskterminals("9002", ["8", "29"], previous_terminal_ids=["5", "6"])
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 502

    assert calls == [
        ("remove", ["5", "6"]),
        ("set", ["8", "29"]),
        ("remove", ["8", "29"]),
        ("set", ["5", "6"]),
    ]


def test_remote_replace_taskterminals_skips_delete_for_first_binding(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", lambda task_id: ([], False))

    monkeypatch.setattr(
        api_public,
        "_remote_remove_taskterminals",
        lambda task_id, terminal_ids, task=None, bindings=None: calls.append(
            (
                "remove",
                [
                    str((value or {}).get("terminalid") if isinstance(value, dict) else value)
                    for value in (bindings if bindings is not None else terminal_ids)
                ],
            )
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_set_taskterminals",
        lambda task_id, terminal_ids, task=None, bindings=None: calls.append(
            (
                "set",
                [
                    str((value or {}).get("terminalid") if isinstance(value, dict) else value)
                    for value in (bindings if bindings is not None else terminal_ids)
                ],
            )
        ),
    )

    api_public._remote_replace_taskterminals("9002", ["8", "29"], previous_terminal_ids=[])

    assert calls == [("set", ["8", "29"])]


def test_remote_replace_taskterminals_skips_existing_fetch_when_requested(monkeypatch) -> None:
    captured = {"checked": 0}

    def fake_checked(task_id):
        captured["checked"] += 1
        return ([{"terminalid": "5", "groupid": 0}], True)

    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", fake_checked)
    monkeypatch.setattr(api_public, "_remote_remove_taskterminals", lambda *args, **kwargs: None)

    posted: list[list[str]] = []

    def fake_set(task_id, terminal_ids, task=None, bindings=None, existing_bindings=None):
        del task_id, terminal_ids, task, existing_bindings
        posted.append(
            [str((value or {}).get("terminalid") if isinstance(value, dict) else value) for value in (bindings or [])]
        )

    monkeypatch.setattr(api_public, "_remote_set_taskterminals", fake_set)

    api_public._remote_replace_taskterminals(
        "9002",
        ["8", "29"],
        previous_terminal_ids=[],
        skip_existing_fetch=True,
    )

    assert captured["checked"] == 0
    assert posted == [["8", "29"]]


def test_remote_replace_taskterminals_reuses_existing_bindings_for_add_diff(monkeypatch) -> None:
    captured = {"checked": 0, "existing_bindings": None}

    def fake_checked(task_id):
        captured["checked"] += 1
        return ([{"terminalid": "5", "groupid": 0}], True)

    def fake_set(task_id, terminal_ids, task=None, bindings=None, existing_bindings=None):
        del task_id, terminal_ids, task, bindings
        captured["existing_bindings"] = existing_bindings

    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", fake_checked)
    monkeypatch.setattr(api_public, "_remote_set_taskterminals", fake_set)
    monkeypatch.setattr(api_public, "_remote_remove_taskterminals", lambda *args, **kwargs: None)

    api_public._remote_replace_taskterminals("9002", ["5", "8"], previous_terminal_ids=["5"])

    assert captured["checked"] == 1
    assert captured["existing_bindings"] == [{"terminalid": "5", "groupid": 0}]


def test_schedule_task_terminals_changed_ignores_terminal_order_for_same_bindings() -> None:
    desired_task = {"terminalids": ["29", "8", "8"]}
    remote_task = {
        "taskterminal": [
            {"terminalid": "8", "groupid": 0},
            {"terminalid": "29", "groupid": 0},
        ]
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


def test_schedule_task_terminals_changed_detects_groupid_change_for_same_terminal() -> None:
    desired_task = {
        "terminalids": ["9"],
        "location": [["zone-a", "right-1"]],
    }
    remote_task = {
        "taskterminal": [
            {"terminalid": "9", "groupid": 19, "terminalname": "right-1"},
        ]
    }

    changed = api_public._schedule_task_terminals_changed(
        desired_task,
        remote_task,
        {},
        terminal_lookup={"9": {"zone": 0, "name": "right-1"}},
        zone_items=[
            {"id": 1, "name": "zone-a", "terminal": [{"id": 9, "name": "right-1"}]},
            {"id": 19, "name": "middle-school", "terminal": [{"id": 9, "name": "right-1"}]},
        ],
    )

    assert changed is True


def test_remote_set_taskterminals_skips_post_when_exact_binding_already_exists(monkeypatch) -> None:
    captured = {"posts": 0}

    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {"9": {"zone": "0", "name": "right-1"}},
    )
    monkeypatch.setattr(
        api_public,
        "_fetch_enriched_zone_items",
        lambda force=False: [
            {"id": 1, "name": "zone-a", "terminal": [{"id": 9, "name": "right-1"}]},
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_taskterminal_bindings",
        lambda task_id: [{"terminalid": "9", "groupid": 1, "terminalname": "right-1"}],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda *args, **kwargs: captured.__setitem__("posts", captured["posts"] + 1),
    )

    api_public._remote_set_taskterminals("74513", ["9"], task={"location": [["zone-a", "right-1"]]})

    assert captured["posts"] == 0


def test_remote_add_taskterminal_uses_jsontaskterminal_json_body(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"9": {"zone": "3", "name": "鍙充竴缁堢"}})

    api_public._remote_add_taskterminal("74339", "9")

    assert captured["method"] == "POST"
    assert captured["path"] == "/task/jsontaskterminal"
    assert captured["json_body"] == {
        "data": [
            {
                "id": 74339,
                "terminalid": 9,
                "area": 255,
                "groupid": 3,
            }
        ]
    }
    assert captured["form_body"] is None
    assert captured["allow_form_retry"] is False


def test_remote_set_taskterminals_batches_all_terminals(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {
            "9": {"zone": "1", "name": "缁堢9"},
            "10": {"zone": "2", "name": "缁堢10"},
            "11": {"zone": "0", "name": "缁堢11"},
        },
    )

    api_public._remote_set_taskterminals("74513", ["9", "10", "11"])

    assert captured["method"] == "POST"
    assert captured["path"] == "/task/jsontaskterminal"
    assert captured["json_body"] == {
        "data": [
            {"id": 74513, "terminalid": 9, "area": 255, "groupid": 1},
            {"id": 74513, "terminalid": 10, "area": 255, "groupid": 2},
            {"id": 74513, "terminalid": 11, "area": 255, "groupid": 0},
        ]
    }


def test_remote_set_taskterminals_prefers_location_zone_id_over_terminal_zone(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {"9": {"zone": "0", "name": "鍙充竴缁堢"}},
    )
    monkeypatch.setattr(
        api_public,
        "_fetch_enriched_zone_items",
        lambda force=False: [
            {
                "id": 1,
                "name": "zone-a",
                "terminal": [{"id": 9, "name": "鍙充竴缁堢", "zone": 0}],
            }
        ],
    )

    api_public._remote_set_taskterminals("74513", ["9"], task={"location": [["zone-a", "right-1"]]})

    assert captured["json_body"] == {
        "data": [{"id": 74513, "terminalid": 9, "area": 255, "groupid": 1}]
    }


def test_remote_set_taskterminals_prefers_explicit_taskterminal_bindings_for_multizone_terminal(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings", lambda task_id: [])
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {
            "11": {
                "zone": "3",
                "zone_name": "zone-c",
                "name": "right-2",
                "zone_ambiguous": True,
                "zone_candidates": [
                    {"zone": "3", "zone_name": "zone-c"},
                    {"zone": "4", "zone_name": "zone-d"},
                ],
            }
        },
    )

    api_public._remote_set_taskterminals(
        "74513",
        ["11"],
        task={
            "terminalids": ["11"],
            "taskterminal": [
                {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
                {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
            ],
        },
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/task/jsontaskterminal"
    assert captured["json_body"] == {
        "data": [
            {"id": 74513, "terminalid": 11, "area": 255, "groupid": 3},
            {"id": 74513, "terminalid": 11, "area": 255, "groupid": 4},
        ]
    }


def test_remote_set_taskterminals_retries_jsontaskterminal_in_smaller_chunks_on_502(monkeypatch) -> None:
    calls = []

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/task/jsontaskterminal"
        body = kwargs.get("json_body") or {}
        payload = body.get("data") or []
        calls.append(payload)
        if len(payload) > 1:
            raise api_public.HTTPException(status_code=502, detail="Bad Gateway")
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_remote_taskterminal_bindings",
        lambda task_id: [],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {
            "9": {"zone": "1", "name": "terminal-9"},
            "10": {"zone": "2", "name": "terminal-10"},
            "11": {"zone": "3", "name": "terminal-11"},
        },
    )

    api_public._remote_set_taskterminals("74513", ["9", "10", "11"])

    assert calls == [
        [
            {"id": 74513, "terminalid": 9, "area": 255, "groupid": 1},
            {"id": 74513, "terminalid": 10, "area": 255, "groupid": 2},
            {"id": 74513, "terminalid": 11, "area": 255, "groupid": 3},
        ],
        [{"id": 74513, "terminalid": 9, "area": 255, "groupid": 1}],
        [
            {"id": 74513, "terminalid": 10, "area": 255, "groupid": 2},
            {"id": 74513, "terminalid": 11, "area": 255, "groupid": 3},
        ],
        [{"id": 74513, "terminalid": 10, "area": 255, "groupid": 2}],
        [{"id": 74513, "terminalid": 11, "area": 255, "groupid": 3}],
    ]


def test_desired_taskterminal_bindings_keep_target_subset_of_explicit_bindings(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {
            "11": {
                "zone": "3",
                "zone_name": "zone-c",
                "name": "right-2",
                "zone_ambiguous": True,
                "zone_candidates": [
                    {"zone": "3", "zone_name": "zone-c"},
                    {"zone": "4", "zone_name": "zone-d"},
                ],
            },
            "25": {"zone": "0", "zone_name": "", "name": "amp"},
        },
    )

    bindings = api_public._desired_taskterminal_bindings(
        {
            "terminalids": ["11", "25"],
            "taskterminal": [
                {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
                {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
                {"terminalid": "25", "groupid": 0, "groupid_present": True, "terminalname": "amp"},
            ],
            "location": [["zone-c", "right-2"]],
        },
        ["11"],
    )

    assert bindings == [
        {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
        {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
    ]


def test_desired_taskterminal_bindings_falls_back_when_explicit_bindings_do_not_cover_targets(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {
            "11": {"zone": "3", "zone_name": "zone-c", "name": "right-2"},
            "25": {"zone": "0", "zone_name": "", "name": "amp"},
        },
    )

    bindings = api_public._desired_taskterminal_bindings(
        {
            "terminalids": ["11", "25"],
            "taskterminal": [
                {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
            ],
        },
        ["11", "25"],
    )

    assert bindings == [
        {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
        {"terminalid": "25", "groupid": 0, "groupid_present": True, "terminalname": "amp"},
    ]


def test_remote_replace_taskterminals_prefers_direct_desired_bindings_over_location_resolution(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/jsontaskterminal":
            captured["json_body"] = kwargs.get("json_body")
            return {"ok": True}
        raise AssertionError(f"unexpected remote request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", lambda task_id: ([], True))
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(
        api_public,
        "_resolve_binding_group_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not resolve from location")),
    )

    api_public._remote_replace_taskterminals(
        "74513",
        ["11"],
        previous_terminal_ids=[],
        task={
            "terminalids": ["11"],
            "location": [["zone-c", "right-2"]],
        },
        desired_bindings=[
            {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "right-2"},
            {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "right-2"},
        ],
    )

    assert captured["json_body"] == {
        "data": [
            {"id": 74513, "terminalid": 11, "area": 255, "groupid": 3},
            {"id": 74513, "terminalid": 11, "area": 255, "groupid": 4},
        ]
    }


def test_remote_set_taskterminals_rejects_terminal_not_in_location_zone(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {"9": {"zone": "0", "name": "鍙充竴缁堢"}},
    )
    monkeypatch.setattr(
        api_public,
        "_fetch_enriched_zone_items",
        lambda force=False: [
            {
                "id": 1,
                "name": "zone-a",
                "terminal": [{"id": 11, "name": "鍙充簩缁堢", "zone": 0}],
            }
        ],
    )

    try:
        api_public._remote_set_taskterminals("74513", ["9"], task={"location": [["zone-a", "right-1"]]})
        raise AssertionError("expected HTTPException")
    except api_public.HTTPException as exc:
        assert exc.status_code == 400


def test_remote_fetch_schedule_tasks_uses_swagger_json_body(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"data": []}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    api_public._remote_fetch_schedule_tasks("娴嬭瘯鏂规")

    assert captured["method"] == "POST"
    assert captured["path"] == "/task/sechetaskinfo"
    assert captured["json_body"] == {"name": "娴嬭瘯鏂规"}
    assert captured["form_body"] is None
    assert captured["allow_form_retry"] is False


def test_remote_set_schedule_status_uses_swagger_json_body(monkeypatch) -> None:
    captured = {}

    def fake_remote_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    api_public._remote_set_schedule_status("娴嬭瘯鏂规", True)

    assert captured["method"] == "POST"
    assert captured["path"] == "/task/sechenableordisable"
    assert captured["json_body"] == {"sechename": "娴嬭瘯鏂规", "state": 0}
    assert captured["form_body"] is None
    assert captured["allow_form_retry"] is False


def test_save_schedules_payload_normalizes_schedule_terminal_fields(monkeypatch) -> None:
    stored: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [{"id": "1", "name": "server251", "zone": "1"}],
    )
    monkeypatch.setattr(api_public, "_store_set", lambda key, value: stored.__setitem__(key, deepcopy(value)))
    monkeypatch.setattr(api_public, "_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)

    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {
                        "taskid": "73660",
                        "taskname": "ring",
                        "starttime": "08:20:00",
                        "startdate": "2026-01-14",
                        "enddate": "2039-01-31",
                        "location": [["stale-zone", "server251"]],
                        "terminalids": [],
                        "liveterminalid": 0,
                        "liveterminalname": "server251",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    api_public._save_schedules_payload(
        deepcopy(payload),
        sync_schedules=False,
        sync_broadcasts=False,
        sync_livecasts=False,
    )

    saved_task = stored["broadcast_schedules"]["schedules"][0]["tasks"][0]
    assert saved_task["terminalids"] == ["1"]
    assert str(saved_task["liveterminalid"]) == "1"
    assert saved_task["liveterminalname"] == "server251"
    assert saved_task["terminalnames"] == ["server251"]
    assert saved_task["location"] == [[api_public._zone_label("1"), "server251"]]

    all_task_row = stored["all_task"]["data"][0]
    assert str(all_task_row["liveterminalid"]) == "1"
    assert all_task_row["liveterminalname"] == "server251"
    assert all_task_row["location"] == [[api_public._zone_label("1"), "server251"]]

def test_save_schedules_payload_accepts_explicit_multi_terminal_locations_without_precomputed_ids(monkeypatch) -> None:
    stored: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [
            {"id": "9", "name": "right-1", "zone": "1"},
            {"id": "10", "name": "right-2", "zone": "1"},
        ],
    )
    monkeypatch.setattr(api_public, "_store_set", lambda key, value: stored.__setitem__(key, deepcopy(value)))
    monkeypatch.setattr(api_public, "_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)

    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {
                        "taskid": "73661",
                        "taskname": "ring-multi",
                        "starttime": "08:30:00",
                        "startdate": "2026-01-14",
                        "enddate": "2039-01-31",
                        "location": [["教学区", "right-1"], ["教学区", "right-2"]],
                        "terminalids": [],
                        "terminalnames": [],
                        "liveterminalid": 0,
                        "liveterminalname": "",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    api_public._save_schedules_payload(
        deepcopy(payload),
        sync_schedules=False,
        sync_broadcasts=False,
        sync_livecasts=False,
    )

    saved_task = stored["broadcast_schedules"]["schedules"][0]["tasks"][0]
    assert saved_task["terminalids"] == ["9", "10"]
    assert saved_task["terminalnames"] == ["right-1", "right-2"]
    assert str(saved_task["liveterminalid"]) == "9"
    assert saved_task["location"] == [[api_public._zone_label("1"), "right-1"], [api_public._zone_label("1"), "right-2"]]


def test_location_paths_from_terminals_uses_unassigned_label_for_zone_zero() -> None:
    terminal_lookup = {
        "9": {"zone": 0, "name": "鍙充竴缁堢"},
    }

    assert api_public._location_paths_from_terminals(["9"], terminal_lookup) == [[api_public._zone_label("0"), terminal_lookup["9"]["name"]]]


def test_normalize_schedule_task_terminal_preserves_explicit_location_when_lookup_zone_differs() -> None:
    task = {
        "taskid": "701",
        "taskname": "morning-bell",
        "starttime": "08:00:00",
        "location": [["zone-a", "right-1"]],
        "terminalids": ["9"],
        "liveterminalid": "9",
    }

    changed = api_public._normalize_schedule_task_terminal(
        task,
        {"9": {"zone": "19", "zone_name": "middle-school", "name": "right-1"}},
        {"鍙充竴缁堢": "9"},
    )

    assert changed is True
    assert task["terminalids"] == ["9"]
    assert str(task["liveterminalid"]) == "9"
    assert task["liveterminalname"] == "right-1"
    assert task["location"] == [["zone-a", "right-1"]]


def test_apply_terminal_lookup_to_schedules_preserves_explicit_location_when_lookup_zone_differs(
    monkeypatch,
) -> None:
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)

    schedules = [
        {
            "schedule_name": "summer",
            "tasks": [
                {
                    "taskid": "701",
                    "taskname": "morning-bell",
                    "starttime": "08:00:00",
                    "location": [["zone-a", "right-1"]],
                    "terminalids": ["9"],
                    "liveterminalid": "9",
                }
            ],
        }
    ]

    api_public._apply_terminal_lookup_to_schedules(
        schedules,
        {"9": {"zone": "19", "zone_name": "middle-school", "name": "right-1"}},
    )

    task = schedules[0]["tasks"][0]
    assert task["terminalids"] == ["9"]
    assert str(task["liveterminalid"]) == "9"
    assert task["terminalnames"] == ["right-1"]
    assert task["liveterminalname"] == "right-1"
    assert task["location"] == [["zone-a", "right-1"]]


def test_fetch_remote_schedule_payload_preserves_schedule_location_during_sync(monkeypatch) -> None:
    remote_payload = {
        "version": "remote",
        "generated_at": "2026-03-19 21:38:44",
        "schedules": [
            {
                "schedule_name": "summer",
                "status": "鍚敤",
                "tasks": [
                    {
                        "taskid": "701",
                        "taskname": "morning-bell",
                        "starttime": "08:00:00",
                        "liveterminalid": "9",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    local_all_task = {
        "data": [
            {
                "taskid": "701",
                "taskname": "morning-bell",
                "starttime": "08:00:00",
                "sechename": "summer",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "liveterminalid": "9",
                "liveterminalname": "right-1",
                "location": [["zone-a", "right-1"]],
            }
        ]
    }

    def fake_store_get(key: str):
        if key == "all_task":
            return deepcopy(local_all_task)
        return None

    monkeypatch.setattr(api_public, "_remote_fetch_schedule_sources", lambda force=False: [{"data": []}])
    monkeypatch.setattr(api_public, "_adapt_remote_schedules", lambda raw: deepcopy(remote_payload))
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_load_local_broadcasts", lambda: {"broadcasts": [], "livecasts": []})
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {"9": {"zone": "19", "zone_name": "middle-school", "name": "right-1"}},
    )
    monkeypatch.setattr(api_public, "_remote_task_terminal_ids", lambda task_id: ["9"])
    monkeypatch.setattr(api_public, "_fetch_remote_taskinfo_list", lambda kind, task_type: [])
    monkeypatch.setattr(api_public, "_store_get", fake_store_get)

    payload = api_public._fetch_remote_schedule_payload()

    task = payload["schedules"][0]["tasks"][0]
    assert task["terminalids"] == ["9"]
    assert str(task["liveterminalid"]) == "9"
    assert task["terminalnames"] == ["right-1"]
    assert task["liveterminalname"] == "right-1"
    assert task["location"] == [["zone-a", "right-1"]]


def test_fetch_remote_schedule_payload_preserves_broadcast_location_during_sync(monkeypatch) -> None:
    remote_payload = {
        "version": "remote",
        "generated_at": "2026-03-19 21:38:44",
        "schedules": [],
        "broadcasts": [],
        "livecasts": [],
    }
    local_all_task = {
        "data": [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "liveterminalid": "9",
                "liveterminalname": "right-1",
                "location": [["zone-a", "right-1"]],
            }
        ]
    }
    terminal_lookup = {"9": {"zone": "19", "zone_name": "middle-school", "name": "right-1"}}
    media_lookup = {"911": "bell"}

    def fake_store_get(key: str):
        if key == "all_task":
            return deepcopy(local_all_task)
        return None

    def fake_fetch_remote_taskinfo_list(kind: str, task_type: str):
        if kind != "broadcast":
            return []
        return api_public._map_remote_taskinfo_items(
            [
                {
                    "taskid": "501",
                    "taskname": "afternoon-bell",
                    "starttime": "15:00:00",
                    "mediaid": "911",
                    "liveterminalid": "9",
                    "volume": 60,
                }
            ],
            media_lookup,
            terminal_lookup,
            kind,
        )

    monkeypatch.setattr(api_public, "_remote_fetch_schedule_sources", lambda force=False: [{"data": []}])
    monkeypatch.setattr(api_public, "_adapt_remote_schedules", lambda raw: deepcopy(remote_payload))
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_load_local_broadcasts", lambda: {"broadcasts": [], "livecasts": []})
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: media_lookup)
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: terminal_lookup)
    monkeypatch.setattr(api_public, "_fetch_remote_taskinfo_list", fake_fetch_remote_taskinfo_list)
    monkeypatch.setattr(api_public, "_store_get", fake_store_get)

    payload = api_public._fetch_remote_schedule_payload()

    task = payload["broadcasts"][0]
    assert task["terminalids"] == ["9"]
    assert str(task["liveterminalid"]) == "9"
    assert task["terminalnames"] == ["right-1"]
    assert task["location"] == [["zone-a", "right-1"]]


def test_get_broadcast_schedules_enriches_location_only_schedule_tasks(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {
                        "taskid": "73660",
                        "taskname": "ring",
                        "starttime": "08:20:00",
                        "startdate": "2026-01-14",
                        "enddate": "2039-01-31",
                        "location": [["stale-zone", "server251"]],
                        "terminalids": [],
                        "liveterminalid": 0,
                        "liveterminalname": "server251",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [{"id": "1", "name": "server251", "zone": "1"}],
    )

    result = api_public.get_broadcast_schedules()

    task = result["schedules"][0]["tasks"][0]
    assert task["terminalids"] == ["1"]
    assert str(task["liveterminalid"]) == "1"
    assert task["liveterminalname"] == "server251"
    assert task["terminalnames"] == ["server251"]
    assert task["location"] == [[api_public._zone_label("1"), "server251"]]


def test_build_all_task_payload_prefers_terzone_name_over_terminalinfo_zone(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [{"id": "9", "name": "right-1", "zone": "19"}],
    )
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_fetch_enriched_zone_items",
        lambda force=False: [
            {
                "id": "1",
                "name": "zone-a",
                "terminal": [{"id": "9", "name": "right-1"}],
            }
        ],
    )

    built = api_public._build_all_task_payload(
        {
            "schedules": [
                {
                    "schedule_name": "summer",
                    "tasks": [
                        {
                            "taskid": "1",
                            "taskname": "morning-bell",
                            "mediaid": "911",
                            "medianame": "bell",
                            "starttime": "08:00:00",
                            "terminalids": ["9"],
                        }
                    ],
                }
            ],
            "broadcasts": [],
            "livecasts": [],
        }
    )

    assert built["data"][0]["location"] == [["zone-a", "right-1"]]


def test_map_remote_taskinfo_items_prefers_zone_name_from_lookup(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)

    rows = api_public._map_remote_taskinfo_items(
        [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "mediaid": "911",
                "liveterminalid": "9",
                "volume": 60,
            }
        ],
        {"911": "bell"},
        {"9": {"zone": "19", "zone_name": "zone-a", "name": "right-1"}},
        "broadcast",
    )

    assert rows[0]["location"] == [["zone-a", "right-1"]]


def test_enrich_lookup_zones_from_terzone_marks_multi_zone_terminal_ambiguous(monkeypatch) -> None:
    warnings = []
    lookup = api_public._terminal_lookup_from_items(
        [
            {
                "id": 9,
                "name": "right-1",
                "zone": 0,
            }
        ]
    )

    monkeypatch.setattr(api_public.LOGGER, "warning", lambda message, payload: warnings.append((message, payload)))

    api_public._enrich_lookup_zones_from_terzone(
        lookup,
        [
            {"id": 1, "name": "zone-a", "terminal": [{"id": 9, "name": "right-1"}]},
            {"id": 19, "name": "middle-school", "terminal": [{"id": 9, "name": "right-1"}]},
        ],
    )

    item = lookup["9"]
    assert item["zone"] == "1"
    assert item["zone_name"] == "zone-a"
    assert item["zone_ambiguous"] is True
    assert item["zone_candidates"] == [
        {"zone": "1", "zone_name": "zone-a"},
        {"zone": "19", "zone_name": "middle-school"},
    ]
    assert warnings
    assert warnings[-1][0] == "ambiguous terminal zone mapping %s"
    assert warnings[-1][1]["terminal_id"] == "9"


def test_fetch_enriched_zone_items_attaches_zoneterminal_members(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_remote_terzone_cached",
        lambda force=False: {"data": [{"id": 1, "name": "zone-a"}, {"id": 19, "name": "middle-school"}]},
    )
    monkeypatch.setattr(
        api_public,
        "_remote_zoneterminal_cached",
        lambda zone_id, force=False: (
            {"data": [{"id": 9, "name": "right-1"}]}
            if str(zone_id) == "1"
            else {"data": [{"id": 35, "name": "tea-room"}]}
        ),
    )

    enriched = api_public._fetch_enriched_zone_items(force=True)

    assert enriched == [
        {"id": 1, "name": "zone-a", "terminal": [{"id": 9, "name": "right-1"}]},
        {"id": 19, "name": "middle-school", "terminal": [{"id": 35, "name": "tea-room"}]},
    ]


def test_location_paths_from_terminals_returns_empty_for_ambiguous_lookup() -> None:
    lookup = {
        "9": {
            "zone": "1",
            "zone_name": "zone-a",
            "name": "right-1",
            "zone_ambiguous": True,
            "zone_candidates": [
                {"zone": "1", "zone_name": "zone-a"},
                {"zone": "19", "zone_name": "middle-school"},
            ],
        }
    }

    assert api_public._location_paths_from_terminals(["9"], lookup) == []


def test_location_paths_from_taskterminal_bindings_use_groupid_and_unassigned_zone() -> None:
    result = api_public._location_paths_from_taskterminal_bindings(
        [
            {"terminalid": "9", "groupid": 3, "terminalname": "right-1"},
            {"terminalid": "8", "groupid": 0, "terminalname": "lectern"},
        ],
        {"9": {"name": "right-1"}, "8": {"name": "lectern"}},
        [{"id": 3, "name": "zone-c"}],
    )

    assert result == [
        [api_public._zone_label(0), "lectern"],
        ["zone-c", "right-1"],
    ]


def test_enrich_lookup_zones_from_terzone_picks_smallest_zone_id_regardless_of_source_order(monkeypatch) -> None:
    warnings = []
    lookup = {
        "9": {
            "zone": 0,
            "name": "right-1",
            "zone_name": "",
            "zone_candidates": [],
            "zone_ambiguous": False,
        }
    }

    monkeypatch.setattr(api_public.LOGGER, "warning", lambda message, payload: warnings.append((message, payload)))

    api_public._enrich_lookup_zones_from_terzone(
        lookup,
        [
            {"id": 19, "name": "middle-school", "terminal": [{"id": 9, "name": "right-1"}]},
            {"id": 3, "name": "zone-c", "terminal": [{"id": 9, "name": "right-1"}]},
            {"id": 1, "name": "zone-a", "terminal": [{"id": 9, "name": "right-1"}]},
        ],
    )

    item = lookup["9"]
    assert item["zone"] == "1"
    assert item["zone_name"] == "zone-a"
    assert item["zone_ambiguous"] is True
    assert item["zone_candidates"] == [
        {"zone": "1", "zone_name": "zone-a"},
        {"zone": "3", "zone_name": "zone-c"},
        {"zone": "19", "zone_name": "middle-school"},
    ]
    assert warnings


def test_resolve_binding_group_context_requires_explicit_location_for_ambiguous_terminal() -> None:
    lookup = {
        "9": {
            "zone": "1",
            "zone_name": "zone-a",
            "name": "right-1",
            "zone_ambiguous": True,
            "zone_candidates": [
                {"zone": "1", "zone_name": "zone-a"},
                {"zone": "19", "zone_name": "middle-school"},
            ],
        }
    }

    with pytest.raises(api_public.HTTPException, match="explicit location is required"):
        api_public._resolve_binding_group_context({}, "9", lookup, [])


def test_apply_terminal_lookup_to_schedules_uses_remote_taskterminal_groupid_for_ambiguous_lookup(monkeypatch) -> None:
    schedules = [
        {
            "schedule_name": "summer",
            "tasks": [
                {
                    "taskid": "501",
                    "taskname": "ring",
                    "starttime": "08:00:00",
                    "liveterminalid": "9",
                }
            ],
        }
    ]
    lookup = {
        "9": {
            "zone": "3",
            "zone_name": "zone-c",
            "name": "right-1",
            "zone_ambiguous": True,
            "zone_candidates": [
                {"zone": "3", "zone_name": "zone-c"},
                {"zone": "4", "zone_name": "zone-d"},
            ],
        }
    }

    monkeypatch.setattr(api_public, "_store_get", lambda key: {"data": []} if key == "all_task" else None)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_fetch_enriched_zone_items", lambda force=False: [{"id": 3, "name": "zone-c"}])
    monkeypatch.setattr(
        api_public,
        "_remote_taskterminal_bindings",
        lambda task_id: [{"terminalid": "9", "groupid": 3, "terminalname": "right-1"}],
    )

    api_public._apply_terminal_lookup_to_schedules(schedules, lookup)

    task = schedules[0]["tasks"][0]
    assert task["terminalids"] == ["9"]
    assert str(task["liveterminalid"]) == "9"
    assert task["terminalnames"] == ["right-1"]
    assert task["liveterminalname"] == "right-1"
    assert task["location"] == [["zone-c", "right-1"]]


def test_get_schedule_tasks_uses_taskterminal_groupid_for_ambiguous_lookup(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {
                        "taskid": "501",
                        "taskname": "ring",
                        "starttime": "08:00:00",
                        "terminalids": ["9"],
                        "liveterminalid": "9",
                        "location": [],
                        "taskterminal": [
                            {"terminalid": "9", "groupid": 3, "terminalname": "right-1"},
                        ],
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_terminalinfo_items", lambda: [{"id": "9", "name": "right-1", "zone": "4"}])
    monkeypatch.setattr(
        api_public,
        "_fetch_enriched_zone_items",
        lambda force=False: [
            {"id": 3, "name": "zone-c", "terminal": [{"id": 9, "name": "right-1"}]},
            {"id": 4, "name": "zone-d", "terminal": [{"id": 9, "name": "right-1"}]},
        ],
    )

    result = api_public.get_schedule_tasks("summer")

    task = result["tasks"][0]
    assert task["terminalids"] == ["9"]
    assert str(task["liveterminalid"]) == "9"
    assert task["liveterminalname"] == "right-1"
    assert task["location"] == [["zone-c", "right-1"]]


def test_get_broadcast_schedules_filters_once_ephemeral_tasks(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "summer",
                "tasks": [
                    {
                        "taskid": "501",
                        "taskname": "normal-task",
                        "starttime": "08:00:00",
                        "terminalids": [],
                        "liveterminalid": "0",
                    },
                    {
                        "taskid": "93001",
                        "taskname": "normal-task_once_501_20260414080000",
                        "starttime": "08:10:00",
                        "terminalids": [],
                        "liveterminalid": "0",
                    },
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_ensure_once_overrides_cleaned", lambda: None)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_store_terminalinfo_items", lambda: [])

    result = api_public.get_broadcast_schedules()

    tasks = result["schedules"][0]["tasks"]
    assert [task["taskid"] for task in tasks] == ["501"]
    assert [task["taskname"] for task in tasks] == ["normal-task"]


def test_map_remote_taskinfo_items_uses_remote_taskterminal_groupid_for_ambiguous_lookup(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_fetch_enriched_zone_items", lambda force=False: [{"id": 3, "name": "zone-c"}])
    monkeypatch.setattr(
        api_public,
        "_remote_taskterminal_bindings",
        lambda task_id: [{"terminalid": "9", "groupid": 3, "terminalname": "right-1"}],
    )

    rows = api_public._map_remote_taskinfo_items(
        [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "mediaid": "911",
                "liveterminalid": "9",
                "volume": 60,
            }
        ],
        {"911": "bell"},
        {
            "9": {
                "zone": "3",
                "zone_name": "zone-c",
                "name": "right-1",
                "zone_ambiguous": True,
                "zone_candidates": [
                    {"zone": "3", "zone_name": "zone-c"},
                    {"zone": "4", "zone_name": "zone-d"},
                ],
            }
        },
        "broadcast",
    )

    assert rows[0]["terminalids"] == ["9"]
    assert rows[0]["terminalnames"] == ["right-1"]
    assert rows[0]["location"] == [["zone-c", "right-1"]]


def test_map_remote_taskinfo_items_preserves_explicit_location_from_local_backup_when_lookup_zone_differs(
    monkeypatch,
) -> None:
    backup_payload = {
        "data": [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "liveterminalid": "9",
                "liveterminalname": "right-1",
                "location": [["zone-a", "right-1"]],
            }
        ]
    }

    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: deepcopy(backup_payload) if key == "all_task" else None,
    )

    rows = api_public._map_remote_taskinfo_items(
        [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "mediaid": "911",
                "liveterminalid": "9",
                "volume": 60,
            }
        ],
        {"911": "bell"},
        {"9": {"zone": "19", "zone_name": "middle-school", "name": "right-1"}},
        "broadcast",
    )

    assert rows[0]["location"] == [["zone-a", "right-1"]]
    assert rows[0]["terminalids"] == ["9"]
    assert rows[0]["terminalnames"] == ["right-1"]


def test_map_remote_taskinfo_items_prefers_broadcast_schedule_backup_over_all_task(monkeypatch) -> None:
    broadcast_payload = {
        "broadcasts": [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "liveterminalid": "9",
                "liveterminalname": "right-1",
                "location": [["zone-a", "right-1"]],
            }
        ],
        "livecasts": [],
    }
    all_task_payload = {
        "data": [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "liveterminalid": "9",
                "liveterminalname": "right-1",
                "location": [["middle-school", "right-1"]],
            }
        ]
    }

    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: (
            deepcopy(broadcast_payload)
            if key == "broadcast_schedules"
            else deepcopy(all_task_payload) if key == "all_task" else None
        ),
    )

    rows = api_public._map_remote_taskinfo_items(
        [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "mediaid": "911",
                "liveterminalid": "9",
                "volume": 60,
            }
        ],
        {"911": "bell"},
        {
            "9": {
                "zone": None,
                "zone_name": "",
                "name": "right-1",
                "zone_ambiguous": True,
                "zone_candidates": [
                    {"zone": "1", "zone_name": "zone-a"},
                    {"zone": "19", "zone_name": "middle-school"},
                ],
            }
        },
        "broadcast",
    )

    assert rows[0]["location"] == [["zone-a", "right-1"]]
    assert rows[0]["terminalids"] == ["9"]
    assert rows[0]["terminalnames"] == ["right-1"]


def test_map_remote_taskinfo_items_preserves_item_location_when_lookup_zone_differs(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)

    rows = api_public._map_remote_taskinfo_items(
        [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "mediaid": "911",
                "terminalids": ["9"],
                "liveterminalid": "9",
                "location": [["zone-a", "right-1"]],
                "volume": 60,
            }
        ],
        {"911": "bell"},
        {"9": {"zone": "19", "zone_name": "middle-school", "name": "right-1"}},
        "broadcast",
    )

    assert rows[0]["location"] == [["zone-a", "right-1"]]
    assert rows[0]["terminalids"] == ["9"]
    assert rows[0]["terminalnames"] == ["right-1"]


def test_map_remote_taskinfo_items_logs_location_resolution_source(monkeypatch) -> None:
    logged = []
    backup_payload = {
        "data": [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "liveterminalid": "9",
                "liveterminalname": "right-1",
                "location": [["zone-a", "right-1"]],
            }
        ]
    }

    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: deepcopy(backup_payload) if key == "all_task" else None,
    )
    monkeypatch.setattr(
        api_public,
        "_debug_remote",
        lambda message, **fields: logged.append((message, fields)),
    )

    rows = api_public._map_remote_taskinfo_items(
        [
            {
                "taskid": "501",
                "taskname": "afternoon-bell",
                "starttime": "15:00:00",
                "mediaid": "911",
                "liveterminalid": "9",
                "volume": 60,
            }
        ],
        {"911": "bell"},
        {"9": {"zone": "19", "zone_name": "middle-school", "name": "right-1"}},
        "broadcast",
    )

    assert rows[0]["location"] == [["zone-a", "right-1"]]
    assert logged
    location_logs = [entry for entry in logged if entry[0] == "taskinfo location resolved"]
    assert location_logs
    message, fields = location_logs[-1]
    assert message == "taskinfo location resolved"
    assert fields["kind"] == "broadcast"
    assert fields["task_id"] == "501"
    assert fields["terminal_ids"] == ["9"]
    assert fields["preserve_explicit_location"] is True
    assert fields["location_source"] == "backup"
    assert fields["final_location"] == [["zone-a", "right-1"]]

    terminal_logs = [entry for entry in logged if entry[0] == "taskinfo terminal resolved"]
    assert terminal_logs
    message, fields = terminal_logs[-1]
    assert message == "taskinfo terminal resolved"
    assert fields["kind"] == "broadcast"
    assert fields["task_id"] == "501"
    assert fields["task_name"] == "afternoon-bell"
    assert fields["terminal_ids"] == ["9"]
    assert fields["terminal_names"] == ["right-1"]
    assert str(fields["liveterminalid"]) == "9"
    assert fields["liveterminalname"] == "right-1"
    assert fields["final_location"] == [["zone-a", "right-1"]]


def test_save_schedules_payload_inherits_terminal_binding_from_matching_task_key(monkeypatch) -> None:
    stored: dict = {}
    source_payload = {
        "schedules": [
            {
                "schedule_name": "source",
                "tasks": [
                    {
                        "taskid": "701",
                        "taskname": "morning-bell",
                        "starttime": "08:00:00",
                        "terminalids": ["9"],
                        "terminalnames": ["right-1"],
                        "liveterminalid": "9",
                        "liveterminalname": "right-1",
                        "location": [[api_public._zone_label("1"), "right-1"]],
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    all_task_payload = {
        "data": [
            {
                "taskid": "701",
                "taskname": "morning-bell",
                "starttime": "08:00:00",
                "sechename": "source",
                "terminalids": ["9"],
                "terminalnames": ["right-1"],
                "liveterminalid": "9",
                "liveterminalname": "right-1",
                "location": [[api_public._zone_label("1"), "right-1"]],
            }
        ]
    }

    def fake_store_get(key: str):
        if key == "broadcast_schedules":
            return deepcopy(source_payload)
        if key == "all_task":
            return deepcopy(all_task_payload)
        return None

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [{"id": "9", "name": "right-1", "zone": "1"}],
    )
    monkeypatch.setattr(api_public, "_store_get", fake_store_get)
    monkeypatch.setattr(api_public, "_store_set", lambda key, value: stored.__setitem__(key, deepcopy(value)))
    monkeypatch.setattr(api_public, "_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)

    api_public._save_schedules_payload(
        {
            "schedules": [
                {
                    "schedule_name": "999",
                    "tasks": [
                        {
                            "id": "draft-1",
                            "taskid": "0",
                            "taskname": "morning-bell",
                            "starttime": "08:00:00",
                            "startdate": "2026-01-18",
                            "enddate": "2039-01-31",
                            "terminalids": [],
                            "liveterminalid": 0,
                            "location": [],
                        }
                    ],
                }
            ],
            "broadcasts": [],
            "livecasts": [],
        },
        sync_schedules=False,
        sync_broadcasts=False,
        sync_livecasts=False,
    )

    task = stored["broadcast_schedules"]["schedules"][0]["tasks"][0]
    assert task["terminalids"] == ["9"]
    assert str(task["liveterminalid"]) == "9"
    assert task["terminalnames"] == ["right-1"]
    assert task["liveterminalname"] == "right-1"
    assert task["location"] == [[api_public._zone_label("1"), "right-1"]]


def test_save_schedules_payload_blocks_remote_sync_when_schedule_task_binding_missing(monkeypatch) -> None:
    sync_called = {"value": False}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)
    monkeypatch.setattr(api_public, "_remote_terminalinfo_payload", lambda force=False: {"data": []})
    monkeypatch.setattr(api_public, "_remote_terzone_cached", lambda force=False: {"data": []})
    monkeypatch.setattr(api_public, "_sync_remote_schedules", lambda payload: sync_called.__setitem__("value", True))

    with pytest.raises(api_public.HTTPException, match="Missing terminal binding for schedule tasks"):
        api_public._save_schedules_payload(
            {
                "schedules": [
                    {
                        "schedule_name": "summer",
                        "tasks": [
                            {
                                "taskid": "0",
                                "taskname": "morning-bell",
                                "starttime": "08:00:00",
                                "startdate": "2026-01-18",
                                "enddate": "2039-01-31",
                                "terminalids": [],
                                "liveterminalid": 0,
                                "location": [],
                            }
                        ],
                    }
                ],
                "broadcasts": [],
                "livecasts": [],
            },
            sync_schedules=True,
            sync_broadcasts=False,
            sync_livecasts=False,
            update_all_task=False,
        )

    assert sync_called["value"] is False


def test_save_schedules_payload_validates_only_changed_schedule_bindings(monkeypatch) -> None:
    targeted_calls: list[list[str]] = []
    removed_calls: list[list[str]] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)
    monkeypatch.setattr(api_public, "_remote_terminalinfo_payload", lambda force=False: {"data": []})
    monkeypatch.setattr(api_public, "_remote_terzone_cached", lambda force=False: {"data": []})
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_targeted",
        lambda payload, names: targeted_calls.append(list(names)),
    )
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_removed",
        lambda names, remote_tasks_by_name=None: removed_calls.append(list(names)),
    )
    monkeypatch.setattr(api_public, "_write_cache_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)
    monkeypatch.setattr(api_public, "_store_set", lambda *args, **kwargs: None)

    api_public._save_schedules_payload(
        {
            "schedules": [
                {
                    "schedule_name": "legacy",
                    "tasks": [
                        {
                            "taskid": "101",
                            "taskname": "legacy-ring",
                            "starttime": "07:40:00",
                            "startdate": "2026-01-18",
                            "enddate": "2039-01-31",
                            "terminalids": [],
                            "liveterminalid": 0,
                            "location": [],
                        }
                    ],
                },
                {
                    "schedule_name": "fresh",
                    "tasks": [
                        {
                            "taskid": "202",
                            "taskname": "fresh-ring",
                            "starttime": "08:00:00",
                            "startdate": "2026-01-18",
                            "enddate": "2039-01-31",
                            "terminalids": ["9"],
                            "liveterminalid": "9",
                            "location": [],
                        }
                    ],
                },
            ],
            "broadcasts": [],
            "livecasts": [],
            "directories": [],
        },
        sync_schedules=True,
        sync_broadcasts=False,
        sync_livecasts=False,
        update_all_task=False,
        schedule_sync_delta={
            "changed_or_added_names": ["fresh"],
            "removed_names": ["legacy"],
            "renamed": [],
        },
    )

    assert targeted_calls == [["fresh"]]
    assert removed_calls == [["legacy"]]


def test_remote_token_serializes_concurrent_login(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TOKEN", None)
    call_count = {"value": 0}
    results: list[str] = []
    barrier = threading.Barrier(5)

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/authorizations"
        call_count["value"] += 1
        api_public.time.sleep(0.05)
        return {"data": [{"token": "locked-token"}]}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    def worker() -> None:
        barrier.wait()
        results.append(str(api_public._remote_token()))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert call_count["value"] == 1
    assert results == ["locked-token"] * 5


