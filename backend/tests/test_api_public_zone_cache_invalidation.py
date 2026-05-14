from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public
from backend.assistant.runtime_reply import stable_reply


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


def test_create_zone_clears_zone_runtime_caches_after_success(monkeypatch) -> None:
    sync_calls = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_slot_values", lambda slots, *keys: ["zone-new"])
    monkeypatch.setattr(api_public, "_remote_zone_items", lambda: [])
    monkeypatch.setattr(api_public, "_try_create_zone_remote", lambda zone_name: (True, [{"ok": True, "zone": zone_name}]))
    monkeypatch.setattr(
        api_public,
        "_sync_remote_data",
        lambda force=False, keys=None: sync_calls.append((force, tuple(keys or []))) or {"all_loc": True},
    )

    api_public.TTL_CACHE["terzone_payload"] = (time.time(), 30, {"data": [{"id": "3", "zonename": "zone-old"}]})
    api_public.TTL_CACHE["zoneterminal_3"] = (time.time(), 15, {"data": [{"id": "9"}]})
    api_public.TTL_CACHE["enriched_terzone_items"] = (time.time(), 30, [{"id": "3", "zonename": "zone-old"}])
    api_public.TTL_CACHE["terminal_map"] = (time.time(), 30, {"terminal-a": "9"})
    api_public.REMOTE_CACHE["terminal_lookup"] = {"9": {"name": "terminal-a", "zone": "zone-old"}}
    api_public.REMOTE_CACHE["terminal_map"] = {"terminal-a": "9"}

    reply, state, action_log = api_public._apply_create_zone_intent("create zone-new", {"zone_name": "zone-new"})

    assert "zone-new" in reply
    assert "分区" in reply
    assert "Created zones" not in reply
    assert state == {"missing_slots": []}
    assert action_log[0]["action"] == "create_zone"
    assert sync_calls == [(True, ("all_loc",))]
    assert "terzone_payload" not in api_public.TTL_CACHE
    assert "zoneterminal_3" not in api_public.TTL_CACHE
    assert "enriched_terzone_items" not in api_public.TTL_CACHE
    assert "terminal_map" not in api_public.TTL_CACHE
    assert "terminal_lookup" not in api_public.REMOTE_CACHE
    assert "terminal_map" not in api_public.REMOTE_CACHE


def test_delete_zone_clears_targeted_zone_runtime_caches(monkeypatch) -> None:
    sync_calls = []

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_slot_values", lambda slots, *keys: ["zone-old"])
    monkeypatch.setattr(api_public, "_strict_resolve_zone_ids", lambda *args: (["8"], [], None))
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(api_public, "_ensure_remote_write_ack", lambda resp, label: None)
    monkeypatch.setattr(api_public, "_zone_ids_present", lambda zone_ids: set())
    monkeypatch.setattr(
        api_public,
        "_sync_remote_data",
        lambda force=False, keys=None: sync_calls.append((force, tuple(keys or []))) or {"all_loc": True},
    )

    api_public.TTL_CACHE["terzone_payload"] = (time.time(), 30, {"data": [{"id": "8", "zonename": "zone-old"}]})
    api_public.TTL_CACHE["zoneterminal_8"] = (time.time(), 15, {"data": [{"id": "9"}]})
    api_public.TTL_CACHE["zoneterminal_9"] = (time.time(), 15, {"data": [{"id": "10"}]})

    reply, state, action_log = api_public._apply_delete_zone_intent("delete zone-old", {"zone_name": "zone-old"})

    assert isinstance(reply, str)
    assert "zone-old" in reply
    assert "删除" in reply
    assert state == {"missing_slots": []}
    assert action_log[0]["action"] == "delete_zone"
    assert sync_calls == [(True, ("all_loc",))]
    assert "terzone_payload" not in api_public.TTL_CACHE
    assert "zoneterminal_8" not in api_public.TTL_CACHE
    assert "zoneterminal_9" in api_public.TTL_CACHE


def test_delete_zone_waits_for_remote_eventual_consistency(monkeypatch) -> None:
    sync_calls = []
    sleep_calls = []
    remaining_states = [{"8"}, set()]

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_slot_values", lambda slots, *keys: ["zone-new"])
    monkeypatch.setattr(api_public, "_strict_resolve_zone_ids", lambda *args: (["8"], [], None))
    monkeypatch.setattr(api_public, "_remote_request", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        api_public,
        "_sync_remote_data",
        lambda force=False, keys=None: sync_calls.append((force, tuple(keys or []))) or {"all_loc": True},
    )
    monkeypatch.setattr(api_public.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        api_public,
        "_zone_ids_present",
        lambda zone_ids: remaining_states.pop(0),
    )

    reply, state, action_log = api_public._apply_delete_zone_intent("delete zone-new", {"zone_name": "zone-new"})

    assert "zone-new" in reply
    assert "删除" in reply
    assert state == {"missing_slots": []}
    assert action_log[0]["action"] == "delete_zone"
    assert sleep_calls == [api_public.REMOTE_ZONE_VERIFY_DELAY_SECONDS]
    assert sync_calls == [(True, ("all_loc",))]


def test_remove_terminal_from_zone_delete_payload_includes_terminalid_and_waits_for_membership_clear(monkeypatch) -> None:
    sync_calls = []
    sleep_calls = []
    verify_states = [False, True]
    captured = {}

    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_slot_values", lambda slots, *keys: ["zone-a"])
    monkeypatch.setattr(api_public, "_strict_resolve_zone_ids", lambda *args: (["8"], [], None))
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots, expand_zones=False: (["9"], {}))
    monkeypatch.setattr(api_public, "_terminal_lookup_for_actions", lambda: {"9": {"name": "终端9"}})
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda method, path, **kwargs: captured.update(
            {"method": method, "path": path, "json_body": kwargs.get("json_body")}
        ) or {"status": "ok"},
    )
    monkeypatch.setattr(
        api_public,
        "_verify_zone_membership",
        lambda zone_ids, terminal_ids, should_contain: verify_states.pop(0),
    )
    monkeypatch.setattr(api_public.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        api_public,
        "_sync_remote_data",
        lambda force=False, keys=None: sync_calls.append((force, tuple(keys or []))) or {"all_loc": True},
    )

    reply, state, action_log = api_public._apply_remove_terminal_from_zone_intent(
        "remove terminal 9 from zone-a",
        {"zone_name": "zone-a", "terminal_id": "9"},
    )

    assert "zone-a" in reply
    assert ("移除" in reply) or ("移出" in reply)
    assert state == {"missing_slots": []}
    assert action_log[0]["action"] == "remove_terminal_from_zone"
    assert captured == {
        "method": "DELETE",
        "path": "/terminal/zoneterminal",
        "json_body": {"data": [{"id": 9, "terminalid": 9, "taskid": 8}]},
    }
    assert sleep_calls == [api_public.REMOTE_ZONE_VERIFY_DELAY_SECONDS]
    assert sync_calls == [(True, ("all_loc",))]


def test_remove_terminal_from_zone_surfaces_remote_ack_error_detail(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_slot_values", lambda slots, *keys: ["zone-a"])
    monkeypatch.setattr(api_public, "_strict_resolve_zone_ids", lambda *args: (["8"], [], None))
    monkeypatch.setattr(api_public, "_resolve_terminal_ids_for_play_media", lambda slots, expand_zones=False: (["9"], {}))
    monkeypatch.setattr(
        api_public,
        "_remote_request",
        lambda *args, **kwargs: {
            "message": 'Undefined array key "terminalid"',
            "exception": "ErrorException",
            "file": "/var/www/html/lumen/app/Http/Controllers/Test.php",
        },
    )

    reply, state, logs = api_public._apply_remove_terminal_from_zone_intent(
        "remove terminal 9 from zone-a",
        {"zone_name": "zone-a", "terminal_id": "9"},
    )

    assert state == {"missing_slots": []}
    assert logs == []
    assert 'Undefined array key "terminalid"' in reply
    assert "ErrorException" in reply
    assert "Test.php" in reply


def test_create_zone_failure_reply_is_fully_chinese(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_enabled", lambda: True)
    monkeypatch.setattr(api_public, "_slot_values", lambda slots, *keys: ["zone-new"])
    monkeypatch.setattr(api_public, "_remote_zone_items", lambda: [])
    monkeypatch.setattr(
        api_public,
        "_try_create_zone_remote",
        lambda zone_name: (False, [{"error": "payload rejected"}]),
    )
    monkeypatch.setattr(api_public, "_sync_remote_data", lambda force=False, keys=None: {"all_loc": True})

    reply, state, action_log = api_public._apply_create_zone_intent("create zone-new", {"zone_name": "zone-new"})

    assert state == {"missing_slots": []}
    assert action_log[0]["action"] == "create_zone"
    assert "创建" in reply or "新建" in reply
    assert "First error" not in reply
    assert "No zone was created" not in reply


def test_stable_runtime_reply_is_deterministic() -> None:
    variants = ["已删除分区：{name}。", "分区{name}已删除。", "分区“{name}”删除完成。"]

    first = stable_reply("delete_zone", variants, "萝卜丁", name="萝卜丁")
    second = stable_reply("delete_zone", variants, "萝卜丁", name="萝卜丁")

    assert first == second
