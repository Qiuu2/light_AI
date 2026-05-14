from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_adjust_volume_task_persists_local_payload_after_remote_success(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "71665", "taskname": "anthem", "volume": 80}],
        "livecasts": [],
    }
    committed: dict = {"remote_calls": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_remote_set_task_volume",
        lambda task_id, volume: committed["remote_calls"].append((task_id, volume)),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_adjust_volume_task("anthem", "20")

    assert "设置为 20%" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["task_ids"] == ["71665"]
    assert logs[0]["details"]["mode"] == "absolute"
    assert logs[0]["details"]["target"] == 20
    assert committed["remote_calls"] == [("71665", 20)]
    assert committed["payload"]["broadcasts"][0]["volume"] == 20
    assert committed["sync_flags"] == {
        "sync_schedules": False,
        "sync_broadcasts": False,
        "sync_livecasts": False,
    }
    assert "generated_at" in committed["payload"]


def test_adjust_volume_task_partial_remote_failure_only_persists_successes(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [
            {"taskid": "1", "taskname": "anthem", "volume": 80},
            {"taskid": "2", "taskname": "anthem", "volume": 60},
        ],
        "livecasts": [],
    }
    committed: dict = {"remote_calls": []}

    def fake_remote_set(task_id: str, volume: int) -> None:
        committed["remote_calls"].append((task_id, volume))
        if task_id == "2":
            raise api_public.HTTPException(status_code=502, detail="boom")

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_set_task_volume", fake_remote_set)
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_adjust_volume_task("anthem", "20")

    assert "设置为 20%" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["task_ids"] == ["1"]
    assert committed["remote_calls"] == [("1", 20), ("2", 20)]
    assert committed["payload"]["broadcasts"][0]["volume"] == 20
    assert committed["payload"]["broadcasts"][1]["volume"] == 60


def test_adjust_volume_task_does_not_persist_when_all_remote_updates_fail(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "1", "taskname": "anthem", "volume": 80}],
        "livecasts": [],
    }
    committed: dict = {"save_calls": 0}

    def fake_remote_set(task_id: str, volume: int) -> None:
        raise api_public.HTTPException(status_code=502, detail="boom")

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_set_task_volume", fake_remote_set)
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"save_calls": committed["save_calls"] + 1}),
    )

    reply, state, logs = api_public._apply_adjust_volume_task("anthem", "20")

    assert "音量" in reply
    assert "boom" not in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["failure_reason"] == "boom"
    assert state["diagnostics"][0]["user_reason"] == "没有成功改动任何任务音量"
    assert state["diagnostics"][0]["retryable"] is True
    assert len(logs) == 1
    assert logs[0]["details"]["failure_reason"] == "boom"
    assert logs[0]["details"]["user_reason"] == "没有成功改动任何任务音量"
    assert logs[0]["details"]["retryable"] is True
    assert committed["save_calls"] == 0


def test_parse_volume_adjustment_supports_relative_and_absolute() -> None:
    assert api_public._parse_volume_adjustment("提高20") == {
        "mode": "relative",
        "direction": "increase",
        "delta": 20,
        "target": None,
    }
    assert api_public._parse_volume_adjustment("降低15%") == {
        "mode": "relative",
        "direction": "decrease",
        "delta": 15,
        "target": None,
    }
    assert api_public._parse_volume_adjustment("稍微调大一点") == {
        "mode": "relative",
        "direction": "increase",
        "delta": 10,
        "target": None,
    }
    assert api_public._parse_volume_adjustment("调到30") == {
        "mode": "absolute",
        "direction": None,
        "delta": None,
        "target": 30,
    }
    assert api_public._parse_volume_adjustment("静音") == {
        "mode": "absolute",
        "direction": None,
        "delta": None,
        "target": 0,
    }


def test_remote_set_task_volume_allows_zero(monkeypatch) -> None:
    committed: dict = {}

    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: committed.update(
            {"method": method, "path": path, "json_body": kwargs.get("json_body")}
        )
        or {"ok": True},
    )
    monkeypatch.setattr(api_public, "_ensure_remote_write_ack", lambda resp, action: None)

    api_public._remote_set_task_volume("123", 0)

    assert committed == {
        "method": "POST",
        "path": "/task/taskvolume",
        "json_body": {"id": "123", "state": 0},
    }


def test_adjust_volume_task_relative_increase_persists_real_delta(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "71665", "taskname": "anthem", "volume": 80}],
        "livecasts": [],
    }
    committed: dict = {"remote_calls": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_remote_set_task_volume",
        lambda task_id, volume: committed["remote_calls"].append((task_id, volume)),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload), "sync_flags": kwargs}),
    )

    reply, state, logs = api_public._apply_adjust_volume_task("anthem", "提高20")

    assert "增加 20%" in reply
    assert state["missing_slots"] == []
    assert committed["remote_calls"] == [("71665", 100)]
    assert committed["payload"]["broadcasts"][0]["volume"] == 100
    assert logs[0]["details"]["mode"] == "relative"
    assert logs[0]["details"]["direction"] == "increase"
    assert logs[0]["details"]["step"] == 20
    assert logs[0]["details"]["target"] is None


def test_adjust_volume_task_relative_decrease_clamps_to_zero(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "1", "taskname": "anthem", "volume": 5}],
        "livecasts": [],
    }
    committed: dict = {"remote_calls": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_remote_set_task_volume",
        lambda task_id, volume: committed["remote_calls"].append((task_id, volume)),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload)}),
    )

    reply, _, logs = api_public._apply_adjust_volume_task("anthem", "降低20")

    assert "减少 20%" in reply
    assert committed["remote_calls"] == [("1", 0)]
    assert committed["payload"]["broadcasts"][0]["volume"] == 0
    assert logs[0]["details"]["step"] == 20


def test_adjust_volume_task_mute_sets_zero(monkeypatch) -> None:
    payload = {
        "schedules": [],
        "broadcasts": [{"taskid": "1", "taskname": "anthem", "volume": 35}],
        "livecasts": [],
    }
    committed: dict = {"remote_calls": []}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public,
        "_remote_set_task_volume",
        lambda task_id, volume: committed["remote_calls"].append((task_id, volume)),
    )
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: committed.update({"payload": deepcopy(new_payload)}),
    )

    reply, state, logs = api_public._apply_adjust_volume_task("anthem", "静音")

    assert "静音" in reply
    assert state["missing_slots"] == []
    assert committed["remote_calls"] == [("1", 0)]
    assert committed["payload"]["broadcasts"][0]["volume"] == 0
    assert logs[0]["details"]["mode"] == "absolute"
    assert logs[0]["details"]["target"] == 0


def test_adjust_volume_terminal_is_explicitly_unsupported() -> None:
    reply, state, logs = api_public._apply_adjust_volume_terminal(["9", "10"], "提高20")

    assert "仅支持系统全局音量" in reply
    assert state["missing_slots"] == []
    assert logs == [{"action": "adjust_volume", "mode": "terminal", "status": "unsupported"}]


def test_adjust_volume_terminal_mute_is_still_unsupported() -> None:
    reply, state, logs = api_public._apply_adjust_volume_terminal(["9", "10"], "静音")

    assert "仅支持系统全局音量" in reply
    assert state["missing_slots"] == []
    assert logs[0]["status"] == "unsupported"


def test_adjust_volume_terminal_does_not_expose_partial_remote_write_semantics() -> None:
    reply, state, logs = api_public._apply_adjust_volume_terminal(["9", "10"], "提高20")

    assert "仅支持系统全局音量" in reply
    assert state["missing_slots"] == []
    assert logs[0]["status"] == "unsupported"


def test_adjust_volume_global_routes_to_system_volume_action(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setitem(api_public.REMOTE_CACHE, "system_volume", 25)

    def fake_action_request(method, path, *, form, body_mode):
        calls.append((method, path, form, body_mode))
        return {"success": True}

    monkeypatch.setattr("backend.routes.light.action_request", fake_action_request)

    reply, state, logs = api_public._apply_adjust_volume_global("提高20%")

    assert "系统全局音量" in reply
    assert state["missing_slots"] == []
    assert calls == [("POST", "/action/setvolume", {"volume": "45"}, "multipart")]
    assert logs[0]["mode"] == "system"
    assert logs[0]["details"]["target"] == 45


def test_adjust_volume_intent_rejects_zone_fallback_when_task_slot_is_misclassified(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_load_schedules_payload",
        lambda: {"schedules": [], "broadcasts": [], "livecasts": []},
    )
    monkeypatch.setattr(
        api_public,
        "_remote_zone_items",
        lambda: [{"id": "88", "zonename": "高中部"}],
    )
    monkeypatch.setattr(
        api_public,
        "_zone_terminal_ids",
        lambda zone_id: ["101", "102"] if str(zone_id) == "88" else [],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [
            {"id": "101", "name": "高中部走廊终端", "volume": 40},
            {"id": "102", "name": "高中部教室终端", "volume": 55},
        ],
    )
    reply, state, logs = api_public._apply_adjust_volume_intent(
        "将高中部音量增加20",
        {"task_name": "高中部", "volume": "音量增加20"},
    )

    assert "仅支持系统全局音量" in reply
    assert state["missing_slots"] == []
    assert logs[0]["status"] == "unsupported"
