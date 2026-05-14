from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from pathlib import Path
import socket
import sys
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public

assistant_chat = import_module("backend.assistant.chat")


def _pending_once_cancel() -> dict:
    return {
        "intent": "cancel_schedule",
        "schedule_name": "S",
        "task_ids": ["1", "2"],
        "time_start": "2026-03-21 08:00:00",
        "time_end": "2026-03-21 08:30:00",
        "date_specific": True,
        "created_at": api_public._now_str(),
    }


def _pending_once_move() -> dict:
    return {
        "intent": "move_schedule",
        "schedule_name": "S",
        "task_ids": ["1"],
        "source_anchor": {"kind": "date", "date": api_public.date(2026, 3, 21)},
        "target_anchor": {"kind": "date", "date": api_public.date(2026, 3, 22)},
        "time_start": "2026-03-21 08:00:00",
        "time_end": "2026-03-21 08:10:00",
        "new_time_start": "2026-03-22 08:00:00",
        "new_time_end": "2026-03-22 08:10:00",
        "date_specific": True,
        "created_at": api_public._now_str(),
    }


def _schedule_payload() -> dict:
    return {
        "schedules": [{"schedule_name": "S", "tasks": [{"taskid": "1"}, {"taskid": "2"}]}],
        "broadcasts": [],
        "livecasts": [],
    }


def _auth_session(name: str = "tester") -> dict[str, str]:
    return api_public._create_local_session("remote-test-token", name, "test")


def _auth_headers(name: str = "tester") -> dict[str, str]:
    session = _auth_session(name)
    return {"X-Token": session["token"]}


def _set_scoped_pending(action: dict, session_token: str) -> None:
    api_public._set_pending_action_for_scope(deepcopy(action), session_token)


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: TimeoutError("timed out"),
        lambda: socket.timeout("timed out"),
        lambda: URLError(socket.timeout("timed out")),
    ],
)
def test_remote_request_timeouts_are_mapped_to_504(monkeypatch, error_factory) -> None:
    def fake_urlopen(req, timeout):
        del req, timeout
        raise error_factory()

    monkeypatch.setattr(api_public.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        api_public,
        "_resolve_remote_base_url_details",
        lambda value=None: ("http://example.test/api", "test"),
    )

    with pytest.raises(api_public.HTTPException) as excinfo:
        api_public._remote_request("POST", "/task/enabletask", include_auth=False)

    assert excinfo.value.status_code == 504
    assert "POST /task/enabletask" in str(excinfo.value.detail)


def test_handle_pending_cancel_once_timeout_before_first_chunk_returns_failure(monkeypatch) -> None:
    saved: dict = {}

    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: (_ for _ in ()).throw(
            api_public.HTTPException(
                status_code=504,
                detail="Remote request timed out after 15.0s: POST /task/enabletask",
            )
        ),
    )
    monkeypatch.setattr(api_public, "PENDING_ACTION", _pending_once_cancel())

    reply, state, logs = api_public._handle_pending_action("once")

    assert "未生效" in reply
    assert "超时" in reply
    assert state["missing_slots"] == []
    assert state["intent"] == "cancel_schedule"
    assert logs == []
    assert saved == {}
    assert api_public.PENDING_ACTION is not None


def test_handle_pending_cancel_once_partial_restore_failure_saves_failed_entry(monkeypatch) -> None:
    saved: dict = {}
    call_state = {"count": 0}

    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/task/enabletask"
        call_state["count"] += 1
        if call_state["count"] == 1:
            return {"ok": True}
        raise api_public.HTTPException(
            status_code=504,
            detail="Remote request timed out after 15.0s: POST /task/enabletask",
        )

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "PENDING_ACTION", _pending_once_cancel())

    reply, state, logs = api_public._handle_pending_action("once")

    assert reply == "一次性操作未完整生效: 部分远端指令可能已下发,请立即检查远端任务启停状态。"
    assert state["missing_slots"] == []
    assert state["intent"] == "cancel_schedule"
    assert logs == []
    entry = saved["data"]["overrides"][0]
    assert entry["action"] == "cancel"
    assert entry["execution_state"] == "failed"
    assert entry["active"] is False
    assert entry["failed_phase"] == "restore"
    assert entry["failed_payload"]["taskid"] == "1,2"
    assert len(entry["commands"]) == 1
    assert entry["commands"][0]["phase"] == "disable"
    assert api_public.PENDING_ACTION is not None


def test_once_migrate_enabletask_timeout_rolls_back_shadow_and_saves_failed_entry(monkeypatch) -> None:
    saved: dict = {}
    deleted_shadow_ids: list[str] = []
    call_state = {"count": 0}
    schedule = {
        "schedule_name": "S",
        "tasks": [
            {
                "taskid": "1",
                "id": "1",
                "tasktype": "2",
                "taskname": "morning-bell",
                "starttime": "08:00:00",
                "startdate": "2026-03-21",
                "enddate": "2026-03-21",
                "timelength": 1,
                "timelengthtype": 1,
                "mediaid": "11",
                "terminalids": ["21"],
                "liveterminalid": "21",
            }
        ],
    }
    action = {
        "schedule_name": "S",
        "task_ids": ["1"],
        "time_start": "2026-03-21 08:00:00",
        "time_end": "2026-03-21 08:10:00",
        "new_time_start": "2026-03-22 08:00:00",
        "new_time_end": "2026-03-22 08:10:00",
    }

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))
    monkeypatch.setattr(api_public, "_remote_add_task", lambda schedule_name, task, media_map, terminal_map: "93001")
    monkeypatch.setattr(api_public, "_remote_delete_task", lambda task_id: deleted_shadow_ids.append(str(task_id)))

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/task/enabletask"
        call_state["count"] += 1
        if call_state["count"] == 1:
            return {"ok": True}
        raise api_public.HTTPException(
            status_code=504,
            detail="Remote request timed out after 15.0s: POST /task/enabletask",
        )

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    with pytest.raises(api_public.HTTPException) as excinfo:
        api_public._execute_once_migrate_action(action, schedule, dry_run=False)

    assert "一次性操作未完整生效" in str(excinfo.value.detail)
    assert deleted_shadow_ids == ["93001"]
    entry = saved["data"]["overrides"][0]
    assert entry["action"] == "migrate"
    assert entry["execution_state"] == "failed"
    assert entry["active"] is False
    assert entry["failed_phase"] == "disable_source"
    assert entry["shadow_task_ids"] == ["93001"]
    assert entry["rollback_attempts"][0]["taskid"] == "93001"
    assert entry["rollback_attempts"][0]["status"] == "ok"


def test_chat_api_returns_retry_and_preserves_pending_when_pending_action_raises_unexpected_error(monkeypatch) -> None:
    class FakeEngine:
        def infer(self, text: str) -> dict:
            del text
            return {
                "intent": "sync_terminal_time",
                "intent_confidence": 1.0,
                "slots": {"play_count": "一"},
                "missing_slots": [],
                "entities": {"play_count": ["一"]},
                "tokens": ["一", "次", "性"],
                "tag_ids": [9, 0, 0],
            }

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(
        api_public,
        "_execute_once_cancel_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())

    session = _auth_session()
    _set_scoped_pending(_pending_once_cancel(), session["token"])

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "一次性"}, headers={"X-Token": session["token"]})

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "当前网络不稳定，请重新发送。"
    assert data["output_speech"] == "当前网络不稳定，请重新发送。"
    assert data["intent"] == "cancel_schedule"
    assert data["action_log"] == []
    assert data["pending_action"] is not None
    assert data["pending_action"]["intent"] == "cancel_schedule"


def test_chat_api_pending_followup_overrides_fresh_nlu_intent_for_cancel_once(monkeypatch) -> None:
    class FakeEngine:
        def infer(self, text: str) -> dict:
            del text
            return {
                "intent": "sync_terminal_time",
                "intent_confidence": 0.62,
                "slots": {"play_count": "一"},
                "missing_slots": [],
                "entities": {"play_count": ["一"]},
                "tokens": ["一", "次", "性"],
                "tag_ids": [9, 0, 0],
            }

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())
    monkeypatch.setattr(
        api_public,
        "_execute_once_cancel_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": "cancel-1"},
            "已设置一次性取消,任务执行后将自动恢复。",
        ),
    )

    session = _auth_session("cancel-followup")
    _set_scoped_pending(_pending_once_cancel(), session["token"])

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "一次性"}, headers={"X-Token": session["token"]})

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "cancel_schedule"
    assert data["reply"] == "已设置一次性取消,任务执行后将自动恢复。"
    assert data["pending_action"] is None
    assert data["action_log"][0]["action"] == "cancel_schedule"


def test_session_scoped_pending_actions_do_not_leak_between_users(monkeypatch) -> None:
    class FakeEngine:
        def infer(self, text: str) -> dict:
            del text
            return {
                "intent": "sync_terminal_time",
                "intent_confidence": 0.5,
                "slots": {},
                "missing_slots": [],
                "entities": {},
                "tokens": [],
                "tag_ids": [],
            }

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())
    monkeypatch.setattr(
        api_public,
        "_execute_once_cancel_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": "cancel-a"},
            "已设置一次性取消,任务执行后将自动恢复。",
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_execute_once_migrate_action",
        lambda action, schedule, dry_run=False, diagnostics=None, diagnostic_id="": (
            {"id": "move-b", "shadow_task_ids": []},
            "已设置一次性挪动,原任务会在原时段静音并在目标时段播放临时任务。",
        ),
    )

    session_a = _auth_session("user-a")
    session_b = _auth_session("user-b")
    _set_scoped_pending(_pending_once_cancel(), session_a["token"])
    _set_scoped_pending(_pending_once_move(), session_b["token"])

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "一次性"}, headers={"X-Token": session_a["token"]})

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "cancel_schedule"
    assert data["reply"] == "已设置一次性取消,任务执行后将自动恢复。"
    assert api_public._get_pending_action(session_a["token"]) is None
    assert api_public._get_pending_action(session_b["token"]) is not None
    assert api_public._get_pending_action(session_b["token"])["intent"] == "move_schedule"


def test_chat_api_returns_200_when_apply_action_raises_http_502(monkeypatch) -> None:
    class FakeEngine:
        def infer(self, text: str) -> dict:
            del text
            return {
                "intent": "query_task",
                "intent_confidence": 1.0,
                "slots": {"source_time": "今天下午"},
                "missing_slots": [],
                "entities": {"source_time": ["今天下午"]},
                "tokens": [],
                "tag_ids": [],
            }

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())
    monkeypatch.setattr(
        assistant_chat,
        "apply_action",
        lambda text, result: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="Bad Gateway")),
    )

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "查看今天下午的任务"}, headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "当前网络不稳定，请重新发送。"
    assert data["output_speech"] == "当前网络不稳定，请重新发送。"
    assert data["action_log"] == []
    assert "Bad Gateway" not in data["reply"]


def test_chat_api_cancel_schedule_today_prompt_returns_missing_time_range_instead_of_500(monkeypatch) -> None:
    class FakeEngine:
        def infer(self, text: str) -> dict:
            assert text == "取消夏季作息今天的早读开始铃声"
            return {
                "intent": "cancel_schedule",
                "intent_confidence": 0.9999980926513672,
                "slots": {
                    "schedule_name": "夏季作息",
                    "task_name": "早读",
                    "schedule_name_matched": "春季作息",
                    "schedule_name_score": 0.75,
                    "task_name_matched": "早读开始铃",
                    "task_id": "77373",
                    "task_name_score": 0.9,
                },
                "missing_slots": [],
                "entities": {"schedule_name": ["夏季作息"], "task_name": ["早读"]},
                "tokens": ["取", "消", "夏", "季", "作", "息", "今", "天", "的", "早", "读", "开", "始", "铃", "声"],
                "tag_ids": [0, 0, 13, 14, 14, 14, 0, 0, 0, 17, 18, 0, 0, 0, 0],
                "output_speech": "已经帮您取消“夏季作息”里对应的任务了。",
                "dialog_state": "complete",
                "dialog_state_detail": "complete",
            }

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "取消夏季作息今天的早读开始铃声"},
            headers=_auth_headers("cancel-today-range"),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "cancel_schedule"
    assert "时间范围" in data["reply"]
    assert "比如" in data["reply"]
    assert data["output_speech"] == data["reply"]
    assert data["missing_slots"] == ["time_range_start", "time_range_end"]
    assert data["dialog_state_detail"] == "ask_missing_slot"
    assert data["action_log"] == []
    assert data["pending_action"] is None


def test_chat_api_returns_retry_when_engine_infer_raises_unexpected_error(monkeypatch) -> None:
    class FakeEngine:
        def infer(self, text: str) -> dict:
            del text
            raise RuntimeError("boom")

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "取消夏季作息今天的早读开始铃声"},
            headers=_auth_headers("infer-boom"),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "当前网络不稳定，请重新发送。"
    assert data["output_speech"] == "当前网络不稳定，请重新发送。"
    assert data["intent"] == ""
    assert data["missing_slots"] == []
    assert data["dialog_state_detail"] == "complete"
    assert data["action_log"] == []
    assert data["pending_action"] is None
