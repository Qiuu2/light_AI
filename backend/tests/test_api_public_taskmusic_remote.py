from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_remote_replace_taskmusic_uses_swagger_bodies(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    def fake_remote_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_task_media_ids", lambda task_id: ["21", "22"])

    api_public._remote_replace_taskmusic("74587", ["12", "13"])

    assert calls[0][0] == "DELETE"
    assert calls[0][1] == "/task/taskmusic"
    assert calls[0][2]["json_body"] == {
        "data": [
            {"id": 74587, "mediaid": 21},
            {"id": 74587, "mediaid": 22},
        ]
    }
    assert calls[0][2]["form_body"] is None
    assert calls[0][2]["allow_form_retry"] is False
    assert "params" not in calls[0][2]

    assert calls[1][0] == "POST"
    assert calls[1][1] == "/task/taskmusic"
    assert calls[1][2]["json_body"] == {
        "data": [
            {"id": 74587, "mediaid": 12},
            {"id": 74587, "mediaid": 13},
        ]
    }
    assert calls[1][2]["form_body"] is None
    assert calls[1][2]["allow_form_retry"] is False


def test_remote_replace_taskmusic_defaults_missing_mediaid_to_zero(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    def fake_remote_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "_remote_task_media_ids", lambda task_id: [])

    api_public._remote_replace_taskmusic("74589", [])

    assert calls[0][0] == "DELETE"
    assert calls[0][1] == "/task/taskmusic"
    assert calls[0][2]["json_body"] == {"data": [{"id": 74589, "mediaid": 0}]}
    assert calls[1][0] == "POST"
    assert calls[1][1] == "/task/taskmusic"
    assert calls[1][2]["json_body"] == {"data": [{"id": 74589, "mediaid": 0}]}


def test_remote_add_taskinfo_post_payload_omits_legacy_id(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "existing-task",
                "tasktype": 2,
                "startdate": "2026-03-10",
                "starttime": "07:00:00",
                "mediaid": 8,
                "liveterminalid": 9,
            },
            ["9"],
            "8",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)

    def fake_remote_request(method, path, **kwargs):
        if method == "POST" and path == "/task/taskinfo":
            captured["json_body"] = kwargs.get("json_body")
            captured["form_body"] = kwargs.get("form_body")
            return {"data": {"taskid": "72134"}}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    task = {"taskid": "72134", "id": "72134", "taskname": "existing-task"}
    task_id = api_public._remote_add_taskinfo("broadcast", task, {}, {})

    assert task_id == "72134"
    payload = captured["form_body"] if captured["form_body"] is not None else captured["json_body"]
    assert "id" not in payload
    assert payload["taskid"] == "72134"


def test_remote_update_taskinfo_put_payload_omits_legacy_id(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        api_public,
        "_build_remote_taskinfo_payload",
        lambda kind, task, media_map, terminal_map, remote_fallback=None: (
            {
                "taskname": "existing-task",
                "tasktype": 2,
                "startdate": "2026-03-10",
                "starttime": "07:00:00",
                "mediaid": 8,
                "liveterminalid": 9,
            },
            ["9"],
            "8",
        ),
    )
    monkeypatch.setattr(api_public, "_remote_replace_taskmusic", lambda task_id, media_ids: None)
    monkeypatch.setattr(api_public, "_remote_replace_taskterminals", lambda task_id, terminal_ids: None)

    def fake_remote_request(method, path, **kwargs):
        if method == "PUT" and path == "/task/taskinfo":
            captured["json_body"] = kwargs.get("json_body")
            captured["form_body"] = kwargs.get("form_body")
            return {"ok": True}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    api_public._remote_update_taskinfo("72134", "broadcast", {"taskname": "existing-task"}, {}, {}, {})

    payload = captured["form_body"] if captured["form_body"] is not None else captured["json_body"]
    assert "id" not in payload
    assert payload["taskid"] == "72134"
