from __future__ import annotations

import json
import time
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import build_app
import backend.api_public as api_public


def _json_response_payload(response: JSONResponse) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_readyz_returns_not_ready_when_startup_not_finished(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", False)
    monkeypatch.setattr(api_public, "_missing_ready_data_keys", lambda: [])
    monkeypatch.setattr(api_public, "_loaded_data_keys", lambda: [])
    monkeypatch.setattr(api_public, "_runtime_data_dir_write_check", lambda: (True, ""))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_resolve_remote_base_url", lambda: "")
    monkeypatch.setattr(api_public, "_remote_sync_status_snapshot", lambda: {})

    response = api_public.readyz()
    payload = _json_response_payload(response)

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["remote_status"] == "starting"


def test_readyz_returns_ready_when_local_data_loaded_and_remote_disabled(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", True)
    monkeypatch.setattr(api_public, "_missing_ready_data_keys", lambda: [])
    monkeypatch.setattr(api_public, "_loaded_data_keys", lambda: ["all_audio", "all_loc", "broadcast_schedules"])
    monkeypatch.setattr(api_public, "_runtime_data_dir_write_check", lambda: (True, ""))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_resolve_remote_base_url", lambda: "")
    monkeypatch.setattr(api_public, "_remote_sync_status_snapshot", lambda: {})

    response = api_public.readyz()
    payload = _json_response_payload(response)

    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["remote_status"] == "disabled"
    assert payload["degraded"] is False


def test_readyz_returns_not_ready_when_remote_never_synced(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", True)
    monkeypatch.setattr(api_public, "_missing_ready_data_keys", lambda: [])
    monkeypatch.setattr(api_public, "_loaded_data_keys", lambda: ["all_audio", "all_loc", "broadcast_schedules"])
    monkeypatch.setattr(api_public, "_runtime_data_dir_write_check", lambda: (True, ""))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_remote_base_url", lambda: "http://remote/api")
    monkeypatch.setattr(
        api_public,
        "_remote_sync_status_snapshot",
        lambda: {
            "last_attempt_at": "2026-04-08 10:00:00",
            "last_success_at": "",
            "last_error": "remote sync incomplete (startup): all_audio",
            "consecutive_failures": 1,
            "last_duration_ms": 15.0,
        },
    )

    response = api_public.readyz()
    payload = _json_response_payload(response)

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["remote_status"] == "not_synced"
    assert "all_audio" in payload["remote_sync"]["last_error"]


def test_readyz_returns_degraded_when_remote_sync_has_previous_success(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", True)
    monkeypatch.setattr(api_public, "_missing_ready_data_keys", lambda: [])
    monkeypatch.setattr(api_public, "_loaded_data_keys", lambda: ["all_audio", "all_loc", "broadcast_schedules"])
    monkeypatch.setattr(api_public, "_runtime_data_dir_write_check", lambda: (True, ""))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_resolve_remote_base_url", lambda: "http://remote/api")
    monkeypatch.setattr(
        api_public,
        "_remote_sync_status_snapshot",
        lambda: {
            "last_attempt_at": "2026-04-08 10:05:00",
            "last_success_at": "2026-04-08 09:55:00",
            "last_error": "socket timeout",
            "consecutive_failures": 2,
            "last_duration_ms": 250.0,
        },
    )

    response = api_public.readyz()
    payload = _json_response_payload(response)

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["remote_status"] == "degraded"
    assert payload["degraded"] is True


def test_get_ops_status_returns_runtime_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "SERVICE_STARTED_AT", time.time() - 12.5)
    monkeypatch.setattr(api_public, "SERVICE_STARTED_AT_TEXT", "2026-04-08 10:00:00")
    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", True)
    monkeypatch.setattr(api_public, "_loaded_data_keys", lambda: ["all_audio", "broadcast_schedules"])
    monkeypatch.setattr(api_public, "_pending_action_count", lambda: 3)
    monkeypatch.setattr(api_public, "_resolve_remote_base_url_details", lambda: ("http://remote/api", "saved"))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(
        api_public,
        "_remote_sync_status_snapshot",
        lambda: {
            "thread_started": True,
            "thread_alive": True,
            "stop_requested": False,
            "last_attempt_at": "2026-04-08 10:10:00",
            "last_success_at": "2026-04-08 10:09:58",
            "last_error": "",
            "consecutive_failures": 0,
            "last_duration_ms": 22.0,
            "interval_seconds": 180.0,
        },
    )
    monkeypatch.setattr(api_public, "REMOTE_AUTO_SYNC_SECONDS", 180.0)
    monkeypatch.setattr(
        api_public,
        "psutil",
        SimpleNamespace(
            Process=lambda pid: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=123456)),
        ),
    )

    payload = api_public.get_ops_status()

    assert payload["status"] == "ok"
    assert payload["service"] == "ai-speaker-api"
    assert payload["process_rss_bytes"] == 123456
    assert payload["pending_action_count"] == 3
    assert payload["current_remote_base_url"] == "http://remote/api"
    assert payload["current_remote_base_url_source"] == "saved"
    assert payload["remote_sync"]["thread_alive"] is True
    assert payload["uptime_seconds"] >= 12


def test_build_app_exposes_readyz_and_ops_status(monkeypatch) -> None:
    monkeypatch.setattr(
        api_public,
        "readyz",
        lambda: JSONResponse(status_code=200, content={"status": "ready", "service": "ai-speaker-api"}),
    )
    monkeypatch.setattr(
        api_public,
        "get_ops_status",
        lambda: {"status": "ok", "service": "ai-speaker-api"},
    )
    monkeypatch.setattr(api_public, "_startup_load_data", lambda: None)
    monkeypatch.setattr(api_public, "_shutdown_runtime", lambda: None)

    with TestClient(build_app()) as client:
        ready = client.get("/readyz")
        ops = client.get("/ops/status")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ops.status_code == 200
    assert ops.json()["status"] == "ok"


def test_api_public_app_allows_readyz_and_ops_status_without_auth(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "STARTUP_LOAD_DONE", True)
    monkeypatch.setattr(api_public, "_missing_ready_data_keys", lambda: [])
    monkeypatch.setattr(api_public, "_loaded_data_keys", lambda: ["all_audio"])
    monkeypatch.setattr(api_public, "_runtime_data_dir_write_check", lambda: (True, ""))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: False)
    monkeypatch.setattr(api_public, "_resolve_remote_base_url", lambda: "")
    monkeypatch.setattr(api_public, "_resolve_remote_base_url_details", lambda: ("", "none"))
    monkeypatch.setattr(
        api_public,
        "_remote_sync_status_snapshot",
        lambda: {
            "thread_started": False,
            "thread_alive": False,
            "stop_requested": False,
            "last_attempt_at": "",
            "last_success_at": "",
            "last_error": "",
            "consecutive_failures": 0,
            "last_duration_ms": None,
            "interval_seconds": 180.0,
        },
    )
    monkeypatch.setattr(api_public, "_pending_action_count", lambda: 0)
    monkeypatch.setattr(api_public, "psutil", None)

    with TestClient(api_public.app) as client:
        ready = client.get("/readyz")
        ops = client.get("/ops/status")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ops.status_code == 200
    assert ops.json()["status"] == "ok"


def test_cors_middleware_options_defaults_to_locked_down_production(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.delenv("AI_SPEAKER_ENV", raising=False)
    monkeypatch.delenv("AI_SPEAKER_DEV_CORS", raising=False)

    options = api_public.cors_middleware_options()

    assert options["allow_origins"] == []
    assert options["allow_credentials"] is False


def test_cors_middleware_options_uses_explicit_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://127.0.0.1:5018, http://localhost:8080")
    monkeypatch.delenv("AI_SPEAKER_ENV", raising=False)
    monkeypatch.delenv("AI_SPEAKER_DEV_CORS", raising=False)

    options = api_public.cors_middleware_options()

    assert options["allow_origins"] == ["http://127.0.0.1:5018", "http://localhost:8080"]
    assert options["allow_credentials"] is True


def test_cors_middleware_options_allows_dev_defaults_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.setenv("AI_SPEAKER_ENV", "development")
    monkeypatch.delenv("AI_SPEAKER_DEV_CORS", raising=False)

    options = api_public.cors_middleware_options()

    assert "http://127.0.0.1:8080" in options["allow_origins"]
    assert options["allow_credentials"] is True
