from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def _schedule_payload(tasks: list[dict]) -> dict:
    return {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "status": "0",
                "tasks": deepcopy(tasks),
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }


def _infer_result(intent: str, slots: dict) -> dict:
    return {
        "intent": intent,
        "intent_confidence": 0.99,
        "slots": deepcopy(slots),
        "missing_slots": [],
        "entities": {},
        "tokens": [],
        "tag_ids": [],
    }


def _auth_headers() -> dict[str, str]:
    session = api_public._create_local_session("remote-test-token", "tester", "test")
    return {"X-Token": session["token"]}


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch):
    original_logs = deepcopy(api_public.DATA_STORE["assistant_command_logs"])
    api_public._store_set(
        "assistant_command_logs",
        api_public._normalize_assistant_command_logs_payload({"items": []}),
    )
    api_public._clear_pending_action()
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_write_cache_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    yield
    api_public.DATA_STORE["assistant_command_logs"] = original_logs
    api_public._clear_pending_action()


def test_apply_move_schedule_ignores_implicit_task_id_from_slots(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "77919",
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_move_schedule_intent(
        "把春季作息里周四的早读开始铃挪到周六去",
        {
            "schedule_name": "春季作息",
            "source_time": "周四",
            "target_time": "周六",
            "task_name": "早读",
            "task_id": "77889",
            "task_name_matched": "早读开始铃",
            "task_name_score": 0.9,
        },
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert state["missing_slots"] == []
    assert logs == []
    pending = api_public._get_pending_action()
    assert pending is not None
    assert pending["intent"] == "move_schedule"
    assert pending["task_ids"] == ["77919"]
    assert pending["task_id"] == ""


def test_apply_move_schedule_respects_explicit_task_id_from_text(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "77919",
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_move_schedule_intent(
        "把春季作息里周四的任务77889挪到周六去",
        {
            "schedule_name": "春季作息",
            "source_time": "周四",
            "target_time": "周六",
            "task_id": "77889",
        },
    )

    assert reply == "在“春季作息”未找到匹配“周四”的任务。"
    assert logs == []
    diagnostics = state["diagnostics"]
    assert diagnostics[0]["candidate_count_after_time_match"] == 1
    assert diagnostics[0]["candidate_count_after_task_name_match"] == 0
    assert diagnostics[0]["strict_task_id_applied"] is True
    assert diagnostics[0]["strict_task_id_value"] == "77889"
    assert diagnostics[0]["task_name_filter_applied"] is False


def test_chat_api_move_ignores_implicit_task_id_from_slots(monkeypatch) -> None:
    payload = _schedule_payload(
        [
            {
                "taskid": "77919",
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
            }
        ]
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(
        api_public.ENGINE,
        "infer",
        lambda text: _infer_result(
            "move_schedule",
            {
                "schedule_name": "春季作息",
                "source_time": "周四",
                "end_time": "周六",
                "task_name": "早读",
                "task_id": "77889",
                "task_name_matched": "早读开始铃",
                "task_name_score": 0.9,
            },
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/assistant/chat",
            json={"text": "把春季作息里周四的早读开始铃挪到周六去"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "move_schedule"
    assert "请确认要一次性执行还是永久生效" in data["reply"]
    assert data["pending_action"]["intent"] == "move_schedule"
    assert data["pending_action"]["task_ids"] == ["77919"]
    assert data["pending_action"]["task_id"] == ""


def test_phase1_effective_strict_task_id_keeps_confirmed_choice() -> None:
    assert (
        api_public._phase1_effective_strict_task_id(
            "move_schedule",
            "把春季作息里周四的早读开始铃挪到周六去",
            {"task_id": "77919", "task_id_confirmed": True, "task_id_source": "confirmed_choice"},
        )
        == "77919"
    )


def test_build_recurring_risk_prompt_omits_window_preview() -> None:
    reply = api_public._build_recurring_risk_prompt(
        "找到这些任务：07:50:00 早读开始铃。请确认要一次性执行还是永久生效？",
        14,
        "早读开始铃: 2026-01-18~2039-01-31 -> 2026-01-19~2039-02-01",
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert "长期循环任务" in reply
    assert "窗口变化示例" not in reply
