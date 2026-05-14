from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

from fastapi import HTTPException
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def _phase1_media_library(
    items: list[dict],
    *,
    source: str = "local",
    remote_expected: bool = False,
    remote_fetch_ok: bool = False,
    fallback_used: bool = False,
) -> dict:
    return {
        "items": deepcopy(items),
        "source": source,
        "remote_expected": remote_expected,
        "remote_fetch_ok": remote_fetch_ok,
        "fallback_used": fallback_used,
    }


@pytest.fixture(autouse=True)
def _default_phase1_template_media_library(monkeypatch):
    original_media_name = api_public._phase1_template_media_name
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library([{"mediaid": "911", "name": "上课铃"}]),
    )
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_name",
        lambda task, _original=original_media_name: _original(task) or "上课铃",
    )


def _assistant_playback_terminal_items() -> list[dict]:
    return [
        {"id": 46, "type": 11, "name": "\u53f3\u4e00\u7ec8\u7aef", "zone": 0},
        {"id": 25, "type": 24, "name": "\u64cd\u573a\u529f\u653e", "zone": 0},
        {"id": 28, "type": 2, "name": "\u5bfb\u547c\u8bdd\u7b52", "zone": 1},
    ]


class _FakePath:
    def __init__(self, text: str = "", *, exists: bool = True, label: str = "/virtual/path") -> None:
        self._text = text
        self._exists = exists
        self._label = label

    def exists(self) -> bool:
        return self._exists

    def read_text(self, encoding: str = "utf-8", errors: str | None = None) -> str:
        del encoding
        del errors
        return self._text

    def __str__(self) -> str:
        return self._label


def _ambiguous_playback_terminal_items() -> list[dict]:
    return [
        {"id": 11, "type": 11, "name": "\u53f3\u4e8c\u7ec8\u7aef", "zone": 0},
    ]


def _ambiguous_zone_items() -> list[dict]:
    return [
        {"id": 3, "name": "zone-c", "terminal": [{"id": 11, "name": "\u53f3\u4e8c\u7ec8\u7aef"}]},
        {"id": 4, "name": "zone-d", "terminal": [{"id": 11, "name": "\u53f3\u4e8c\u7ec8\u7aef"}]},
    ]


def _stale_terminal_bound_task() -> dict:
    return {
        "taskname": "\u65e9\u8bfb\u5f00\u59cb\u94c3",
        "medianame": "上课铃",
        "audio": "上课铃",
        "mediaid": "911",
        "starttime": "07:50:00",
        "startdate": "2026-01-18",
        "enddate": "2039-01-31",
        "weekdays": [
            "\u5468\u4e00",
            "\u5468\u4e8c",
            "\u5468\u4e09",
            "\u5468\u56db",
            "\u5468\u4e94",
        ],
        "terminalids": ["9"],
        "terminalnames": ["\u53f3\u4e00\u7ec8\u7aef"],
        "liveterminalid": "9",
        "liveterminalname": "\u53f3\u4e00\u7ec8\u7aef",
        "location": [["A\u533a", "\u53f3\u4e00\u7ec8\u7aef"]],
        "taskterminal": [
            {
                "terminalid": "9",
                "terminalname": "\u53f3\u4e00\u7ec8\u7aef",
                "groupid": 1,
                "groupid_present": True,
            }
        ],
    }


def _build_phase1_template_paths() -> tuple[object, object]:
    class FakeTemplateFile:
        def __init__(self, text: str) -> None:
            self._text = text

        def exists(self) -> bool:
            return True

        def read_text(self, encoding: str = "utf-8", errors: str | None = None) -> str:
            del encoding
            del errors
            return self._text

    class FakeTemplateDir:
        def __init__(self, files: dict[str, FakeTemplateFile]) -> None:
            self._files = files

        def __truediv__(self, name: str) -> FakeTemplateFile:
            return self._files.get(name, FakeTemplateFile(""))

    manifest_path = FakeTemplateFile(
        json.dumps(
            {
                "default": {
                    "kind": "小学",
                    "season": "夏季",
                    "local_template_file": "school_summer_default.json",
                },
                "kind_aliases": {
                    "小学部": "小学",
                    "小学生": "小学",
                    "小": "小学",
                },
                "season_aliases": {
                    "夏": "夏季",
                    "冬": "冬季",
                },
                "kind_templates": {
                    "小学": {
                        "season_templates": {
                            "夏季": {
                                "local_template_file": "school_summer_default.json",
                            },
                            "冬季": {
                                "local_template_file": "school_summer_default.json",
                            },
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
    )
    template_file = FakeTemplateFile(
        json.dumps(
            {
                "schedule_name": "学校标准夏季模板",
                "status": "启用",
                "tasks": [
                    {
                        "all": 14,
                        "count": 1,
                        "start": 1,
                        "state": 0,
                        "taskid": "72841",
                        "enablestate": 1,
                        "taskstate": 0,
                        "timelength": 20,
                        "timelengthtype": 1,
                        "volume": 80,
                        "priority": 10,
                        "starttime": "07:50:00",
                        "startdate": "2026-01-18",
                        "enddate": "2039-01-31",
                        "taskname": "早读开始铃",
                        "customName": "早读开始铃",
                        "audio": "上课铃",
                        "weekdays": ["周一", "周二", "周三", "周四", "周五"],
                        "terminalids": ["9"],
                        "terminalnames": ["右一终端"],
                        "liveterminalid": "9",
                        "liveterminalname": "右一终端",
                        "powerOn": True,
                        "taskLevel": "正常",
                        "sendMode": "单播",
                        "playMode": "串行",
                        "ledSetting": "",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    template_dir = FakeTemplateDir({"school_summer_default.json": template_file})
    return manifest_path, template_dir


def _set_default_schedule_kind(monkeypatch, value: str = "小学", season: str = "夏季") -> None:
    monkeypatch.setattr(api_public, "_load_default_schedule_kind", lambda: value)
    monkeypatch.setattr(api_public, "_load_default_schedule_season", lambda: season)


def _select_phase1_template_entry_result(kind: str, *, season: str = "夏季", **entry):
    def _resolver(text: str, schedule_kind: str, schedule_season: str):
        del text
        del schedule_kind
        del schedule_season
        return kind, season, dict(entry)

    return _resolver


def _seasonal_manifest() -> dict:
    return {
        "kind_aliases": {
            "高中部": "高中",
            "大学部": "大学",
        },
        "season_aliases": {
            "夏": "夏季",
            "冬": "冬季",
        },
        "kind_templates": {
            "高中": {
                "season_templates": {
                    "夏季": {"source_schedule_name": "中学夏季作息方案"},
                    "冬季": {"source_schedule_name": "中学冬季作息方案"},
                },
            },
            "大学": {
                "season_templates": {
                    "夏季": {"source_schedule_name": "大学夏季作息方案"},
                    "冬季": {"source_schedule_name": "大学冬季作息方案"},
                },
            },
        },
    }


def _stub_schedule_persistence(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_store_get",
        lambda key: {"schedules": []} if key == "broadcast_schedules" else ({"data": []} if key == "all_task" else {}),
    )
    monkeypatch.setattr(api_public, "_store_set", lambda key, value: None)
    monkeypatch.setattr(api_public, "_write_cache_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda payload: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda payload: None)
    monkeypatch.setattr(api_public, "_build_all_task_payload", lambda payload: {"data": []})
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)


def test_create_scheme_uses_system_default_kind_and_local_template(monkeypatch) -> None:
    manifest_path, template_dir = _build_phase1_template_paths()
    committed: dict = {}

    _set_default_schedule_kind(monkeypatch, "小学")
    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_RESOURCE_DIR", template_dir)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_write_json", lambda *args, **kwargs: None)

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建小学春季作息",
        {"schedule_name": "春季作息"},
    )

    assert "春季作息" in reply
    assert "创建" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "create_schedule"
    assert logs[0]["details"]["kind"] == "小学"
    assert logs[0]["details"]["creation_path"] == "local_template_only"
    assert committed["sync_remote"] is False
    assert committed["schedule"]["schedule_name"] == "春季作息"

    saved_task = committed["schedule"]["tasks"][0]
    assert "taskid" not in saved_task
    assert "all" not in saved_task
    assert "taskstate" not in saved_task
    assert saved_task["sechename"] == "春季作息"
    assert saved_task["info"] == "春季作息"
    assert saved_task["execmode"] == 62


def test_create_scheme_prefers_remote_copy_when_remote_template_is_available(monkeypatch) -> None:
    captured: dict = {}

    _set_default_schedule_kind(monkeypatch, "小学")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result(
            "小学",
            remote_template="远端模板",
            local_template_file="school_summer_default.json",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["远端模板"])
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [{"taskid": "501", "taskname": f"{schedule_name}-任务"}],
    )

    def fake_remote_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/task/sechinfo"
        captured["copy_payload"] = kwargs.get("json_body") or kwargs.get("form_body")
        return {"ok": True}

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        captured["schedule"] = deepcopy(new_schedule)
        captured["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建小学春季作息",
        {"schedule_name": "春季作息"},
    )

    assert "远端模板" in reply
    assert "春季作息" in reply
    assert "创建" in reply or "生成" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["action"] == "create_schedule"
    assert logs[0]["details"]["creation_path"] == "remote_copy"
    assert logs[0]["details"]["remote_template"] == "远端模板"
    assert captured["copy_payload"] == {"fromtaskname": "远端模板", "totaskname": "春季作息"}
    assert captured["sync_remote"] is False
    assert captured["schedule"]["schedule_name"] == "春季作息"


def test_create_scheme_local_template_sync_failure_returns_rollback_message(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "学校标准夏季模板",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
            }
        ],
    }

    _set_default_schedule_kind(monkeypatch, "小学")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result(
            "小学",
            remote_template="远端模板",
            local_template_file="school_summer_default.json",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda new_schedule, *, sync_remote: (_ for _ in ()).throw(HTTPException(status_code=502, detail="sync failed")),
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建小学春季作息",
        {"schedule_name": "春季作息"},
    )

    assert "新作息方案" in reply
    assert "回滚" in reply or "再试一次" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["details"]["failure_reason"] == "sync failed"
    assert logs[0]["details"]["user_reason"]
    assert logs[0]["details"]["retryable"] is True


def test_create_scheme_supports_source_time_and_end_time_slots(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "标准模板",
        "tasks": [
            {
                "taskname": "晨读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
            }
        ],
    }
    committed: dict = {}

    _set_default_schedule_kind(monkeypatch, "小学")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("小学", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda new_schedule, *, sync_remote: committed.update(
            {"schedule": deepcopy(new_schedule), "sync_remote": sync_remote}
        ),
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建小学春季作息",
        {
            "schedule_name": "春季作息",
            "source_time": "2026-03-01",
            "end_time": "2026-03-31",
        },
    )

    assert "2026-03-01 至 2026-03-31" in reply
    assert state["missing_slots"] == []
    assert logs[0]["action"] == "create_schedule"
    saved_task = committed["schedule"]["tasks"][0]
    assert saved_task["startdate"] == "2026-03-01"
    assert saved_task["enddate"] == "2026-03-31"


def test_create_scheme_invalid_configured_schedule_kind_returns_error(monkeypatch) -> None:
    manifest_path, template_dir = _build_phase1_template_paths()

    _set_default_schedule_kind(monkeypatch, "夜校")
    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_RESOURCE_DIR", template_dir)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建夜校作息",
        {"schedule_name": "夜校作息"},
    )

    assert "未识别的方案场景类型" in reply
    assert "可用类型" in reply
    assert state["missing_slots"] == []
    assert logs == []


def test_select_phase1_template_entry_maps_high_school_to_middle_school_templates(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_load_phase1_template_manifest", _seasonal_manifest)

    resolved_kind, resolved_season, entry = api_public._select_phase1_template_entry("", "高中", "冬季")

    assert resolved_kind == "高中"
    assert resolved_season == "冬季"
    assert entry["source_schedule_name"] == "中学冬季作息方案"


def test_select_phase1_template_entry_uses_university_season_source_schedule(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_load_phase1_template_manifest", _seasonal_manifest)

    resolved_kind, resolved_season, entry = api_public._select_phase1_template_entry("", "大学", "夏季")

    assert resolved_kind == "大学"
    assert resolved_season == "夏季"
    assert entry["source_schedule_name"] == "大学夏季作息方案"


def test_load_phase1_local_schedule_template_reads_versioned_catalog(monkeypatch) -> None:
    catalog_path = Path("virtual-template-catalog.json")
    catalog_payload = {
        "schedules": [
            {
                "schedule_name": "大学夏季作息方案",
                "tasks": [
                    {
                        "taskname": "大学起床铃",
                        "starttime": "07:30:00",
                        "startdate": "2026-01-18",
                        "enddate": "2039-01-31",
                        "weekdays": ["周一"],
                    }
                ],
            }
        ]
    }

    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_CATALOG_PATH", catalog_path)
    monkeypatch.setattr(api_public, "_read_json_optional", lambda path: deepcopy(catalog_payload) if path == catalog_path else None)
    monkeypatch.setattr(
        api_public,
        "_load_schedules_payload",
        lambda: (_ for _ in ()).throw(AssertionError("runtime schedules should not be used as template catalog")),
    )

    schedule = api_public._load_phase1_local_schedule_template("大学夏季作息方案")

    assert schedule["schedule_name"] == "大学夏季作息方案"
    assert schedule["tasks"][0]["taskname"] == "大学起床铃"


def test_load_phase1_template_manifest_warns_once_for_legacy_root_inputs(
    monkeypatch,
    caplog,
) -> None:
    manifest_path = _FakePath("{}", label="/virtual/default_data/schedule_template_manifest.json")
    legacy_catalog_path = _FakePath("{}", label="/virtual/data/broadcast_schedules.json")
    legacy_manifest_path = _FakePath("{}", label="/virtual/data/schedule_template")

    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(api_public, "LEGACY_PHASE1_TEMPLATE_CATALOG_PATH", legacy_catalog_path)
    monkeypatch.setattr(api_public, "LEGACY_PHASE1_TEMPLATE_MANIFEST_PATH", legacy_manifest_path)
    monkeypatch.setattr(api_public, "_PHASE1_LEGACY_TEMPLATE_WARNING_EMITTED", False)

    with caplog.at_level("WARNING"):
        api_public._load_phase1_template_manifest()
        api_public._load_phase1_template_manifest()

    warning_rows = [
        record for record in caplog.records if "legacy schedule template inputs detected" in record.message
    ]
    assert len(warning_rows) == 1


def test_load_schedules_payload_initializes_missing_runtime_file(monkeypatch) -> None:
    schedules_path = Path("virtual-broadcast-schedules.json")
    writes: list[tuple[Path, object]] = []

    monkeypatch.setattr(api_public, "_read_json_optional", lambda path: None if path == schedules_path else {})
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: writes.append((path, deepcopy(payload))))
    monkeypatch.setitem(api_public.DATA_STORE["broadcast_schedules"], "path", schedules_path)
    monkeypatch.setitem(api_public.DATA_STORE["broadcast_schedules"], "payload", None)
    monkeypatch.setitem(api_public.DATA_STORE["broadcast_schedules"], "loaded", False)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)

    payload = api_public._load_schedules_payload()

    assert payload["schedules"] == []
    assert payload["broadcasts"] == []
    assert payload["livecasts"] == []
    assert payload["directories"] == []
    assert len(writes) == 1
    assert writes[0][0] == schedules_path
    assert writes[0][1]["schedules"] == []
    assert writes[0][1]["broadcasts"] == []
    assert writes[0][1]["livecasts"] == []


def test_create_scheme_requires_schedule_name(monkeypatch) -> None:
    _set_default_schedule_kind(monkeypatch, "小学")

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建一个新的作息方案",
        {"source_time": "2026-03-01"},
    )

    assert "方案名称" in reply
    assert state["missing_slots"] == ["schedule_name"]
    assert logs == []


def test_create_scheme_requires_system_default_kind(monkeypatch) -> None:
    _set_default_schedule_kind(monkeypatch, "")

    reply, state, logs = api_public._apply_create_scheme_intent(
        "生成一个暑假作息",
        {"schedule_name": "暑假作息"},
    )

    assert "AI助手" in reply
    assert "学校类型" in reply
    assert state["missing_slots"] == []
    assert logs == []


def test_create_scheme_requires_system_default_season(monkeypatch) -> None:
    _set_default_schedule_kind(monkeypatch, "小学", season="")

    reply, state, logs = api_public._apply_create_scheme_intent(
        "生成一个暑假作息",
        {"schedule_name": "暑假作息"},
    )

    assert "AI助手" in reply
    assert "作息季节" in reply
    assert state["missing_slots"] == []
    assert logs == []


def test_create_scheme_uses_source_schedule_name_template(monkeypatch) -> None:
    committed: dict = {}
    template_schedule = {
        "schedule_name": "大学夏季作息方案",
        "tasks": [
            {
                "taskname": "大学起床铃",
                "medianame": "上课铃",
                "audio": "上课铃",
                "mediaid": "911",
                "starttime": "07:30:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
            }
        ],
    }

    _set_default_schedule_kind(monkeypatch, "大学", season="夏季")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("大学", season="夏季", source_schedule_name="大学夏季作息方案"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_schedule_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_load_phase1_local_template",
        lambda _: (_ for _ in ()).throw(AssertionError("local template fallback should not be used")),
    )
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建大学夏季作息",
        {"schedule_name": "大学夏季新方案"},
    )

    assert "大学夏季新方案" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["season"] == "夏季"
    assert logs[0]["details"]["source_schedule_name"] == "大学夏季作息方案"
    assert committed["schedule"]["tasks"][0]["taskname"] == "大学起床铃"


def test_create_scheme_remote_copy_commit_failure_triggers_remote_cleanup(monkeypatch) -> None:
    captured: dict = {}

    _set_default_schedule_kind(monkeypatch, "小学")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result(
            "小学",
            remote_template="远端模板",
            local_template_file="fallback.json",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["远端模板"])
    monkeypatch.setattr(
        api_public,
        "_create_phase1_schedule_via_remote_copy",
        lambda final_name, template_name, start_date, end_date: ({"schedule_name": final_name, "tasks": []}, 0),
    )
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda new_schedule, *, sync_remote: (_ for _ in ()).throw(HTTPException(status_code=502, detail="sync failed")),
    )
    monkeypatch.setattr(
        api_public,
        "_cleanup_remote_created_schedule",
        lambda schedule_name: captured.update({"cleaned": schedule_name}) or "",
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "创建小学春季作息",
        {"schedule_name": "春季作息"},
    )

    assert "新作息方案" in reply
    assert "回滚" in reply or "再试一次" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["details"]["failure_reason"] == "sync failed"
    assert logs[0]["details"]["user_reason"]
    assert logs[0]["details"]["retryable"] is True
    assert captured["cleaned"] == "春季作息"


def test_remote_copy_date_update_failure_cleans_up_created_schedule(monkeypatch) -> None:
    cleanup_calls: list[str] = []

    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "501",
                "taskname": f"{schedule_name}-任务",
                "startdate": "2026-01-01",
                "enddate": "2026-01-01",
                "starttime": "07:00:00",
            }
        ],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {"铃声": "11"})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"高一1班": "101"})
    monkeypatch.setattr(
        api_public,
        "_remote_update_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(status_code=502, detail="update failed")),
    )
    monkeypatch.setattr(
        api_public,
        "_cleanup_remote_created_schedule",
        lambda schedule_name: cleanup_calls.append(schedule_name) or "",
    )

    try:
        api_public._create_phase1_schedule_via_remote_copy(
            "春季作息",
            "远端模板",
            api_public.date(2026, 3, 1),
            api_public.date(2026, 3, 31),
        )
    except HTTPException as exc:
        assert "有效期更新失败" in str(exc.detail)
        assert "已回滚远端新方案" in str(exc.detail)
    else:
        raise AssertionError("expected HTTPException")

    assert cleanup_calls == ["春季作息"]


def test_remote_copy_media_lookup_failure_cleans_up_created_schedule(monkeypatch) -> None:
    cleanup_calls: list[str] = []

    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "501",
                "taskname": f"{schedule_name}-任务",
                "startdate": "2026-01-01",
                "enddate": "2026-01-01",
                "starttime": "07:00:00",
            }
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_remote_media_map",
        lambda: (_ for _ in ()).throw(HTTPException(status_code=502, detail="media lookup failed")),
    )
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"高一1班": "101"})
    monkeypatch.setattr(
        api_public,
        "_cleanup_remote_created_schedule",
        lambda schedule_name: cleanup_calls.append(schedule_name) or "",
    )

    try:
        api_public._create_phase1_schedule_via_remote_copy(
            "春季作息",
            "远端模板",
            api_public.date(2026, 3, 1),
            api_public.date(2026, 3, 31),
        )
    except HTTPException as exc:
        assert "读取远端依赖失败" in str(exc.detail)
        assert "已回滚远端新方案" in str(exc.detail)
    else:
        raise AssertionError("expected HTTPException")

    assert cleanup_calls == ["春季作息"]


def test_remote_copy_terminal_lookup_failure_cleans_up_created_schedule(monkeypatch) -> None:
    cleanup_calls: list[str] = []

    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_tasks",
        lambda schedule_name: [
            {
                "taskid": "501",
                "taskname": f"{schedule_name}-任务",
                "startdate": "2026-01-01",
                "enddate": "2026-01-01",
                "starttime": "07:00:00",
            }
        ],
    )
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {"铃声": "11"})
    monkeypatch.setattr(
        api_public,
        "_remote_terminal_map",
        lambda: (_ for _ in ()).throw(HTTPException(status_code=502, detail="terminal lookup failed")),
    )
    monkeypatch.setattr(
        api_public,
        "_cleanup_remote_created_schedule",
        lambda schedule_name: cleanup_calls.append(schedule_name) or "",
    )

    try:
        api_public._create_phase1_schedule_via_remote_copy(
            "春季作息",
            "远端模板",
            api_public.date(2026, 3, 1),
            api_public.date(2026, 3, 31),
        )
    except HTTPException as exc:
        assert "读取远端依赖失败" in str(exc.detail)
        assert "已回滚远端新方案" in str(exc.detail)
    else:
        raise AssertionError("expected HTTPException")

    assert cleanup_calls == ["春季作息"]


def test_create_scheme_assistant_scope_rebinds_local_template_to_all_playback_terminals(monkeypatch) -> None:
    committed: dict = {}
    template_schedule = {
        "schedule_name": "template",
        "tasks": [_stale_terminal_bound_task()],
    }

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("primary", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_store_terminalinfo_items", _assistant_playback_terminal_items)

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create spring-schedule",
        {"schedule_name": "spring-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "spring-schedule" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["creation_path"] == "local_template_only"
    assert committed["sync_remote"] is False
    assert committed["schedule"]["status"] == "停用"
    saved_task = committed["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["46", "25"]
    assert saved_task["terminalnames"] == ["\u53f3\u4e00\u7ec8\u7aef", "\u64cd\u573a\u529f\u653e"]
    assert saved_task["liveterminalid"] == 46
    assert saved_task["liveterminalname"] == "\u53f3\u4e00\u7ec8\u7aef"
    assert saved_task["location"] == [
        [api_public._zone_label(0), "\u64cd\u573a\u529f\u653e"],
        [api_public._zone_label(0), "\u53f3\u4e00\u7ec8\u7aef"],
    ]
    assert saved_task["taskterminal"] == [
        {"terminalid": "25", "groupid": 0, "groupid_present": True, "terminalname": "\u64cd\u573a\u529f\u653e"},
        {"terminalid": "46", "groupid": 0, "groupid_present": True, "terminalname": "\u53f3\u4e00\u7ec8\u7aef"},
    ]
    assert "taskTerminal" not in saved_task


def test_create_scheme_assistant_scope_rebinds_remote_copy_to_all_playback_terminals(monkeypatch) -> None:
    captured: dict = {}

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result(
            "primary",
            remote_template="remote-template",
            local_template_file="school_summer_default.json",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["remote-template"])
    monkeypatch.setattr(api_public, "_remote_terminalinfo_items", _assistant_playback_terminal_items)
    monkeypatch.setattr(
        api_public,
        "_create_phase1_schedule_via_remote_copy",
        lambda final_name, template_name, start_date, end_date: (
            {"schedule_name": final_name, "tasks": [_stale_terminal_bound_task()]},
            1,
        ),
    )

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        captured["schedule"] = deepcopy(new_schedule)
        captured["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create spring-schedule",
        {"schedule_name": "spring-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "spring-schedule" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["creation_path"] == "remote_copy"
    assert captured["sync_remote"] is True
    assert captured["schedule"]["status"] == "停用"
    saved_task = captured["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["46", "25"]
    assert saved_task["terminalnames"] == ["\u53f3\u4e00\u7ec8\u7aef", "\u64cd\u573a\u529f\u653e"]
    assert saved_task["liveterminalid"] == 46
    assert saved_task["liveterminalname"] == "\u53f3\u4e00\u7ec8\u7aef"
    assert saved_task["location"] == [
        [api_public._zone_label(0), "\u64cd\u573a\u529f\u653e"],
        [api_public._zone_label(0), "\u53f3\u4e00\u7ec8\u7aef"],
    ]
    assert saved_task["taskterminal"] == [
        {"terminalid": "25", "groupid": 0, "groupid_present": True, "terminalname": "\u64cd\u573a\u529f\u653e"},
        {"terminalid": "46", "groupid": 0, "groupid_present": True, "terminalname": "\u53f3\u4e00\u7ec8\u7aef"},
    ]
    assert "taskTerminal" not in saved_task


def test_create_scheme_assistant_scope_remote_copy_sync_failure_triggers_remote_cleanup(monkeypatch) -> None:
    captured: dict = {}

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result(
            "primary",
            remote_template="remote-template",
            local_template_file="school_summer_default.json",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["remote-template"])
    monkeypatch.setattr(api_public, "_remote_terminalinfo_items", _assistant_playback_terminal_items)
    monkeypatch.setattr(
        api_public,
        "_create_phase1_schedule_via_remote_copy",
        lambda final_name, template_name, start_date, end_date: (
            {"schedule_name": final_name, "tasks": [_stale_terminal_bound_task()]},
            1,
        ),
    )

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        captured["schedule"] = deepcopy(new_schedule)
        captured["sync_remote"] = sync_remote
        raise HTTPException(status_code=502, detail="sync failed")

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)
    monkeypatch.setattr(
        api_public,
        "_cleanup_remote_created_schedule",
        lambda schedule_name: captured.update({"cleaned": schedule_name}) or "",
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create spring-schedule",
        {"schedule_name": "spring-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "新作息方案" in reply
    assert "回滚" in reply or "再试一次" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["details"]["failure_reason"] == "sync failed"
    assert logs[0]["details"]["user_reason"]
    assert logs[0]["details"]["retryable"] is True
    assert captured["sync_remote"] is True
    assert captured["cleaned"] == "spring-schedule"
    saved_task = captured["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["46", "25"]
    assert saved_task["liveterminalid"] == 46
    assert saved_task["taskterminal"] == [
        {"terminalid": "25", "groupid": 0, "groupid_present": True, "terminalname": "\u64cd\u573a\u529f\u653e"},
        {"terminalid": "46", "groupid": 0, "groupid_present": True, "terminalname": "\u53f3\u4e00\u7ec8\u7aef"},
    ]


def test_create_scheme_assistant_scope_multizone_terminal_generates_explicit_taskterminal_bindings(monkeypatch) -> None:
    committed: dict = {}
    template_schedule = {
        "schedule_name": "template",
        "tasks": [_stale_terminal_bound_task()],
    }

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("primary", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_remote_terminalinfo_items", _ambiguous_playback_terminal_items)
    monkeypatch.setattr(api_public, "_fetch_enriched_zone_items", lambda force=False: _ambiguous_zone_items())

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create winter-schedule",
        {"schedule_name": "winter-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "winter-schedule" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["creation_path"] == "local_template_sync"
    assert committed["sync_remote"] is True
    assert committed["schedule"]["status"] == "停用"
    saved_task = committed["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["11"]
    assert saved_task["terminalnames"] == ["\u53f3\u4e8c\u7ec8\u7aef"]
    assert saved_task["liveterminalid"] == 11
    assert saved_task["liveterminalname"] == "\u53f3\u4e8c\u7ec8\u7aef"
    assert saved_task["taskterminal"] == [
        {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "\u53f3\u4e8c\u7ec8\u7aef"},
        {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "\u53f3\u4e8c\u7ec8\u7aef"},
    ]
    assert saved_task["location"] == [
        ["zone-c", "\u53f3\u4e8c\u7ec8\u7aef"],
        ["zone-d", "\u53f3\u4e8c\u7ec8\u7aef"],
    ]


def test_create_scheme_assistant_scope_local_template_real_remote_add_uses_explicit_multizone_bindings(
    monkeypatch,
) -> None:
    captured: dict = {"ensured": [], "status": [], "task_payloads": [], "bind_payloads": []}
    template_schedule = {
        "schedule_name": "template",
        "tasks": [_stale_terminal_bound_task()],
    }
    ambiguous_lookup = {
        "11": {
            "zone": "3",
            "zone_name": "zone-c",
            "name": "\u53f3\u4e8c\u7ec8\u7aef",
            "zone_ambiguous": True,
            "zone_candidates": [
                {"zone": "3", "zone_name": "zone-c"},
                {"zone": "4", "zone_name": "zone-d"},
            ],
        }
    }

    _set_default_schedule_kind(monkeypatch, "primary")
    _stub_schedule_persistence(monkeypatch)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("primary", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_remote_terminalinfo_items", _ambiguous_playback_terminal_items)
    monkeypatch.setattr(api_public, "_fetch_enriched_zone_items", lambda force=False: _ambiguous_zone_items())
    monkeypatch.setattr(api_public, "_remote_schedule_catalog_snapshot", lambda: (set(), {}))
    monkeypatch.setattr(
        api_public,
        "_remote_ensure_schedule",
        lambda schedule_name, catalog_names=None: captured["ensured"].append(schedule_name),
    )
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"\u53f3\u4e8c\u7ec8\u7aef": "11", "11": "11"})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: deepcopy(ambiguous_lookup))
    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", lambda task_id: ([], True))
    monkeypatch.setattr(api_public, "_resolve_created_schedule_task_id", lambda *args, **kwargs: "9001")
    monkeypatch.setattr(api_public, "_remote_set_schedule_status", lambda schedule_name, enabled: captured["status"].append((schedule_name, enabled)))
    monkeypatch.setattr(
        api_public,
        "_resolve_binding_group_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not resolve ambiguous location")),
    )
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda schedule_name, task, media_map, terminal_map, remote_fallback=None: {
            "taskname": task.get("taskname") or "prep-bell",
            "customName": task.get("customName") or task.get("taskname") or "prep-bell",
            "starttime": task.get("starttime") or "07:50:00",
            "startdate": task.get("startdate") or "2026-01-18",
            "enddate": task.get("enddate") or "2039-01-31",
            "mediaid": "911",
        },
    )

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/sechetask":
            captured["task_payloads"].append(deepcopy(kwargs.get("json_body")))
            return {"data": {"id": 9001}}
        if method == "POST" and path == "/task/jsontaskterminal":
            captured["bind_payloads"].append(deepcopy(kwargs.get("json_body")))
            return {"ok": True}
        raise AssertionError(f"unexpected remote request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create spring-schedule",
        {"schedule_name": "spring-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "spring-schedule" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["creation_path"] == "local_template_sync"
    assert captured["ensured"] == ["spring-schedule"]
    assert captured["status"] == [("spring-schedule", False)]
    assert captured["bind_payloads"] == [
        {
            "data": [
                {"id": 9001, "terminalid": 11, "area": 255, "groupid": 3},
                {"id": 9001, "terminalid": 11, "area": 255, "groupid": 4},
            ]
        }
    ]


def test_create_scheme_assistant_scope_remote_copy_targeted_sync_accepts_multizone_bindings(monkeypatch) -> None:
    captured: dict = {}
    remote_task = {
        "taskid": "501",
        "taskname": "\u65e9\u8bfb\u5f00\u59cb\u94c3",
        "customName": "\u65e9\u8bfb\u5f00\u59cb\u94c3",
        "starttime": "07:50:00",
        "startdate": "2026-01-18",
        "enddate": "2039-01-31",
        "weekdays": ["\u5468\u4e00"],
        "terminalids": ["11"],
        "liveterminalid": "11",
        "liveterminalname": "\u53f3\u4e8c\u7ec8\u7aef",
        "terminalnames": ["\u53f3\u4e8c\u7ec8\u7aef"],
        "location": [["zone-c", "\u53f3\u4e8c\u7ec8\u7aef"]],
        "taskterminal": [
            {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "\u53f3\u4e8c\u7ec8\u7aef"},
        ],
    }
    ambiguous_lookup = {
        "11": {
            "zone": "3",
            "zone_name": "zone-c",
            "name": "\u53f3\u4e8c\u7ec8\u7aef",
            "zone_ambiguous": True,
            "zone_candidates": [
                {"zone": "3", "zone_name": "zone-c"},
                {"zone": "4", "zone_name": "zone-d"},
            ],
        }
    }

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result(
            "primary",
            remote_template="remote-template",
            local_template_file="school_summer_default.json",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: ["remote-template"])
    monkeypatch.setattr(api_public, "_remote_terminalinfo_items", _ambiguous_playback_terminal_items)
    monkeypatch.setattr(api_public, "_fetch_enriched_zone_items", lambda force=False: _ambiguous_zone_items())
    monkeypatch.setattr(
        api_public,
        "_create_phase1_schedule_via_remote_copy",
        lambda final_name, template_name, start_date, end_date: (
            {"schedule_name": final_name, "status": "\u542f\u7528", "tasks": [deepcopy(remote_task)]},
            1,
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_schedule_catalog_snapshot",
        lambda: ({"winter-schedule"}, {"winter-schedule": "\u542f\u7528"}),
    )
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [deepcopy(remote_task)])
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"\u53f3\u4e8c\u7ec8\u7aef": "11", "11": "11"})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: deepcopy(ambiguous_lookup))
    monkeypatch.setattr(api_public, "_remote_task_changed", lambda desired, remote, payload: False)
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda schedule_name, task, media_map, terminal_map, remote_fallback=None: {"taskid": task.get("taskid") or "501"},
    )
    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", lambda task_id: ([], False))
    monkeypatch.setattr(api_public, "_remote_set_schedule_status", lambda schedule_name, enabled: None)

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/jsontaskterminal":
            captured["json_body"] = kwargs.get("json_body")
            return {"ok": True}
        raise AssertionError(f"unexpected remote request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        captured["schedule"] = deepcopy(new_schedule)
        captured["sync_remote"] = sync_remote
        payload = {"schedules": [deepcopy(new_schedule)]}
        api_public._sync_remote_schedules_targeted(payload, [str(new_schedule.get("schedule_name") or "")])
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create winter-schedule",
        {"schedule_name": "winter-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "winter-schedule" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["creation_path"] == "remote_copy"
    assert captured["sync_remote"] is True
    assert captured["schedule"]["status"] == "停用"
    assert captured["schedule"]["tasks"][0]["taskterminal"] == [
        {"terminalid": "11", "groupid": 3, "groupid_present": True, "terminalname": "\u53f3\u4e8c\u7ec8\u7aef"},
        {"terminalid": "11", "groupid": 4, "groupid_present": True, "terminalname": "\u53f3\u4e8c\u7ec8\u7aef"},
    ]
    assert captured["json_body"] == {
        "data": [
            {"id": 501, "terminalid": 11, "area": 255, "groupid": 4},
        ]
    }


def test_create_scheme_assistant_scope_requires_playback_terminals(monkeypatch) -> None:
    commit_called = {"value": False}
    remote_copy_called = {"value": False}

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("primary", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [
            {"id": 28, "type": 2, "name": "pager", "zone": 1},
            {"id": 23, "type": 8, "name": "collector", "zone": 5},
        ],
    )
    monkeypatch.setattr(
        api_public,
        "_create_phase1_schedule_via_remote_copy",
        lambda *args, **kwargs: remote_copy_called.update({"value": True}),
    )
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda *args, **kwargs: commit_called.update({"value": True}),
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create spring-schedule",
        {"schedule_name": "spring-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert reply == "\u672a\u627e\u5230\u53ef\u7ed1\u5b9a\u7684\u64ad\u653e\u7ec8\u7aef\uff0c\u5df2\u53d6\u6d88\u65b0\u5efa\u4f5c\u606f\u3002"
    assert state["missing_slots"] == []
    assert logs == []
    assert remote_copy_called["value"] is False
    assert commit_called["value"] is False


def test_create_scheme_assistant_scope_local_template_sync_failure_rolls_back_created_remote_schedule(
    monkeypatch,
) -> None:
    captured: dict = {"catalog": set(), "deleted": []}
    template_schedule = {
        "schedule_name": "template",
        "tasks": [_stale_terminal_bound_task()],
    }
    ambiguous_lookup = {
        "11": {
            "zone": "3",
            "zone_name": "zone-c",
            "name": "\u53f3\u4e8c\u7ec8\u7aef",
            "zone_ambiguous": True,
            "zone_candidates": [
                {"zone": "3", "zone_name": "zone-c"},
                {"zone": "4", "zone_name": "zone-d"},
            ],
        }
    }

    _set_default_schedule_kind(monkeypatch, "primary")
    _stub_schedule_persistence(monkeypatch)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("primary", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_remote_terminalinfo_items", _ambiguous_playback_terminal_items)
    monkeypatch.setattr(api_public, "_fetch_enriched_zone_items", lambda force=False: _ambiguous_zone_items())
    monkeypatch.setattr(
        api_public,
        "_remote_schedule_catalog_snapshot",
        lambda: (set(captured["catalog"]), {name: "\u542f\u7528" for name in captured["catalog"]}),
    )
    monkeypatch.setattr(
        api_public,
        "_remote_ensure_schedule",
        lambda schedule_name, catalog_names=None: captured["catalog"].add(schedule_name),
    )
    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", lambda schedule_name: [])
    monkeypatch.setattr(api_public, "_remote_media_map", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {"\u53f3\u4e8c\u7ec8\u7aef": "11", "11": "11"})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: deepcopy(ambiguous_lookup))
    monkeypatch.setattr(api_public, "_remote_taskterminal_bindings_checked", lambda task_id: ([], True))
    monkeypatch.setattr(api_public, "_resolve_created_schedule_task_id", lambda *args, **kwargs: "9001")
    monkeypatch.setattr(
        api_public,
        "_remote_delete_schedule_entry",
        lambda schedule_name: captured["deleted"].append(schedule_name) or captured["catalog"].discard(schedule_name),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: list(captured["catalog"]))
    monkeypatch.setattr(
        api_public,
        "_build_remote_task_payload",
        lambda schedule_name, task, media_map, terminal_map, remote_fallback=None: {
            "taskname": task.get("taskname") or "prep-bell",
            "customName": task.get("customName") or task.get("taskname") or "prep-bell",
            "starttime": task.get("starttime") or "07:50:00",
            "startdate": task.get("startdate") or "2026-01-18",
            "enddate": task.get("enddate") or "2039-01-31",
            "mediaid": "911",
        },
    )

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/sechetask":
            return {"data": {"id": 9001}}
        if method == "POST" and path == "/task/jsontaskterminal":
            return {"ok": True}
        raise AssertionError(f"unexpected remote request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(
        api_public,
        "_remote_set_schedule_status",
        lambda schedule_name, enabled: (_ for _ in ()).throw(HTTPException(status_code=502, detail="status failed")),
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create spring-schedule",
        {"schedule_name": "spring-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "新作息方案" in reply
    assert "回滚" in reply or "再试一次" in reply
    assert state["missing_slots"] == []
    assert len(logs) == 1
    assert logs[0]["details"]["failure_reason"] == "status failed"
    assert logs[0]["details"]["user_reason"]
    assert logs[0]["details"]["retryable"] is True
    assert captured["deleted"] == ["spring-schedule"]
    assert "spring-schedule" not in captured["catalog"]


def test_create_scheme_manual_hidden_slot_is_ignored_on_shared_path(monkeypatch) -> None:
    committed: dict = {}
    template_schedule = {
        "schedule_name": "template",
        "tasks": [_stale_terminal_bound_task()],
    }

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("primary", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(api_public, "_store_terminalinfo_items", _assistant_playback_terminal_items)

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create spring-schedule",
        {
            "schedule_name": "spring-schedule",
            "__assistant_create_schedule_terminal_scope": "all_playback_terminals",
        },
    )

    assert "spring-schedule" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["creation_path"] == "local_template_only"
    saved_task = committed["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["9"]
    assert saved_task["liveterminalid"] == "9"


def test_create_scheme_assistant_scope_name_fallback_uses_lookup_values(monkeypatch) -> None:
    committed: dict = {}
    template_schedule = {
        "schedule_name": "template",
        "tasks": [_stale_terminal_bound_task()],
    }

    _set_default_schedule_kind(monkeypatch, "primary")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("primary", local_template_file="school_summer_default.json"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [
            {"id": 46, "type": 11, "ip": "192.168.3.26", "zone": 0},
            {"id": 25, "type": 24, "zone": 0},
        ],
    )

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "create fallback-schedule",
        {"schedule_name": "fallback-schedule"},
        assistant_terminal_scope=api_public._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS,
    )

    assert "fallback-schedule" in reply
    assert state["missing_slots"] == []
    assert logs[0]["details"]["creation_path"] == "local_template_only"
    saved_task = committed["schedule"]["tasks"][0]
    assert saved_task["terminalids"] == ["46", "25"]
    assert saved_task["terminalnames"] == ["192.168.3.26", "25"]
    assert saved_task["liveterminalname"] == "192.168.3.26"
    assert saved_task["taskterminal"] == [
        {"terminalid": "25", "groupid": 0, "groupid_present": True, "terminalname": "25"},
        {"terminalid": "46", "groupid": 0, "groupid_present": True, "terminalname": "192.168.3.26"},
    ]
    assert saved_task["location"] == [
        [api_public._zone_label(0), "25"],
        [api_public._zone_label(0), "192.168.3.26"],
    ]


def test_create_scheme_rebinds_template_media_by_name_and_persists_catalog(monkeypatch) -> None:
    catalog_path = Path("virtual-template-catalog.json")
    writes: list[tuple[Path, object]] = []
    committed: dict = {}
    template_schedule = {
        "schedule_name": "中学夏季作息方案",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
                "mediaid": "999",
                "medianame": "上课铃",
                "audio": "上课铃",
            }
        ],
    }
    catalog_payload = {
        "schedules": [deepcopy(template_schedule)],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }

    _set_default_schedule_kind(monkeypatch, "中学", season="夏季")
    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_CATALOG_PATH", catalog_path)
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("中学", season="夏季", source_schedule_name="中学夏季作息方案"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_schedule_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library([{"mediaid": "911", "name": "上课铃"}]),
    )
    monkeypatch.setattr(
        api_public,
        "_read_json_optional",
        lambda path: deepcopy(catalog_payload) if path == catalog_path else None,
    )
    monkeypatch.setattr(
        api_public,
        "_write_json",
        lambda path, payload: writes.append((path, deepcopy(payload))),
    )

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "新建一个夏季作息",
        {"schedule_name": "夏季新作息"},
    )

    assert "夏季新作息" in reply
    assert state["missing_slots"] == []
    assert committed["schedule"]["tasks"][0]["mediaid"] == "911"
    assert committed["schedule"]["tasks"][0]["medianame"] == "上课铃"
    assert logs[0]["details"]["template_media_rebound_count"] == 1
    assert len(writes) == 1
    assert writes[0][0] == catalog_path
    assert writes[0][1]["schedules"][0]["tasks"][0]["mediaid"] == "911"


def test_normalize_phase1_template_media_bindings_persists_template_file(monkeypatch) -> None:
    writes: list[tuple[object, object]] = []
    template_schedule = {
        "schedule_name": "学校标准模板",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "mediaid": "999",
                "medianame": "上课铃",
                "audio": "上课铃",
            }
        ],
    }

    class FakeTemplateFile:
        def __init__(self, text: str) -> None:
            self._text = text

        def exists(self) -> bool:
            return True

        def read_text(self, encoding: str = "utf-8", errors: str | None = None) -> str:
            del encoding
            del errors
            return self._text

    class FakeTemplateDir:
        def __init__(self, files: dict[str, FakeTemplateFile]) -> None:
            self._files = files

        def __truediv__(self, name: str) -> FakeTemplateFile:
            return self._files[name]

    raw_template = {
        "schedule_name": "学校标准模板",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "mediaid": "999",
                "medianame": "上课铃",
                "audio": "上课铃",
            }
        ],
    }
    fake_file = FakeTemplateFile(json.dumps(raw_template, ensure_ascii=False))
    monkeypatch.setattr(api_public, "PHASE1_TEMPLATE_RESOURCE_DIR", FakeTemplateDir({"school.json": fake_file}))
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library([{"mediaid": "911", "name": "上课铃"}]),
    )
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: writes.append((path, deepcopy(payload))))

    details = api_public._normalize_phase1_template_media_bindings(
        template_schedule,
        local_template_file="school.json",
    )

    assert template_schedule["tasks"][0]["mediaid"] == "911"
    assert details["template_media_rebound_count"] == 1
    assert len(writes) == 1
    assert writes[0][1]["tasks"][0]["mediaid"] == "911"


def test_normalize_phase1_template_media_bindings_matches_extensionless_template_name_to_mp3_library_name(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "学校标准模板",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "medianame": "上课铃",
                "audio": "上课铃",
            }
        ],
    }
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library([{"mediaid": "130", "folderid": "2", "name": "上课铃.mp3"}]),
    )

    details = api_public._normalize_phase1_template_media_bindings(template_schedule)

    assert template_schedule["tasks"][0]["mediaid"] == "130"
    assert template_schedule["tasks"][0]["medianame"] == "上课铃.mp3"
    assert template_schedule["tasks"][0]["audio"] == "上课铃.mp3"
    assert details["template_media_rebound_count"] == 1
    assert details["template_media_rebound"][0]["folderid"] == "2"


def test_create_scheme_returns_missing_media_error_before_commit(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "中学夏季作息方案",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
                "medianame": "上课铃",
                "audio": "上课铃",
            }
        ],
    }

    _set_default_schedule_kind(monkeypatch, "中学", season="夏季")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("中学", season="夏季", source_schedule_name="中学夏季作息方案"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_schedule_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library([{"mediaid": "912", "name": "下课铃"}]),
    )
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("commit should not be called")),
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "新建一个夏季作息",
        {"schedule_name": "夏季新作息"},
    )

    assert "目前音频库缺少能够生成作息的媒体" in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["missing_media_names"] == ["上课铃"]
    assert logs[0]["details"]["missing_media_names"] == ["上课铃"]


def test_normalize_phase1_template_media_bindings_prefers_smallest_folderid_then_mediaid(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "学校标准模板",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "mediaid": "999",
                "medianame": "上课铃.mp3",
                "audio": "上课铃.mp3",
            }
        ],
    }
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library(
            [
                {"mediaid": "140", "folderid": "3", "name": "上课铃.mp3"},
                {"mediaid": "131", "folderid": "2", "name": "上课铃.mp3"},
                {"mediaid": "130", "folderid": "2", "name": "上课铃.mp3"},
            ]
        ),
    )

    details = api_public._normalize_phase1_template_media_bindings(template_schedule)

    assert template_schedule["tasks"][0]["mediaid"] == "130"
    assert template_schedule["tasks"][0]["medianame"] == "上课铃.mp3"
    assert details["template_media_rebound_count"] == 1
    assert details["template_media_rebound"][0]["folderid"] == "2"


def test_create_scheme_uses_stable_template_media_binding_for_duplicate_mp3_names(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "中学夏季作息方案",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
                "mediaid": "911",
                "medianame": "上课铃.mp3",
                "audio": "上课铃.mp3",
            }
        ],
    }
    committed: dict[str, object] = {}

    _set_default_schedule_kind(monkeypatch, "中学", season="夏季")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("中学", season="夏季", source_schedule_name="中学夏季作息方案"),
    )
    monkeypatch.setattr(api_public, "_load_phase1_local_schedule_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library(
            [
                {"mediaid": "140", "folderid": "3", "name": "上课铃.mp3"},
                {"mediaid": "130", "folderid": "2", "name": "上课铃.mp3"},
            ]
        ),
    )

    def fake_commit(new_schedule: dict, *, sync_remote: bool) -> dict:
        committed["schedule"] = deepcopy(new_schedule)
        committed["sync_remote"] = sync_remote
        return deepcopy(new_schedule)

    monkeypatch.setattr(api_public, "_commit_phase1_created_schedule", fake_commit)

    reply, state, logs = api_public._apply_create_scheme_intent(
        "新建一个春季作息",
        {"schedule_name": "春季新作息"},
    )

    assert "春季新作息" in reply
    assert state["missing_slots"] == []
    assert committed["schedule"]["tasks"][0]["mediaid"] == "130"
    assert committed["schedule"]["tasks"][0]["medianame"] == "上课铃.mp3"
    assert logs[0]["details"]["template_media_rebound"][0]["folderid"] == "2"


def test_create_scheme_returns_remote_media_unavailable_error_before_commit(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "中学夏季作息方案",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
                "medianame": "上课铃",
                "audio": "上课铃",
            }
        ],
    }
    writes: list[tuple[object, object]] = []

    _set_default_schedule_kind(monkeypatch, "中学", season="夏季")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("中学", season="夏季", source_schedule_name="中学夏季作息方案"),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_load_phase1_local_schedule_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library(
            [],
            source="remote",
            remote_expected=True,
            remote_fetch_ok=False,
            fallback_used=False,
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("commit should not be called")),
    )
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: writes.append((path, deepcopy(payload))))

    reply, state, logs = api_public._apply_create_scheme_intent(
        "新建一个夏季作息",
        {"schedule_name": "夏季新作息"},
    )

    assert "远端媒体库" in reply
    assert state["missing_slots"] == []
    assert writes == []
    assert state["diagnostics"][0]["failure_code"] == "template_media_remote_unavailable"
    assert state["diagnostics"][0]["template_media_source"] == "remote"
    assert state["diagnostics"][0]["template_media_fallback_used"] is False
    assert logs[0]["details"]["template_media_source"] == "remote"
    assert logs[0]["details"]["template_media_remote_fetch_ok"] is False


def test_create_scheme_returns_remote_media_empty_error_before_commit(monkeypatch) -> None:
    template_schedule = {
        "schedule_name": "中学夏季作息方案",
        "tasks": [
            {
                "taskname": "早读开始铃",
                "starttime": "07:50:00",
                "startdate": "2026-01-18",
                "enddate": "2039-01-31",
                "weekdays": ["周一", "周二", "周三", "周四", "周五"],
                "medianame": "上课铃",
                "audio": "上课铃",
            }
        ],
    }

    _set_default_schedule_kind(monkeypatch, "中学", season="夏季")
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_select_phase1_template_entry",
        _select_phase1_template_entry_result("中学", season="夏季", source_schedule_name="中学夏季作息方案"),
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_load_phase1_local_schedule_template", lambda _: deepcopy(template_schedule))
    monkeypatch.setattr(
        api_public,
        "_phase1_template_media_library_items",
        lambda: _phase1_media_library(
            [],
            source="remote",
            remote_expected=True,
            remote_fetch_ok=True,
            fallback_used=False,
        ),
    )
    monkeypatch.setattr(
        api_public,
        "_commit_phase1_created_schedule",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("commit should not be called")),
    )

    reply, state, logs = api_public._apply_create_scheme_intent(
        "新建一个夏季作息",
        {"schedule_name": "夏季新作息"},
    )

    assert "远端媒体库" in reply
    assert state["missing_slots"] == []
    assert state["diagnostics"][0]["failure_code"] == "template_media_remote_unavailable"
    assert state["diagnostics"][0]["template_media_source"] == "remote"
    assert state["diagnostics"][0]["template_media_remote_fetch_ok"] is True
    assert logs[0]["details"]["template_media_fallback_used"] is False
