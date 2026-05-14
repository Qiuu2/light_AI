from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_row_to_all_task_row_parses_hms_duration() -> None:
    row = api_public._row_to_all_task_row(
        {
            "id": "501",
            "name": "broadcast",
            "time": "08:00",
            "durationMode": "duration",
            "duration": "00:05:00",
        },
        2,
    )

    assert row["timelength"] == "300"
    assert row["timelengthtype"] == "1"


def test_normalize_view_task_parses_hms_timelength() -> None:
    task = api_public._normalize_view_task(
        {
            "taskid": "601",
            "taskname": "broadcast",
            "starttime": "08:00:00",
            "timelength": "00:05:00",
            "timelengthtype": "1",
        }
    )

    assert task["durationMode"] == "duration"
    assert task["duration"] == "5"
    assert task["loop"] == 1


def test_normalize_view_task_preserves_broadcast_seconds_for_hms_editor() -> None:
    task = api_public._normalize_view_task(
        {
            "taskid": "602",
            "taskname": "broadcast",
            "starttime": "08:00:00",
            "timelength": "300",
            "timelengthtype": "1",
        },
        kind="broadcast",
    )

    assert task["durationMode"] == "duration"
    assert task["duration"] == "300"
    assert task["loop"] == 1


def test_task_duration_seconds_accepts_hms_timelength(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    seconds = api_public._task_duration_seconds(
        {
            "timelength": "00:05:00",
            "timelengthtype": "1",
        }
    )

    assert seconds == 300


def test_task_duration_seconds_preserves_schedule_seconds_for_numeric_timelength(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    seconds = api_public._task_duration_seconds(
        {
            "timelength": "20",
            "timelengthtype": "1",
        }
    )

    assert seconds == 20


def test_task_duration_seconds_preserves_one_second_numeric_timelength(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    seconds = api_public._task_duration_seconds(
        {
            "timelength": "1",
            "timelengthtype": "1",
        }
    )

    assert seconds == 1


def test_task_duration_seconds_keeps_loop_mode_as_minutes(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    seconds = api_public._task_duration_seconds(
        {
            "timelength": "2",
            "timelengthtype": "2",
        }
    )

    assert seconds == 120


def test_task_matches_dated_query_window_keeps_short_schedule_seconds(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    task = {
        "starttime": "08:20:00",
        "startdate": "2026-04-26",
        "enddate": "2026-04-26",
        "timelength": "20",
        "timelengthtype": "1",
        "execmode": "127",
    }

    assert api_public._task_matches_dated_query_window(
        task,
        datetime(2026, 4, 26, 8, 20, 10),
        datetime(2026, 4, 26, 8, 20, 15),
    ) is True
    assert api_public._task_matches_dated_query_window(
        task,
        datetime(2026, 4, 26, 8, 20, 21),
        datetime(2026, 4, 26, 8, 20, 22),
    ) is False


def test_task_matches_dated_query_window_does_not_expand_one_second_task(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    task = {
        "starttime": "11:40:00",
        "startdate": "2026-04-26",
        "enddate": "2026-04-26",
        "timelength": "1",
        "timelengthtype": "1",
        "execmode": "127",
    }

    assert api_public._task_matches_dated_query_window(
        task,
        datetime(2026, 4, 26, 11, 40, 0),
        datetime(2026, 4, 26, 11, 40, 1),
    ) is True
    assert api_public._task_matches_dated_query_window(
        task,
        datetime(2026, 4, 26, 11, 40, 1),
        datetime(2026, 4, 26, 11, 40, 2),
    ) is False


def test_task_matches_query_time_uses_real_seconds_for_time_range(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", False)

    task = {
        "starttime": "09:50:00",
        "timelength": "8",
        "timelengthtype": "1",
    }

    assert api_public._task_matches_query_time(
        task,
        datetime(2026, 4, 26, 9, 50, 0),
        datetime(2026, 4, 26, 9, 50, 8),
        "09:50:00",
        "09:50:08",
    ) is True
    assert api_public._task_matches_query_time(
        task,
        datetime(2026, 4, 26, 9, 50, 8),
        datetime(2026, 4, 26, 9, 50, 9),
        "09:50:08",
        "09:50:09",
    ) is False


def test_parse_hms_duration_seconds_accepts_remote_schedule_format() -> None:
    seconds = api_public._parse_hms_duration_seconds("2000-01-01 00:05:00")

    assert seconds == 300


def test_build_remote_task_payload_formats_duration_for_schedule_remote() -> None:
    payload = api_public._build_remote_task_payload(
        "summer",
        {
            "taskname": "放学铃",
            "starttime": "16:15:00",
            "startdate": "2026-03-19",
            "enddate": "2026-03-19",
            "mediaid": "912",
            "medianame": "下课铃",
            "terminalids": ["9"],
            "durationMode": "duration",
            "duration": "300",
        },
        {},
        {},
    )

    assert payload["timelength"] == "300"
    assert payload["timelengthtype"] == "1"


def test_build_remote_task_payload_accepts_clock_duration_for_schedule_remote() -> None:
    payload = api_public._build_remote_task_payload(
        "summer",
        {
            "taskname": "放学铃",
            "starttime": "16:15:00",
            "startdate": "2026-03-19",
            "enddate": "2026-03-19",
            "mediaid": "912",
            "medianame": "下课铃",
            "terminalids": ["9"],
            "durationMode": "duration",
            "duration": "00:05:00",
        },
        {},
        {},
    )

    assert payload["timelength"] == "300"
    assert payload["timelengthtype"] == "1"


def test_taskinfo_timelength_accepts_hms_duration_when_remote_uses_seconds(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_TASKINFO_DURATION_AS_SECONDS", True)

    timelength, timelengthtype = api_public._taskinfo_timelength(
        {
            "durationMode": "duration",
            "duration": "00:05:00",
        }
    )

    assert timelength == 300
    assert timelengthtype == 1


def test_build_remote_taskinfo_payload_formats_duration_for_remote() -> None:
    payload, terminal_ids, media_id = api_public._build_remote_taskinfo_payload(
        "broadcast",
        {
            "taskname": "文件广播",
            "starttime": "08:00:00",
            "startdate": "2026-03-19",
            "enddate": "2026-03-19",
            "mediaid": "912",
            "medianame": "下课铃",
            "terminalids": ["9"],
            "durationMode": "duration",
            "duration": "00:05:00",
        },
        {},
        {},
    )

    assert payload["timelength"] == "300"
    assert payload["timelengthtype"] == "1"
    assert terminal_ids == ["9"]
    assert media_id == "912"
