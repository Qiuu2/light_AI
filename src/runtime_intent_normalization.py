from __future__ import annotations

from typing import Dict, Mapping, Tuple


_TASK_NAME_KEYS = ("task_name", "TASK", "task")
_MEDIA_NAME_KEYS = ("media_name", "CONTENT", "audio", "medianame")
_MEDIA_SIGNAL_KEYS = (
    "zone_name",
    "terminal_id",
    "terminal_name",
    "scope_id",
    "SCOPE",
    "LOC",
    "play_duration",
    "duration",
    "play_length",
    "play_count",
    "count",
    "volume",
)


def _slot_text(slots: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = slots.get(key)
        if value in (None, ""):
            continue
        return str(value)
    return ""


def normalize_runtime_play_intent(intent: str, slots: Mapping[str, object] | None) -> Tuple[str, Dict[str, object]]:
    normalized_intent = str(intent or "").strip()
    normalized_slots = dict(slots or {})
    if normalized_intent not in {"play_media", "play_task"}:
        return normalized_intent, normalized_slots

    task_name = _slot_text(normalized_slots, *_TASK_NAME_KEYS)
    media_name = _slot_text(normalized_slots, *_MEDIA_NAME_KEYS)
    if not (task_name or media_name):
        return normalized_intent, normalized_slots

    has_media_signal = bool(_slot_text(normalized_slots, *_MEDIA_SIGNAL_KEYS))
    normalized_intent = "play_media" if has_media_signal else "play_task"
    if normalized_intent == "play_media" and not media_name and task_name:
        normalized_slots["media_name"] = task_name
    elif normalized_intent == "play_task" and not task_name and media_name:
        normalized_slots["task_name"] = media_name
    return normalized_intent, normalized_slots


__all__ = ["normalize_runtime_play_intent"]
