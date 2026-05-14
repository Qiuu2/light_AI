from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_get_terminalinfo_hides_type_zero_terminals(monkeypatch) -> None:
    payload = {
        "data": [
            {"id": 1, "name": "server-251", "type": 0, "zone": 1},
            {"id": 2, "name": "teaching-building-terminal", "type": 1, "zone": 1},
            {"id": 3, "name": "playground-terminal", "zone": 2},
        ]
    }

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_terminalinfo_payload", lambda force=False: deepcopy(payload))

    result = api_public.get_terminalinfo()

    assert [item["id"] for item in result["data"]] == [2, 3]
    assert all(str(item.get("type")).strip() != "0" for item in result["data"])


def test_get_terminals_by_zone_hides_type_zero_terminals(monkeypatch) -> None:
    payload = {
        "data": [
            {"id": 1, "name": "server-251", "type": 0, "zone": 8},
            {"id": 2, "name": "classroom-a", "type": 1, "zone": 8},
            {"id": 3, "name": "classroom-b", "zone": 8},
        ]
    }

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_zoneterminal_cached", lambda zone_id: deepcopy(payload))

    result = api_public.get_terminals_by_zone("8")

    assert [item["id"] for item in result["data"]] == [2, 3]
    assert all(str(item.get("type")).strip() != "0" for item in result["data"])


def test_get_terminal_zones_adds_name_alias_from_zonename(monkeypatch) -> None:
    payload = {"data": [{"id": 1, "zonename": "教学区", "description": ""}]}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_remote_terzone_cached", lambda force=False: deepcopy(payload))

    result = api_public.get_terminal_zones()

    assert result["data"][0]["zonename"] == "教学区"
    assert result["data"][0]["name"] == "教学区"


def test_fetch_all_terminal_data_normalizes_zone_names_and_filters_terminal_visibility(monkeypatch) -> None:
    zones_payload = {"data": [{"id": 1, "zonename": "教学区"}]}
    terminal_info_payload = {
        "data": [
            {"id": 1, "name": "server-251", "type": 0, "zone": 1},
            {"id": 2, "name": "teaching-building-terminal", "type": 1, "zone": 1},
            {"id": 3, "name": "playground-terminal", "zone": 0},
        ]
    }
    zone_terminal_payload = {
        "data": [
            {"id": 1, "name": "server-251", "type": 0, "zone": 1},
            {"id": 2, "name": "teaching-building-terminal", "type": 1, "zone": 1},
        ]
    }

    monkeypatch.setattr(api_public, "_remote_terzone_cached", lambda force=False: deepcopy(zones_payload))
    monkeypatch.setattr(api_public, "_remote_terminalinfo_payload", lambda force=False: deepcopy(terminal_info_payload))
    monkeypatch.setattr(
        api_public,
        "_parallel_map",
        lambda values, func: [deepcopy(zone_terminal_payload) for _ in values],
    )

    result = api_public._fetch_all_terminal_data(force=True)

    assert result["zones"]["data"][0]["zonename"] == "教学区"
    assert result["zones"]["data"][0]["name"] == "教学区"
    assert [item["id"] for item in result["terminal_info"]["data"]] == [2, 3]
    assert [item["id"] for item in result["zone_terminals"]["1"]["data"]] == [2]
