from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def _sequential_parallel(values, fn):
    return [fn(value) for value in values]


def test_enrich_task_links_uses_taskmedia_and_taskterminal(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)
    monkeypatch.setattr(api_public, "_parallel_map", _sequential_parallel)

    tasks = [
        {
            "taskid": "101",
            "taskname": "课前铃声",
            "taskmedia": [{"mediaid": "944", "medianame": "朴树-平凡之路"}],
            "taskterminal": [{"terminalid": "8", "terminalname": "讲台终端"}],
        }
    ]
    media_lookup = {"944": "朴树-平凡之路"}
    terminal_lookup = {"8": {"zone": "1", "name": "讲台终端"}}

    api_public._enrich_task_links(tasks, media_lookup, terminal_lookup)

    task = tasks[0]
    assert task["mediaid"] == "944"
    assert task["medianame"] == "朴树-平凡之路"
    assert task["audio"] == "朴树-平凡之路"
    assert task["terminalids"] == ["8"]
    assert task["terminalnames"] == ["讲台终端"]
    assert str(task["liveterminalid"]) == "8"
    assert task["liveterminalname"] == "讲台终端"
    assert task["location"] == [["区域一", "讲台终端"]]


def test_enrich_task_links_deep_fetches_missing_media_and_terminal(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)
    monkeypatch.setattr(api_public, "_parallel_map", _sequential_parallel)
    monkeypatch.setattr(api_public, "_remote_task_media_ids", lambda task_id: ["911"])
    monkeypatch.setattr(api_public, "_remote_task_terminal_ids", lambda task_id: ["3"])

    tasks = [{"taskid": "202", "taskname": "上课铃任务"}]
    media_lookup = {"911": "上课铃"}
    terminal_lookup = {"3": {"zone": "2", "name": "三年级一班终端"}}

    api_public._enrich_task_links(tasks, media_lookup, terminal_lookup)

    task = tasks[0]
    assert task["mediaid"] == "911"
    assert task["medianame"] == "上课铃"
    assert task["audio"] == "上课铃"
    assert task["terminalids"] == ["3"]
    assert task["terminalnames"] == ["三年级一班终端"]
    assert str(task["liveterminalid"]) == "3"
    assert task["location"] == [["区域二", "三年级一班终端"]]


def test_enrich_task_links_keeps_backup_fields_when_remote_fetch_returns_empty(monkeypatch) -> None:
    backup_payload = {
        "data": [
            {
                "taskid": "303",
                "mediaid": "777",
                "medianame": "旧媒体",
                "liveterminalid": 9,
                "liveterminalname": "旧终端",
                "terminalids": ["9"],
                "terminalnames": ["旧终端"],
                "location": [["区域九", "旧终端"]],
            }
        ]
    }

    def fake_store_get(key: str):
        if key == "all_task":
            return deepcopy(backup_payload)
        return None

    monkeypatch.setattr(api_public, "_store_get", fake_store_get)
    monkeypatch.setattr(api_public, "_parallel_map", _sequential_parallel)
    monkeypatch.setattr(api_public, "_remote_task_media_ids", lambda task_id: [])
    monkeypatch.setattr(api_public, "_remote_task_terminal_ids", lambda task_id: [])

    tasks = [{"taskid": "303", "taskname": "备份恢复任务"}]

    api_public._enrich_task_links(tasks, {}, {})

    task = tasks[0]
    assert task["mediaid"] == "777"
    assert task["medianame"] == "旧媒体"
    assert task["terminalids"] == ["9"]
    assert task["terminalnames"] == ["旧终端"]
    assert task["location"] == [["区域九", "旧终端"]]
    assert task["liveterminalname"] == "旧终端"


def test_build_all_task_payload_keeps_schedule_media_and_terminal_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "_store_terminalinfo_items",
        lambda: [{"id": "8", "name": "讲台终端", "zone": "1"}],
    )

    payload = {
        "schedules": [
            {
                "schedule_name": "春季作息",
                "tasks": [
                    {
                        "taskid": "1",
                        "taskname": "铃声",
                        "mediaid": "944",
                        "medianame": "朴树-平凡之路",
                        "starttime": "08:00:00",
                        "timelength": 10,
                        "timelengthtype": 1,
                        "terminalids": ["8"],
                    }
                ],
            }
        ],
        "broadcasts": [],
        "livecasts": [],
    }

    built = api_public._build_all_task_payload(payload)

    row = built["data"][0]
    assert row["mediaid"] == "944"
    assert row["terminalids"] == ["8"]
    assert row["terminalnames"] == ["讲台终端"]
    assert row["location"] == [["区域一", "讲台终端"]]


def test_schedule_task_and_broadcast_row_share_media_and_terminal_fields(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_store_get", lambda key: None)
    monkeypatch.setattr(api_public, "_parallel_map", _sequential_parallel)

    media_lookup = {"911": "上课铃"}
    terminal_lookup = {"8": {"zone": "1", "name": "讲台终端"}}

    schedule_tasks = [
        {
            "taskid": "401",
            "taskname": "早读开始铃",
            "starttime": "07:50:00",
            "timelength": 20,
            "timelengthtype": 1,
            "taskmedia": [{"mediaid": "911", "medianame": "上课铃"}],
            "taskterminal": [{"terminalid": "8", "terminalname": "讲台终端"}],
        }
    ]
    broadcast_items = [
        {
            "taskid": "401",
            "taskname": "早读开始铃",
            "starttime": "07:50:00",
            "timelength": 20,
            "timelengthtype": 1,
            "taskmedia": [{"mediaid": "911", "medianame": "上课铃"}],
            "taskterminal": [{"terminalid": "8", "terminalname": "讲台终端"}],
            "taskstate": 0,
            "enablestate": 1,
        }
    ]

    api_public._enrich_task_links(schedule_tasks, media_lookup, terminal_lookup)
    rows = api_public._map_remote_taskinfo_items(deepcopy(broadcast_items), media_lookup, terminal_lookup, "broadcast")

    schedule_task = schedule_tasks[0]
    row = rows[0]
    assert schedule_task["mediaid"] == row["mediaid"] == "911"
    assert schedule_task["audio"] == row["audio"] == "上课铃"
    assert schedule_task["terminalids"] == row["terminalids"] == ["8"]
    assert schedule_task["terminalnames"] == row["terminalnames"] == ["讲台终端"]
    assert schedule_task["location"] == row["location"] == [["区域一", "讲台终端"]]
