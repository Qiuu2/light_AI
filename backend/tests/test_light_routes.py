from __future__ import annotations

from io import BytesIO
from email.message import Message
from pathlib import Path
import sys
import urllib.request
from urllib.error import HTTPError

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import build_app
from backend.routes import light
import backend.api_public as api_public


LOGIN_PAGE_HTML = b"<html><form action='/action/login'><input name='password'></form></html>"


@pytest.fixture(autouse=True)
def _isolate_light_runtime():
    original_action_base_url = light._ACTION_REMOTE_BASE_URL
    original_credentials = dict(light._ACTION_REMOTE_CREDENTIALS_BY_BASE_URL)
    original_openers = dict(light._OPENERS_BY_BASE_URL)
    original_cookie_jars = dict(light._COOKIE_JARS_BY_BASE_URL)
    yield
    light._ACTION_REMOTE_BASE_URL = original_action_base_url
    light._ACTION_REMOTE_CREDENTIALS_BY_BASE_URL.clear()
    light._ACTION_REMOTE_CREDENTIALS_BY_BASE_URL.update(original_credentials)
    light._OPENERS_BY_BASE_URL.clear()
    light._OPENERS_BY_BASE_URL.update(original_openers)
    light._COOKIE_JARS_BY_BASE_URL.clear()
    light._COOKIE_JARS_BY_BASE_URL.update(original_cookie_jars)


def _client(monkeypatch):
    monkeypatch.setattr(api_public, "_startup_load_data", lambda: None)
    monkeypatch.setattr(api_public, "_shutdown_runtime", lambda: None)
    return TestClient(build_app())


def test_remote_html_kind_classifies_login_and_success_samples() -> None:
    login_html = (ROOT / "login.txt").read_text(encoding="utf-8")
    success_html = (ROOT / "loginsucess.txt").read_text(encoding="utf-8")

    assert light._remote_html_kind(login_html) == "login_page"
    assert light._remote_html_kind(success_html) == "app_shell"


def test_action_diagnostic_exposes_remote_html_kind() -> None:
    login_html = (ROOT / "login.txt").read_text(encoding="utf-8")
    diagnostic = light._action_diagnostic(
        phase="initial",
        method="POST",
        path="/action/getmedia",
        url="http://192.168.3.199/action/getmedia",
        remote_base_url="http://192.168.3.199",
        remote_base_url_source="explicit",
        body_mode="none",
        cookie_jar=light.http.cookiejar.CookieJar(),
        raw=login_html,
    )

    assert diagnostic["html_like"] is True
    assert diagnostic["html_kind"] == "login_page"
    assert diagnostic["login_page_like"] is True
    assert diagnostic["app_shell_like"] is False


def test_light_task_routes_map_to_action_api(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        return {"success": True, "message": "ok", "data": {"ok": True}, "raw": "{}"}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        client.get("/api/light/schedules")
        client.post("/api/light/schedules/1/tasks", json={"taskname": "上课铃"})
        client.put("/api/light/tasks/119", json={"taskname": "下课铃"})
        client.delete("/api/light/tasks/119")
        client.get("/api/light/tasks")
        client.post("/api/light/tasks/120/execute")
        client.post("/api/light/tasks/120/stop")

    assert calls == [
        {"method": "POST", "path": "/action/getallsech", "params": None, "form": None, "body_mode": "none"},
        {
            "method": "POST",
            "path": "/action/addtask",
            "params": {"id": "1"},
            "form": {"taskname": "上课铃"},
            "body_mode": "multipart",
        },
        {
            "method": "POST",
            "path": "/action/modifytask",
            "params": {"taskid": "119"},
            "form": {"taskname": "下课铃"},
            "body_mode": "multipart",
        },
        {
            "method": "POST",
            "path": "/action/deletetask",
            "params": None,
            "form": {"taskid": "119"},
            "body_mode": "multipart",
        },
        {"method": "POST", "path": "/action/getquicktask", "params": None, "form": None, "body_mode": "none"},
        {
            "method": "POST",
            "path": "/action/taskstart",
            "params": None,
            "form": {"taskid": "120"},
            "body_mode": "urlencoded",
        },
        {
            "method": "POST",
            "path": "/action/taskstop",
            "params": None,
            "form": {"taskid": "120"},
            "body_mode": "urlencoded",
        },
    ]


def test_light_schedules_aggregate_schemes_and_opensech(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        if path == "/action/getallsech":
            return {
                "success": True,
                "message": "ok",
                "data": {"rows": [{"id": 1, "name": "方案1"}, {"id": 2, "name": "方案2"}]},
                "raw": '{"rows":[]}',
            }
        if path == "/action/opensech" and params == {"id": "1"}:
            return {
                "success": True,
                "message": "ok",
                "data": {"rows": [{"id": 119, "data": ["上课铃", "08:00:00", "00:03:00", "√", "80"]}]},
                "raw": '{"rows":[]}',
            }
        return {"success": True, "message": "ok", "data": {"rows": []}, "raw": '{"rows":[]}'}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/schedules")

    payload = response.json()
    assert response.status_code == 200
    assert calls == [
        {"method": "POST", "path": "/action/getallsech", "params": None, "form": None, "body_mode": "none"},
        {
            "method": "POST",
            "path": "/action/opensech",
            "params": {"id": "1"},
            "form": None,
            "body_mode": "none",
        },
        {
            "method": "POST",
            "path": "/action/opensech",
            "params": {"id": "2"},
            "form": None,
            "body_mode": "none",
        },
    ]
    assert payload["success"] is True
    assert payload["data"]["schemes"][0]["id"] == "1"
    assert payload["data"]["schemes"][0]["tasks"][0]["taskid"] == 119
    assert payload["data"]["schemes"][0]["tasks"][0]["taskname"] == "上课铃"
    assert payload["data"]["schemes"][0]["task_success"] is True
    assert payload["raw"]["tasks_by_scheme"]["1"]["success"] is True


def test_light_schedules_preserve_opensech_failures_per_scheme(monkeypatch) -> None:
    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        if path == "/action/getallsech":
            return {
                "success": True,
                "message": "ok",
                "data": {"rows": [{"id": 1, "name": "方案1"}, {"id": 2, "name": "方案2"}]},
                "raw": "schemes",
            }
        if path == "/action/opensech" and params == {"id": "2"}:
            return {"success": False, "message": "remote opensech failed", "data": None, "raw": "failed"}
        return {"success": True, "message": "ok", "data": {"rows": []}, "raw": "ok"}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/schedules")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    failed_scheme = payload["data"]["schemes"][1]
    assert failed_scheme["task_success"] is False
    assert failed_scheme["task_error"] == "remote opensech failed"
    assert failed_scheme["tasks"] == []


def test_light_schedules_do_not_fallback_to_fake_default_schemes(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        if path == "/action/getallsech":
            return {"success": True, "message": "ok", "data": {"rows": []}, "raw": '{"rows":[]}'}
        return {"success": True, "message": "ok", "data": {"rows": []}, "raw": '{"rows":[]}'}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/schedules")

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"]["schemes"] == []
    assert calls == [
        {"method": "POST", "path": "/action/getallsech", "params": None, "form": None, "body_mode": "none"}
    ]


def test_light_task_details_wraps_remote_detail_payloads(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        if path == "/action/gettaskinfo":
            return {
                "success": True,
                "message": "ok",
                "data": {
                    "rows": [
                        {
                            "id": 118,
                            "taskname": "other",
                        },
                        {
                            "id": 119,
                            "taskname": "222",
                            "playtime": "00:02:00",
                            "playlength": "00:03:00",
                            "enable": "1",
                            "volume": "80",
                            "mon": "1",
                            "tue": "1",
                            "wed": "1",
                            "thu": "1",
                            "fri": "1",
                            "sat": "0",
                            "sun": "0",
                            "rand": "0",
                            "Pre-Start": "10",
                            "Pre-Stop": "11",
                            "area": "11111110",
                        },
                    ]
                },
                "raw": "taskinfo",
            }
        return {"success": True, "message": "ok", "data": {"rows": [{"path": path}]}, "raw": path}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/tasks/119/details")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert calls == [
        {
            "method": "POST",
            "path": "/action/gettaskmedia",
            "params": None,
            "form": {"taskid": "119"},
            "body_mode": "urlencoded",
        },
        {
            "method": "POST",
            "path": "/action/gettaskterminal",
            "params": None,
            "form": {"taskid": "119"},
            "body_mode": "urlencoded",
        },
        {
            "method": "GET",
            "path": "/action/gettaskarea",
            "params": {"taskid": "119"},
            "form": None,
            "body_mode": "none",
        },
        {
            "method": "POST",
            "path": "/action/gettaskinfo",
            "params": None,
            "form": None,
            "body_mode": "none",
        },
    ]
    assert payload["data"]["media"]["rows"][0]["path"] == "/action/gettaskmedia"
    detail = payload["data"]["taskinfo"]["detail"]
    assert detail["taskname"] == "222"
    assert detail["time"] == "00:02:00"
    assert detail["playhour"] == "00"
    assert detail["playminute"] == "02"
    assert detail["playsecond"] == "00"
    assert detail["timehour"] == "00"
    assert detail["timeminute"] == "03"
    assert detail["timesecond"] == "00"
    assert detail["pretime"] == "10"
    assert detail["delaytime"] == "11"
    assert detail["random"] == "0"
    assert detail["day0"] == "1"
    assert detail["day5"] == "0"
    assert detail["area0"] == "1"
    assert detail["area7"] == "0"
    assert all(call["path"] != "/action/gettaskprepower" for call in calls)


def test_light_task_details_reports_missing_taskinfo_row(monkeypatch) -> None:
    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        if path == "/action/gettaskinfo":
            return {"success": True, "message": "ok", "data": {"rows": [{"id": 118}]}, "raw": "taskinfo"}
        return {"success": True, "message": "ok", "data": {"rows": []}, "raw": path}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/tasks/119/details")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["message"] == "Failed to load task detail: taskinfo"
    assert payload["data"]["taskinfo"]["detail"] == {}


def test_light_task_details_reports_taskinfo_failure(monkeypatch) -> None:
    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        if path == "/action/gettaskinfo":
            return {"success": False, "message": "taskinfo failed", "data": None, "raw": "failed"}
        return {"success": True, "message": "ok", "data": {"rows": []}, "raw": path}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/tasks/119/details")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["message"] == "Failed to load task detail: taskinfo"


def test_light_activate_schedule_maps_to_activeprogram(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        return {"success": True, "message": "ok", "data": {}, "raw": "{}"}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.post("/api/light/schedules/5/activate")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls == [
        {
            "method": "POST",
            "path": "/action/activeprogram",
            "params": None,
            "form": {"id": "5"},
            "body_mode": "multipart",
        }
    ]


def test_light_current_schedule_tasks_maps_to_gettaskinfo(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        return {
            "success": True,
            "message": "ok",
            "data": {"rows": [{"id": 122, "taskname": "333", "playtime": "00:01:00", "playlength": "00:01:00", "volume": "80"}]},
            "raw": '{"rows":[]}',
        }

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/current-schedule-tasks")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert calls == [
        {"method": "POST", "path": "/action/gettaskinfo", "params": None, "form": None, "body_mode": "none"}
    ]
    assert payload["data"]["tasks"][0]["taskname"] == "333"


def test_light_current_schedule_tasks_preserve_remote_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        light,
        "action_request",
        lambda method, path, **kwargs: {"success": False, "message": "gettaskinfo failed", "data": None, "raw": "failed"},
    )

    with _client(monkeypatch) as client:
        response = client.get("/api/light/current-schedule-tasks")

    payload = response.json()
    assert response.status_code == 200
    assert payload == {"success": False, "message": "gettaskinfo failed", "data": None, "raw": "failed"}


def test_light_instant_play_omits_empty_media_and_stop_has_no_params(monkeypatch) -> None:
    calls = []
    api_public.TTL_CACHE.clear()
    api_public.REMOTE_CACHE["runtime_play_rows"] = (0.0, [{"taskid": "temp-1"}])

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        return {"success": True, "message": "ok", "data": None, "raw": ""}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        play = client.post(
            "/api/light/instant-play",
            json={
                "media": "",
                "terminal": "1_70",
                "playmode": "0",
                "timehour": "0",
                "timeminute": "2",
                "timesecond": "0",
                "volume": "80",
            },
        )
        stop = client.post("/api/light/instant-play/stop")

    assert play.status_code == 200
    assert stop.status_code == 200
    assert calls == [
        {
            "method": "POST",
            "path": "/action/executetmptask",
            "params": None,
            "form": {
                "terminal": "1_70",
                "playmode": "0",
                "timehour": "0",
                "timeminute": "2",
                "timesecond": "0",
                "volume": "80",
            },
            "body_mode": "urlencoded",
        },
        {"method": "POST", "path": "/action/stoptmptask", "params": None, "form": None, "body_mode": "none"},
    ]
    assert "runtime_play_rows" not in api_public.REMOTE_CACHE


def test_light_instant_play_runtime_status_tracks_start_then_stop(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    remote_states = {"501": 0}

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        if path == "/action/executetmptask":
            return {"success": True, "message": "ok", "data": {"taskid": "501"}, "raw": ""}
        if path == "/action/stoptmptask":
            remote_states["501"] = -1
            return {"success": True, "message": "ok", "data": None, "raw": ""}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(light, "action_request", fake_action_request)
    monkeypatch.setattr(api_public, "_fetch_remote_runtime_play_rows", lambda: [])
    monkeypatch.setattr(api_public, "_fetch_remote_task_state", lambda task_id, task_type: {"state": remote_states[str(task_id)]})

    with _client(monkeypatch) as client:
        start = client.post(
            "/api/light/instant-play",
            json={
                "media": "88",
                "terminal": "1_70",
                "playmode": "0",
                "timehour": "0",
                "timeminute": "2",
                "timesecond": "0",
                "volume": "80",
            },
        )
        visible = client.get("/data/runtime_play_tasks", params={"force": "true"})
        stop = client.post("/api/light/instant-play/stop")
        stopped = client.get("/data/runtime_play_tasks", params={"force": "true"})

    assert start.status_code == 200
    assert visible.status_code == 200
    visible_rows = visible.json()["runtime_play_tasks"]
    assert [row["task_id"] for row in visible_rows] == ["501"]
    assert visible_rows[0]["media_id"] == "88"
    assert visible_rows[0]["terminal_ids"] == ["1_70"]
    assert visible_rows[0]["remote_state"] == 0
    assert visible_rows[0]["status"] == "执行中"

    assert stop.status_code == 200
    assert stopped.status_code == 200
    stopped_rows = stopped.json()["runtime_play_tasks"]
    assert [row["task_id"] for row in stopped_rows] == ["501"]
    assert stopped_rows[0]["remote_state"] == -1
    assert stopped_rows[0]["status"] == "停止"


def test_light_instant_play_without_remote_task_id_remains_visible(monkeypatch) -> None:
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    state_queries = []

    monkeypatch.setattr(
        light,
        "action_request",
        lambda method, path, **kwargs: {"success": True, "message": "ok", "data": None, "raw": ""},
    )
    monkeypatch.setattr(api_public, "_fetch_remote_runtime_play_rows", lambda: [])
    monkeypatch.setattr(
        api_public,
        "_fetch_remote_task_state",
        lambda task_id, task_type: state_queries.append((task_id, task_type)) or {"state": -1},
    )

    with _client(monkeypatch) as client:
        start = client.post("/api/light/instant-play", json={"media": "99", "terminal": "2_80", "volume": "66"})
        visible = client.get("/data/runtime_play_tasks", params={"force": "true"})

    assert start.status_code == 200
    rows = visible.json()["runtime_play_tasks"]
    assert len(rows) == 1
    assert rows[0]["task_id"].startswith("light-temp-")
    assert rows[0]["remote_state"] == 0
    assert rows[0]["status"] == "执行中"
    assert state_queries == []


def test_light_resources_wraps_remote_payloads_and_group_options(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append(path)
        if path == "/action/getbasicinfo":
            return {
                "success": True,
                "message": "ok",
                "data": {"rows": [{"Current_Scheme": 3}]},
                "raw": path,
            }
        if path == "/action/getmedia":
            return {
                "success": True,
                "message": "ok",
                "data": {"item": [{"text": "媒体列表", "id": "dir_1", "item": [{"text": "bell.mp3", "id": 341}]}]},
                "raw": path,
            }
        if path == "/action/getterminal":
            return {
                "success": True,
                "message": "ok",
                "data": {"item": [{"text": "分区列表", "id": "dir_2", "item": [{"text": "1-1", "id": 445}]}]},
                "raw": path,
            }
        if path == "/action/getextgroup":
            return {
                "success": True,
                "message": "ok",
                "data": {"rows": [{"id": 70, "name": "Group 70"}]},
                "raw": path,
            }
        return {"success": True, "message": "ok", "data": [{"path": path}], "raw": path}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/resources")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert calls == ["/action/getmedia", "/action/getterminal", "/action/getextgroup", "/action/getbasicinfo"]
    assert payload["data"]["media"]["item"][0]["text"] == "媒体列表"
    assert payload["data"]["media_options"] == [
        {"id": "341", "value": "341", "label": "bell.mp3", "raw": {"text": "bell.mp3", "id": 341}}
    ]
    assert payload["data"]["terminal_options"] == [
        {"id": "445", "value": "2_445", "label": "1-1", "raw": {"text": "1-1", "id": 445}},
        {"id": "70", "value": "1_70", "label": "Group 70", "raw": {"id": 70, "name": "Group 70"}, "kind": "group"},
    ]
    assert payload["data"]["group_options"] == [
        {"id": "70", "value": "1_70", "label": "Group 70", "raw": {"id": 70, "name": "Group 70"}, "kind": "group"}
    ]
    assert payload["data"]["basic"]["rows"][0]["Current_Scheme"] == 3


def test_light_resources_report_basicinfo_failure(monkeypatch) -> None:
    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        if path == "/action/getbasicinfo":
            return {"success": False, "message": "basic failed", "data": None, "raw": "failed"}
        return {"success": True, "message": "ok", "data": [], "raw": "ok"}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/resources")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["message"] == "Failed to load light resources: basic"
    assert payload["parts"]["basic"] == {"success": False, "message": "basic failed"}


def test_light_terminal_read_routes_map_to_swagger_actions(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        return {"success": True, "message": "ok", "data": [{"path": path}], "raw": path}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        terminals = client.get("/api/light/terminals")
        groups = client.get("/api/light/terminal-groups")
        group_terminals = client.get("/api/light/terminal-groups/70/terminals")

    assert terminals.status_code == 200
    assert groups.status_code == 200
    assert group_terminals.status_code == 200
    assert calls == [
        {"method": "POST", "path": "/action/getterminal", "params": None, "form": None, "body_mode": "none"},
        {"method": "POST", "path": "/action/getextgroup", "params": None, "form": None, "body_mode": "none"},
        {
            "method": "POST",
            "path": "/action/getterminalid",
            "params": None,
            "form": {"groupid": "70"},
            "body_mode": "multipart",
        },
    ]


def test_light_terminal_snapshot_aggregates_groups_members_and_terminals(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        if path == "/action/getextgroup":
            return {
                "success": True,
                "message": "ok",
                "data": {"rows": [{"id": 70, "name": "教学楼"}, {"groupid": "71", "name": "操场"}]},
                "raw": "groups",
            }
        if path == "/action/getterminal":
            return {"success": True, "message": "ok", "data": [{"id": "1"}], "raw": "terminals"}
        return {"success": True, "message": "ok", "data": None, "raw": form["groupid"]}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/terminal-snapshot")

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["zones"]["data"]["rows"][0]["id"] == 70
    assert payload["terminal_info"]["data"][0]["id"] == "1"
    assert payload["zone_terminals"]["70"]["data"][0]["value"] == "2_70"
    assert payload["zone_terminals"]["71"]["data"][0]["value"] == "2_71"
    assert calls == [
        {"method": "POST", "path": "/action/getextgroup", "params": None, "form": None, "body_mode": "none"},
        {"method": "POST", "path": "/action/getterminal", "params": None, "form": None, "body_mode": "none"},
        {
            "method": "POST",
            "path": "/action/getterminalid",
            "params": None,
            "form": {"groupid": "70"},
            "body_mode": "multipart",
        },
        {
            "method": "POST",
            "path": "/action/getterminalid",
            "params": None,
            "form": {"groupid": "71"},
            "body_mode": "multipart",
        },
    ]


def test_light_terminal_group_terminals_parses_plain_text_terminal_id(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        return {"success": True, "message": "ok", "data": None, "raw": "445"}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/terminal-groups/69/terminals")

    assert response.status_code == 200
    assert response.json()["data"] == [{"id": "445", "value": "2_445", "label": "445", "raw": "445"}]
    assert calls == [
        {
            "method": "POST",
            "path": "/action/getterminalid",
            "params": None,
            "form": {"groupid": "69"},
            "body_mode": "multipart",
        }
    ]


def test_light_system_volume_maps_to_action_setvolume(monkeypatch) -> None:
    calls = []

    def fake_action_request(method, path, *, params=None, form=None, body_mode="multipart"):
        calls.append({"method": method, "path": path, "params": params, "form": form, "body_mode": body_mode})
        return {"success": True, "message": "ok", "data": None, "raw": ""}

    monkeypatch.setattr(light, "action_request", fake_action_request)

    with _client(monkeypatch) as client:
        response = client.post("/api/light/system-volume", json={"volume": 30})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls == [
        {"method": "POST", "path": "/action/setvolume", "params": None, "form": {"volume": "30"}, "body_mode": "multipart"}
    ]


def test_light_decode_remote_response_handles_empty_and_non_json() -> None:
    parsed, raw = light._decode_remote_response(b"")
    assert parsed is None
    assert raw == ""

    parsed, raw = light._decode_remote_response("执行成功".encode("utf-8"))
    assert parsed is None
    assert raw == "执行成功"

    parsed, raw = light._decode_remote_response(b'{"code": 0}')
    assert parsed == {"code": 0}
    assert raw == '{"code": 0}'


class _FakeResponse:
    def __init__(self, body: bytes = b'{"ok": true}', headers=None, url="http://192.168.3.199/action/mock"):
        self.body = body
        self.status = 200
        self.code = 200
        self.msg = "OK"
        self.headers = headers or Message()
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.body

    def geturl(self) -> str:
        return self._url

    def info(self):
        return self.headers


class _CaptureOpener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout=0):
        self.requests.append(request)
        return _FakeResponse()


def test_action_request_sends_multipart_form_data(monkeypatch) -> None:
    opener = _CaptureOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", False)
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.action_request(
        "POST",
        "/action/addtask",
        params={"id": "1"},
        form={"taskname": "上课铃", "media": "360,361"},
    )

    request = opener.requests[0]
    content_type = dict(request.header_items())["Content-type"]
    body = request.data.decode("utf-8")
    assert response["success"] is True
    assert request.full_url.endswith("/action/addtask?id=1")
    assert content_type.startswith("multipart/form-data; boundary=")
    assert 'name="taskname"' in body
    assert "上课铃" in body
    assert 'name="media"' in body
    assert "360,361" in body


def test_action_request_sends_urlencoded_form_data(monkeypatch) -> None:
    opener = _CaptureOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", False)
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.action_request(
        "POST",
        "/action/gettaskmedia",
        form={"taskid": "120", "name": "上课铃"},
        body_mode="urlencoded",
    )

    request = opener.requests[0]
    headers = dict(request.header_items())
    body = request.data.decode("utf-8")
    assert response["success"] is True
    assert request.full_url.endswith("/action/gettaskmedia")
    assert headers["Content-type"] == "application/x-www-form-urlencoded"
    assert "taskid=120" in body
    assert "%E4%B8%8A%E8%AF%BE%E9%93%83" in body


def test_backend_app_light_route_prefers_saved_remote_base_url_without_session(monkeypatch) -> None:
    opener = _CaptureOpener()
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "http://192.168.3.199",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": [],
            }
        ),
    )
    monkeypatch.setattr(light, "_ACTION_REMOTE_BASE_URL", "http://192.168.1.88")
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", False)
    monkeypatch.setattr(light, "_OPENER", opener)

    with _client(monkeypatch) as client:
        response = client.get("/api/light/terminals")

    assert response.status_code == 200
    assert opener.requests[0].full_url == "http://192.168.3.199/action/getterminal"
    assert response.json()["diagnostics"][0]["remote_base_url_source"] == "saved"


def test_cookie_state_is_partitioned_by_remote_base_url() -> None:
    _, jar_a = light._get_remote_cookie_state("http://192.168.3.199")
    _, jar_b = light._get_remote_cookie_state("http://192.168.3.200")

    assert jar_a is not jar_b
    assert set(light._COOKIE_JARS_BY_BASE_URL) >= {"http://192.168.3.199", "http://192.168.3.200"}


def test_light_login_sends_credentials_as_query_without_body(monkeypatch) -> None:
    class LoginOpener(_CaptureOpener):
        def open(self, request, timeout=0):
            self.requests.append(request)
            headers = Message()
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                headers.add_header("Set-Cookie", "-goahead-session-=session-123; Path=/")
                return _FakeResponse(LOGIN_PAGE_HTML, headers=headers, url=request.full_url)
            return _FakeResponse(b'{"rows":[]}', headers=headers, url=request.full_url)

    opener = LoginOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.light_login(force=True)

    assert response["success"] is True
    assert len(opener.requests) == 2
    assert response["diagnostics"][0]["set_cookie_has_action_session"] is True
    assert response["diagnostics"][0]["login_attempt_mode"] == "post_query"
    assert response["diagnostics"][0]["business_probe_success"] is True
    assert response["diagnostics"][1]["phase"] == "business_probe"

    login_request = opener.requests[0]
    assert login_request.full_url.endswith("/action/login?username=useradmin&password=123456")
    assert login_request.data is None
    assert "Content-type" not in dict(login_request.header_items())


def test_cookie_aware_opener_keeps_remote_session_for_follow_up_business_request(monkeypatch) -> None:
    cookie_jar = light.http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    requests = []

    class CookieRecordingHandler(urllib.request.BaseHandler):
        handler_order = 100

        def default_open(self, request):
            requests.append(request)
            headers = Message()
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                headers.add_header("Set-Cookie", "-goahead-session-=session-123; Path=/")
                return _FakeResponse(LOGIN_PAGE_HTML, headers=headers, url=request.full_url)
            return _FakeResponse(b'{"rows":[]}', headers=headers, url=request.full_url)

    opener.add_handler(CookieRecordingHandler())
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "_OPENER", opener)
    monkeypatch.setattr(light, "_COOKIE_JAR", cookie_jar)

    login_response = light.light_login(force=True)
    response = light.action_request("POST", "/action/getmedia")

    assert login_response["success"] is True
    assert response["success"] is True
    assert len(requests) == 3
    assert requests[1].get_header("Cookie") == "-goahead-session-=session-123"
    assert requests[2].get_header("Cookie") == "-goahead-session-=session-123"


def test_action_request_does_not_login_before_successful_business_call(monkeypatch) -> None:
    opener = _CaptureOpener()
    calls = {"login": []}

    def fake_login(force=False):
        calls["login"].append(force)
        return {"success": True, "message": "ok", "raw": ""}

    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "light_login", fake_login)
    monkeypatch.setattr(light, "_OPENER", opener)
    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is True
    assert len(opener.requests) == 1
    assert calls["login"] == []


def test_action_request_does_not_relogin_when_business_api_returns_app_shell(monkeypatch) -> None:
    app_shell = (ROOT / "loginsucess.txt").read_bytes()
    calls = {"login": []}

    class AppShellOpener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout=0):
            self.requests.append(request)
            return _FakeResponse(app_shell, url=request.full_url)

    def fake_login(force=False, **kwargs):
        del kwargs
        calls["login"].append(force)
        return {"success": True, "message": "ok", "raw": ""}

    opener = AppShellOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "light_login", fake_login)
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is True
    assert response["diagnostics"][0]["html_kind"] == "app_shell"
    assert len(opener.requests) == 1
    assert calls["login"] == []


def test_light_login_rejects_http_200_html_without_session_cookie(monkeypatch) -> None:
    class HtmlResponseOpener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout=0):
            self.requests.append(request)
            return _FakeResponse(LOGIN_PAGE_HTML)

    opener = HtmlResponseOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.light_login(force=True)

    assert response["success"] is False
    assert "business probe" in response["message"]
    assert response["raw"] == LOGIN_PAGE_HTML.decode("utf-8")
    assert response["diagnostics"][0]["html_like"] is True
    assert response["diagnostics"][0]["set_cookie_has_action_session"] is False
    assert response["diagnostics"][0]["business_probe_success"] is False
    assert len(opener.requests) == 6
    assert opener.requests[0].full_url.endswith("/action/login?username=useradmin&password=123456")


def test_light_login_accepts_no_cookie_when_business_probe_succeeds(monkeypatch) -> None:
    class HtmlThenJsonOpener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout=0):
            self.requests.append(request)
            if request.full_url.endswith("/action/getmedia"):
                return _FakeResponse(b'{"rows":[]}', url=request.full_url)
            return _FakeResponse(LOGIN_PAGE_HTML, url=request.full_url)

    opener = HtmlThenJsonOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.light_login(force=True)

    assert response["success"] is True
    assert response["diagnostics"][0]["set_cookie_has_action_session"] is False
    assert response["diagnostics"][0]["business_probe_success"] is True
    assert [item["phase"] for item in response["diagnostics"]] == ["relogin", "business_probe"]


def test_light_login_accepts_app_shell_response_without_cookie(monkeypatch) -> None:
    app_shell = (ROOT / "loginsucess.txt").read_bytes()

    class AppShellOpener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout=0):
            self.requests.append(request)
            return _FakeResponse(app_shell, url=request.full_url)

    opener = AppShellOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.light_login(force=True)

    assert response["success"] is True
    assert len(opener.requests) == 1
    assert response["diagnostics"][0]["html_kind"] == "app_shell"
    assert response["diagnostics"][0]["business_probe_attempted"] is False


def test_light_login_accepts_http_200_html_with_session_cookie(monkeypatch) -> None:
    class HtmlCookieResponseOpener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout=0):
            self.requests.append(request)
            headers = Message()
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                headers.add_header("Set-Cookie", "-goahead-session-=session-abc; Path=/")
                return _FakeResponse(LOGIN_PAGE_HTML, headers=headers, url=request.full_url)
            return _FakeResponse(b'{"rows":[]}', headers=headers, url=request.full_url)

    opener = HtmlCookieResponseOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.light_login(force=True)

    assert response["success"] is True
    assert response["diagnostics"][0]["html_like"] is True
    assert response["diagnostics"][0]["set_cookie_has_action_session"] is True
    assert response["diagnostics"][0]["business_probe_success"] is True
    assert len(opener.requests) == 2


def test_light_login_falls_back_to_get_query_when_post_query_probe_returns_html(monkeypatch) -> None:
    class GetQuerySuccessOpener:
        def __init__(self):
            self.requests = []
            self.last_login_method = ""

        def open(self, request, timeout=0):
            self.requests.append(request)
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                self.last_login_method = request.get_method()
                return _FakeResponse(LOGIN_PAGE_HTML, url=request.full_url)
            if request.full_url.endswith("/action/getmedia") and self.last_login_method == "GET":
                return _FakeResponse(b'{"rows":[]}', url=request.full_url)
            return _FakeResponse(LOGIN_PAGE_HTML, url=request.full_url)

    opener = GetQuerySuccessOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.light_login(force=True)

    assert response["success"] is True
    assert [item.get("login_attempt_mode") for item in response["diagnostics"] if item["phase"] == "relogin"] == [
        "post_query",
        "get_query",
    ]
    assert response["diagnostics"][-2]["business_probe_success"] is True


def test_light_login_falls_back_to_urlencoded_form_when_query_modes_fail(monkeypatch) -> None:
    class FormSuccessOpener:
        def __init__(self):
            self.requests = []
            self.form_login_seen = False

        def open(self, request, timeout=0):
            self.requests.append(request)
            content_type = dict(request.header_items()).get("Content-type") or dict(request.header_items()).get("Content-Type")
            if request.full_url.endswith("/action/login") and content_type == "application/x-www-form-urlencoded":
                self.form_login_seen = True
                assert request.data == b"username=useradmin&password=123456"
                return _FakeResponse(LOGIN_PAGE_HTML, url=request.full_url)
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                return _FakeResponse(LOGIN_PAGE_HTML, url=request.full_url)
            if request.full_url.endswith("/action/getmedia") and self.form_login_seen:
                return _FakeResponse(b'{"rows":[]}', url=request.full_url)
            return _FakeResponse(LOGIN_PAGE_HTML, url=request.full_url)

    opener = FormSuccessOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.light_login(force=True)

    assert response["success"] is True
    assert [item.get("login_attempt_mode") for item in response["diagnostics"] if item["phase"] == "relogin"] == [
        "post_query",
        "get_query",
        "post_urlencoded",
    ]
    assert opener.requests[-2].full_url.endswith("/action/login")
    assert "?" not in opener.requests[-2].full_url


def test_force_light_login_accepts_unchanged_existing_session_cookie_after_probe(monkeypatch) -> None:
    cookie_jar = light.http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    requests = []
    cookie_jar.set_cookie(
        light.http.cookiejar.Cookie(
            version=0,
            name="-goahead-session-",
            value="old-session",
            port=None,
            port_specified=False,
            domain="192.168.3.199",
            domain_specified=False,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=False,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
    )

    class HtmlNoCookieThenProbeHandler(urllib.request.BaseHandler):
        handler_order = 100

        def default_open(self, request):
            requests.append(request)
            if request.full_url.endswith("/action/getmedia"):
                return _FakeResponse(b'{"rows":[]}', headers=Message(), url=request.full_url)
            return _FakeResponse(LOGIN_PAGE_HTML, headers=Message(), url=request.full_url)

    opener.add_handler(HtmlNoCookieThenProbeHandler())
    monkeypatch.setattr(light, "_OPENER", opener)
    monkeypatch.setattr(light, "_COOKIE_JAR", cookie_jar)

    response = light.light_login(
        force=True,
        remote_base_url="http://192.168.3.199",
        username="useradmin",
        password="123456",
    )

    assert response["success"] is True
    diagnostic = response["diagnostics"][0]
    assert diagnostic["cookies_before"]["has_action_session"] is True
    assert diagnostic["cookies_after"]["has_action_session"] is True
    assert diagnostic["cookie_changed"] is False
    assert diagnostic["business_probe_attempted"] is True
    assert diagnostic["business_probe_success"] is True
    assert diagnostic["business_probe_path"] == "/action/getmedia"
    assert response["diagnostics"][1]["phase"] == "business_probe"
    assert response["diagnostics"][1]["html_like"] is False
    assert [request.full_url for request in requests] == [
        "http://192.168.3.199/action/login?username=useradmin&password=123456",
        "http://192.168.3.199/action/getmedia",
    ]


def test_force_light_login_rejects_unchanged_existing_session_cookie_when_probe_returns_html(monkeypatch) -> None:
    cookie_jar = light.http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    cookie_jar.set_cookie(
        light.http.cookiejar.Cookie(
            version=0,
            name="-goahead-session-",
            value="old-session",
            port=None,
            port_specified=False,
            domain="192.168.3.199",
            domain_specified=False,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=False,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
    )

    class HtmlNoCookieAndHtmlProbeHandler(urllib.request.BaseHandler):
        handler_order = 100

        def default_open(self, request):
            return _FakeResponse(LOGIN_PAGE_HTML, headers=Message(), url=request.full_url)

    opener.add_handler(HtmlNoCookieAndHtmlProbeHandler())
    monkeypatch.setattr(light, "_OPENER", opener)
    monkeypatch.setattr(light, "_COOKIE_JAR", cookie_jar)

    response = light.light_login(
        force=True,
        remote_base_url="http://192.168.3.199",
        username="useradmin",
        password="123456",
    )

    assert response["success"] is False
    diagnostic = response["diagnostics"][0]
    assert diagnostic["cookie_changed"] is False
    assert diagnostic["business_probe_attempted"] is True
    assert diagnostic["business_probe_success"] is False
    assert response["diagnostics"][1]["phase"] == "business_probe"
    assert response["diagnostics"][1]["html_like"] is True


def test_force_light_login_accepts_changed_existing_session_cookie(monkeypatch) -> None:
    cookie_jar = light.http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    cookie_jar.set_cookie(
        light.http.cookiejar.Cookie(
            version=0,
            name="-goahead-session-",
            value="old-session",
            port=None,
            port_specified=False,
            domain="192.168.3.199",
            domain_specified=False,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=False,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
    )

    class HtmlNewCookieHandler(urllib.request.BaseHandler):
        handler_order = 100

        def default_open(self, request):
            headers = Message()
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                headers.add_header("Set-Cookie", "-goahead-session-=new-session; Path=/")
                return _FakeResponse(LOGIN_PAGE_HTML, headers=headers, url=request.full_url)
            return _FakeResponse(b'{"rows":[]}', headers=headers, url=request.full_url)

    opener.add_handler(HtmlNewCookieHandler())
    monkeypatch.setattr(light, "_OPENER", opener)
    monkeypatch.setattr(light, "_COOKIE_JAR", cookie_jar)

    response = light.light_login(
        force=True,
        remote_base_url="http://192.168.3.199",
        username="useradmin",
        password="123456",
    )

    assert response["success"] is True
    diagnostic = response["diagnostics"][0]
    assert diagnostic["cookies_before"]["has_action_session"] is True
    assert diagnostic["cookies_after"]["has_action_session"] is True
    assert diagnostic["cookie_changed"] is True
    assert diagnostic["business_probe_success"] is True


def test_light_login_returns_false_on_http_error(monkeypatch) -> None:
    class FailOpener:
        def open(self, request, timeout=0):
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                hdrs=None,
                fp=BytesIO(b"forbidden"),
            )

    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "_OPENER", FailOpener())

    response = light.light_login(force=True)

    assert response["success"] is False
    assert "forbidden" in response["message"].lower()
    assert response["diagnostics"][0]["status_code"] == 403


def test_action_request_relogs_and_retries_once_when_business_api_returns_html(monkeypatch) -> None:
    class HtmlThenJsonOpener:
        def __init__(self):
            self.count = 0

        def open(self, request, timeout=0):
            self.count += 1
            if self.count == 1:
                return _FakeResponse(b"<html><form action='/action/login'><input name='password'></form></html>")
            return _FakeResponse(b'{"rows":[{"id":1}]}')

    calls = {"login": []}

    def fake_login(force=False, **kwargs):
        del kwargs
        calls["login"].append(force)
        return {"success": True, "message": "ok", "data": None, "raw": ""}

    opener = HtmlThenJsonOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "light_login", fake_login)
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is True
    assert response["data"] == {"rows": [{"id": 1}]}
    assert opener.count == 2
    assert calls["login"] == [True]


def test_action_request_relogs_with_cookie_and_decodes_json_bytes_without_content_type(monkeypatch) -> None:
    cookie_jar = light.http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    requests = []

    class HtmlLoginJsonHandler(urllib.request.BaseHandler):
        handler_order = 100

        def default_open(self, request):
            requests.append(request)
            headers = Message()
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                headers.add_header("Set-Cookie", "-goahead-session-=session-json; Path=/")
                return _FakeResponse(LOGIN_PAGE_HTML, headers=headers, url=request.full_url)
            if len(requests) == 1:
                return _FakeResponse(LOGIN_PAGE_HTML, headers=headers, url=request.full_url)
            return _FakeResponse(
                b'{\n\t"rows": [{"id": 1, "name": "\xe4\xb8\x8a\xe8\xaf\xbe\xe9\x93\x83"}]\n}',
                headers=headers,
                url=request.full_url,
            )

    opener.add_handler(HtmlLoginJsonHandler())
    monkeypatch.setattr(light, "LIGHT_REMOTE_USERNAME", "useradmin")
    monkeypatch.setattr(light, "LIGHT_REMOTE_PASSWORD", "123456")
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "_OPENER", opener)
    monkeypatch.setattr(light, "_COOKIE_JAR", cookie_jar)

    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is True
    assert response["data"] == {"rows": [{"id": 1, "name": "上课铃"}]}
    assert [item["phase"] for item in response["diagnostics"]] == [
        "initial",
        "relogin",
        "business_probe",
        "retry_after_relogin",
    ]
    assert response["diagnostics"][1]["set_cookie_has_action_session"] is True
    assert response["diagnostics"][1]["business_probe_success"] is True
    assert requests[3].get_header("Cookie") == "-goahead-session-=session-json"


def test_action_request_reports_relogin_failure_when_business_api_returns_html(monkeypatch) -> None:
    class HtmlOpener:
        def open(self, request, timeout=0):
            return _FakeResponse(b"<html><form action='/action/login'><input name='password'></form></html>")

    calls = {"login": []}

    def fake_login(force=False, **kwargs):
        del kwargs
        calls["login"].append(force)
        return {"success": False, "message": "cookie refresh failed", "data": None, "raw": ""}

    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "light_login", fake_login)
    monkeypatch.setattr(light, "_OPENER", HtmlOpener())

    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is False
    assert "re-login failed" in response["message"].lower()
    assert "cookie refresh failed" in response["message"]
    assert calls["login"] == [True]


def test_action_request_reports_html_after_successful_relogin_without_infinite_retry(monkeypatch) -> None:
    class AlwaysHtmlOpener:
        def __init__(self):
            self.count = 0

        def open(self, request, timeout=0):
            self.count += 1
            return _FakeResponse(b"<html><form action='/action/login'><input name='password'></form></html>")

    calls = {"login": []}

    def fake_login(force=False, **kwargs):
        del kwargs
        calls["login"].append(force)
        return {"success": True, "message": "ok", "data": None, "raw": ""}

    opener = AlwaysHtmlOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "light_login", fake_login)
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is False
    assert "still returned login page" in response["message"].lower()
    assert [item["phase"] for item in response["diagnostics"]] == ["initial", "retry_after_relogin"]
    assert all(item["html_like"] for item in response["diagnostics"])
    assert opener.count == 2
    assert calls["login"] == [True]


def test_action_request_relogs_and_retries_once_on_401(monkeypatch) -> None:
    class RetryOpener:
        def __init__(self):
            self.count = 0

        def open(self, request, timeout=0):
            self.count += 1
            if self.count == 1:
                raise HTTPError(
                    request.full_url,
                    401,
                    "Unauthorized",
                    hdrs=None,
                    fp=BytesIO(b"unauthorized"),
                )
            return _FakeResponse(b'{"rows":[{"id":1}]}')

    calls = {"login": []}

    def fake_login(force=False, **kwargs):
        del kwargs
        calls["login"].append(force)
        return {"success": True, "message": "ok", "data": None, "raw": ""}

    opener = RetryOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "light_login", fake_login)
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is True
    assert response["data"] == {"rows": [{"id": 1}]}
    assert opener.count == 2
    assert calls["login"] == [True]


def test_action_request_reports_relogin_failure_on_401(monkeypatch) -> None:
    class UnauthorizedOpener:
        def __init__(self):
            self.count = 0

        def open(self, request, timeout=0):
            self.count += 1
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                hdrs=None,
                fp=BytesIO(b"unauthorized"),
            )

    calls = {"login": []}

    def fake_login(force=False, **kwargs):
        del kwargs
        calls["login"].append(force)
        return {"success": False, "message": "bad credentials", "data": None, "raw": ""}

    opener = UnauthorizedOpener()
    monkeypatch.setattr(light, "LIGHT_REMOTE_AUTO_LOGIN", True)
    monkeypatch.setattr(light, "light_login", fake_login)
    monkeypatch.setattr(light, "_OPENER", opener)

    response = light.action_request("POST", "/action/getmedia")

    assert response["success"] is False
    assert "re-login failed" in response["message"].lower()
    assert "bad credentials" in response["message"]
    assert opener.count == 1
    assert calls["login"] == [True]
