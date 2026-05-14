from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_move_schedule_confirm_reply_avoids_old_self_narration(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "morning-read",
                        "starttime": "07:00:00",
                        "startdate": "2026-10-01",
                        "enddate": "2026-10-01",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    api_public.PENDING_ACTION = None

    reply, state, logs = api_public._apply_move_schedule_intent(
        "move 2026-10-01 to 2026-10-02",
        {"source_time": "2026-10-01", "target_time": "2026-10-02"},
    )

    assert "请确认要一次性执行还是永久生效" in reply
    assert "我找到这些任务" not in reply
    assert "morning-read" in reply or "07:00" in reply
    assert state["missing_slots"] == []
    assert logs == []
    api_public.PENDING_ACTION = None


def test_create_schedule_success_reply_keeps_result_first(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_load_default_schedule_kind", lambda: "小学")
    monkeypatch.setattr(api_public, "_load_default_schedule_season", lambda: "夏季")
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        lambda text, schedule_kind, schedule_season: (
            schedule_kind,
            schedule_season,
            {"source_schedule_name": "标准模板"},
        ),
    )
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_load_phase1_local_schedule_template",
        lambda source_schedule_name: {"schedule_name": source_schedule_name, "tasks": []},
    )
    monkeypatch.setattr(
        api_public,
        "_build_phase1_local_schedule_from_template",
        lambda template_schedule, final_name, start_date, end_date: (
            {"schedule_name": final_name, "status": "启用", "tasks": []},
            0,
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda new_schedule_entry, *, sync_remote: deepcopy(new_schedule_entry),
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建春季作息",
        {"schedule_name": "春季作息"},
    )

    assert "春季作息" in reply
    assert "创建" in reply
    assert "小电已经" in reply
    assert reply.endswith("请问还有什么别的需求吗？")
    assert "我先帮您" not in reply
    assert "巡视机房" not in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1


def test_play_media_success_reply_uses_high_persona_and_followup(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {"zone_name": [], "terminal_name": [], "terminal_id": []}))
    monkeypatch.setattr(api_public, "_play_media_folder_exact_match", lambda slots, media_text, slot_key="media_name": ("m1", "国歌"))
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda *, media_ids, terminal_ids, volume, playtype, playlength, playpriority: "9001",
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(api_public, "_reply_preview_terminals_by_ids", lambda terminal_ids, limit=3: "高三一班")
    monkeypatch.setattr(
        api_public,
        "_build_action_log",
        lambda *args, **kwargs: {"action": "play_media", "details": kwargs.get("details", {})},
    )
    monkeypatch.setattr(api_public, "_store_recent_runtime_play_entry", lambda payload: None)

    reply, state, logs = api_public._apply_play_media_intent("播放国歌", {"media_name": "国歌", "terminal_name": "高三一班"})

    assert "国歌" in reply
    assert "高三一班" in reply
    assert "小电已经" in reply
    assert reply.endswith("请问还有什么别的需求吗？")
    assert state["missing_slots"] == []
    assert len(logs) == 1


def test_play_media_reply_keeps_followup_when_inline_details_exist(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_resolve_terminal_ids_for_play_media",
        lambda slots: (["101"], {"zone_name": ["未匹配分区"], "terminal_name": [], "terminal_id": []}),
    )
    monkeypatch.setattr(api_public, "_play_media_folder_exact_match", lambda slots, media_text, slot_key="media_name": ("m1", "国歌"))
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda *, media_ids, terminal_ids, volume, playtype, playlength, playpriority: "9001",
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, ["右一终端"]))
    monkeypatch.setattr(api_public, "_reply_preview_terminals_by_ids", lambda terminal_ids, limit=3: "高三一班")
    monkeypatch.setattr(
        api_public,
        "_build_action_log",
        lambda *args, **kwargs: {"action": "play_media", "details": kwargs.get("details", {})},
    )
    monkeypatch.setattr(api_public, "_store_recent_runtime_play_entry", lambda payload: None)

    reply, state, logs = api_public._apply_play_media_intent(
        "播放国歌",
        {"media_name": "国歌", "terminal_name": "高三一班", "zone_name": "教学楼"},
    )

    assert "国歌" in reply
    assert "高三一班" in reply
    assert "当前离线" in reply
    assert "未执行" in reply or "没有匹配上" in reply
    assert "\n" not in reply
    assert reply.endswith("请问还有什么别的需求吗？")
    assert state["missing_slots"] == []
    assert len(logs) == 1


def test_play_media_not_found_reply_is_clear_and_direct(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(api_public, "_play_media_folder_exact_match", lambda slots, media_text, slot_key="media_name": None)

    reply, state, logs = api_public._apply_play_media_intent(
        "播放校歌",
        {"media_name": "校歌"},
    )

    assert reply == '媒体库中未找到可即时点播的“校歌”。'
    assert "小电" not in reply
    assert "安排好了" not in reply
    assert state["missing_slots"] == []
    assert logs == []


def test_query_terminal_reply_avoids_old_self_narration(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: (["1", "2"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [
            {"id": "1", "name": "右一终端", "netstate": 1, "devicestate": 1, "taskstate": 0},
            {"id": "2", "name": "右二终端", "netstate": 0, "devicestate": 1, "taskstate": 1},
        ],
    )

    reply, state, logs = api_public._apply_query_terminal_intent("查询终端", {"zone_name": "教学楼"})

    assert "在线 1 个" in reply
    assert "离线 1 个" in reply
    assert reply.endswith("请问还有什么别的需求吗？")
    assert "这条我已经帮您查完了" not in reply
    assert "我已经查到" not in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1


def test_query_terminal_reply_keeps_followup_when_unresolved_exists(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_from_slots", lambda slots: (["1"], {"terminal_name": ["右三终端"]}))
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [
            {"id": "1", "name": "右一终端", "netstate": 1, "devicestate": 1, "taskstate": 0},
        ],
    )

    reply, state, logs = api_public._apply_query_terminal_intent("查询右一和右三", {"terminal_name": "右一终端"})

    assert "在线 1 个" in reply
    assert "以下对象没有匹配上" in reply
    assert "\n" not in reply
    assert reply.endswith("请问还有什么别的需求吗？")
    assert state["missing_slots"] == []
    assert len(logs) == 1


def test_adjust_volume_zone_fallback_reply_stays_direct(monkeypatch) -> None:
    remote_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_load_schedules_payload",
        lambda: {"schedules": [], "broadcasts": [], "livecasts": []},
    )
    monkeypatch.setattr(api_public, "_remote_zone_items", lambda: [{"id": "88", "zonename": "高中部"}])
    monkeypatch.setattr(api_public, "_zone_terminal_ids", lambda zone_id: ["101"] if str(zone_id) == "88" else [])
    monkeypatch.setattr(
        api_public,
        "_remote_terminalinfo_items",
        lambda: [{"id": "101", "name": "高中部走廊终端", "volume": 40}],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_set_terminal_volume",
        lambda terminal_id, volume: remote_calls.append((str(terminal_id), volume)),
    )

    reply, state, logs = api_public._apply_adjust_volume_intent(
        "将高中部音量增加20",
        {"task_name": "高中部", "volume": "音量增加20"},
    )

    assert "未找到任务“高中部”，已先按分区“高中部”" in reply
    assert "音量" in reply
    assert "请问还有什么别的需求吗？" in reply
    assert "\n" not in reply
    assert "我暂时没找到任务" not in reply
    assert state["missing_slots"] == []
    assert remote_calls == [("101", 60)]
    assert len(logs) == 1


def test_query_task_success_reply_keeps_result_and_preview(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "spring_schedule",
                "status": "0",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "anthem",
                        "starttime": "08:00:00",
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))

    reply, state, logs = api_public._apply_query_task_intent("query anthem", {"task_name": "anthem"})

    assert "1 条任务" in reply
    assert "anthem(08:00)" in reply
    assert reply.endswith("请问还有什么别的需求吗？")
    assert "我已经查到" not in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
