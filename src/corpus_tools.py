from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_CORPUS_PATH = Path(__file__).resolve().parent / "data_clean_balanced.json"
DATA_CORPUS_PATH = BASE_DIR / "data" / "data_clean_balanced.json"
ALL_AUDIO_PATH = BASE_DIR / "backend" / "data" / "all_audio.json"

SINGLE_VALUE_SLOTS = {
    "schedule_name",
    "new_schedule_name",
    "media_name",
    "new_media_name",
    "task_name",
    "task_type",
    "terminal_id",
    "terminal_name",
    "zone_name",
    "source_time",
    "end_time",
    "time_offset",
    "play_duration",
    "play_count",
    "volume",
}

REQUIRED_SLOTS_BY_INTENT = {
    "replace_media": ("media_name", "new_media_name"),
    "replace_media_in_task": ("schedule_name", "media_name", "new_media_name"),
}
REQUIRED_SLOT_GROUPS_BY_INTENT = {
    "add_terminal_to_task": (
        ("terminal_id", "terminal_name"),
        ("schedule_name", "task_name"),
    ),
    "remove_terminal_from_task": (
        ("terminal_id", "terminal_name"),
        ("schedule_name", "task_name"),
    ),
}

PLACEHOLDER_MARKERS = (
    "另一个音频",
    "另一个媒体",
    "某歌曲",
    "某个音频",
    "某个媒体",
    "xx歌曲",
    "xxx歌曲",
    "xx音频",
    "xxx音频",
    "旧媒体",
    "新媒体",
)

MULTI_VALUE_DELIMS = re.compile(r"[，,、]")
WHITESPACE_RE = re.compile(r"\s+")
COMPACT_TEXT_RE = re.compile(r"[\s\-_.·•—~]+")


RANGE_HYPHEN_RE = re.compile(
    r"(?:(?:[01]?\d|2[0-3]):[0-5]\d|[上下]午\d{1,2}点(?:半|\d{1,2}分)?|\d{1,2}点(?:半|\d{1,2}分)?)\s*-\s*"
    r"(?:(?:[01]?\d|2[0-3]):[0-5]\d|[上下]午\d{1,2}点(?:半|\d{1,2}分)?|\d{1,2}点(?:半|\d{1,2}分)?)"
)
RANGE_TEXT_RE = re.compile(
    r"(?:今天|明天|后天|本周[一二三四五六日天]?|下周[一二三四五六日天]?|上周[一二三四五六日天]?|"
    r"周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天]|"
    r"\d{1,2}月\d{1,2}[日号]?|(?:上午|下午|中午|晚上|凌晨)?\d{1,2}(?::\d{2}|点(?:半|\d{1,2}分)?)?)"
    r"\s*(?:到|至|~|～)\s*"
    r"(?:今天|明天|后天|本周[一二三四五六日天]?|下周[一二三四五六日天]?|上周[一二三四五六日天]?|"
    r"周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天]|"
    r"\d{1,2}月\d{1,2}[日号]?|(?:上午|下午|中午|晚上|凌晨)?\d{1,2}(?::\d{2}|点(?:半|\d{1,2}分)?)?)"
)
SYMBOL_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)
RANGE_AUDIT_INTENTS = {"cancel_schedule", "query_task"}
SWAP_REQUIRED_SHAPE = ("schedule_name", "source_time", "end_time")


def _compact_text(value: str) -> str:
    return COMPACT_TEXT_RE.sub("", str(value or "")).lower()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path = SRC_CORPUS_PATH) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    payload = _load_json(path)
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"Expected list-like corpus payload, got {type(rows)}")
    samples = [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["data"] = samples
        return payload, samples
    return {"data": samples}, samples


def save_corpus(payload: Dict[str, Any], path: Path = SRC_CORPUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_corpus_copy(src_path: Path = SRC_CORPUS_PATH, dst_path: Path = DATA_CORPUS_PATH) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_path, dst_path)


def _iter_audio_names(payload: Any) -> Iterable[str]:
    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    names: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("medianame") or item.get("media_name")
        if not name:
            continue
        text = str(name).strip()
        if text:
            names.append(text)
    return names


def build_audio_canonical_map(path: Path = ALL_AUDIO_PATH) -> Dict[str, str]:
    if not path.exists():
        return {}
    compact_to_names: Dict[str, set[str]] = defaultdict(set)
    for name in _iter_audio_names(_load_json(path)):
        compact = _compact_text(name)
        if compact:
            compact_to_names[compact].add(name)
    canonical_map: Dict[str, str] = {}
    for compact, names in compact_to_names.items():
        if len(names) == 1:
            canonical_map[compact] = next(iter(names))
    return canonical_map


def _normalize_slots(slots: Any) -> Dict[str, str]:
    if not isinstance(slots, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key, value in slots.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            normalized[str(key)] = text
    return normalized


def canonicalize_media_slots(sample: Dict[str, Any], canonical_map: Dict[str, str]) -> Dict[str, Any]:
    text = str(sample.get("text", "") or "").strip()
    slots = _normalize_slots(sample.get("slots"))
    changed = False
    for key in ("media_name", "new_media_name"):
        raw_value = slots.get(key, "")
        if not raw_value:
            continue
        canonical = canonical_map.get(_compact_text(raw_value))
        if not canonical or canonical == raw_value:
            continue
        if raw_value in text:
            text = text.replace(raw_value, canonical)
        slots[key] = canonical
        changed = True
    if changed:
        sample = dict(sample)
        sample["text"] = text
        sample["slots"] = slots
        return sample
    if slots != sample.get("slots"):
        sample = dict(sample)
        sample["slots"] = slots
    return sample


def _is_multi_value(slot_key: str, value: str) -> bool:
    return slot_key in SINGLE_VALUE_SLOTS and bool(MULTI_VALUE_DELIMS.search(value))


def _contains_placeholder(value: str) -> bool:
    lower = str(value or "").strip().lower()
    if not lower:
        return False
    if any(marker.lower() in lower for marker in PLACEHOLDER_MARKERS):
        return True
    return bool(re.search(r"\b[xX]{2,}\b", lower))


def _missing_required_slots(intent: str, slots: Dict[str, str]) -> List[str]:
    return [slot for slot in REQUIRED_SLOTS_BY_INTENT.get(intent, ()) if not slots.get(slot)]


def _missing_required_slot_groups(intent: str, slots: Dict[str, str]) -> List[Tuple[str, ...]]:
    missing_groups: List[Tuple[str, ...]] = []
    for group in REQUIRED_SLOT_GROUPS_BY_INTENT.get(intent, ()):
        if not any(slots.get(slot_name) for slot_name in group):
            missing_groups.append(group)
    return missing_groups


def _slot_missing_from_text(text: str, slot_value: str) -> bool:
    return slot_value not in text


def _looks_like_range_text(text: str) -> bool:
    return bool(RANGE_TEXT_RE.search(text) or RANGE_HYPHEN_RE.search(text))


def _has_single_endpoint_range(intent: str, text: str, slots: Dict[str, str]) -> bool:
    if intent not in RANGE_AUDIT_INTENTS or not _looks_like_range_text(text):
        return False
    has_source = bool(slots.get("source_time"))
    has_end = bool(slots.get("end_time"))
    return has_source ^ has_end


def _has_invalid_swap_shape(intent: str, slots: Dict[str, str]) -> bool:
    if intent != "swap_schedule":
        return False
    return any(not slots.get(slot_name) for slot_name in SWAP_REQUIRED_SHAPE)


def _is_low_value_none_text(intent: str, text: str) -> bool:
    if intent != "none" or not text:
        return False
    if "lorem ipsum" in text.lower():
        return True
    compact = WHITESPACE_RE.sub("", text)
    return len(compact) >= 1 and SYMBOL_ONLY_RE.fullmatch(compact) is not None


def summarize_unknown_media_names(samples: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    canonical_map = build_audio_canonical_map()
    unknown_counts = Counter()
    for sample in samples:
        slots = _normalize_slots(sample.get("slots"))
        for key in ("media_name", "new_media_name"):
            value = slots.get(key, "")
            if not value:
                continue
            if _compact_text(value) not in canonical_map:
                unknown_counts[value] += 1
    return [{"name": name, "count": count} for name, count in unknown_counts.most_common(limit)]


def build_audit_report(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    intent_counts = Counter()
    slot_counts = Counter()
    required_missing = Counter()
    multi_value_slots = Counter()
    slot_not_in_text = Counter()
    placeholder_slots = Counter()
    placeholder_text_intents = Counter()
    range_text_single_endpoint = Counter()
    swap_schedule_invalid_shape = 0
    none_noise_count = 0
    issue_rows = 0

    duplicate_groups = defaultdict(list)
    for index, sample in enumerate(samples):
        text = str(sample.get("text", "") or "").strip()
        intent = str(sample.get("intent", "") or "").strip()
        slots = _normalize_slots(sample.get("slots"))

        if text:
            duplicate_groups[text].append((index, intent, json.dumps(slots, ensure_ascii=False, sort_keys=True)))

        if intent:
            intent_counts[intent] += 1
        for key, value in slots.items():
            slot_counts[key] += 1

        row_has_issue = False
        missing = _missing_required_slots(intent, slots)
        for slot_name in missing:
            required_missing[f"{intent}:{slot_name}"] += 1
            row_has_issue = True
        missing_groups = _missing_required_slot_groups(intent, slots)
        for group in missing_groups:
            required_missing[f"{intent}:{'/'.join(group)}"] += 1
            row_has_issue = True

        if intent in REQUIRED_SLOTS_BY_INTENT and _contains_placeholder(text):
            placeholder_text_intents[intent] += 1
            row_has_issue = True

        if _has_single_endpoint_range(intent, text, slots):
            range_text_single_endpoint[intent] += 1
            row_has_issue = True

        if _has_invalid_swap_shape(intent, slots):
            swap_schedule_invalid_shape += 1
            row_has_issue = True

        if _is_low_value_none_text(intent, text):
            none_noise_count += 1

        for key, value in slots.items():
            if _contains_placeholder(value):
                placeholder_slots[key] += 1
                row_has_issue = True
            if _is_multi_value(key, value):
                multi_value_slots[key] += 1
                row_has_issue = True
            if key in SINGLE_VALUE_SLOTS and _slot_missing_from_text(text, value):
                slot_not_in_text[key] += 1
                row_has_issue = True

        if row_has_issue:
            issue_rows += 1

    conflicting_duplicate_texts = []
    duplicate_slot_conflicts = 0
    for text, entries in duplicate_groups.items():
        intents = {intent for _, intent, _ in entries}
        slot_views = {slot_json for _, _, slot_json in entries}
        if len(entries) > 1 and (len(intents) > 1 or len(slot_views) > 1):
            duplicate_slot_conflicts += 1
            conflicting_duplicate_texts.append(text)

    report = {
        "total_samples": len(samples),
        "intent_count": len(intent_counts),
        "intent_counts": dict(intent_counts),
        "slot_counts": dict(slot_counts),
        "required_missing": dict(required_missing),
        "multi_value_slots": dict(multi_value_slots),
        "slot_not_in_text": dict(slot_not_in_text),
        "placeholder_slots": dict(placeholder_slots),
        "placeholder_text_intents": dict(placeholder_text_intents),
        "range_text_single_endpoint": dict(range_text_single_endpoint),
        "swap_schedule_invalid_shape": swap_schedule_invalid_shape,
        "none_noise_count": none_noise_count,
        "high_freq_unknown_media_names": summarize_unknown_media_names(samples),
        "duplicate_slot_conflicts": duplicate_slot_conflicts,
        "issue_rows": issue_rows,
        "hard_error_count": issue_rows + duplicate_slot_conflicts,
        "conflicting_duplicate_text_examples": conflicting_duplicate_texts[:20],
    }
    return report


def _sample_error_reasons(text: str, intent: str, slots: Dict[str, str]) -> List[str]:
    reasons: List[str] = []
    missing = _missing_required_slots(intent, slots)
    if missing:
        reasons.append(f"missing_required:{','.join(missing)}")
    missing_groups = _missing_required_slot_groups(intent, slots)
    for group in missing_groups:
        reasons.append(f"missing_required_any:{'/'.join(group)}")
    if intent in REQUIRED_SLOTS_BY_INTENT and _contains_placeholder(text):
        reasons.append("placeholder_in_text")
    if intent == "replace_media_in_task" and "task_name" in slots:
        reasons.append("replace_media_in_task_has_task_name")
    for key, value in slots.items():
        if _contains_placeholder(value):
            reasons.append(f"placeholder_slot:{key}")
        if _is_multi_value(key, value):
            reasons.append(f"multi_value:{key}")
        if key in SINGLE_VALUE_SLOTS and _slot_missing_from_text(text, value):
            reasons.append(f"slot_not_in_text:{key}")
    return reasons


def clean_corpus_payload(payload: Dict[str, Any], canonical_map: Dict[str, str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_rows = payload.get("data", [])
    if not isinstance(source_rows, list):
        raise ValueError("Corpus payload must contain a list under `data`.")

    cleaned_rows: List[Dict[str, Any]] = []
    removed_by_reason = Counter()
    duplicates_removed = 0

    for raw_sample in source_rows:
        if not isinstance(raw_sample, dict):
            removed_by_reason["invalid_sample"] += 1
            continue

        sample = canonicalize_media_slots(dict(raw_sample), canonical_map)
        text = str(sample.get("text", "") or "").strip()
        intent = str(sample.get("intent", "") or "").strip()
        slots = _normalize_slots(sample.get("slots"))

        sample["text"] = text
        sample["intent"] = intent
        sample["slots"] = slots

        if not text or not intent:
            removed_by_reason["empty_text_or_intent"] += 1
            continue

        reasons = _sample_error_reasons(text, intent, slots)
        if reasons:
            for reason in reasons:
                removed_by_reason[reason] += 1
            continue
        cleaned_rows.append(sample)

    grouped = defaultdict(list)
    for sample in cleaned_rows:
        grouped[str(sample["text"])].append(sample)

    deduped_rows: List[Dict[str, Any]] = []
    for text, entries in grouped.items():
        serialized = {
            json.dumps(
                {"intent": item["intent"], "slots": item["slots"]},
                ensure_ascii=False,
                sort_keys=True,
            ): item
            for item in entries
        }
        intents = {item["intent"] for item in entries}
        if len(entries) > 1 and (len(intents) > 1 or len(serialized) > 1):
            duplicates_removed += len(entries)
            removed_by_reason["duplicate_conflict"] += len(entries)
            continue
        deduped_rows.append(entries[0])
        if len(entries) > 1:
            duplicates_removed += len(entries) - 1
            removed_by_reason["duplicate_exact"] += len(entries) - 1

    cleaned_payload = dict(payload)
    cleaned_payload["data"] = deduped_rows
    stats = {
        "before_count": len(source_rows),
        "after_count": len(deduped_rows),
        "removed_count": len(source_rows) - len(deduped_rows),
        "duplicates_removed": duplicates_removed,
        "removed_by_reason": dict(removed_by_reason),
    }
    return cleaned_payload, stats
