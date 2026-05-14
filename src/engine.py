"""
Inference engine: NLU (intent/slots) + business routing + integrity check + NLG response.

v3.1 - Uses new intent and slot names from 意图与槽位规范 v3.1.
     - Removes all regex-based intent overrides; trusts the model's predictions.
     - Keeps lightweight post-processing for slot value normalization and fuzzy matching.
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import torch
from transformers import AutoTokenizer, AutoModel

try:
    from .preprocessor import DATA_DIR
    from .runtime_intent_normalization import normalize_runtime_play_intent
    from .trainer import JointRBT3Model, TrainConfig, _load_label_config, resolve_model_dir
    from .adaptation import load_adaptation_assets
    from .session_manager import SessionState, resolve_with_session
    from .response_manager import ResponseManager
except ImportError:  # pragma: no cover - fallback for script usage
    from preprocessor import DATA_DIR
    from runtime_intent_normalization import normalize_runtime_play_intent
    from trainer import JointRBT3Model, TrainConfig, _load_label_config, resolve_model_dir
    from adaptation import load_adaptation_assets
    from session_manager import SessionState, resolve_with_session
    from response_manager import ResponseManager

try:
    from rapidfuzz import process as fuzz_process
except Exception:  # pragma: no cover - optional dependency
    fuzz_process = None


BASE_DIR = Path(__file__).resolve().parent.parent

# ── All 30 intents from v3.1 spec + none ──
ALL_INTENTS = {
    # Core intents (3.1)
    "move_schedule", "swap_schedule", "cancel_schedule", "create_schedule",
    "play_media",
    # Other intents (3.2)
    "enable_schedule", "disable_schedule",
    "shift_schedule_later", "shift_schedule_earlier", "delete_schedule", "replace_media_in_task",
    "query_terminal", "enable_terminal", "disable_terminal", "sync_terminal_time", "check_terminal",
    "create_zone", "delete_zone", "add_terminal_to_zone", "remove_terminal_from_zone",
    "add_terminal_to_task", "remove_terminal_from_task", "query_task", "play_task", "stop_task",
    "pause_task", "resume_task",
    "adjust_volume", "broadcast_emergency",
    "none",
}

# ── All slot names from v3.1 spec + play_duration ──
ALL_SLOTS = {
    "source_time", "end_time", "time_offset", "play_duration",
    "schedule_name", "new_schedule_name",
    "media_name", "new_media_name",
    "task_name", "task_type",
    "terminal_id", "terminal_name",
    "zone_name",
    "volume", "play_count",
}


def _normalize_infer_text(text: object) -> str:
    """Normalize user input for inference by removing ASCII spaces only."""
    value = "" if text is None else str(text)
    return value.strip().replace(" ", "")


@dataclass
class EngineConfig:
    model_dir: Path = TrainConfig().output_dir
    data_dir: Path = DATA_DIR
    all_media_path: Path = DATA_DIR / "all_audio"
    all_loc_path: Path = DATA_DIR / "all_loc"
    all_task_path: Path = DATA_DIR / "all_task"
    all_zone_path: Path = DATA_DIR / "all_loc"
    schedule_path: Path = DATA_DIR / "broadcast_schedules.json"
    max_length: int = 128
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    confidence_threshold: float = 0.5


def decode_entities(tokens: Sequence[str], tag_ids: Sequence[int], label_list: Sequence[str]) -> Dict[str, List[str]]:
    """Decode BIO tag sequence into entity dict: {slot_name: [value1, value2, ...]}."""
    entities: Dict[str, List[str]] = {}
    current_tokens: List[str] = []
    current_label: Optional[str] = None
    for token, tag_id in zip(tokens, tag_ids):
        label = label_list[tag_id] if 0 <= tag_id < len(label_list) else "O"
        if label == "O":
            if current_label:
                entities.setdefault(current_label, []).append("".join(current_tokens))
            current_tokens = []
            current_label = None
            continue
        prefix, slot = label.split("-", 1)
        if prefix == "B" or slot != current_label:
            if current_label:
                entities.setdefault(current_label, []).append("".join(current_tokens))
            current_tokens = [token]
            current_label = slot
        else:
            current_tokens.append(token)
    if current_label:
        entities.setdefault(current_label, []).append("".join(current_tokens))
    return entities


class JointInferenceEngine:
    def __init__(self, cfg: EngineConfig, tokenizer: AutoTokenizer, model: JointRBT3Model, label_cfg: Dict[str, object]):
        self.cfg = cfg
        self.tokenizer = tokenizer
        self.model = model
        self.label_cfg = label_cfg
        self.slot_labels: List[str] = label_cfg["slot_labels"]
        self.id2intent: Dict[int, str] = {int(k): v for k, v in label_cfg["id2intent"].items()}
        self.media_index, self.loc_index, self.task_index, self.zone_index = load_adaptation_assets(
            cfg.all_media_path, cfg.all_loc_path, cfg.all_task_path, cfg.all_zone_path
        )
        self.schedule_map: Dict[str, object] = {}
        self.schedule_names: List[str] = []
        if cfg.schedule_path.exists():
            try:
                self.schedule_map = json.loads(cfg.schedule_path.read_text(encoding="utf-8"))
                schedules = self.schedule_map.get("schedules", [])
                if isinstance(schedules, list):
                    for item in schedules:
                        if isinstance(item, dict):
                            name = str(item.get("schedule_name", "")).strip()
                            if name:
                                self.schedule_names.append(name)
            except Exception:
                self.schedule_map = {}
        self.session = SessionState()
        self.responder = ResponseManager()

    @classmethod
    def from_artifacts(cls, cfg: EngineConfig | None = None) -> "JointInferenceEngine":
        cfg = cfg or EngineConfig()
        label_cfg = _load_label_config()
        num_slot_labels = len(label_cfg["slot_labels"])
        num_intents = len(label_cfg["intent2id"])
        tokenizer = AutoTokenizer.from_pretrained(cfg.model_dir, use_fast=True)
        model = JointRBT3Model(
            resolve_model_dir(label_cfg.get("model_name")),
            num_intents=num_intents,
            num_slot_labels=num_slot_labels,
        )
        state = torch.load(cfg.model_dir / "joint_model.pt", map_location=cfg.device)
        model.load_state_dict(state["model_state_dict"])
        model.to(cfg.device)
        model.eval()
        return cls(cfg, tokenizer, model, label_cfg)

    # ── Model Inference ──

    def _select_slot_tags(self, full_tags: Sequence[int], word_ids: Sequence[int | None], token_count: int) -> List[int]:
        """Align subword-level tags back to character-level."""
        aligned: List[int] = []
        prev_word = None
        for idx, word_id in enumerate(word_ids):
            if word_id is None:
                continue
            if word_id != prev_word:
                aligned.append(int(full_tags[idx]))
                prev_word = word_id
        return aligned[:token_count]

    def _run_model(self, text: str) -> Tuple[str, float, Dict[str, List[str]], List[str], List[int]]:
        """Run the joint model and return (intent, confidence, entities, tokens, tag_ids)."""
        tokens = list(text)
        batch_encoding = self.tokenizer(
            tokens,
            is_split_into_words=True,
            max_length=self.cfg.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        word_ids = batch_encoding.word_ids()
        inputs = {k: v.to(self.cfg.device) for k, v in batch_encoding.items()}

        with torch.no_grad():
            outputs = self.model(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                token_type_ids=inputs.get("token_type_ids"),
            )

        # Intent
        intent_logits = outputs["intent_logits"][0]
        intent_probs = torch.softmax(intent_logits, dim=-1)
        intent_id = int(intent_probs.argmax(dim=-1).item())
        intent_conf = intent_probs[intent_id].item()
        intent_label = self.id2intent.get(intent_id, "none")

        # If confidence is too low, fall back to none
        if intent_conf < self.cfg.confidence_threshold:
            intent_label = "none"

        # Slots
        if outputs.get("slot_tags") is not None and outputs["slot_tags"]:
            full_tag_ids = outputs["slot_tags"][0]
        else:
            full_tag_ids = outputs["slot_logits"][0].argmax(dim=-1).tolist()

        tag_ids = self._select_slot_tags(full_tag_ids, word_ids, len(tokens))
        entities = decode_entities(tokens, tag_ids, self.slot_labels)

        return intent_label, intent_conf, entities, tokens, tag_ids

    # ── Slot Post-Processing (lightweight, no intent overrides) ──

    def _fuzzy_match_name(self, value: str, candidates: List[str], score_cutoff: float = 60.0) -> Tuple[Optional[str], float]:
        """Fuzzy match a value against a list of candidates."""
        if not fuzz_process or not candidates or not value:
            return None, 0.0
        res = fuzz_process.extractOne(value, candidates, score_cutoff=score_cutoff)
        if res:
            choice, score, _ = res
            return choice, score / 100.0
        return None, 0.0

    def _enrich_schedule_name(self, slots: Dict[str, object]) -> None:
        """Try to match schedule_name against known schedules via fuzzy matching."""
        value = slots.get("schedule_name")
        if not value or not self.schedule_names:
            return
        value_str = str(value)
        if value_str in self.schedule_names:
            slots["schedule_name_matched"] = value_str
            return
        matched, score = self._fuzzy_match_name(value_str, self.schedule_names)
        if matched:
            slots["schedule_name_matched"] = matched
            slots["schedule_name_score"] = score

    def _enrich_media_name(self, slots: Dict[str, object], key: str = "media_name") -> None:
        """Try to match media_name against known media via fuzzy matching."""
        value = slots.get(key)
        if not value or not self.media_index.names:
            return
        value_str = str(value)
        matched_name, meta, score = self.media_index.fuzzy_match(value_str, score_cutoff=60.0)
        if matched_name:
            slots[f"{key}_matched"] = matched_name
            if isinstance(meta, dict) and meta.get("mediaid"):
                slots[f"{key}_id"] = meta["mediaid"]
            slots[f"{key}_score"] = score

    def _enrich_task_name(self, slots: Dict[str, object]) -> None:
        """Try to match task_name against known tasks via fuzzy matching."""
        value = slots.get("task_name")
        if not value or not self.task_index.names:
            return
        value_str = str(value)
        matched_name, meta, score = self.task_index.fuzzy_match(value_str, score_cutoff=60.0)
        if matched_name:
            slots["task_name_matched"] = matched_name
            if isinstance(meta, dict) and meta.get("taskid"):
                slots["task_id"] = meta["taskid"]
            slots["task_name_score"] = score

    def _enrich_zone_name(self, slots: Dict[str, object]) -> None:
        """Try to match zone_name against known zones via fuzzy matching."""
        value = slots.get("zone_name")
        if not value or not self.zone_index.names:
            return
        value_str = str(value)
        matched_name, meta, score = self.zone_index.fuzzy_match(value_str, score_cutoff=60.0)
        if matched_name:
            slots["zone_name_matched"] = matched_name
            if isinstance(meta, dict):
                zone_id = meta.get("zone") or meta.get("id") or meta.get("zoneid")
                if zone_id:
                    slots["zone_id"] = zone_id
            slots["zone_name_score"] = score

    def _enrich_terminal(self, slots: Dict[str, object]) -> None:
        """Try to match terminal_name against known terminals via fuzzy matching."""
        value = slots.get("terminal_name")
        if not value or not self.loc_index.names:
            return
        value_str = str(value)
        matched_name, meta, score = self.loc_index.fuzzy_match(value_str, score_cutoff=60.0)
        if matched_name:
            slots["terminal_name_matched"] = matched_name
            if isinstance(meta, dict):
                tid = meta.get("id") or meta.get("terminalid")
                if tid:
                    slots["terminal_matched_id"] = tid
            slots["terminal_name_score"] = score

    def _parse_volume_value(self, slots: Dict[str, object]) -> None:
        """Parse volume expression into a structured cmdargs value."""
        volume_text = str(slots.get("volume", ""))
        if not volume_text:
            return

        # Try to extract numeric value
        m_num = re.search(r"\d+", volume_text)
        if m_num:
            slots["volume_value"] = int(m_num.group(0))
            return

        # Try Chinese numerals
        cn_map = {"零": 0, "〇": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
                  "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        m_cn = re.search(r"[零〇一二两三四五六七八九十百]+", volume_text)
        if m_cn:
            token = m_cn.group(0)
            if "十" in token:
                parts = token.split("十")
                tens = cn_map.get(parts[0], 1) if parts[0] else 1
                ones = cn_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
                slots["volume_value"] = tens * 10 + ones
                return
            total = 0
            for ch in token:
                if ch in cn_map:
                    total = total * 10 + cn_map[ch]
            if total > 0:
                slots["volume_value"] = total
                return

        # Relative direction
        has_slight = any(k in volume_text for k in ["一点", "些", "稍微", "点点"])
        if any(k in volume_text for k in ["大", "加", "高", "增", "升"]):
            slots["volume_direction"] = "up"
            slots["volume_delta"] = 10 if has_slight else 20
        elif any(k in volume_text for k in ["小", "低", "减", "降"]):
            slots["volume_direction"] = "down"
            slots["volume_delta"] = 10 if has_slight else 20

    def _post_process_slots(self, entities: Dict[str, List[str]], intent: str) -> Dict[str, object]:
        """Convert raw entities to clean slot dict and enrich with fuzzy matching."""
        slots: Dict[str, object] = {}

        for slot_key, values in entities.items():
            if not values:
                continue
            # For most slots, take the longest value (handles partial extractions)
            value = max(values, key=len)
            slots[slot_key] = value

        # Enrich with fuzzy matching against known assets
        self._enrich_schedule_name(slots)
        self._enrich_media_name(slots, "media_name")
        self._enrich_media_name(slots, "new_media_name")
        self._enrich_task_name(slots)
        self._enrich_zone_name(slots)
        self._enrich_terminal(slots)

        # Parse volume for adjust_volume intent
        if intent == "adjust_volume" and "volume" in slots:
            self._parse_volume_value(slots)

        return slots

    # ── Missing Slot Check ──

    def _check_missing_slots(self, intent: str, slots: Dict[str, object]) -> List[str]:
        """Check for missing required slots based on v3.1 spec."""
        missing: List[str] = []

        if intent == "move_schedule":
            if "source_time" not in slots:
                missing.append("source_time")
            if "end_time" not in slots:
                missing.append("end_time")

        elif intent == "swap_schedule":
            if "source_time" not in slots:
                missing.append("source_time")

        elif intent == "play_media":
            if "media_name" not in slots:
                missing.append("media_name")
            has_target = any(slots.get(k) for k in ("zone_name", "terminal_id", "terminal_name"))
            if not has_target:
                missing.append("zone_name/terminal_id/terminal_name")

        elif intent in ("enable_schedule", "disable_schedule"):
            has_target = any(slots.get(k) for k in ("schedule_name", "task_name"))
            if not has_target:
                missing.append("schedule_name/task_name")

        elif intent in ("shift_schedule_later", "shift_schedule_earlier"):
            if "schedule_name" not in slots:
                missing.append("schedule_name")
            if "time_offset" not in slots:
                missing.append("time_offset")

        elif intent == "delete_schedule":
            if "schedule_name" not in slots:
                missing.append("schedule_name")

        elif intent == "replace_media_in_task":
            if "schedule_name" not in slots:
                missing.append("schedule_name")
            if "media_name" not in slots:
                missing.append("media_name")
            if "new_media_name" not in slots:
                missing.append("new_media_name")

        elif intent in ("query_terminal", "enable_terminal", "disable_terminal",
                        "sync_terminal_time"):
            has_target = any(slots.get(k) for k in ("terminal_id", "terminal_name", "zone_name"))
            if not has_target:
                missing.append("terminal_id/terminal_name/zone_name")

        elif intent in ("create_zone", "delete_zone"):
            if "zone_name" not in slots:
                missing.append("zone_name")

        elif intent in ("add_terminal_to_zone", "remove_terminal_from_zone"):
            if "zone_name" not in slots:
                missing.append("zone_name")
            has_terminal = any(slots.get(k) for k in ("terminal_id", "terminal_name"))
            if not has_terminal:
                missing.append("terminal_id/terminal_name")

        elif intent in ("add_terminal_to_task", "remove_terminal_from_task"):
            has_target = any(slots.get(k) for k in ("terminal_id", "terminal_name", "task_name", "schedule_name"))
            if not has_target:
                missing.append("terminal_id/terminal_name/task_name/schedule_name")

        elif intent == "play_task":
            if "task_name" not in slots:
                missing.append("task_name")

        elif intent == "stop_task":
            if "task_name" not in slots:
                missing.append("task_name")

        elif intent == "adjust_volume":
            if "volume" not in slots:
                missing.append("volume")

        elif intent == "broadcast_emergency":
            if "task_type" not in slots:
                missing.append("task_type")
            if "zone_name" not in slots:
                missing.append("zone_name")

        elif intent == "cancel_schedule":
            if "schedule_name" not in slots:
                missing.append("schedule_name")

        # query_task, pause_task, resume_task, check_terminal
        # have no strictly required slots per spec

        return missing

    # ── Intent Command Code Mapping ──

    @staticmethod
    def _intent_cmd(intent: str) -> int:
        """Map intent to numeric command code for backend integration."""
        mapping = {
            "move_schedule": 5,
            "swap_schedule": 5,
            "cancel_schedule": 6,
            "create_schedule": 0,
            "play_media": 1,
            "enable_schedule": 8,
            "disable_schedule": 9,
            "shift_schedule_later": 5,
            "shift_schedule_earlier": 5,
            "delete_schedule": 6,
            "replace_media_in_task": 7,
            "query_terminal": 22,
            "enable_terminal": 23,
            "disable_terminal": 24,
            "sync_terminal_time": 25,
            "check_terminal": 26,
            "create_zone": 30,
            "delete_zone": 31,
            "add_terminal_to_zone": 32,
            "remove_terminal_from_zone": 33,
            "add_terminal_to_task": 34,
            "remove_terminal_from_task": 35,
            "query_task": 20,
            "play_task": 1,
            "stop_task": 2,
            "pause_task": 3,
            "resume_task": 4,
            "adjust_volume": 10,
            "broadcast_emergency": 99,
            "none": -1,
        }
        return mapping.get(intent, -1)

    # ── Time Parsing Utilities (used by api_public.py) ──

    _DATE_KEYWORDS = {
        "今天", "明天", "后天", "大后天", "昨天", "前天",
        "今日", "明日", "后日",
        "本周", "下周", "下下周", "这周", "上周",
        "本星期", "下星期", "下下星期", "这星期",
        "本礼拜", "下礼拜", "下下礼拜", "这礼拜",
        "下个周", "下个星期", "下个礼拜",
        "周一", "周二", "周三", "周四", "周五", "周六", "周日",
        "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天", "星期日",
        "礼拜一", "礼拜二", "礼拜三", "礼拜四", "礼拜五", "礼拜六", "礼拜天", "礼拜日",
    }

    _CN_NUM = {
        "零": 0, "〇": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "十一": 11, "十二": 12,
    }

    @staticmethod
    def _contains_date_word(text: str) -> bool:
        """Check if text contains any date-related keywords."""
        if not text:
            return False
        for kw in JointInferenceEngine._DATE_KEYWORDS:
            if kw in text:
                return True
        # Check for explicit date patterns like 2026-03-05, 3月5日
        if re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
            return True
        if re.search(r"\d{1,2}月\d{1,2}[日号]", text):
            return True
        return False

    @staticmethod
    def _split_time_range(text: str) -> Optional[Tuple[str, str]]:
        """Split a time range expression like '8点到9点' into ('8点', '9点')."""
        if not text:
            return None
        pattern = r"(.+?)\s*(?:到|至|~|～|-)\s*(.+)"
        m = re.match(pattern, text.strip())
        if m:
            left = m.group(1).strip()
            right = m.group(2).strip()
            if left and right:
                return left, right
        return None

    @staticmethod
    def _resolve_date_base(text: str) -> Optional[datetime]:
        """Resolve the date portion from text like '今天', '明天', '周三', '下周五'."""
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if "大后天" in text:
            return today + timedelta(days=3)
        if "后天" in text:
            return today + timedelta(days=2)
        if "明天" in text or "明日" in text:
            return today + timedelta(days=1)
        if "昨天" in text or "昨日" in text:
            return today - timedelta(days=1)
        if "前天" in text:
            return today - timedelta(days=2)
        if "今天" in text or "今日" in text:
            return today

        # Explicit date: 2026-03-05 or 2026/03/05
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        # Chinese date: 3月5日
        m = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", text)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            try:
                candidate = datetime(now.year, month, day)
                if candidate.date() < now.date():
                    candidate = datetime(now.year + 1, month, day)
                return candidate
            except ValueError:
                pass

        # Weekday resolution
        weekday_map = {
            "一": 0, "二": 1, "三": 2, "四": 3,
            "五": 4, "六": 5, "日": 6, "天": 6,
        }
        m_wk = re.search(r"(?:周|星期|礼拜)\s*([一二三四五六日天])", text)
        if m_wk:
            target_wd = weekday_map.get(m_wk.group(1))
            if target_wd is not None:
                today_wd = now.weekday()
                # Calculate this_monday
                this_monday = today - timedelta(days=today_wd)

                has_next_next = any(k in text for k in ["下下周", "下下星期", "下下礼拜"])
                has_next = any(k in text for k in ["下周", "下星期", "下礼拜", "下个周", "下个星期", "下个礼拜"])

                if has_next_next:
                    base_monday = this_monday + timedelta(days=14)
                elif has_next:
                    base_monday = this_monday + timedelta(days=7)
                else:
                    base_monday = this_monday

                return base_monday + timedelta(days=target_wd)

        return None

    @staticmethod
    def _parse_time_of_day(text: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract hour and minute from time expression."""
        # Standard format: 14:30 or 14：30
        m = re.search(r"(\d{1,2})[:：](\d{1,2})", text)
        if m:
            return int(m.group(1)), int(m.group(2))

        # Chinese format: X点Y分 / X点半 / X点
        m = re.search(r"(\d{1,2}|[零〇一二两三四五六七八九十]{1,3})点(?:(\d{1,2}|[零〇一二两三四五六七八九十]{1,3})分|半|一刻|三刻)?", text)
        if m:
            cn = JointInferenceEngine._CN_NUM
            raw_h = m.group(1)
            hour = cn.get(raw_h, None)
            if hour is None:
                try:
                    hour = int(raw_h)
                except ValueError:
                    return None, None

            minute = 0
            if m.group(0).endswith("半"):
                minute = 30
            elif m.group(0).endswith("一刻"):
                minute = 15
            elif m.group(0).endswith("三刻"):
                minute = 45
            elif m.group(2):
                raw_m = m.group(2)
                minute = cn.get(raw_m, None)
                if minute is None:
                    try:
                        minute = int(raw_m)
                    except ValueError:
                        minute = 0

            # Handle period-of-day modifiers
            if any(k in text for k in ["下午", "晚上", "夜里", "夜间", "傍晚"]):
                if hour < 12:
                    hour += 12
            elif "中午" in text:
                if hour < 12 and hour != 0:
                    hour += 12

            return hour, minute

        return None, None

    def _parse_time_point(self, text: str, base: Optional[datetime] = None) -> Optional[datetime]:
        """
        Parse a Chinese time expression into a datetime object.

        Args:
            text: The time expression, e.g. '明天下午3点', '周五8:30', '14:00'
            base: Optional base datetime for resolving relative time-of-day
        """
        if not text or not text.strip():
            return None
        text = text.strip()

        # Try to resolve the date part
        date_base = self._resolve_date_base(text)
        if date_base is None:
            date_base = base

        # Try to extract time-of-day
        hour, minute = self._parse_time_of_day(text)

        if date_base is not None and hour is not None:
            return date_base.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)

        if date_base is not None:
            # Date without specific time -> return start of day
            return date_base.replace(hour=0, minute=0, second=0, microsecond=0)

        if hour is not None:
            # Time without date -> use today or base
            now = datetime.now()
            ref = base or now.replace(hour=0, minute=0, second=0, microsecond=0)
            result = ref.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)
            # If no explicit date and result is in the past, bump to tomorrow
            if base is None and result < now:
                result += timedelta(days=1)
            return result

        # Try ISO format as last resort
        try:
            return datetime.fromisoformat(text.replace("T", " "))
        except (ValueError, TypeError):
            pass

        return None

    # ── Main Inference ──

    def infer(self, text: str) -> Dict[str, object]:
        """Run full NLU pipeline on input text."""
        cleaned = _normalize_infer_text(text)
        if not cleaned:
            return self._empty_result(cleaned)

        prev_dialog_state = self.session.last_dialog_state

        intent_label, intent_conf, entities, tokens, tag_ids = self._run_model(cleaned)
        slots = self._post_process_slots(entities, intent_label)
        intent_label, slots = normalize_runtime_play_intent(intent_label, slots)
        missing = self._check_missing_slots(intent_label, slots)

        resolution = resolve_with_session(self.session, intent_label, slots, cleaned, None)
        if resolution:
            if resolution.kind == "interrupt_confirm":
                resolution_slots = dict(resolution.slots or slots)
                same_semantic_source = (
                    bool(resolution.intent)
                    and resolution.intent == intent_label
                    and resolution_slots == slots
                )
                return {
                    "input": cleaned,
                    "intent": resolution.intent or intent_label,
                    "intent_confidence": intent_conf if same_semantic_source else 0.0,
                    "slots": resolution_slots,
                    "entities": entities if same_semantic_source else {},
                    "tokens": tokens if same_semantic_source else [],
                    "tag_ids": tag_ids if same_semantic_source else [],
                    "status": "interrupt_confirm",
                    "cmd": -1,
                    "output_speech": resolution.reply,
                    "dialog_state": resolution.dialog_state or "interrupt_confirm",
                    "dialog_state_detail": resolution.dialog_state_detail or "confirm_interrupt_switch",
                }

            if resolution.kind == "cancel":
                result = {
                    "input": cleaned,
                    "intent": "none",
                    "intent_confidence": 1.0,
                    "slots": {},
                    "entities": {},
                    "tokens": tokens,
                    "tag_ids": tag_ids,
                    "status": "success",
                    "cmd": self._intent_cmd("none"),
                    "output_speech": resolution.reply,
                    "dialog_state": resolution.dialog_state or "complete",
                    "dialog_state_detail": resolution.dialog_state_detail or "complete",
                }
                self.session.update(
                    "none",
                    {},
                    [],
                    result["dialog_state"],
                    "success",
                    [],
                    result["dialog_state_detail"],
                )
                return result

            if resolution.intent:
                intent_label = resolution.intent
            if resolution.slots is not None:
                slots = dict(resolution.slots)
            if resolution.missing_slots is not None:
                missing = list(resolution.missing_slots)
            else:
                intent_label, slots = normalize_runtime_play_intent(intent_label, slots)
                missing = self._check_missing_slots(intent_label, slots)

        intent_label, slots = normalize_runtime_play_intent(intent_label, slots)

        status = "success" if not missing else "incomplete"
        cmd_code = self._intent_cmd(intent_label)
        nlg = self.responder.generate(intent_label, status, slots, missing, prev_dialog_state)

        result = {
            "input": cleaned,
            "intent": intent_label,
            "intent_confidence": intent_conf,
            "slots": slots,
            "entities": entities,
            "tokens": tokens,
            "tag_ids": tag_ids,
            "status": status,
            "cmd": cmd_code,
        }
        if missing:
            result["missing_slots"] = missing
        if nlg:
            result.update(nlg)

        result["dialog_state"] = (
            (resolution.dialog_state if resolution and resolution.dialog_state else None)
            or result.get("dialog_state")
            or ("complete" if status == "success" else "ask")
        )
        result["dialog_state_detail"] = (
            (resolution.dialog_state_detail if resolution and resolution.dialog_state_detail else None)
            or ("ask_missing_slot" if result["dialog_state"] == "ask" else "complete")
        )

        self.session.update(
            intent_label,
            slots,
            [],
            result["dialog_state"],
            status,
            missing,
            result["dialog_state_detail"],
        )
        return result

    def _empty_result(self, text: str) -> Dict[str, object]:
        return {
            "input": text,
            "intent": "none",
            "intent_confidence": 0.0,
            "slots": {},
            "entities": {},
            "tokens": [],
            "tag_ids": [],
            "status": "success",
            "cmd": -1,
            "output_speech": "您直接说要查什么或调什么就行。",
            "dialog_state": "complete",
            "dialog_state_detail": "complete",
        }


def load_engine() -> JointInferenceEngine:
    return JointInferenceEngine.from_artifacts()

if __name__ == "__main__":
    engine = load_engine()
    while True:
        try:
            text = input("Input> ").strip()
        except EOFError:
            break
        if not text:
            break
        result = engine.infer(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
