from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


@pytest.fixture(autouse=True)
def _isolate_remote_caches():
    remote_cache = dict(api_public.REMOTE_CACHE)
    ttl_cache = dict(api_public.TTL_CACHE)
    api_public.REMOTE_CACHE.clear()
    api_public.TTL_CACHE.clear()
    yield
    api_public.REMOTE_CACHE.clear()
    api_public.REMOTE_CACHE.update(remote_cache)
    api_public.TTL_CACHE.clear()
    api_public.TTL_CACHE.update(ttl_cache)


def test_remote_fetch_schedule_sources_prefers_primary_without_fetching_fallback(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(api_public, "REMOTE_SCHEDULES_PATH", "/primary")
    monkeypatch.setattr(api_public, "REMOTE_SCHEDULES_FALLBACK_PATH", "/fallback")

    def fake_remote_request(method: str, path: str, **kwargs):
        del method, kwargs
        calls.append(path)
        if path == "/primary":
            return {"data": [{"sechename": "春季作息"}]}
        raise AssertionError(f"unexpected fallback fetch: {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    raws = api_public._remote_fetch_schedule_sources()

    assert calls == ["/primary"]
    assert raws == [{"data": [{"sechename": "春季作息"}]}]


def test_remote_fetch_schedule_sources_falls_back_when_primary_is_empty(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(api_public, "REMOTE_SCHEDULES_PATH", "/primary")
    monkeypatch.setattr(api_public, "REMOTE_SCHEDULES_FALLBACK_PATH", "/fallback")

    def fake_remote_request(method: str, path: str, **kwargs):
        del method, kwargs
        calls.append(path)
        if path == "/primary":
            return {"data": []}
        if path == "/fallback":
            return {"data": [{"sechename": "空目录方案"}]}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    raws = api_public._remote_fetch_schedule_sources()

    assert calls == ["/primary", "/fallback"]
    assert raws == [{"data": [{"sechename": "空目录方案"}]}]


def test_fetch_remote_schedule_payload_reuses_prefetched_media_and_terminal_payloads(monkeypatch) -> None:
    api_public.TTL_CACHE["mediainfo_payload"] = (
        time.time(),
        api_public.REMOTE_LOOKUP_CACHE_SECONDS,
        {"data": [{"mediaid": "911", "name": "上课铃"}]},
    )
    api_public.TTL_CACHE["terminalinfo_payload"] = (
        time.time(),
        api_public.REMOTE_LOOKUP_CACHE_SECONDS,
        {"data": [{"id": "8", "name": "讲台终端", "zone": "1"}]},
    )

    monkeypatch.setattr(
        api_public,
        "_remote_fetch_schedule_sources",
        lambda force=False: [{"data": [{"sechename": "春季作息"}]}],
    )
    monkeypatch.setattr(
        api_public,
        "_adapt_remote_schedules",
        lambda raw: {
            "version": "remote",
            "generated_at": "",
            "schedules": [{"schedule_name": "春季作息", "status": "启用", "tasks": []}],
            "broadcasts": [],
            "livecasts": [],
        },
    )
    monkeypatch.setattr(api_public, "_remote_schedule_names", lambda: [])
    monkeypatch.setattr(api_public, "_fetch_remote_taskinfo_list", lambda kind, task_type: [])
    monkeypatch.setattr(api_public, "_load_local_broadcasts", lambda: {"broadcasts": [], "livecasts": []})

    calls = []

    def fake_remote_request(method: str, path: str, **kwargs):
        del method, kwargs
        calls.append(path)
        raise AssertionError(f"unexpected remote fetch: {path}")

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    payload = api_public._fetch_remote_schedule_payload(
        force=True,
        reuse_prefetched_media=True,
        reuse_prefetched_terminal=True,
    )

    assert payload["schedules"][0]["schedule_name"] == "春季作息"
    assert calls == []


def test_sync_remote_data_reuses_prefetched_lookups_for_schedule_sync(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_fetch_remote_all_audio", lambda force=False: {"data": []})
    monkeypatch.setattr(api_public, "_fetch_remote_all_loc", lambda force=False: {"data": []})

    def fake_fetch_remote_schedule_payload(**kwargs):
        captured["kwargs"] = kwargs
        return {"schedules": [], "broadcasts": [], "livecasts": []}

    monkeypatch.setattr(api_public, "_fetch_remote_schedule_payload", fake_fetch_remote_schedule_payload)
    monkeypatch.setattr(api_public, "_build_all_task_payload", lambda payload: {"data": []})
    monkeypatch.setattr(api_public, "_store_set", lambda key, payload: None)
    monkeypatch.setattr(api_public, "_write_cache_json", lambda path, payload: None)
    monkeypatch.setattr(api_public, "_write_engine_all_task", lambda payload: None)
    monkeypatch.setattr(api_public, "_write_engine_schedules", lambda payload: None)
    monkeypatch.setattr(api_public, "_reload_engine_schedules", lambda: None)
    monkeypatch.setattr(api_public, "_write_engine_all_audio", lambda payload: None)
    monkeypatch.setattr(api_public, "_write_engine_all_loc", lambda payload: None)

    results = api_public._sync_remote_data(force=True)

    assert results == {"all_audio": True, "all_loc": True, "broadcast_schedules": True}
    assert captured["kwargs"] == {
        "force": True,
        "reuse_prefetched_media": True,
        "reuse_prefetched_terminal": True,
    }
