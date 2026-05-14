"""
Centralized configuration constants for the AI Speaker API.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HISTORY_DIR = DATA_DIR / ".history"
ALL_AUDIO_PATH = DATA_DIR / "all_audio.json"
ALL_LOC_PATH = DATA_DIR / "all_loc.json"
ALL_TASK_PATH = DATA_DIR / "all_task.json"
SCHEDULES_PATH = DATA_DIR / "broadcast_schedules.json"
OVERRIDES_PATH = DATA_DIR / "task_overrides.json"
TEMPLATES_PATH = DATA_DIR / "templates.json"
ASSISTANT_COMMAND_LOGS_PATH = DATA_DIR / "assistant_command_logs.json"
CALENDAR_HOLIDAYS_CN_PATH = DATA_DIR / "calendar_holidays_cn.json"

REMOTE_BASE_URL = os.getenv("REMOTE_BASE_URL", "").rstrip("/")
REMOTE_USERNAME = os.getenv("REMOTE_USERNAME", "admin")
REMOTE_PASSWORD = os.getenv("REMOTE_PASSWORD", "123456")
REMOTE_TIMEOUT = float(os.getenv("REMOTE_TIMEOUT", "15"))
REMOTE_POST_AS_FORM = os.getenv("REMOTE_POST_AS_FORM", "1") == "1"
REMOTE_ALLOW_CREATE_SCHEDULE = os.getenv("REMOTE_ALLOW_CREATE_SCHEDULE", "1") == "1"
REMOTE_SCHEDULE_TEMPLATE = os.getenv("REMOTE_SCHEDULE_TEMPLATE", "请添加作息")
REMOTE_TASKINFO_DURATION_AS_SECONDS = os.getenv("REMOTE_TASKINFO_DURATION_AS_SECONDS", "0") == "1"
REMOTE_TASKINFO_TWO = os.getenv("REMOTE_TASKINFO_TWO", "1") == "1"
REMOTE_TASKINFO_TWO_PATH = os.getenv("REMOTE_TASKINFO_TWO_PATH", "/task/taskinfotwo").strip() or "/task/taskinfotwo"
REMOTE_TASKINFO_TWO_BROADCAST_ID = os.getenv("REMOTE_TASKINFO_TWO_BROADCAST_ID", "2")
REMOTE_TASKINFO_TWO_LIVECAST_ID = os.getenv("REMOTE_TASKINFO_TWO_LIVECAST_ID", "3")
REMOTE_BROADCAST_TASK_TYPE = os.getenv("REMOTE_BROADCAST_TASK_TYPE", "2")
REMOTE_LIVECAST_TASK_TYPE = os.getenv("REMOTE_LIVECAST_TASK_TYPE", "3")
REMOTE_CACHE_SECONDS = float(os.getenv("REMOTE_CACHE_SECONDS", "8"))
REMOTE_FETCH_WORKERS = max(1, int(os.getenv("REMOTE_FETCH_WORKERS", "6")))
REMOTE_SCHEDULES_PATH = os.getenv("REMOTE_SCHEDULES_PATH", "/task/sechinfoall").strip() or "/task/sechinfo"
REMOTE_SCHEDULES_FALLBACK_PATH = os.getenv("REMOTE_SCHEDULES_FALLBACK_PATH", "/task/sechinfo").strip() or "/task/sechinfo"
REMOTE_LOOKUP_CACHE_SECONDS = float(os.getenv("REMOTE_LOOKUP_CACHE_SECONDS", "60"))
REMOTE_TASKINFO_FILL_MEDIA = os.getenv("REMOTE_TASKINFO_FILL_MEDIA", "1") == "1"
REMOTE_TASKINFO_FILL_TERMINAL = os.getenv("REMOTE_TASKINFO_FILL_TERMINAL", "1") == "1"
REMOTE_AUTO_SYNC_SECONDS = float(os.getenv("REMOTE_AUTO_SYNC_SECONDS", "0"))
REMOTE_TOKEN: Optional[str] = os.getenv("REMOTE_TOKEN") or None

DEBUG_REMOTE = os.getenv("DEBUG_REMOTE", "1") == "1"
LOGGER = logging.getLogger("ai_speaker_api")
if DEBUG_REMOTE and not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Intent -> required slots mapping
REQUIRED_SLOTS = {
    "SET_SCHEDULE": ["time", "content"],
    "DELETE_TASK": ["time", "content"],
    "INSTANT_PLAY": ["content"],
    "VOL_ADJUST": ["value"],
}

OTHERS_MESSAGE = "您好！我是校园广播小助手小电。我目前主要负责设置播放任务、取消广播记录以及调节音量。暂时还不会陪您聊天或处理其他事务哦。您可以试着对我说：'明天早上八点播放国歌'。"

PENDING_EXPIRE_SECONDS = 180
