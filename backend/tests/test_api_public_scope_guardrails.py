from __future__ import annotations

from copy import deepcopy

import backend.api_public as api_public


def test_play_task_defaults_to_broadcasts_only(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "tasks": [{"taskid": "11", "taskname": "大课间", "taskstate": 0, "status": "停止"}],
            }
        ],
        "broadcasts": [{"taskid": "21", "taskname": "大课间", "taskstate": 0, "status": "停止"}],
        "livecasts": [{"taskid": "31", "taskname": "大课间", "taskstate": 0, "status": "停止"}],
    }
    captured: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda new_payload, **kwargs: captured.update({"payload": deepcopy(new_payload), "kwargs": kwargs}),
    )

    reply, state, logs = api_public._apply_play_task_intent("播放大课间", {"task_name": "大课间"})

    assert state == {"missing_slots": []}
    assert "大课间" in reply
    assert "播放" in reply
    assert logs[0]["action"] == "play_task"
    assert logs[0]["details"]["scope"] == "broadcast"
    assert captured["payload"]["broadcasts"][0]["taskstate"] == 1
    assert captured["payload"]["schedules"][0]["tasks"][0]["taskstate"] == 0
    assert captured["payload"]["livecasts"][0]["taskstate"] == 0


def test_enable_schedule_with_task_name_only_requires_schedule_name() -> None:
    reply, state, logs = api_public._apply_enable_schedule_intent("启用大课间", {"task_name": "大课间"})

    assert reply == "请补充 schedule_name，以确定要操作的作息方案。"
    assert state == {"missing_slots": ["schedule_name"]}
    assert logs == []


def test_check_terminal_with_explicit_target_does_not_fallback_to_all(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_resolve_terminal_ids_from_slots",
        lambda slots: ([], {"zone_name": ["高三"]}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: (_ for _ in ()).throw(AssertionError("should not fallback to all terminals")),
    )

    reply, state, logs = api_public._apply_check_terminal_intent("检查高三终端", {"zone_name": "高三"})

    assert reply == "未找到匹配的终端或分区,未执行全量自检。"
    assert state == {"missing_slots": []}
    assert logs == []


def test_check_terminal_without_target_can_check_all(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: ([], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [{"id": "1"}, {"id": "2"}],
    )
    monkeypatch.setattr(
        api_public,
        "_check_terminal_online_status",
        lambda terminal_ids: (["1"], ["终端2"]),
    )

    reply, state, logs = api_public._apply_check_terminal_intent("做一次终端自检", {})

    assert state == {"missing_slots": []}
    assert "在线 0 个" in reply
    assert "离线 0 个" in reply
    assert "未知 2 个" in reply
    assert logs[0]["action"] == "check_terminal"


def test_delete_schedule_remote_failure_does_not_persist_local(monkeypatch) -> None:
    payload = {
        "schedules": [{"schedule_name": "春季作息", "tasks": [{"taskid": "9", "taskname": "铃声"}]}],
        "broadcasts": [],
        "livecasts": [],
    }
    overrides = {
        "overrides": [
            {"id": "once-1", "mode": "once", "schedule_name": "春季作息", "action": "migrate"}
        ]
    }
    called = {"saved": False, "override_saved": False}

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
        "_save_schedules_payload_local",
        lambda payload: called.update({"saved": True}),
    )
    monkeypatch.setattr(
        api_public,
        "_save_overrides_payload",
        lambda payload: called.update({"override_saved": True}),
    )

    reply, state, logs = api_public._apply_delete_schedule_intent("删除春季作息", {"schedule_name": "春季作息"})

    assert "方案没有删除成功" in reply
    assert "远端任务还没清完" in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["failure_code"] == "delete_schedule_remote_failed"
    assert len(logs) == 1
    assert called["saved"] is False
    assert called["override_saved"] is False


def test_delete_schedule_local_failure_after_remote_delete_is_explicit(monkeypatch) -> None:
    payload = {
        "schedules": [{"schedule_name": "春季作息", "tasks": [{"taskid": "9", "taskname": "铃声"}]}],
        "broadcasts": [],
        "livecasts": [],
    }
    save_calls = {"count": 0}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_delete_remote_schedule_tasks_strict", lambda schedule_name, tasks: ["9"])

    def save_local_once_then_succeed(payload):
        save_calls["count"] += 1
        if save_calls["count"] == 1:
            raise api_public.HTTPException(status_code=500, detail="disk failed")

    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload_local",
        save_local_once_then_succeed,
    )

    reply, state, logs = api_public._apply_delete_schedule_intent("删除春季作息", {"schedule_name": "春季作息"})

    assert "方案删除已生效" in reply
    assert "本地保存失败" in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["failure_code"] == "delete_schedule_save_failed"
    assert len(logs) == 1
    assert save_calls["count"] == 1


def test_delete_schedule_override_cleanup_failure_reports_partial_cleanup(monkeypatch) -> None:
    payload = {
        "schedules": [{"schedule_name": "春季作息", "tasks": [{"taskid": "9", "taskname": "铃声"}]}],
        "broadcasts": [],
        "livecasts": [],
    }
    overrides = {
        "overrides": [
            {"id": "once-1", "mode": "once", "schedule_name": "春季作息", "action": "migrate"},
            {"id": "once-keep", "mode": "once", "schedule_name": "秋季作息", "action": "swap"},
        ]
    }
    called = {"schedule_saved": 0, "override_saved": 0}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: deepcopy(overrides))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_delete_remote_schedule_tasks_strict", lambda schedule_name, tasks: ["9"])
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload_local",
        lambda payload: called.update({"schedule_saved": called["schedule_saved"] + 1}),
    )

    def fail_override_save(payload):
        called["override_saved"] += 1
        raise api_public.HTTPException(status_code=500, detail="override disk failed")

    monkeypatch.setattr(api_public, "_save_overrides_payload", fail_override_save)

    reply, state, logs = api_public._apply_delete_schedule_intent("删除春季作息", {"schedule_name": "春季作息"})

    assert "方案已经删除" in reply
    assert "临时变更清理未完成" in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["failure_code"] == "delete_schedule_override_cleanup_failed"
    assert len(logs) == 1
    assert called["schedule_saved"] == 1
    assert called["override_saved"] == 1


def test_shift_schedule_remote_failure_rolls_back_local_and_cleans_remote(monkeypatch) -> None:
    snapshot = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "tasks": [{"taskid": "1", "id": "1", "taskname": "早读", "starttime": "08:00:00"}],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    saved_schedule_names: list[list[str]] = []

    def fake_save_local(payload: dict) -> None:
        names = [
            str(item.get("schedule_name") or item.get("name") or "")
            for item in payload.get("schedules", [])
            if isinstance(item, dict)
        ]
        saved_schedule_names.append(names)

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(snapshot))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_save_schedules_payload_local", fake_save_local)
    monkeypatch.setattr(
        api_public,
        "_sync_remote_schedules_targeted",
        lambda payload, target_names: (_ for _ in ()).throw(
            api_public.HTTPException(status_code=502, detail="sync failed")
        ),
    )
    monkeypatch.setattr(api_public, "_cleanup_remote_created_schedule", lambda schedule_name: "")

    reply, state, logs = api_public._apply_shift_schedule_later_intent(
        "春季作息后移30分钟生成新方案",
        {
            "schedule_name": "春季作息",
            "new_schedule_name": "春季作息-后移",
            "time_offset": "30分钟",
        },
    )

    assert "已回滚本地并清理远端新方案" in reply
    assert state == {"missing_slots": []}
    assert logs == []
    assert saved_schedule_names[0] == ["春季作息", "春季作息-后移"]
    assert saved_schedule_names[1] == ["春季作息"]
