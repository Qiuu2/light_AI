from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_workweek_execmode_mapping_is_consistent() -> None:
    weekdays = ["周一", "周二", "周三", "周四", "周五"]

    assert api_public._execmode_from_weekdays(weekdays) == 62
    assert api_public._weekdays_from_execmode(62) == weekdays
    assert api_public._weekdays_from_execmode(31) == ["周二", "周三", "周四", "周五", "周六"]


def test_perform_import_from_template_normalizes_new_schedule_to_workweek(monkeypatch) -> None:
    captured: dict = {}

    class FakeTemplatePath:
        def exists(self) -> bool:
            return True

        def read_text(self, encoding: str = "utf-8") -> str:
            del encoding
            return json.dumps(
                {
                    "schedules": [
                        {
                            "schedule_name": "冬季作息",
                            "tasks": [
                                {
                                    "taskid": "9001",
                                    "taskname": "早读开始铃",
                                    "weekdays": ["周二", "周三", "周四", "周五", "周六"],
                                    "execmode": 31,
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(api_public, "TEMPLATES_PATH", FakeTemplatePath())
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: {"schedules": []})
    monkeypatch.setattr(
        api_public,
        "_save_schedules_payload",
        lambda payload, **kwargs: captured.update({"payload": payload, "kwargs": kwargs}),
    )

    final_name, task_count = api_public._perform_import_from_template("冬季作息", "新方案")

    assert final_name == "新方案"
    assert task_count == 1
    saved_schedule = captured["payload"]["schedules"][0]
    saved_task = saved_schedule["tasks"][0]
    assert saved_schedule["schedule_name"] == "新方案"
    assert saved_task["weekdays"] == ["周一", "周二", "周三", "周四", "周五"]
    assert saved_task["execmode"] == 62
    assert saved_task["sechename"] == "新方案"
    assert saved_task["info"] == "新方案"
