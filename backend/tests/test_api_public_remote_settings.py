from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
import socket
import sys
import urllib.parse
import urllib.request

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public
from backend.routes import light


def test_remote_settings_helpers_are_defined_once() -> None:
    source = Path(api_public.__file__).read_text(encoding="utf-8")
    assert source.count("def _normalize_remote_base_url(") == 1
    assert source.count("def _normalize_remote_settings_payload(") == 1


@pytest.fixture(autouse=True)
def _isolate_remote_settings(monkeypatch: pytest.MonkeyPatch):
    original_remote_settings = deepcopy(api_public.DATA_STORE["remote_settings"])
    original_sessions = deepcopy(api_public.LOCAL_AUTH_SESSIONS)
    original_remote_base_url = api_public.REMOTE_BASE_URL
    original_remote_token = api_public.REMOTE_TOKEN

    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {"remote_base_url": "", "last_verified_at": "", "last_verified_ip": "", "excluded_candidate_ips": []}
        ),
    )
    api_public.LOCAL_AUTH_SESSIONS.clear()
    api_public.REMOTE_TOKEN = None
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)
    monkeypatch.setattr(api_public, "_write_json", lambda path, payload: None)
    yield
    api_public.DATA_STORE["remote_settings"] = original_remote_settings
    api_public.LOCAL_AUTH_SESSIONS.clear()
    api_public.LOCAL_AUTH_SESSIONS.update(original_sessions)
    api_public.REMOTE_BASE_URL = original_remote_base_url
    api_public.REMOTE_TOKEN = original_remote_token


def test_remote_bootstrap_candidates_exclude_loopback_and_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_psutil = SimpleNamespace(
        net_if_addrs=lambda: {
            "lo": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
            "eth0": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.2.159"),
                SimpleNamespace(family=socket.AF_INET, address="192.168.2.159"),
            ],
            "eth1": [SimpleNamespace(family=socket.AF_INET, address="12.12.2.51")],
        }
    )
    monkeypatch.setattr(api_public, "psutil", fake_psutil)

    assert api_public._remote_bootstrap_candidates() == [
        {"interface": "eth0", "ip": "192.168.2.159"},
        {"interface": "eth1", "ip": "12.12.2.51"},
    ]


def test_remote_bootstrap_candidates_respect_excluded_candidate_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": ["212.218.2.1"],
            }
        ),
    )
    fake_psutil = SimpleNamespace(
        net_if_addrs=lambda: {
            "eth0": [SimpleNamespace(family=socket.AF_INET, address="192.168.3.159")],
            "eth1": [SimpleNamespace(family=socket.AF_INET, address="12.12.2.51")],
            "eth2": [SimpleNamespace(family=socket.AF_INET, address="212.218.2.1")],
        }
    )
    monkeypatch.setattr(api_public, "psutil", fake_psutil)

    assert api_public._remote_bootstrap_candidates() == [
        {"interface": "eth0", "ip": "192.168.3.159"},
        {"interface": "eth1", "ip": "12.12.2.51"},
    ]


def test_auth_remote_bootstrap_returns_suggested_remote_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_public,
        "psutil",
        SimpleNamespace(
            net_if_addrs=lambda: {
                "eth0": [SimpleNamespace(family=socket.AF_INET, address="192.168.2.159")],
            }
        ),
    )

    with TestClient(api_public.app) as client:
        response = client.get("/auth/remote-bootstrap")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["saved_remote_base_url"] == ""
    assert data["candidates"] == [{"interface": "eth0", "ip": "192.168.2.159"}]
    assert data["suggested_remote_base_urls"] == ["http://192.168.2.159:99"]
    assert data["excluded_candidate_ips"] == []


def test_remote_settings_management_routes_are_not_exposed() -> None:
    routes = {
        (path, tuple(sorted(methods)))
        for path, methods in (
            (getattr(route, "path", ""), getattr(route, "methods", set()))
            for route in api_public.app.routes
        )
    }

    assert ("/data/remote_settings", ("GET",)) not in routes
    assert ("/data/remote_settings", ("PUT",)) not in routes


def test_api_public_app_mounts_light_routes() -> None:
    routes = {getattr(route, "path", "") for route in api_public.app.routes}
    assert "/api/light/resources" in routes
    assert "/api/light/schedules" in routes
    assert "/api/light/tasks" in routes
    assert "/api/light/instant-play" in routes


def test_auth_login_uses_explicit_remote_base_url_and_persists_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, str] = {}

    def fake_action_login(remote_base_url: str, username: str, password: str):
        recorded["remote_base_url"] = remote_base_url
        recorded["username"] = username
        recorded["password"] = password
        return {"success": True, "message": "ok", "data": None, "raw": ""}

    monkeypatch.setattr(api_public._light_action, "login_with_credentials", fake_action_login)
    with TestClient(api_public.app) as client:
        response = client.post(
            "/auth/login",
            json={
                "username": "admin",
                "password": "123456",
                "remote_base_url": "http://192.168.2.159:99",
            },
        )

    assert response.status_code == 200
    assert recorded == {
        "remote_base_url": "http://192.168.2.159:99",
        "username": "admin",
        "password": "123456",
    }
    assert api_public._load_remote_settings_payload()["remote_base_url"] == "http://192.168.2.159:99"


def test_auth_login_then_light_resources_uses_same_action_base_url_and_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cookie_jar = light.http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    requests = []

    class ActionHandler(urllib.request.BaseHandler):
        handler_order = 100

        def default_open(self, request):
            requests.append(request)
            headers = Message()
            if request.full_url.endswith("/action/login?username=useradmin&password=123456"):
                headers.add_header("Set-Cookie", "-goahead-session-=session-199; Path=/")
                return _LightFakeResponse(b"<html>login</html>", headers=headers, url=request.full_url)
            return _LightFakeResponse(b'{"rows":[]}', headers=headers, url=request.full_url)

    class _LightFakeResponse:
        def __init__(self, body: bytes, headers=None, url="http://192.168.3.199/action/mock"):
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

    opener.add_handler(ActionHandler())
    monkeypatch.setattr(light, "_OPENER", opener)
    monkeypatch.setattr(light, "_COOKIE_JAR", cookie_jar)

    with TestClient(api_public.app) as client:
        login_response = client.post(
            "/auth/login",
            json={
                "username": "useradmin",
                "password": "123456",
                "remote_base_url": "http://192.168.3.199",
            },
        )
        token = login_response.json()["data"]["token"]
        resources_response = client.get("/api/light/resources", headers={"X-Token": token})

    assert login_response.status_code == 200
    assert resources_response.status_code == 200
    assert {urllib.parse.urlparse(item.full_url).netloc for item in requests} == {"192.168.3.199"}
    business_cookie_headers = [item.get_header("Cookie") for item in requests if "/action/login" not in item.full_url]
    assert business_cookie_headers == [
        "-goahead-session-=session-199",
        "-goahead-session-=session-199",
        "-goahead-session-=session-199",
        "-goahead-session-=session-199",
        "-goahead-session-=session-199",
    ]


def test_auth_token_login_route_is_removed() -> None:
    with TestClient(api_public.app) as client:
        response = client.post(
            "/auth/token-login",
            json={
                "token": "remote-token-1",
                "remote_base_url": "http://192.168.2.159:99",
            },
        )

    assert response.status_code == 404
    return
    assert "不支持 token 登录" in response.json()["detail"]


def test_submit_with_current_remote_token_propagates_remote_base_url_into_worker() -> None:
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "http://117.40.88.155:99/api",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": [],
            }
        ),
    )
    reset_base_url = api_public.CURRENT_REMOTE_BASE_URL.set("http://192.168.2.159:99/api")
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = api_public._submit_with_current_remote_token(executor, api_public._resolve_remote_base_url)
            assert future.result() == "http://192.168.2.159:99/api"
    finally:
        api_public.CURRENT_REMOTE_BASE_URL.reset(reset_base_url)


def test_fetch_remote_schedule_payload_keeps_session_remote_base_url_inside_parallel_schedule_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "http://117.40.88.155:99/api",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": [],
            }
        ),
    )
    recorded_urls: list[str] = []

    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_sources",
        lambda force=False: [[{"sechename": "早操"}, {"sechename": "眼保健操"}]],
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_remote_media_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_remote_terminal_lookup", lambda: {})
    monkeypatch.setattr(api_public, "_fetch_remote_taskinfo_list", lambda kind, task_type: [])

    def fake_remote_fetch_schedule_tasks(schedule_name: str) -> list:
        del schedule_name
        recorded_urls.append(api_public._resolve_remote_base_url())
        return []

    monkeypatch.setattr(api_public, "_remote_fetch_schedule_tasks", fake_remote_fetch_schedule_tasks)

    reset_base_url = api_public.CURRENT_REMOTE_BASE_URL.set("http://192.168.2.159:99/api")
    try:
        payload = api_public._fetch_remote_schedule_payload(force=True)
    finally:
        api_public.CURRENT_REMOTE_BASE_URL.reset(reset_base_url)

    assert [item["schedule_name"] for item in payload["schedules"]] == ["早操", "眼保健操"]
    assert recorded_urls == [
        "http://192.168.2.159:99/api",
        "http://192.168.2.159:99/api",
    ]


def test_resolve_remote_base_url_prefers_saved_value_before_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "http://192.168.2.159:99/api",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": [],
            }
        ),
    )
    monkeypatch.setattr(api_public, "REMOTE_BASE_URL", "http://117.40.88.155:99/api")

    assert api_public._resolve_remote_base_url() == "http://192.168.2.159:99/api"


def test_sync_data_route_prefers_session_remote_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "http://117.40.88.155:99/api",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": [],
            }
        ),
    )
    recorded: dict[str, str] = {}

    def fake_sync_remote_data(force: bool = False, keys=None):
        del force, keys
        recorded["remote_base_url"] = api_public._resolve_remote_base_url()
        return {"broadcast_schedules": False}

    monkeypatch.setattr(api_public, "_sync_remote_data", fake_sync_remote_data)
    monkeypatch.setattr(api_public, "_reload_engine_assets", lambda: None)

    session = api_public._create_local_session(
        "remote-token-4",
        "Token User",
        "token",
        remote_base_url="http://192.168.2.159:99/api",
    )

    with TestClient(api_public.app) as client:
        response = client.post(
            "/admin/sync_data?repair_catalog=false",
            headers={"X-Token": session["token"]},
        )

    assert response.status_code == 200
    assert recorded["remote_base_url"] == "http://192.168.2.159:99/api"


def test_remote_request_rejects_legacy_terminal_protocol() -> None:
    with pytest.raises(HTTPException) as exc_info:
        api_public._remote_request(
            "GET",
            "/terminal/terzone",
            include_auth=False,
            remote_base_url="http://192.168.2.159:99",
        )

    assert exc_info.value.status_code == 501
    assert "不再支持旧远端接口" in str(exc_info.value.detail)


def test_remote_request_rejects_legacy_terminal_protocol_from_session_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "http://117.40.88.155:99/api",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": [],
            }
        ),
    )
    reset_base_url = api_public.CURRENT_REMOTE_BASE_URL.set("http://192.168.2.159:99")
    try:
        with pytest.raises(HTTPException) as exc_info:
            api_public._remote_request(
                "GET",
                "/terminal/terzone",
                include_auth=False,
            )
    finally:
        api_public.CURRENT_REMOTE_BASE_URL.reset(reset_base_url)

    assert exc_info.value.status_code == 501
    assert "不再支持旧远端接口" in str(exc_info.value.detail)


def test_legacy_all_terminal_data_route_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_public._store_set(
        "remote_settings",
        api_public._normalize_remote_settings_payload(
            {
                "remote_base_url": "http://117.40.88.155:99/api",
                "last_verified_at": "",
                "last_verified_ip": "",
                "excluded_candidate_ips": [],
            }
        ),
    )
    recorded_urls: list[str] = []

    def fake_remote_terzone_cached(force: bool = False):
        del force
        recorded_urls.append(api_public._resolve_remote_base_url())
        return {"data": [{"id": "zone-1"}, {"id": "zone-2"}]}

    def fake_remote_terminalinfo_payload(force: bool = False):
        del force
        recorded_urls.append(api_public._resolve_remote_base_url())
        return {"data": []}

    def fake_remote_zoneterminal_cached(zone_id: str, force: bool = False):
        del zone_id, force
        recorded_urls.append(api_public._resolve_remote_base_url())
        return {"data": []}

    monkeypatch.setattr(api_public, "_remote_terzone_cached", fake_remote_terzone_cached)
    monkeypatch.setattr(api_public, "_remote_terminalinfo_payload", fake_remote_terminalinfo_payload)
    monkeypatch.setattr(api_public, "_remote_zoneterminal_cached", fake_remote_zoneterminal_cached)

    session = api_public._create_local_session(
        "remote-token-5",
        "Token User",
        "token",
        remote_base_url="http://192.168.2.159:99/api",
    )

    with TestClient(api_public.app) as client:
        response = client.get(
            "/terminal/alldata",
            headers={"X-Token": session["token"]},
        )

    assert response.status_code == 404
    assert recorded_urls == []
