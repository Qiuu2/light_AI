from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_move_terminal_zone_removes_only_current_zone_association(monkeypatch) -> None:
    captured: dict = {}
    invalidated: list[list[str] | None] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_sync_remote_data", lambda force=False, keys=None: {"all_loc": True})
    monkeypatch.setattr(api_public, "_invalidate_zone_runtime_caches", lambda zone_ids=None: invalidated.append(zone_ids))

    def fake_remote_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = kwargs.get("json_body")
        return {"status": "ok"}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    result = api_public.move_terminal_zone({
        "deviceId": "9",
        "sourceZoneId": "3",
        "targetZoneId": "unassigned",
    })

    assert captured == {
        "method": "DELETE",
        "path": "/terminal/zoneterminal",
        "json_body": {"data": [{"id": 9, "terminalid": 9, "taskid": 3}]},
    }
    assert result["status"] == "ok"
    assert result["deviceId"] == "9"
    assert result["sourceZoneId"] == "3"
    assert result["targetZoneId"] == "unassigned"
    assert result["operation"] == "remove_from_zone"
    assert "without deleting the terminal device" in result["message"]
    assert invalidated == [["3"]]


def test_move_terminal_zone_requires_source_zone_when_moving_to_unassigned(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)

    with pytest.raises(api_public.HTTPException) as exc_info:
        api_public.move_terminal_zone({
            "deviceId": "9",
            "targetZoneId": "unassigned",
        })

    assert exc_info.value.status_code == 400
    assert "sourceZoneId is required" in str(exc_info.value.detail)


def test_move_terminal_zone_rejects_invalid_target_zone(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)

    with pytest.raises(api_public.HTTPException) as exc_info:
        api_public.move_terminal_zone({
            "deviceId": "9",
            "sourceZoneId": "3",
            "targetZoneId": "invalid-zone",
        })

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid targetZoneId"


def test_move_terminal_zone_invalidates_source_and_target_zone_caches(monkeypatch) -> None:
    invalidated: list[list[str] | None] = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_sync_remote_data", lambda force=False, keys=None: {"all_loc": True})
    monkeypatch.setattr(api_public, "_invalidate_zone_runtime_caches", lambda zone_ids=None: invalidated.append(zone_ids))
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"status": "ok"})

    result = api_public.move_terminal_zone({
        "deviceId": "9",
        "sourceZoneId": "3",
        "targetZoneId": "5",
    })

    assert result["status"] == "ok"
    assert result["operation"] == "add_to_zone"
    assert invalidated == [["3", "5"]]
