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


def _session_headers() -> dict[str, str]:
    session = api_public._create_local_session("remote-test-token", "tester", "test")
    return {"X-Token": session["token"]}


@pytest.fixture(autouse=True)
def _isolate_assistant_settings(monkeypatch):
    original_entry = deepcopy(api_public.DATA_STORE["assistant_settings"])
    api_public._store_set(
        "assistant_settings",
        api_public._normalize_assistant_settings_payload(
            {"default_schedule_kind": "", "default_schedule_season": ""}
        ),
    )
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)
    yield
    api_public.DATA_STORE["assistant_settings"] = original_entry


def test_get_assistant_settings_returns_empty_default(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)

    with TestClient(api_public.app) as client:
        response = client.get("/data/assistant_settings", headers=_session_headers())

    assert response.status_code == 200
    assert response.json() == {
        "default_schedule_kind": "",
        "default_schedule_season": "",
        "allowed_schedule_kinds": list(api_public.ALLOWED_SCHEDULE_KINDS),
        "allowed_schedule_seasons": list(api_public.ALLOWED_SCHEDULE_SEASONS),
    }


def test_put_assistant_settings_persists_supported_kind(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    supported_kind = api_public.ALLOWED_SCHEDULE_KINDS[1]
    supported_season = api_public.ALLOWED_SCHEDULE_SEASONS[0]

    with TestClient(api_public.app) as client:
        response = client.put(
            "/data/assistant_settings",
            json={
                "default_schedule_kind": supported_kind,
                "default_schedule_season": supported_season,
            },
            headers=_session_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "default_schedule_kind": supported_kind,
        "default_schedule_season": supported_season,
        "allowed_schedule_kinds": list(api_public.ALLOWED_SCHEDULE_KINDS),
        "allowed_schedule_seasons": list(api_public.ALLOWED_SCHEDULE_SEASONS),
    }
    assert api_public._load_default_schedule_kind() == supported_kind
    assert api_public._load_default_schedule_season() == supported_season


def test_put_assistant_settings_rejects_invalid_kind(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)

    with TestClient(api_public.app) as client:
        response = client.put(
            "/data/assistant_settings",
            json={"default_schedule_kind": "invalid-kind"},
            headers=_session_headers(),
        )

    assert response.status_code == 400
    assert "default_schedule_kind" in response.json()["detail"]
    assert api_public._load_default_schedule_kind() == ""
    assert api_public._load_default_schedule_season() == ""


def test_put_assistant_settings_rejects_invalid_season(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)

    with TestClient(api_public.app) as client:
        response = client.put(
            "/data/assistant_settings",
            json={
                "default_schedule_kind": api_public.ALLOWED_SCHEDULE_KINDS[0],
                "default_schedule_season": "invalid-season",
            },
            headers=_session_headers(),
        )

    assert response.status_code == 400
    assert "default_schedule_season" in response.json()["detail"]
    assert api_public._load_default_schedule_kind() == ""
    assert api_public._load_default_schedule_season() == ""


def test_load_assistant_settings_initializes_missing_runtime_file(monkeypatch) -> None:
    settings_path = Path("virtual-assistant-settings.json")
    writes: list[tuple[Path, object]] = []

    monkeypatch.setattr(api_public, "_read_json_optional", lambda path: None if path == settings_path else {})
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: writes.append((path, deepcopy(payload))))
    monkeypatch.setitem(api_public.DATA_STORE["assistant_settings"], "path", settings_path)
    monkeypatch.setitem(api_public.DATA_STORE["assistant_settings"], "payload", None)
    monkeypatch.setitem(api_public.DATA_STORE["assistant_settings"], "loaded", False)

    payload = api_public._load_assistant_settings_payload()

    assert payload == {
        "default_schedule_kind": "",
        "default_schedule_season": "",
    }
    assert writes == [(settings_path, payload)]
