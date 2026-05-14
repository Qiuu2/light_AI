"""Reply helpers for assistant orchestration."""
from __future__ import annotations

from typing import List

from ._compat import api_public


def compute_missing(intent: str, slots: dict) -> List[str]:
    module = api_public()
    required = getattr(module, "REQUIRED_SLOTS", {}).get(intent, [])
    return [slot for slot in required if not slots or not slots.get(slot)]


def build_reply(intent: str, missing: List[str], slots: dict) -> str:
    module = api_public()
    if missing:
        missing_str = "、".join(missing)
        return f"我需要补充这些信息:{missing_str}。请告诉我。"
    if intent == "SET_SCHEDULE":
        return f"好的,已记录排程请求:{slots}"
    if intent == "DELETE_TASK":
        return "好的,已收到删除任务的请求。"
    if intent == "INSTANT_PLAY":
        return "好的,准备立即播放。"
    if intent == "VOL_ADJUST":
        val = slots.get("value")
        return f"好的,音量调整到 {val}。" if val else "已收到音量调整指令。"
    if intent == "OTHERS":
        return getattr(module, "OTHERS_MESSAGE", "好的,我已经理解了。")
    return "好的,我已经理解了。"


__all__ = ["build_reply", "compute_missing"]
