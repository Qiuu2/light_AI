from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_resolve_terminal_ids_prefers_terminal_matched_id(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_remote_terminal_map", lambda: {})

    resolved_ids, unresolved = api_public._resolve_terminal_ids_from_slots(
        {
            "terminal_name": "接待室喝茶终端",
            "terminal_name_matched": "接待室喝茶",
            "terminal_matched_id": 35,
        }
    )

    assert resolved_ids == ["35"]
    assert unresolved == {}


def test_sanitize_play_media_slots_removes_terminal_id_from_volume_collision() -> None:
    sanitized = api_public._sanitize_play_media_slots(
        "在接待室喝茶播放远走高飞，音量25",
        {
            "terminal_name": "接待室喝茶",
            "terminal_matched_id": 35,
            "terminal_id": "25",
            "volume": "25",
        },
    )

    assert sanitized["terminal_name"] == "接待室喝茶"
    assert sanitized["terminal_matched_id"] == 35
    assert "terminal_id" not in sanitized


def test_sanitize_play_media_slots_keeps_explicit_terminal_id_even_when_volume_matches() -> None:
    sanitized = api_public._sanitize_play_media_slots(
        "终端25播放远走高飞，音量25",
        {
            "terminal_id": "25",
            "volume": "25",
        },
    )

    assert sanitized["terminal_id"] == "25"
