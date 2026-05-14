from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def _pending_once_cancel() -> dict:
    return {
        "intent": "cancel_schedule",
        "schedule_name": "S",
        "task_ids": ["1", "2"],
        "time_start": "2026-03-21 08:00:00",
        "time_end": "2026-03-21 08:30:00",
        "date_specific": True,
        "created_at": api_public._now_str(),
    }


def _schedule_payload() -> dict:
    return {
        "schedules": [{"schedule_name": "S", "tasks": [{"taskid": "1"}, {"taskid": "2"}]}],
        "broadcasts": [],
        "livecasts": [],
    }


def _auth_session(name: str = "tester") -> dict[str, str]:
    return api_public._create_local_session("remote-test-token", name, "test")


def _auth_headers(name: str = "tester") -> dict[str, str]:
    session = _auth_session(name)
    return {"X-Token": session["token"]}


def _new_diag(phase: str, payload: dict | None = None) -> dict:
    diagnostics: list[dict] = []
    diag = api_public._new_remote_phase_diagnostic(
        diagnostics,
        diagnostic_id="diag-123",
        action="cancel",
        phase=phase,
        path="/task/enabletask",
        request_payload=payload,
    )
    assert diag is not None
    return diag


def test_remote_request_success_populates_diagnostic(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def read(self):
            return b'{"data":{"ok":true}}'

        def getcode(self):
            return 200

    monkeypatch.setattr(api_public.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    monkeypatch.setattr(
        api_public,
        "_resolve_remote_base_url_details",
        lambda value=None: ("http://example.test/api", "test"),
    )
    diagnostic = _new_diag("disable", {"taskid": "1"})

    result = api_public._remote_request(
        "POST",
        "/task/enabletask",
        form_body={"taskid": "1"},
        include_auth=False,
        diagnostic=diagnostic,
    )

    assert result == {"data": {"ok": True}}
    assert diagnostic["status_code"] == 200
    assert diagnostic["ok"] is True
    assert diagnostic["timeout"] is False
    assert diagnostic["response_body"] == {"data": {"ok": True}}
    assert diagnostic["request_payload"] == {"taskid": "1"}


def test_remote_request_http_error_populates_response_body(monkeypatch) -> None:
    def fake_urlopen(req, timeout):
        del req, timeout
        raise HTTPError(
            url="http://example.test/task/enabletask",
            code=500,
            msg="boom",
            hdrs=None,
            fp=BytesIO(b'{"message":"remote-bad"}'),
        )

    monkeypatch.setattr(api_public.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        api_public,
        "_resolve_remote_base_url_details",
        lambda value=None: ("http://example.test/api", "test"),
    )
    diagnostic = _new_diag("restore", {"taskid": "1"})

    with pytest.raises(api_public.HTTPException) as excinfo:
        api_public._remote_request(
            "POST",
            "/task/enabletask",
            form_body={"taskid": "1"},
            include_auth=False,
            diagnostic=diagnostic,
        )

    assert excinfo.value.status_code == 500
    assert diagnostic["status_code"] == 500
    assert diagnostic["ok"] is False
    assert diagnostic["timeout"] is False
    assert diagnostic["response_body"] == {"message": "remote-bad"}
    assert "remote-bad" in diagnostic["error_detail"]


def test_remote_request_timeout_populates_timeout_diagnostic(monkeypatch) -> None:
    def fake_urlopen(req, timeout):
        del req, timeout
        raise socket.timeout("timed out")

    monkeypatch.setattr(api_public.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        api_public,
        "_resolve_remote_base_url_details",
        lambda value=None: ("http://example.test/api", "test"),
    )
    diagnostic = _new_diag("restore", {"taskid": "1"})

    with pytest.raises(api_public.HTTPException) as excinfo:
        api_public._remote_request(
            "POST",
            "/task/enabletask",
            form_body={"taskid": "1"},
            include_auth=False,
            diagnostic=diagnostic,
        )

    assert excinfo.value.status_code == 504
    assert diagnostic["status_code"] == 504
    assert diagnostic["ok"] is False
    assert diagnostic["timeout"] is True
    assert diagnostic["response_body"] is None
    assert "POST /task/enabletask" in diagnostic["error_detail"]


def test_chat_api_returns_public_diagnostics_for_once_failure(monkeypatch) -> None:
    saved: dict = {}
    call_state = {"count": 0}

    class FakeEngine:
        def infer(self, text: str) -> dict:
            del text
            return {
                "intent": "cancel_schedule",
                "intent_confidence": 1.0,
                "slots": {},
                "missing_slots": [],
                "entities": {},
                "tokens": [],
                "tag_ids": [],
            }

    def fake_remote_request(method, path, json_body=None, diagnostic=None, **kwargs):
        del kwargs
        assert method == "POST"
        assert path == "/task/enabletask"
        assert isinstance(json_body, dict)
        call_state["count"] += 1
        if call_state["count"] == 1:
            if isinstance(diagnostic, dict):
                diagnostic["status_code"] = 200
                diagnostic["elapsed_ms"] = 12.5
                diagnostic["ok"] = True
                diagnostic["response_body"] = {"message": "disable-ok"}
                diagnostic["error_detail"] = ""
                diagnostic["timeout"] = False
            return {"message": "disable-ok"}
        if isinstance(diagnostic, dict):
            diagnostic["status_code"] = 504
            diagnostic["elapsed_ms"] = 15000.0
            diagnostic["ok"] = False
            diagnostic["response_body"] = {"message": "restore-timeout"}
            diagnostic["error_detail"] = "Remote request timed out after 15.0s: POST /task/enabletask"
            diagnostic["timeout"] = True
        raise api_public.HTTPException(
            status_code=504,
            detail="Remote request timed out after 15.0s: POST /task/enabletask",
        )

    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_pending_expired", lambda pending: False)
    monkeypatch.setattr(api_public, "_load_schedules_payload", lambda: deepcopy(_schedule_payload()))
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))
    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)
    monkeypatch.setattr(api_public, "ENGINE", FakeEngine())

    session = _auth_session("diag-once-failure")
    api_public._set_pending_action_for_scope(deepcopy(_pending_once_cancel()), session["token"])

    with TestClient(api_public.app) as client:
        response = client.post("/assistant/chat", json={"text": "一次性"}, headers={"X-Token": session["token"]})

    assert response.status_code == 200
    data = response.json()
    assert "未完整生效" in data["reply"]
    assert data["intent"] == "cancel_schedule"
    assert data["pending_action"] is not None
    assert len(data["diagnostics"]) == 2
    success_diag, failed_diag = data["diagnostics"]
    assert success_diag["phase"] == "disable"
    assert success_diag["ok"] is True
    assert success_diag["request_payload"] is None
    assert success_diag["response_body"] is None
    assert failed_diag["phase"] == "restore"
    assert failed_diag["ok"] is False
    assert failed_diag["request_payload"]["taskid"] == "1,2"
    assert failed_diag["response_body"] == {"message": "restore-timeout"}
    assert "POST /task/enabletask" in failed_diag["error_detail"]


def test_failed_once_override_persists_remote_diagnostics(monkeypatch) -> None:
    saved: dict = {}
    call_state = {"count": 0}
    action = {
        "schedule_name": "S",
        "task_ids": ["1", "2"],
        "time_start": "2026-03-21 08:00:00",
        "time_end": "2026-03-21 08:30:00",
    }

    def fake_remote_request(method, path, json_body=None, diagnostic=None, **kwargs):
        del kwargs
        assert method == "POST"
        assert path == "/task/enabletask"
        assert isinstance(json_body, dict)
        call_state["count"] += 1
        if call_state["count"] == 1:
            if isinstance(diagnostic, dict):
                diagnostic["status_code"] = 200
                diagnostic["elapsed_ms"] = 11.2
                diagnostic["ok"] = True
                diagnostic["response_body"] = {"message": "disable-ok"}
                diagnostic["error_detail"] = ""
                diagnostic["timeout"] = False
            return {"message": "disable-ok"}
        if isinstance(diagnostic, dict):
            diagnostic["status_code"] = 504
            diagnostic["elapsed_ms"] = 15000.0
            diagnostic["ok"] = False
            diagnostic["response_body"] = {"message": "restore-timeout"}
            diagnostic["error_detail"] = "Remote request timed out after 15.0s: POST /task/enabletask"
            diagnostic["timeout"] = True
        raise api_public.HTTPException(
            status_code=504,
            detail="Remote request timed out after 15.0s: POST /task/enabletask",
        )

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_load_overrides_payload", lambda: {"overrides": []})
    monkeypatch.setattr(api_public, "_save_overrides_payload", lambda data: saved.update({"data": deepcopy(data)}))
    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    with pytest.raises(api_public.HTTPException):
        api_public._execute_once_cancel_action(action, {"schedule_name": "S"}, dry_run=False)

    entry = saved["data"]["overrides"][0]
    assert entry["action"] == "cancel"
    assert entry["diagnostic_id"].startswith("diag-")
    assert len(entry["remote_diagnostics"]) == 2
    assert entry["remote_diagnostics"][0]["phase"] == "disable"
    assert entry["remote_diagnostics"][0]["response_body"] == {"message": "disable-ok"}
    assert entry["remote_diagnostics"][1]["phase"] == "restore"
    assert entry["remote_diagnostics"][1]["response_body"] == {"message": "restore-timeout"}


def test_remote_enabletask_response_state_15_is_treated_as_failure() -> None:
    ok, detail = api_public._remote_enabletask_response_ok({"data": [{"taskid": 0, "state": 15}]})

    assert ok is False
    assert "state=15" in detail
    assert '"taskid": 0' in detail


def test_remote_schedule_enabletask_splits_on_business_failure(monkeypatch) -> None:
    calls: list[str] = []
    diagnostics: list[dict] = []

    def fake_remote_request(method, path, json_body=None, diagnostic=None, **kwargs):
        del kwargs, diagnostic
        assert method == "POST"
        assert path == "/task/enabletask"
        assert isinstance(json_body, dict)
        key = json_body["taskid"]
        calls.append(key)
        if key == "1,2,3,4":
            return {"data": [{"taskid": 0, "state": 15}]}
        return {"data": [{"taskid": 100 + len(calls), "state": 0}]}

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    payloads = api_public._remote_schedule_enabletask(
        ["1", "2", "3", "4"],
        0,
        api_public.datetime(2026, 3, 16, 23, 59, 59),
        dry_run=False,
        source_task_ids=["1", "2", "3", "4"],
        diagnostics=diagnostics,
        diagnostic_id="diag-split",
        action_name="cancel",
        phase="restore",
    )

    assert calls == ["1,2,3,4", "1,2", "3,4"]
    assert [item["taskid"] for item in payloads] == ["1,2", "3,4"]
    assert all("yuantaskid" not in item for item in payloads)
    assert len(diagnostics) == 3
    assert [item["request_payload"]["taskid"] for item in diagnostics] == ["1,2,3,4", "1,2", "3,4"]
    assert all("yuantaskid" not in item["request_payload"] for item in diagnostics)
