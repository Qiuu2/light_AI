"""NLG templates for v3.1 intents."""
from __future__ import annotations

import random
from typing import Any

TEMPLATES = {
    "ack": [
        "好的。",
        "收到。",
        "明白。",
        "记下了。",
    ],
    "ask_more": [
        "还有别的安排，直接说。",
        "还要继续处理的话，接着说就行。",
        "如果还要查别的，直接告诉我。",
    ],
    "move_schedule_success": {
        "standard": [
            "已为您把“{schedule_name}”里 {source_time} 的任务调整到 {end_time}。",
            "“{schedule_name}”里 {source_time} 的任务已经改到 {end_time}。",
        ],
        "light": [
            "安排好了，小电已经把“{schedule_name}”里 {source_time} 的任务调整到 {end_time}。",
            "搞定啦，“{schedule_name}”里 {source_time} 的任务已经改到 {end_time}。",
        ],
    },
    "swap_schedule_success": [
        "已为您对调“{schedule_name}”里对应的两个时段。",
        "“{schedule_name}”里指定时段的任务已经对调好了。",
    ],
    "cancel_schedule_success": [
        "已为您取消“{schedule_name}”里对应的任务。",
        "“{schedule_name}”里匹配到的任务已经取消。",
    ],
    "create_schedule_success": {
        "standard": [
            "已为您创建“{schedule_name}”。",
            "新的作息方案“{schedule_name}”已经建好了。",
        ],
        "light": [
            "小电已经为您创建好了“{schedule_name}”。",
            "搞定啦，小电已经把“{schedule_name}”创建好了。",
        ],
    },
    "play_media_success": {
        "standard": [
            "“{media_name}”已经开始播放。",
            "已为您播放“{media_name}”。",
        ],
        "light": [
            "小电已经为您播放“{media_name}”了。",
            "搞定啦，小电已经帮您安排播放“{media_name}”。",
        ],
    },
    "enable_schedule_success": [
        "“{target}”已经启用。",
        "已为您启用“{target}”。",
    ],
    "disable_schedule_success": [
        "“{target}”已经停用。",
        "已为您停用“{target}”。",
    ],
    "shift_schedule_later_success": [
        "“{schedule_name}”已整体后移 {time_offset}。",
        "已将“{schedule_name}”整体顺延 {time_offset}。",
    ],
    "shift_schedule_earlier_success": [
        "“{schedule_name}”已整体提前 {time_offset}。",
        "已将“{schedule_name}”整体前移 {time_offset}。",
    ],
    "delete_schedule_success": [
        "“{schedule_name}”已经删除。",
        "已为您删除“{schedule_name}”。",
    ],
    "replace_media_in_task_success": [
        "已将“{schedule_name}”里的“{media_name}”替换成“{new_media_name}”。",
        "任务中的媒体已经更新为“{new_media_name}”。",
    ],
    "query_terminal_success": {
        "standard": [
            "终端状态已经查到。",
            "终端查询结果已经出来了。",
        ],
        "light": [
            "终端状态已经查到，小电已经为您整理好了。",
            "终端查询结果已经出来了，小电已经帮您查到了。",
        ],
    },
    "enable_terminal_success": [
        "“{target}”已经启用。",
        "已为您启用“{target}”。",
    ],
    "disable_terminal_success": [
        "“{target}”已经停用。",
        "已为您停用“{target}”。",
    ],
    "sync_terminal_time_success": [
        "“{target}”的校时指令已经发出。",
        "已向“{target}”下发校时指令。",
    ],
    "check_terminal_success": [
        "“{target}”的状态已经查完。",
        "“{target}”的自检结果已经返回。",
    ],
    "create_zone_success": [
        "分区“{zone_name}”已经创建。",
        "已为您新建分区“{zone_name}”。",
    ],
    "delete_zone_success": [
        "分区“{zone_name}”已经删除。",
        "已为您删除分区“{zone_name}”。",
    ],
    "add_terminal_to_zone_success": [
        "已将“{terminal}”加入“{zone_name}”。",
        "“{terminal}”现在属于“{zone_name}”。",
    ],
    "remove_terminal_from_zone_success": [
        "已将“{terminal}”从“{zone_name}”移出。",
        "“{terminal}”已不在“{zone_name}”里。",
    ],
    "add_terminal_to_task_success": [
        "已将“{terminal}”加入“{task_name}”。",
        "“{terminal}”现在会参与“{task_name}”。",
    ],
    "remove_terminal_from_task_success": [
        "已将“{terminal}”从“{task_name}”移出。",
        "“{terminal}”已不再参与“{task_name}”。",
    ],
    "query_task_success": {
        "standard": [
            "任务结果已经查到。",
            "任务查询结果如下。",
        ],
        "light": [
            "任务结果已经查到，小电已经帮您整理好了。",
            "任务查询结果已经出来了，小电已经为您查到了。",
        ],
    },
    "play_task_success": [
        "“{task_name}”已经启动。",
        "已为您执行“{task_name}”。",
    ],
    "stop_task_success": [
        "“{task_name}”已经停止。",
        "已为您停止“{task_name}”。",
    ],
    "pause_task_success": [
        "“{task_name}”已经暂停。",
        "已为您暂停“{task_name}”。",
    ],
    "resume_task_success": [
        "“{task_name}”已经恢复播放。",
        "已为您恢复“{task_name}”的播放。",
    ],
    "adjust_volume_success": {
        "standard": [
            "“{target}”的音量已经调整好。",
            "已为您调整“{target}”的音量。",
        ],
        "light": [
            "小电已经帮您把“{target}”的音量调好了。",
            "搞定啦，小电已经把“{target}”的音量调整好了。",
        ],
    },
    "broadcast_emergency_success": [
        "“{zone_name}”正在执行 {task_type} 应急广播。",
        "已在“{zone_name}”发起 {task_type} 应急广播。",
    ],
    "none_response": [
        "这句我没听明白，您换个说法试试。",
        "这句话还不够明确，您再具体一点。",
        "您直接说要查什么或调什么就行。",
    ],
    "ask_source_time": [
        "还差源时间。",
        "请补充原来的时间点。",
    ],
    "ask_end_time": [
        "还差目标时间。",
        "请补充要调整到什么时候。",
    ],
    "ask_schedule_name": [
        "还差作息方案名称。",
        "请补充要操作的作息方案。",
    ],
    "ask_media_name": [
        "还差媒体名称。",
        "请补充要播放的媒体。",
    ],
    "ask_new_media_name": [
        "还差新的媒体名称。",
        "请补充要替换成哪条媒体。",
    ],
    "ask_task_name": [
        "还差任务名称。",
        "请补充具体任务。",
    ],
    "ask_task_type": [
        "还差广播类型。",
        "请补充应急广播类型，比如地震或消防。",
    ],
    "ask_terminal": [
        "还差终端信息。",
        "请补充终端名称、编号或分区。",
    ],
    "ask_zone_name": [
        "还差分区名称。",
        "请补充要操作的分区。",
    ],
    "ask_volume": [
        "还差音量目标。",
        "请补充音量怎么调，比如调大一点或调到 60。",
    ],
    "ask_time_offset": [
        "还差位移量。",
        "请补充要提前或顺延多少时间。",
    ],
    "ask_target": [
        "还差目标信息。",
        "请把要操作的对象再说具体一点。",
    ],
}


def _template_variants(template_key: str, *, persona: str = "standard") -> list[str]:
    entry = TEMPLATES.get(template_key)
    if isinstance(entry, dict):
        variants = entry.get(persona) or entry.get("standard") or entry.get("light") or []
        if isinstance(variants, list):
            return variants
        return []
    if isinstance(entry, list):
        return entry
    return []


def render_speech(template_key: str, *, persona: str = "standard", **kwargs: Any) -> str:
    """Render a random template with given kwargs."""
    templates = _template_variants(template_key, persona=persona) or ["已经处理完成。"]
    template = random.choice(templates)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def compose(
    main_key: str,
    ack: bool = True,
    ask_more: bool = True,
    *,
    persona: str = "standard",
    **kwargs: Any,
) -> str:
    parts = []
    if ack:
        parts.append(random.choice(_template_variants("ack")))
    parts.append(render_speech(main_key, persona=persona, **kwargs))
    if ask_more:
        parts.append(random.choice(_template_variants("ask_more")))
    return " ".join(part.strip() for part in parts if str(part).strip())
