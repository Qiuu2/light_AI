"""
Pure utility functions used across the application.
No dependencies on other service modules.
"""
from __future__ import annotations

import json
import re
import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.config import (
    REMOTE_FETCH_WORKERS, REMOTE_BROADCAST_TASK_TYPE,
    REMOTE_LIVECAST_TASK_TYPE, REMOTE_TASKINFO_DURATION_AS_SECONDS,
)


def coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def format_hhmm(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) >= 5:
        return text[:5]
    return text


def format_hhmmss(value: str) -> str:
    if not value:
        return ""
    parts = [part.zfill(2) for part in str(value).strip().split(":") if part != ""]
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}:00"
    if len(parts) >= 3:
        return f"{parts[0]}:{parts[1]}:{parts[2]}"
    return str(value)


def encode_date_value(value: str) -> int:
    text = str(value or "").strip()
    if not text or text in {"0-00-00", "0000-00-00"}:
        return 0
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return coerce_int(text.replace("-", ""), 0)
    return coerce_int(text, 0)


def encode_time_value(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    parts = [part for part in text.split(":") if part != ""]
    if len(parts) >= 2:
        hh = parts[0].zfill(2)
        mm = parts[1].zfill(2)
        ss = parts[2].zfill(2) if len(parts) >= 3 else "00"
        return coerce_int(f"{hh}{mm}{ss}", 0)
    return coerce_int(text, 0)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def touch_generated_at(payload: dict) -> dict:
    payload["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return payload


def unique_list(values: List[str]) -> List[str]:
    seen: set = set()
    ordered: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def normalize_str_list(values: object) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned = [str(value).strip() for value in values if value not in (None, "")]
    cleaned = [value for value in cleaned if value]
    cleaned = [value for value in cleaned if value.lower() != "string"]
    return unique_list(cleaned)


def join_media_names(values: object, separator: str = " / ") -> str:
    cleaned = normalize_str_list(values)
    if not cleaned:
        return ""
    return separator.join(cleaned)


def clean_media_name(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return join_media_names(value)
    text = str(value).strip()
    if not text:
        return ""
    if text.lower() == "string":
        return ""
    if "/" not in text:
        return text
    parts = [part.strip() for part in text.split("/") if part.strip()]
    parts = [part for part in parts if part.lower() != "string"]
    return " / ".join(parts)


def compact_text(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[\s\-_.·•—~]+", "", value).lower()


def best_text_match(text: str, candidates: List[str]) -> str:
    if not text:
        return ""
    text_lower = text.lower()
    compact_t = compact_text(text)
    best = ""
    for candidate in candidates:
        cand = str(candidate or "").strip()
        if len(cand) < 2:
            continue
        if cand in text or cand.lower() in text_lower:
            if len(cand) > len(best):
                best = cand
            continue
        cand_compact = compact_text(cand)
        if cand_compact and cand_compact in compact_t:
            if len(cand) > len(best):
                best = cand
    return best


def match_media_from_map(audio_name: Optional[str], media_map: dict) -> Optional[Tuple[str, str]]:
    if not audio_name or not media_map:
        return None
    target = str(audio_name).strip()
    target_lower = target.lower()
    for name, media_id in media_map.items():
        if str(name) == target:
            return str(media_id), str(name)
    best_score = 0.0
    best_match = None
    for name, media_id in media_map.items():
        candidate = str(name)
        score = difflib.SequenceMatcher(None, target, candidate).ratio()
        if score > 0.4 and score > best_score:
            best_score = score
            best_match = (str(media_id), candidate)
    if best_match is None:
        best_len_diff = 1000
        for name, media_id in media_map.items():
            candidate = str(name)
            candidate_lower = candidate.lower()
            if target_lower in candidate_lower or candidate_lower in target_lower:
                diff = abs(len(candidate) - len(target))
                if diff < best_len_diff:
                    best_len_diff = diff
                    best_match = (str(media_id), candidate)
    return best_match


def parallel_map(values: List[str], func) -> List[Optional[object]]:
    if REMOTE_FETCH_WORKERS <= 1 or len(values) <= 1:
        return [func(value) for value in values]
    results: List[Optional[object]] = [None] * len(values)
    with ThreadPoolExecutor(max_workers=REMOTE_FETCH_WORKERS) as executor:
        future_map = {executor.submit(func, value): idx for idx, value in enumerate(values)}
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = None
    return results


def redact_payload(payload: Optional[dict]) -> Optional[dict]:
    if not isinstance(payload, dict):
        return payload
    redacted = dict(payload)
    for key in ("userpwd", "password", "Authorization", "token"):
        if key in redacted:
            redacted[key] = "***"
    return redacted


def is_numeric_id(value: object) -> bool:
    return bool(value) and str(value).isdigit()


def numeric_task_id(value: object) -> int:
    if value is None:
        return 0
    text = str(value)
    digits = re.sub(r"[^0-9]", "", text)
    return coerce_int(digits, 0)


def task_id(task: dict) -> Optional[str]:
    if not isinstance(task, dict):
        return None
    for key in ("taskid", "id", "task_id", "taskId", "sechetaskid"):
        value = task.get(key)
        if value is not None:
            return str(value)
    return None


def extract_number_set(text: str) -> set:
    if not text:
        return set()
    arab_nums = re.findall(r'\d+', text)
    result = set(arab_nums)
    cn_nums = re.findall(r'[零一二三四五六七八九十]+', text)
    mapping = {
        '零': '0', '一': '1', '二': '2', '两': '2', '三': '3', '四': '4',
        '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'
    }
    for n in cn_nums:
        for char in n:
            if char in mapping:
                result.add(mapping[char])
    return result


def duration_minutes(value: object) -> int:
    try:
        number = float(value)
    except Exception:
        return 0
    if number >= 60:
        return max(1, round(number / 60))
    return max(1, round(number))


def parse_datetime(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("T", " "))
    except Exception:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def parse_time_minutes(value: str) -> Optional[int]:
    if not value:
        return None
    text = str(value)
    parts = text.split(":")
    if not parts:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return None
    return hour * 60 + minute


def weekday_label(dt: datetime) -> str:
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return labels[dt.weekday()] if dt else ""


def weekday_from_token(token: str) -> Optional[str]:
    if not token:
        return None
    day = "日" if token == "天" else token
    return f"周{day}"


def zone_label(zone: object) -> str:
    text = str(zone)
    mapping = {
        "0": "区域零", "1": "区域一", "2": "区域二", "3": "区域三", "4": "区域四",
        "5": "区域五", "6": "区域六", "7": "区域七", "8": "区域八", "9": "区域九",
    }
    if text in mapping:
        return mapping[text]
    return f"区域{text}"


def location_paths_from_terminals(terminal_ids: list, terminal_lookup: dict) -> list:
    locations = []
    for term_id in terminal_ids:
        lookup = terminal_lookup.get(str(term_id)) if terminal_lookup else None
        if not lookup:
            continue
        name = lookup.get("name")
        zone_val = lookup.get("zone")
        if name is None:
            continue
        if zone_val is not None and zone_val != "":
            locations.append([zone_label(zone_val), str(name)])
        else:
            locations.append([str(name)])
    return locations


def terminal_ids_from_taskterminal(task_terminal: object) -> List[str]:
    if not isinstance(task_terminal, list):
        return []
    ids: List[str] = []
    for terminal_item in task_terminal:
        if not isinstance(terminal_item, dict):
            continue
        terminal_id = (
            terminal_item.get("terminalid")
            or terminal_item.get("terminal_id")
            or terminal_item.get("id")
        )
        if terminal_id is not None:
            ids.append(str(terminal_id))
    return unique_list([value for value in ids if value not in (None, "")])


def terminal_names_from_taskterminal(task_terminal: object) -> List[str]:
    if not isinstance(task_terminal, list):
        return []
    names: List[str] = []
    for terminal_item in task_terminal:
        if not isinstance(terminal_item, dict):
            continue
        name = terminal_item.get("terminalname") or terminal_item.get("name")
        if name:
            names.append(str(name))
    return unique_list([value for value in names if value])


def extract_date_range(task: dict) -> tuple:
    startdate = task.get("startdate") or task.get("start_date") or ""
    enddate = task.get("enddate") or task.get("end_date") or ""
    if str(startdate) in {"0-00-00", "0000-00-00"}:
        startdate = ""
    if str(enddate) in {"0-00-00", "0000-00-00"}:
        enddate = ""
    date_range = task.get("dateRange")
    if isinstance(date_range, list) and date_range:
        if not startdate:
            startdate = date_range[0]
        if not enddate:
            enddate = date_range[1] if len(date_range) > 1 else date_range[0]
    if startdate and not enddate:
        enddate = startdate
    return str(startdate or ""), str(enddate or "")


def normalize_timelength(task: dict) -> tuple:
    timelength = task.get("timelength")
    if timelength is None:
        timelength = task.get("duration")
    timelengthtype = task.get("timelengthtype")
    duration_mode = task.get("durationMode")
    if timelengthtype is None and duration_mode:
        if str(duration_mode) == "loop":
            timelengthtype = 2
        else:
            timelengthtype = 1
    if timelength is None:
        if timelengthtype in (2, "2"):
            timelength = task.get("loop") or 1
        else:
            timelength = task.get("duration") or 1
    return str(timelength), str(timelengthtype if timelengthtype is not None else "")


def taskinfo_timelength(task: dict) -> tuple:
    timelength = task.get("timelength")
    timelengthtype = task.get("timelengthtype")
    if timelength is not None:
        return coerce_int(timelength, 1), coerce_int(timelengthtype, 1)
    duration_mode = task.get("durationMode")
    if str(duration_mode) == "loop":
        return coerce_int(task.get("loop"), 1), 2
    value = coerce_int(task.get("duration"), 1)
    if REMOTE_TASKINFO_DURATION_AS_SECONDS:
        value = max(1, value * 60)
    return value, 1


def weekdays_from_execmode(value: object) -> List[str]:
    """
    从远端的 execmode 位掩码中提取星期列表
    远端编码（7位二进制，从高位到低位）：周日 周一 周二 周三 周四 周五 周六
    即: bit6=周日(64), bit5=周一(32), bit4=周二(16), bit3=周三(8),
        bit2=周四(4), bit1=周五(2), bit0=周六(1)
    例: 周一~周五 = 32+16+8+4+2 = 62, 全周 = 127
    """
    try:
        num = int(value)
    except Exception:
        return []
    if num <= 0:
        return []
    mapping = [
        (32, "周一"),   # bit5
        (16, "周二"),   # bit4
        (8,  "周三"),   # bit3
        (4,  "周四"),   # bit2
        (2,  "周五"),   # bit1
        (1,  "周六"),   # bit0
        (64, "周日"),   # bit6
    ]
    return [label for bit, label in mapping if num & bit]


def execmode_from_weekdays(weekdays: object) -> int:
    if not isinstance(weekdays, list):
        return 0
    mapping = {
        "周一": 32, "周二": 16, "周三": 8, "周四": 4,
        "周五": 2, "周六": 1, "周日": 64, "周天": 64,
    }
    value = 0
    for day in weekdays:
        bit = mapping.get(str(day))
        if bit:
            value |= bit
    return value


def lookup_name_by_id(mapping: dict, target_id: object) -> str:
    if target_id is None:
        return ""
    target = str(target_id)
    for name, value in mapping.items():
        if str(value) == target:
            return str(name)
    return ""


# --- Status conversion helpers ---

def status_from_remote(item: dict) -> str:
    value = item.get("status") or item.get("state") or item.get("projectstate")
    value_str = str(value)
    if value_str in {"0", "启用", "执行中", "enabled", "true", "True"}:
        return "启用"
    if value_str in {"1", "停用", "禁用", "disabled", "false", "False"}:
        return "停用"
    return "启用"


def status_enabled(value: object) -> bool:
    value_str = str(value)
    if value_str in {"0", "启用", "执行中", "enabled", "true", "True"}:
        return True
    if value_str in {"1", "停用", "禁用", "disabled", "false", "False"}:
        return False
    return True


def task_status_from_remote(item: dict) -> str:
    value = item.get("taskstate")
    source = "taskstate"
    if value is None:
        value = item.get("state")
        source = "state"
    if value is None:
        value = item.get("enablestate")
        source = "enablestate"
    value_str = str(value)
    if value_str in {"1", "执行", "执行中", "running"}:
        return "执行中"
    if value_str in {"2", "暂停", "paused"}:
        return "暂停"
    if value_str in {"3", "恢复", "resume"}:
        return "执行中"
    if value_str in {"0", "停止", "停用", "disabled"}:
        return "停止" if source in {"taskstate", "state"} else "停用"
    return "待执行"


def task_state_from_label(value: object) -> int:
    text = str(value or "")
    if text in {"执行中", "执行", "启用", "running", "enabled"}:
        return 1
    if text in {"暂停", "paused"}:
        return 2
    if text in {"恢复", "resume"}:
        return 3
    if text in {"停止", "停用", "disabled", "stopped"}:
        return 0
    if text in {"待执行", "排队中", "queued"}:
        return 0
    try:
        return int(text)
    except Exception:
        return 0


def task_display_status(state: int, fallback: Optional[str] = None) -> str:
    if state in {1, 3}:
        return "执行中"
    if state == 2:
        return "暂停"
    if state == 0:
        return "停止"
    if fallback:
        return str(fallback)
    return "待执行"


def schedule_name_from_remote(item: dict, index: int) -> str:
    name = item.get("sechename") or item.get("schedule_name") or item.get("name")
    return str(name or f"方案{index + 1}")
