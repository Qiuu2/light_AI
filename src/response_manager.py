"""Response generation for v3.1 intents."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

try:
    from .speech_templates import TEMPLATES
except ImportError:  # pragma: no cover - fallback for script usage
    from speech_templates import TEMPLATES


LIGHT_PERSONA_RATE = 0.25
KEY_LIGHT_PERSONA_RATE = 1.0
KEY_INTENT_FOLLOWUP = "请问还有什么别的需求吗？"
HIGH_PERSONA_TEMPLATE_KEYS = {
    "create_schedule_success",
    "play_media_success",
    "adjust_volume_success",
    "query_task_success",
    "query_terminal_success",
}
FOLLOWUP_INTENTS = {
    "create_schedule",
    "play_media",
    "adjust_volume",
    "query_task",
    "query_terminal",
}


class ResponseManager:
    def __init__(self) -> None:
        prefixes = TEMPLATES.get("ack")
        followups = TEMPLATES.get("ask_more")
        none_responses = TEMPLATES.get("none_response")
        self.prefixes = prefixes if isinstance(prefixes, list) and prefixes else ["好的。"]
        self.followups = followups if isinstance(followups, list) and followups else []
        self.none_responses = none_responses if isinstance(none_responses, list) and none_responses else ["这句我没听明白，您换个说法试试。"]

    def _choice(self, key: str, fallback: str, *, persona: str = "standard") -> str:
        values = TEMPLATES.get(key)
        if isinstance(values, dict):
            variants = values.get(persona) or values.get("standard") or values.get("light")
            if isinstance(variants, list) and variants:
                return random.choice(variants)
            return fallback
        if isinstance(values, list) and values:
            return random.choice(values)
        return fallback

    def _render(self, key: str, fallback: str, *, persona: str = "standard", **kwargs: Any) -> str:
        template = self._choice(key, fallback, persona=persona)
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def _completion_prefix(self) -> str:
        return random.choice(["好，", "收到，", "明白，"])

    def _join_parts(self, *parts: object) -> str:
        return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())

    def _supports_light_persona(self, key: str) -> bool:
        values = TEMPLATES.get(key)
        return isinstance(values, dict) and isinstance(values.get("light"), list) and bool(values.get("light"))

    def _should_use_light_persona(self, key: str) -> bool:
        if not self._supports_light_persona(key):
            return False
        rate = KEY_LIGHT_PERSONA_RATE if key in HIGH_PERSONA_TEMPLATE_KEYS else LIGHT_PERSONA_RATE
        return random.random() < rate

    def _render_success(self, key: str, fallback: str, **kwargs: Any) -> str:
        persona = "light" if self._should_use_light_persona(key) else "standard"
        return self._render(key, fallback, persona=persona, **kwargs)

    def _should_add_completion_prefix(self, output: str) -> bool:
        return not str(output or "").startswith(("安排好了", "搞定啦", "小电已经"))

    def _ask(self, missing: List[str], intent: str, slots: Dict[str, object]) -> str:
        del intent, slots
        cancel_hint = "不继续的话，说“取消”或“算了”。"
        if not missing:
            return self._join_parts("还差一点关键信息。", cancel_hint)

        key = missing[0]
        ask_map = {
            "source_time": "ask_source_time",
            "end_time": "ask_end_time",
            "target_time": "ask_end_time",
            "schedule_name": "ask_schedule_name",
            "media_name": "ask_media_name",
            "new_media_name": "ask_new_media_name",
            "task_name": "ask_task_name",
            "task_type": "ask_task_type",
            "zone_name": "ask_zone_name",
            "volume": "ask_volume",
            "time_offset": "ask_time_offset",
            "terminal_id": "ask_terminal",
            "terminal_name": "ask_terminal",
        }

        if "/" in key:
            parts = key.split("/")
            for part in parts:
                if part in ask_map:
                    prompt = self._choice(ask_map[part], "还差一点关键信息。")
                    return self._join_parts(prompt, cancel_hint)
            if any("terminal" in part for part in parts):
                return self._join_parts(self._choice("ask_terminal", "还差终端信息。"), cancel_hint)
            if any("zone" in part for part in parts):
                return self._join_parts(self._choice("ask_zone_name", "还差分区名称。"), cancel_hint)

        prompt = self._choice(ask_map.get(key, "ask_target"), "还差一点关键信息。")
        return self._join_parts(prompt, cancel_hint)

    def _get_target_desc(self, slots: Dict[str, object]) -> str:
        for key in ("task_name", "schedule_name", "terminal_name", "zone_name", "media_name"):
            val = slots.get(key)
            if val:
                return str(val)
        return "目标"

    def _get_terminal_desc(self, slots: Dict[str, object]) -> str:
        for key in ("terminal_name", "terminal_id"):
            val = slots.get(key)
            if val:
                return str(val)
        return "终端"

    def _should_add_followup(self, intent: str) -> bool:
        return intent in FOLLOWUP_INTENTS

    def generate(
        self,
        intent: str,
        status: str,
        slots: Dict[str, object],
        missing: Optional[List[str]] = None,
        prev_dialog_state: Optional[str] = None,
    ) -> Dict[str, object]:
        missing = missing or []
        dialog_state = "complete" if status == "success" else "ask"
        output = ""
        target = self._get_target_desc(slots)

        if status == "success":
            completion_prefix = self._completion_prefix() if prev_dialog_state == "ask" else ""

            if intent == "move_schedule":
                source_time = str(slots.get("source_time", "原来的时间"))
                end_time = str(slots.get("end_time", slots.get("target_time", "新的时间")))
                schedule_name = str(slots.get("schedule_name", "作息方案"))
                output = self._render_success(
                    "move_schedule_success",
                    "已为您把“{schedule_name}”里 {source_time} 的任务调整到 {end_time}。",
                    schedule_name=schedule_name,
                    source_time=source_time,
                    end_time=end_time,
                )
            elif intent == "swap_schedule":
                source_time = str(slots.get("source_time", "指定时段"))
                schedule_name = str(slots.get("schedule_name", "作息方案"))
                output = self._render_success(
                    "swap_schedule_success",
                    "已为您对调“{schedule_name}”里 {source_time} 对应的任务。",
                    schedule_name=schedule_name,
                    source_time=source_time,
                )
            elif intent == "cancel_schedule":
                schedule_name = str(slots.get("schedule_name", "作息方案"))
                output = self._render_success(
                    "cancel_schedule_success",
                    "已为您取消“{schedule_name}”里对应的任务。",
                    schedule_name=schedule_name,
                )
            elif intent == "create_schedule":
                schedule_name = str(slots.get("schedule_name", "")).strip() or "新作息方案"
                output = self._render_success(
                    "create_schedule_success",
                    "已为您创建“{schedule_name}”。",
                    schedule_name=schedule_name,
                )
            elif intent == "play_media":
                media_name = str(slots.get("media_name", "媒体"))
                output = self._render_success(
                    "play_media_success",
                    "已为您播放“{media_name}”。",
                    media_name=media_name,
                )
            elif intent in ("enable_schedule", "disable_schedule"):
                output = self._render_success(
                    f"{intent}_success",
                    "已为您处理“{target}”的状态。",
                    target=target,
                )
            elif intent in ("shift_schedule_later", "shift_schedule_earlier"):
                schedule_name = str(slots.get("schedule_name", "作息方案"))
                time_offset = str(slots.get("time_offset", "指定时间"))
                output = self._render_success(
                    f"{intent}_success",
                    "已为您调整“{schedule_name}”的时间。",
                    schedule_name=schedule_name,
                    time_offset=time_offset,
                )
            elif intent == "delete_schedule":
                schedule_name = str(slots.get("schedule_name", "作息方案"))
                output = self._render_success(
                    "delete_schedule_success",
                    "已为您删除“{schedule_name}”。",
                    schedule_name=schedule_name,
                )
            elif intent == "replace_media_in_task":
                schedule_name = str(slots.get("schedule_name", "作息方案"))
                media_name = str(slots.get("media_name", "原媒体"))
                new_media_name = str(slots.get("new_media_name", "新媒体"))
                output = self._render_success(
                    "replace_media_in_task_success",
                    "已将“{schedule_name}”里的“{media_name}”替换成“{new_media_name}”。",
                    schedule_name=schedule_name,
                    media_name=media_name,
                    new_media_name=new_media_name,
                )
            elif intent in ("query_terminal", "enable_terminal", "disable_terminal", "sync_terminal_time", "check_terminal"):
                output = self._render_success(
                    f"{intent}_success",
                    "已为您处理“{target}”。",
                    target=target,
                )
            elif intent == "create_zone":
                zone_name = str(slots.get("zone_name", "分区"))
                output = self._render_success("create_zone_success", "已为您新建分区“{zone_name}”。", zone_name=zone_name)
            elif intent == "delete_zone":
                zone_name = str(slots.get("zone_name", "分区"))
                output = self._render_success("delete_zone_success", "已为您删除分区“{zone_name}”。", zone_name=zone_name)
            elif intent in ("add_terminal_to_zone", "remove_terminal_from_zone"):
                zone_name = str(slots.get("zone_name", "分区"))
                terminal = self._get_terminal_desc(slots)
                output = self._render_success(
                    f"{intent}_success",
                    "已为您调整终端和分区的关系。",
                    terminal=terminal,
                    zone_name=zone_name,
                )
            elif intent in ("add_terminal_to_task", "remove_terminal_from_task"):
                task_name = str(slots.get("task_name", "任务"))
                terminal = self._get_terminal_desc(slots)
                output = self._render_success(
                    f"{intent}_success",
                    "已为您调整终端和任务的关系。",
                    terminal=terminal,
                    task_name=task_name,
                )
            elif intent == "query_task":
                output = self._render_success("query_task_success", "任务结果已经查到。")
            elif intent == "play_task":
                task_name = str(slots.get("task_name", "任务"))
                output = self._render_success("play_task_success", "已为您执行“{task_name}”。", task_name=task_name)
            elif intent == "stop_task":
                task_name = str(slots.get("task_name", "任务"))
                output = self._render_success("stop_task_success", "已为您停止“{task_name}”。", task_name=task_name)
            elif intent == "pause_task":
                task_name = str(slots.get("task_name", "播放"))
                output = self._render_success("pause_task_success", "已为您暂停“{task_name}”。", task_name=task_name)
            elif intent == "resume_task":
                task_name = str(slots.get("task_name", "播放"))
                output = self._render_success("resume_task_success", "已为您恢复“{task_name}”的播放。", task_name=task_name)
            elif intent == "adjust_volume":
                output = self._render_success("adjust_volume_success", "已为您调整“{target}”的音量。", target=target)
            elif intent == "broadcast_emergency":
                task_type = str(slots.get("task_type", "应急"))
                zone_name = str(slots.get("zone_name", "全部区域"))
                output = self._render_success(
                    "broadcast_emergency_success",
                    "已在“{zone_name}”发起 {task_type} 应急广播。",
                    zone_name=zone_name,
                    task_type=task_type,
                )
            elif intent == "none":
                output = random.choice(self.none_responses)
                dialog_state = "complete"
            else:
                output = "已经处理完成。"

            if completion_prefix and intent != "none" and self._should_add_completion_prefix(output):
                output = f"{completion_prefix}{output}"
            if self._should_add_followup(intent):
                output = self._join_parts(output, KEY_INTENT_FOLLOWUP)

        elif status == "incomplete":
            output = self._ask(missing, intent, slots)

        return {"output_speech": output, "dialog_state": dialog_state}
