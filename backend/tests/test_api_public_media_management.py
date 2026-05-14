from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_play_media_missing_media_name_returns_missing_slot() -> None:
    reply, state, logs = api_public._apply_play_media_intent("play", {})

    assert isinstance(reply, str)
    assert state["missing_slots"] == ["media_name"]
    assert logs == []


def test_play_media_requires_target_terminals(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_resolve_terminal_ids_for_play_media",
        lambda slots: ([], {"zone_name": ["zone_a"]}),
    )

    reply, state, logs = api_public._apply_play_media_intent("play old_song", {"media_name": "old_song"})

    assert isinstance(reply, str)
    assert state["missing_slots"] == ["zone_name/terminal_id/terminal_name"]
    assert logs == []


def test_play_media_success_builds_temp_task_and_action_log(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_resolve_terminal_ids_for_play_media",
        lambda slots: (["101", "102"], {"terminal_name": ["unknown_terminal"]}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "morning_tune", "mediaid": "11"}],
    )

    def fake_add_temp_task(**kwargs):
        captured.update(kwargs)
        return "998"

    monkeypatch.setattr(api_public, "_remote_add_temp_task", fake_add_temp_task)
    monkeypatch.setattr(
        api_public,
        "_check_terminal_online_status",
        lambda terminal_ids: (["101"], ["terminal-102"]),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_lookup",
        lambda: {
            "101": {"name": "terminal-101"},
            "102": {"name": "terminal-102"},
        },
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "play morning_tune",
        {
            "media_name": "morning_tune",
            "play_duration": "5 min",
            "volume": "80",
        },
    )

    assert isinstance(reply, str)
    assert state["missing_slots"] == []
    assert captured == {
        "media_ids": ["11"],
        "terminal_ids": ["101", "102"],
        "volume": 80,
        "playtype": 1,
        "playlength": 300,
        "playpriority": 10,
    }

    assert len(logs) == 1
    log = logs[0]
    assert log["action"] == "play_media"
    assert log["task_ids"] == ["998"]
    assert log["mode"] == "runtime"
    assert log["details"]["media_name"] == "morning_tune"
    assert log["details"]["media_id"] == "11"
    assert log["details"]["runtime_scope"] == "temp_task"
    assert log["details"]["task_id"] == "998"
    assert log["details"]["source"] == "runtime_play"
    assert log["details"]["terminal_ids"] == ["101", "102"]
    assert log["details"]["terminal_names"] == ["terminal-101", "terminal-102"]
    assert log["details"]["terminal_count"] == 2
    assert log["details"]["timelength"] == 5
    assert log["details"]["timelengthtype"] == 1
    assert log["details"]["playtype"] == 1
    assert log["details"]["playlength"] == 300
    assert log["details"]["volume"] == 80
    assert log["details"]["unresolved"] == {"terminal_name": ["unknown_terminal"]}


def test_play_media_media_directory_failure_returns_structured_details(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_play_media_folder_exact_match",
        lambda *args, **kwargs: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="folder down")),
    )

    reply, state, logs = api_public._apply_play_media_intent("play bell", {"media_name": "bell"})

    assert "目录" in reply
    assert "folder down" not in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["failure_reason"] == "folder down"
    assert state["diagnostics"][0]["user_reason"] == "即时点播媒体目录暂时不可用"
    assert state["diagnostics"][0]["retryable"] is True
    assert len(logs) == 1
    assert logs[0]["details"]["failure_reason"] == "folder down"
    assert logs[0]["details"]["user_reason"] == "即时点播媒体目录暂时不可用"
    assert logs[0]["details"]["retryable"] is True


def test_play_media_remote_dispatch_failure_returns_structured_details(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "bell", "mediaid": "11"}],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: (_ for _ in ()).throw(api_public.HTTPException(status_code=502, detail="dispatch down")),
    )

    reply, state, logs = api_public._apply_play_media_intent("play bell", {"media_name": "bell"})

    assert "播放" in reply
    assert "dispatch down" not in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["failure_reason"] == "dispatch down"
    assert state["diagnostics"][0]["user_reason"] == "即时播放指令没有发出"
    assert state["diagnostics"][0]["retryable"] is True
    assert len(logs) == 1
    assert logs[0]["details"]["failure_reason"] == "dispatch down"
    assert logs[0]["details"]["user_reason"] == "即时播放指令没有发出"
    assert logs[0]["details"]["retryable"] is True


def test_play_media_seconds_duration_maps_to_playlength_seconds(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "bell", "mediaid": "11"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "终端101"}})
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "播放 bell 30秒",
        {
            "media_name": "bell",
            "play_duration": "30秒",
        },
    )

    assert "30秒" in reply
    assert state["missing_slots"] == []
    assert captured["playtype"] == 1
    assert captured["playlength"] == 30
    assert logs[0]["details"]["playtype"] == 1
    assert logs[0]["details"]["playlength"] == 30


def test_play_media_seconds_duration_uses_text_unit_when_slot_only_has_number(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "bell", "mediaid": "11"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "终端101"}})
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "播放 bell 30秒",
        {
            "media_name": "bell",
            "play_duration": "30",
        },
    )

    assert "30秒" in reply
    assert state["missing_slots"] == []
    assert captured["playtype"] == 1
    assert captured["playlength"] == 30
    assert logs[0]["details"]["playlength"] == 30


def test_play_media_compound_duration_maps_to_total_seconds(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "bell", "mediaid": "11"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "终端101"}})
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "播放 bell 1分30秒",
        {
            "media_name": "bell",
            "play_duration": "1分30秒",
        },
    )

    assert "1分30秒" in reply
    assert state["missing_slots"] == []
    assert captured["playtype"] == 1
    assert captured["playlength"] == 90
    assert logs[0]["details"]["playlength"] == 90


def test_play_media_count_mode_maps_to_playtype_two(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "bell", "mediaid": "11"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "终端101"}})
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "播放 bell 3次",
        {
            "media_name": "bell",
            "play_count": "3次",
        },
    )

    assert "3次" in reply
    assert state["missing_slots"] == []
    assert captured["playtype"] == 2
    assert captured["playlength"] == 3
    assert logs[0]["details"]["playtype"] == 2
    assert logs[0]["details"]["playlength"] == 3


def test_play_media_count_mode_accepts_chinese_numerals(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "bell", "mediaid": "11"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "终端101"}})
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "播放 bell 三次",
        {
            "media_name": "bell",
            "play_count": "三次",
        },
    )

    assert "三次" in reply
    assert state["missing_slots"] == []
    assert captured["playtype"] == 2
    assert captured["playlength"] == 3
    assert logs[0]["details"]["playtype"] == 2
    assert logs[0]["details"]["playlength"] == 3


    snapshot_task = committed["snapshot_payload"]["schedules"][0]["tasks"][0]
    assert snapshot_task["mediaid"] == "101"
    assert snapshot_task["medianame"] == "old_song"

    updated_schedule_task = committed["new_payload"]["schedules"][0]["tasks"][0]
    assert updated_schedule_task["mediaid"] == 202
    assert updated_schedule_task["medianame"] == "new_song"
    assert updated_schedule_task["audio"] == "new_song"

    untouched_task = committed["new_payload"]["schedules"][0]["tasks"][1]
    assert untouched_task["mediaid"] == "999"
    assert untouched_task["medianame"] == "other_song"
    assert untouched_task["audio"] == "keep"

    updated_broadcast = committed["new_payload"]["broadcasts"][0]
    assert updated_broadcast["mediaid"] == 202
    assert updated_broadcast["medianame"] == "new_song"
    assert updated_broadcast["audio"] == "new_song"

    untouched_livecast = committed["new_payload"]["livecasts"][0]
    assert untouched_livecast["taskname"] == "后采集器"
    assert untouched_livecast["medianame"] == "后采集器"
    assert untouched_livecast["audio"] == ""


def test_safe_media_map_falls_back_to_local_store_when_remote_lookup_fails(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_remote_media_map",
        lambda: (_ for _ in ()).throw(HTTPException(status_code=502, detail="remote media down")),
    )
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: [{"name": "morning_tune", "mediaid": "11"}] if key == "all_audio" else None,
    )

    assert api_public._safe_media_map() == {"morning_tune": "11"}


def test_safe_media_map_falls_back_to_local_store_when_remote_lookup_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: [{"name": "morning_tune", "mediaid": "11"}] if key == "all_audio" else None,
    )

    assert api_public._safe_media_map() == {"morning_tune": "11"}


def test_play_media_allows_zero_volume(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "morning_tune", "mediaid": "11"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "play morning_tune",
        {"media_name": "morning_tune", "volume": "0"},
    )

    assert "播放" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["volume"] == 0
    assert captured["volume"] == 0


def test_play_media_drops_terminal_id_caused_by_volume_number(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"接待室喝茶": "35"})
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "金志文-远走高飞", "mediaid": "987"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_play_media_intent(
        "在接待室喝茶播放远走高飞，音量25",
        {
            "terminal_name": "接待室喝茶",
            "terminal_matched_id": 35,
            "terminal_id": "25",
            "media_name": "远走高飞",
            "media_name_matched": "金志文-远走高飞",
            "media_name_id": "987",
            "volume": "25",
        },
    )

    assert "接待室喝茶" in reply
    assert "播放" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["terminal_count"] == 1
    assert captured["terminal_ids"] == ["35"]
    assert api_public.PENDING_ACTION is None


def test_play_media_keeps_explicit_terminal_id_when_volume_matches(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "金志文-远走高飞", "mediaid": "987"}],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "终端25播放远走高飞，音量25",
        {
            "terminal_id": "25",
            "media_name": "远走高飞",
            "media_name_matched": "金志文-远走高飞",
            "media_name_id": "987",
            "volume": "25",
        },
    )

    assert "播放" in reply
    assert ("终端25" in reply) or ("操场功放" in reply)
    assert state["missing_slots"] == []
    assert logs[0]["details"]["terminal_count"] == 1
    assert captured["terminal_ids"] == ["25"]


def test_play_media_uses_matched_media_id_without_disambiguation(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["35"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [
            {"folderid": 3, "name": "金志文-远走高飞", "mediaid": "987"},
            {"folderid": 3, "name": "张三-远走高飞", "mediaid": "654"},
        ],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    api_public.PENDING_ACTION = None
    reply, state, logs = api_public._apply_play_media_intent(
        "播放远走高飞",
        {
            "terminal_name": "接待室喝茶",
            "media_name": "远走高飞",
            "media_name_matched": "金志文-远走高飞",
            "media_name_id": "987",
        },
    )

    assert "金志文-远走高飞" in reply
    assert "播放" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["media_name"] == "金志文-远走高飞"
    assert captured["media_ids"] == ["987"]
    assert api_public.PENDING_ACTION is None


def test_strict_resolve_media_match_single_loose_candidate_resolves_without_pending() -> None:
    api_public.PENDING_ACTION = None

    match, pending_reply = api_public._strict_resolve_media_match(
        "play_media",
        "播放远走高飞",
        {"media_name": "远走高飞"},
        "远走高飞",
        {"金志文-远走高飞": "987"},
        slot_key="media_name",
    )

    assert match == ("987", "金志文-远走高飞")
    assert pending_reply is None
    assert api_public.PENDING_ACTION is None


def test_play_media_zone_only_partial_resolution_fails(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_resolve_terminal_ids_for_play_media",
        lambda slots: (["101"], {"zone_name": ["高一教学楼"]}),
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "在高一教学楼播放 morning_tune",
        {"media_name": "morning_tune", "zone_name": "高一教学楼"},
    )

    assert "未执行即时媒体播放" in reply
    assert "以下分区未匹配" in reply
    assert state["missing_slots"] == []
    assert logs == []


def test_play_media_rejects_media_outside_folder_3(monkeypatch) -> None:
    add_temp_called = {"called": False}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "morning_tune", "mediaid": "11"}],
    )
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: {"data": [{"folderid": 8, "name": "outside_song", "mediaid": "99"}]} if key == "all_audio" else None,
    )
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: add_temp_called.update({"called": True}) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "play outside_song",
        {"media_name": "outside_song"},
    )

    assert reply == '媒体库中未找到可即时点播的“outside_song”。'
    assert state["missing_slots"] == []
    assert logs == []
    assert add_temp_called["called"] is False


def test_play_media_rejects_matched_media_id_outside_folder_3(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [{"folderid": 3, "name": "folder_song", "mediaid": "11"}],
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "play target_song",
        {"media_name": "target_song", "media_name_matched": "target_song", "media_name_id": "99"},
    )

    assert reply == '媒体库中未找到可即时点播的“target_song”。'
    assert state["missing_slots"] == []
    assert logs == []


def test_remote_mediainfo_payload_caches_by_folderid(monkeypatch) -> None:
    api_public._invalidate_media_runtime_caches()
    request_paths: list[str] = []

    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: request_paths.append(path) or {"data": [{"name": path, "mediaid": "1"}]},
    )

    payload_folder_first = api_public._remote_mediainfo_payload(folder_id=3)
    payload_folder_second = api_public._remote_mediainfo_payload(folder_id=3)
    payload_all_first = api_public._remote_mediainfo_payload()
    payload_all_second = api_public._remote_mediainfo_payload()

    assert payload_folder_first == payload_folder_second
    assert payload_all_first == payload_all_second
    assert request_paths == ["/terminal/mediainfo/3", "/terminal/mediainfo"]


def test_get_all_audio_filters_by_folderid(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    api_public._store_set(
        "all_audio",
        {
            "data": [
                {"folderid": 3, "name": "folder_song", "mediaid": "11"},
                {"folderid": 8, "name": "other_song", "mediaid": "22"},
            ]
        },
    )

    payload_all = api_public.get_all_audio()
    payload_folder = api_public.get_all_audio(folderid=3)

    assert payload_all["data"] == [
        {"folderid": 3, "name": "folder_song", "mediaid": "11"},
        {"folderid": 8, "name": "other_song", "mediaid": "22"},
    ]
    assert payload_folder["data"] == [{"folderid": 3, "name": "folder_song", "mediaid": "11"}]


def test_play_media_numeric_name_prefers_exact_name_before_id(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots: (["101"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_mediainfo_items",
        lambda folder_id=None: [
            {"folderid": 3, "name": "123", "mediaid": "77"},
            {"folderid": 3, "name": "other_song", "mediaid": "123"},
        ],
    )
    monkeypatch.setattr(api_public, "_check_terminal_online_status", lambda terminal_ids: (terminal_ids, []))
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {"101": {"name": "终端101"}})
    monkeypatch.setattr(
        api_public,
        "_remote_add_temp_task",
        lambda **kwargs: captured.update(kwargs) or "998",
    )

    reply, state, logs = api_public._apply_play_media_intent(
        "播放123",
        {"media_name": "123"},
    )

    assert "123" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["media_id"] == "77"
    assert captured["media_ids"] == ["77"]


def test_get_runtime_play_tasks_merges_remote_rows_with_recent_cache(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    api_public._RUNTIME_PLAY_LISTING_MODE_LOGGED = False

    monkeypatch.setattr(
        api_public,
        "_fetch_remote_runtime_play_rows",
        lambda: [
            {
                "task_id": "200",
                "id": "200",
                "task_name": "remote-play",
                "media_id": "20",
                "media_ids": ["20"],
                "media_name": "remote-play",
                "media_names": ["remote-play"],
                "terminal_ids": ["2"],
                "terminal_names": ["终端2"],
                "volume": 60,
                "playtype": 1,
                "playlength": 120,
                "status": "执行中",
                "created_at": "2026-04-01 10:00:00",
                "source": "runtime_play",
            }
        ],
    )
    api_public._store_recent_runtime_play_entry(
        {
            "task_id": "100",
            "id": "100",
            "task_name": "cached-play",
            "media_id": "10",
            "media_ids": ["10"],
            "media_name": "cached-play",
            "media_names": ["cached-play"],
            "terminal_ids": ["1"],
            "terminal_names": ["终端1"],
            "volume": 50,
            "playtype": 1,
            "playlength": 60,
            "status": "执行中",
            "created_at": "2026-04-01 09:59:00",
            "source": "runtime_play",
        }
    )

    payload = api_public.get_runtime_play_tasks(force=True)

    assert [row["task_id"] for row in payload["runtime_play_tasks"]] == ["200", "100"]
    assert payload["runtime_play_tasks"][0]["media_name"] == "remote-play"
    assert payload["runtime_play_tasks"][1]["media_name"] == "cached-play"


def test_get_runtime_play_tasks_uses_recent_cache_when_remote_listing_paths_unconfigured(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    api_public._RUNTIME_PLAY_LISTING_MODE_LOGGED = False
    monkeypatch.setattr(api_public, "REMOTE_TEMP_TASK_PATHS", [])
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)

    info_logs: list[tuple[str, object]] = []
    warning_logs: list[tuple[str, object]] = []
    monkeypatch.setattr(api_public.LOGGER, "info", lambda message, payload: info_logs.append((message, payload)))
    monkeypatch.setattr(api_public.LOGGER, "warning", lambda *args, **kwargs: warning_logs.append((args, kwargs)))

    api_public._store_recent_runtime_play_entry(
        {
            "task_id": "150",
            "id": "150",
            "task_name": "cached-only",
            "media_id": "15",
            "media_ids": ["15"],
            "media_name": "cached-only",
            "media_names": ["cached-only"],
            "terminal_ids": ["5"],
            "terminal_names": ["终端5"],
            "volume": 55,
            "playtype": 1,
            "playlength": 90,
            "status": "执行中",
            "created_at": "2026-04-01 09:58:00",
            "source": "runtime_play",
        }
    )
    monkeypatch.setattr(api_public, "_fetch_remote_task_state", lambda task_id, task_type: {"state": 0})

    payload = api_public.get_runtime_play_tasks(force=True)

    assert [row["task_id"] for row in payload["runtime_play_tasks"]] == ["150"]
    assert payload["runtime_play_tasks"][0]["status"] == "执行中"
    assert info_logs[-1][0] == "remote temp task listing unsupported; using recent cache fallback %s"
    assert not warning_logs


def test_fetch_remote_runtime_play_rows_degrades_404_listing_paths_to_empty(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    api_public._RUNTIME_PLAY_LISTING_MODE_LOGGED = False
    monkeypatch.setattr(api_public, "REMOTE_TEMP_TASK_PATHS", ["/task/temptask", "/task/temptaskinfo"])
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda folder_id=None: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})

    calls: list[str] = []
    info_logs: list[tuple[str, object]] = []
    monkeypatch.setattr(api_public.LOGGER, "info", lambda message, payload: info_logs.append((message, payload)))

    def fake_remote_request(method, path, **kwargs):
        calls.append(path)
        raise api_public.HTTPException(status_code=404, detail="missing")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    rows = api_public._fetch_remote_runtime_play_rows()

    assert rows == []
    assert calls == ["/task/temptask", "/task/temptaskinfo"]
    assert info_logs[-1][0] == "remote temp task listing unavailable; using recent cache fallback %s"


def test_fetch_remote_runtime_play_rows_preserves_remote_enumeration_when_paths_configured(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    api_public._RUNTIME_PLAY_LISTING_MODE_LOGGED = False
    monkeypatch.setattr(api_public, "REMOTE_TEMP_TASK_PATHS", ["/task/runtime-list"])
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda folder_id=None: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_runtime_play_items_from_payload", lambda payload: payload.get("data", []))
    monkeypatch.setattr(
        api_public,
        "_map_runtime_play_item",
        lambda item, **kwargs: {
            "task_id": str(item.get("id")),
            "id": str(item.get("id")),
            "task_name": str(item.get("name") or ""),
            "media_name": str(item.get("name") or ""),
            "terminal_ids": ["7"],
            "terminal_names": ["终端7"],
            "status": "执行中",
        },
    )

    calls: list[str] = []

    def fake_remote_request(method, path, **kwargs):
        calls.append(path)
        return {"data": [{"id": 501, "name": "remote-runtime"}]}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    rows = api_public._fetch_remote_runtime_play_rows()

    assert calls == ["/task/runtime-list"]
    assert rows == [
        {
            "task_id": "501",
            "id": "501",
            "task_name": "remote-runtime",
            "media_name": "remote-runtime",
            "terminal_ids": ["7"],
            "terminal_names": ["终端7"],
            "status": "执行中",
        }
    ]


def test_fetch_remote_task_state_uses_gettasktatus_path(monkeypatch) -> None:
    captured: dict = {}

    def fake_remote_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {"state": 0}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    payload = api_public._fetch_remote_task_state(12345, 2)

    assert payload == {"state": 0}
    assert captured["method"] == "POST"
    assert captured["path"] == "/task/gettasktatus"
    assert captured["kwargs"]["json_body"] == {"taskid": 12345, "tasktype": 2}


def test_get_runtime_play_tasks_marks_stopped_rows_from_remote_state(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    api_public._RUNTIME_PLAY_LISTING_MODE_LOGGED = False
    api_public._store_recent_runtime_play_entry(
        {
            "task_id": "300",
            "id": "300",
            "task_name": "cached-play",
            "media_id": "30",
            "media_ids": ["30"],
            "media_name": "cached-play",
            "media_names": ["cached-play"],
            "terminal_ids": ["3"],
            "terminal_names": ["终端3"],
            "volume": 50,
            "playtype": 1,
            "playlength": 60,
            "status": "执行中",
            "remote_state": 0,
            "created_at": "2026-04-01 10:10:00",
            "source": "runtime_play",
        }
    )
    monkeypatch.setattr(
        api_public,
        "_fetch_remote_runtime_play_rows",
        lambda: [
            {
                "task_id": "300",
                "id": "300",
                "task_name": "cached-play",
                "media_id": "30",
                "media_ids": ["30"],
                "media_name": "cached-play",
                "media_names": ["cached-play"],
                "terminal_ids": ["3"],
                "terminal_names": ["终端3"],
                "volume": 50,
                "playtype": 1,
                "playlength": 60,
                "status": "执行中",
                "created_at": "2026-04-01 10:10:00",
                "source": "runtime_play",
            }
        ],
    )
    monkeypatch.setattr(api_public, "_fetch_remote_task_state", lambda task_id, task_type: {"state": -1})

    payload = api_public.get_runtime_play_tasks(force=True)

    row = payload["runtime_play_tasks"][0]
    assert row["task_id"] == "300"
    assert row["remote_state"] == -1
    assert row["status"] == "停止"
    recent = api_public._recent_runtime_play_entries()[0]
    assert recent["task_id"] == "300"
    assert recent["remote_state"] == -1
    assert recent["status"] == "停止"


def test_get_runtime_play_tasks_degrades_unknown_remote_state_to_pending(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    api_public._RUNTIME_PLAY_LISTING_MODE_LOGGED = False
    api_public._store_recent_runtime_play_entry(
        {
            "task_id": "301",
            "id": "301",
            "task_name": "cached-play",
            "media_id": "31",
            "media_ids": ["31"],
            "media_name": "cached-play",
            "media_names": ["cached-play"],
            "terminal_ids": ["3"],
            "terminal_names": ["终端3"],
            "volume": 50,
            "playtype": 1,
            "playlength": 60,
            "status": "执行中",
            "remote_state": 0,
            "created_at": "2026-04-01 10:11:00",
            "source": "runtime_play",
        }
    )
    monkeypatch.setattr(
        api_public,
        "_fetch_remote_runtime_play_rows",
        lambda: [
            {
                "task_id": "301",
                "id": "301",
                "task_name": "cached-play",
                "media_id": "31",
                "media_ids": ["31"],
                "media_name": "cached-play",
                "media_names": ["cached-play"],
                "terminal_ids": ["3"],
                "terminal_names": ["终端3"],
                "volume": 50,
                "playtype": 1,
                "playlength": 60,
                "status": "执行中",
                "created_at": "2026-04-01 10:11:00",
                "source": "runtime_play",
            }
        ],
    )
    monkeypatch.setattr(api_public, "_fetch_remote_task_state", lambda task_id, task_type: (_ for _ in ()).throw(
        api_public.HTTPException(status_code=502, detail="state down")
    ))

    payload = api_public.get_runtime_play_tasks(force=True)

    row = payload["runtime_play_tasks"][0]
    assert row["task_id"] == "301"
    assert row["remote_state"] == ""
    assert row["status"] == "待确认"
    recent = api_public._recent_runtime_play_entries()[0]
    assert recent["task_id"] == "301"
    assert recent["remote_state"] == ""
    assert recent["status"] == "待确认"


def test_stop_runtime_play_tasks_updates_recent_cache(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    api_public._RUNTIME_PLAY_LISTING_MODE_LOGGED = False
    api_public._store_recent_runtime_play_entry(
        {
            "task_id": "400",
            "id": "400",
            "task_name": "stop-me",
            "media_id": "40",
            "media_ids": ["40"],
            "media_name": "stop-me",
            "media_names": ["stop-me"],
            "terminal_ids": ["4"],
            "terminal_names": ["终端4"],
            "volume": 50,
            "playtype": 1,
            "playlength": 60,
            "status": "执行中",
            "remote_state": 0,
            "created_at": "2026-04-01 10:20:00",
            "source": "runtime_play",
        }
    )
    monkeypatch.setattr(api_public, "_remote_stop_temp_tasks", lambda task_ids: list(task_ids))
    monkeypatch.setattr(api_public, "_load_runtime_play_rows", lambda force=False: api_public._recent_runtime_play_entries())

    request = type("RuntimePlayStopRequest", (), {"task_ids": ["400"]})()

    payload = api_public.stop_runtime_play_tasks(request)

    assert payload["stopped_ids"] == ["400"]
    assert payload["runtime_play_tasks"][0]["task_id"] == "400"
    assert payload["runtime_play_tasks"][0]["remote_state"] == -1
    assert payload["runtime_play_tasks"][0]["status"] == "停止"
    recent = api_public._recent_runtime_play_entries()[0]
    assert recent["task_id"] == "400"
    assert recent["remote_state"] == -1
    assert recent["status"] == "停止"


def test_load_remote_auto_sync_seconds_defaults_to_180(monkeypatch) -> None:
    monkeypatch.delenv("REMOTE_AUTO_SYNC_SECONDS", raising=False)
    assert api_public._load_remote_auto_sync_seconds() == 180.0


def test_load_remote_auto_sync_seconds_accepts_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("REMOTE_AUTO_SYNC_SECONDS", "45")
    assert api_public._load_remote_auto_sync_seconds() == 45.0


def test_startup_load_data_runs_initial_sync_and_starts_auto_sync_thread(monkeypatch) -> None:
    captured: dict = {"started": False}
    calls: list = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            captured["target"] = target
            captured["daemon"] = daemon
            captured["thread"] = self
            self.started = False

        def start(self):
            captured["started"] = True
            self.started = True

        def is_alive(self):
            return self.started

    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", False)
    monkeypatch.setattr(api_public, "AUTO_SYNC_THREAD_STARTED", False)
    monkeypatch.setattr(api_public, "AUTO_SYNC_THREAD", None)
    monkeypatch.setattr(api_public, "AUTO_SYNC_STOP_EVENT", api_public.threading.Event())
    monkeypatch.setattr(api_public, "_init_data_store", lambda: calls.append("init"))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_sync_remote_data", lambda force=True: calls.append(("sync", force)) or {})
    monkeypatch.setattr(api_public.threading, "Thread", FakeThread)
    api_public._reset_remote_sync_status()

    api_public._startup_load_data()

    assert calls == ["init", ("sync", True)]
    assert captured["daemon"] is True
    assert captured["started"] is True
    assert callable(captured["target"])
    snapshot = api_public._remote_sync_status_snapshot()
    assert snapshot["thread_started"] is True
    assert snapshot["last_success_at"]
    assert snapshot["last_error"] == ""


def test_startup_load_data_logs_sync_failure_without_blocking_thread_start(monkeypatch) -> None:
    captured: dict = {"started": False}
    warnings: list[str] = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            captured["target"] = target
            captured["daemon"] = daemon
            self.started = False

        def start(self):
            captured["started"] = True
            self.started = True

        def is_alive(self):
            return self.started

    def fake_warning(message, *args):
        text = str(message)
        if args:
            text = text % args
        warnings.append(text)

    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", False)
    monkeypatch.setattr(api_public, "AUTO_SYNC_THREAD_STARTED", False)
    monkeypatch.setattr(api_public, "AUTO_SYNC_THREAD", None)
    monkeypatch.setattr(api_public, "AUTO_SYNC_STOP_EVENT", api_public.threading.Event())
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_sync_remote_data",
        lambda force=True: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(api_public.threading, "Thread", FakeThread)
    monkeypatch.setattr(api_public.LOGGER, "warning", fake_warning)
    api_public._reset_remote_sync_status()

    api_public._startup_load_data()

    assert captured["started"] is True
    assert any("Startup remote sync failed" in item for item in warnings)
    snapshot = api_public._remote_sync_status_snapshot()
    assert "boom" in snapshot["last_error"]
    assert snapshot["consecutive_failures"] == 1


def test_stop_remote_auto_sync_thread_requests_stop_and_clears_started_state(monkeypatch) -> None:
    class FakeThread:
        def __init__(self):
            self.started = True
            self.join_calls = []

        def is_alive(self):
            return self.started

        def join(self, timeout=None):
            self.join_calls.append(timeout)
            self.started = False

    stop_event = api_public.threading.Event()
    fake_thread = FakeThread()

    monkeypatch.setattr(api_public, "AUTO_SYNC_THREAD_STARTED", True)
    monkeypatch.setattr(api_public, "AUTO_SYNC_THREAD", fake_thread)
    monkeypatch.setattr(api_public, "AUTO_SYNC_STOP_EVENT", stop_event)

    api_public._stop_remote_auto_sync_thread(join_timeout=0.25)

    assert stop_event.is_set() is True
    assert fake_thread.join_calls == [0.25]
    assert api_public.AUTO_SYNC_THREAD_STARTED is False
    assert api_public.AUTO_SYNC_THREAD is None



def test_replace_media_in_task_with_only_task_name_requires_schedule_when_multiple_schedules_match(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "S1",
                "tasks": [{"taskid": "1", "taskname": "共同任务", "mediaid": "101", "medianame": "old", "audio": "old"}],
            },
            {
                "schedule_name": "S2",
                "tasks": [{"taskid": "2", "taskname": "共同任务", "mediaid": "101", "medianame": "old", "audio": "old"}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    committed = {"called": False}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_media_map_for_replace", lambda: {"old": "101", "new": "202"})
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda *args, **kwargs: committed.update({"called": True}),
    )

    reply, state, logs = api_public._apply_replace_media_in_task_intent(
        "把共同任务里的old换成new",
        {"task_name": "共同任务", "media_name": "old", "new_media_name": "new"},
    )

    assert '找到了多个可能的任务' in reply
    assert state["missing_slots"] == []
    assert logs == []
    assert committed["called"] is False


def test_replace_media_in_task_with_only_task_name_updates_single_matching_schedule(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "S1",
                "tasks": [{"taskid": "1", "taskname": "共同任务", "mediaid": "101", "medianame": "old", "audio": "old"}],
            },
            {
                "schedule_name": "S2",
                "tasks": [{"taskid": "2", "taskname": "别的任务", "mediaid": "101", "medianame": "old", "audio": "old"}],
            },
        ],
        "broadcasts": [],
        "livecasts": [],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_media_map_for_replace", lambda: {"old": "101", "new": "202"})
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda new_payload, snapshot, **kwargs: committed.update({"payload": deepcopy(new_payload), "kwargs": kwargs}),
    )

    reply, state, logs = api_public._apply_replace_media_in_task_intent(
        "把共同任务里的old换成new",
        {"task_name": "共同任务", "media_name": "old", "new_media_name": "new"},
    )

    assert "共同任务" in reply
    assert "替换" in reply
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "replace_media_in_task"
    assert committed["payload"]["schedules"][0]["tasks"][0]["mediaid"] == 202
    assert committed["payload"]["schedules"][1]["tasks"][0]["mediaid"] == "101"


def test_replace_media_in_task_does_not_touch_livecasts(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "S1",
                "tasks": [{"taskid": "1", "taskname": "共同任务", "mediaid": "101", "medianame": "old", "audio": "old"}],
            }
        ],
        "broadcasts": [],
        "livecasts": [
            {"taskid": "2", "taskname": "共同任务", "medianame": "后采集器", "audio": ""},
        ],
    }
    committed: dict = {}

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_media_map_for_replace", lambda: {"old": "101", "new": "202"})
    monkeypatch.setattr(
        api_public,
        "_commit_payload_with_rollback",
        lambda new_payload, snapshot, **kwargs: committed.update({"payload": deepcopy(new_payload), "kwargs": kwargs}),
    )

    reply, state, logs = api_public._apply_replace_media_in_task_intent(
        "把共同任务里的old换成new",
        {"task_name": "共同任务", "media_name": "old", "new_media_name": "new"},
    )

    assert "共同任务" in reply
    assert "替换" in reply
    assert state["missing_slots"] == []
    assert logs[0]["task_ids"] == ["1"]
    assert committed["kwargs"]["sync_livecasts"] is False
    assert committed["payload"]["schedules"][0]["tasks"][0]["mediaid"] == 202
    assert committed["payload"]["livecasts"][0]["medianame"] == "后采集器"


def test_replace_media_in_task_with_only_task_name_rejects_schedule_and_broadcast_ambiguity(monkeypatch) -> None:
    payload = {
        "schedules": [
            {
                "schedule_name": "S1",
                "tasks": [{"taskid": "1", "taskname": "共同任务", "mediaid": "101", "medianame": "old", "audio": "old"}],
            }
        ],
        "broadcasts": [
            {"taskid": "2", "taskname": "共同任务", "mediaid": "101", "medianame": "old", "audio": "old"}
        ],
        "livecasts": [],
    }

    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(payload))
    monkeypatch.setattr(api_public, "_media_map_for_replace", lambda: {"old": "101", "new": "202"})

    reply, state, logs = api_public._apply_replace_media_in_task_intent(
        "把共同任务里的old换成new",
        {"task_name": "共同任务", "media_name": "old", "new_media_name": "new"},
    )

    assert '找到了多个可能的任务' in reply
    assert state["missing_slots"] == []
    assert logs == []
