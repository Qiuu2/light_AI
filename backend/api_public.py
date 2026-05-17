"""
FastAPI wrapper for engine inference. 
"""
from __future__ import annotations
import copy
from contextvars import ContextVar
import ipaddress
import json
import logging
import os
import re
import socket
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Collection, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
import difflib
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
try:
    import psutil
except Exception:  # pragma: no cover - optional during local import, bundled in production
    psutil = None

from backend.assistant.chat import (
    chat_api as _assistant_chat_api,
    infer_api as _assistant_infer_api,
)
from backend.assistant.dispatch import (
    apply_action as _assistant_apply_action,
    apply_phase1_intent as _assistant_apply_phase1_intent,
)
from backend.assistant.reply import (
    build_reply as _assistant_build_reply,
    compute_missing as _assistant_compute_missing,
)
from backend.assistant.runtime_reply import (
    DEFAULT_FOLLOWUP as _DEFAULT_RUNTIME_FOLLOWUP,
    append_followup as _append_runtime_followup,
    append_reply_details as _append_runtime_reply_details,
    ask_runtime as _ask_runtime_reply,
    confirm_runtime as _confirm_runtime_reply,
    failure_detail_payload as _failure_runtime_detail_payload,
    failure_runtime as _failure_runtime_reply,
    preview_names as _preview_runtime_names,
    query_runtime as _query_runtime_reply,
    success_runtime as _success_runtime_reply,
    stable_reply as _stable_runtime_reply,
    unique_texts as _unique_runtime_texts,
)
from backend.models import (
    AuthLoginRequest,
    ChatResponse,
    DebugApplyActionRequest,
    DebugApplyActionResponse,
    InferRequest,
    InferResponse,
    RuntimePlayStopRequest,
    ScheduleStateRequest,
    TaskStateRequest,
    TestPhase1IntentRequest,
    TestPhase1IntentResponse,
)
from backend.services.file_permissions import apply_shared_json_permissions
from backend.services import remote_runtime as _remote_runtime
from backend.routes import light as _light_action

from src.adaptation import load_adaptation_assets
from src.engine import load_engine
from fastapi.middleware.cors import CORSMiddleware


DEFAULT_DEV_CORS_ORIGINS = (
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:5018",
    "http://localhost:5018",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)


def _cors_dev_mode_enabled() -> bool:
    env_name = str(os.getenv("AI_SPEAKER_ENV", "") or "").strip().lower()
    if env_name in {"dev", "development", "local", "test"}:
        return True
    return str(os.getenv("AI_SPEAKER_DEV_CORS", "0") or "0").strip() == "1"


def _cors_allow_origins() -> List[str]:
    raw_value = str(os.getenv("CORS_ALLOW_ORIGINS", "") or "").strip()
    if raw_value:
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    if _cors_dev_mode_enabled():
        return list(DEFAULT_DEV_CORS_ORIGINS)
    return []


def cors_middleware_options() -> Dict[str, object]:
    origins = _cors_allow_origins()
    return {
        "allow_origins": origins,
        "allow_credentials": bool(origins),
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


def configure_cors(application: FastAPI) -> Dict[str, object]:
    options = cors_middleware_options()
    application.add_middleware(CORSMiddleware, **options)
    return options


app = FastAPI(title="AI Speaker NLU API", version="1.0.0")
ENGINE = load_engine()
# 在 app = FastAPI() 之后加入

def _extract_number_set(text: str) -> set:
    """
    提取文本中包含的所有数字含义 (无论是1还是一),用于防止张冠李戴。
    例如:"测试任务一" -> {'1'}
    """
    if not text: return set()
    import re
    # 1. 提取阿拉伯数字
    arab_nums = re.findall(r'\d+', text)
    result = set(arab_nums)

    # 2. 提取中文数字并转义
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

configure_cors(app)
app.include_router(_light_action.create_router())
# intent→必填槽位配置
REQUIRED_SLOTS = {
    "SET_SCHEDULE": ["time", "content"],
    "DELETE_TASK": ["time", "content"],
    "INSTANT_PLAY": ["content"],
    "VOL_ADJUST": ["value"],
}

OTHERS_MESSAGE = "您好！我是校园广播小助手小电。我目前主要负责设置播放任务、取消广播记录以及调节音量。暂时还不会陪您聊天或处理其他事务哦。您可以试着对我说:‘明天早上八点播放国歌’。"

BASE_DIR = Path(__file__).resolve().parent


def _path_from_env(name: str, default: Path) -> Path:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        return default
    return Path(value).expanduser()


DATA_DIR = _path_from_env("AI_SPEAKER_DATA_DIR", BASE_DIR / "data")
DEFAULT_DATA_DIR = BASE_DIR / "default_data"
LEGACY_ROOT_DATA_DIR = BASE_DIR.parent / "data"
HISTORY_DIR = DATA_DIR / ".history"
ALL_AUDIO_PATH = DATA_DIR / "all_audio.json"
ALL_LOC_PATH = DATA_DIR / "all_loc.json"
ALL_TASK_PATH = DATA_DIR / "all_task.json"
SCHEDULES_PATH = DATA_DIR / "broadcast_schedules.json"
OVERRIDES_PATH = DATA_DIR / "task_overrides.json"
ASSISTANT_COMMAND_LOGS_PATH = DATA_DIR / "assistant_command_logs.json"
ASSISTANT_SETTINGS_PATH = DATA_DIR / "assistant_settings.json"
CALENDAR_HOLIDAYS_CN_PATH = DATA_DIR / "calendar_holidays_cn.json"
REMOTE_SETTINGS_PATH = DATA_DIR / "remote_settings.json"
REMOTE_SYNC_META_PATH = DATA_DIR / "remote_sync_meta.json"
ASSISTANT_COMMAND_LOG_LIMIT = 1000
ALLOWED_SCHEDULE_KINDS = ("小学", "中学", "高中", "大学")
ALLOWED_SCHEDULE_SEASONS = ("夏季", "冬季")
DEFAULT_REMOTE_API_PORT = 99
DEFAULT_REMOTE_API_PATH = ""


def _load_remote_auto_sync_seconds() -> float:
    raw_value = str(os.getenv("REMOTE_AUTO_SYNC_SECONDS", "180") or "180").strip()
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return 180.0

REMOTE_BASE_URL = os.getenv("REMOTE_BASE_URL", "").rstrip("/")
REMOTE_USERNAME = os.getenv("REMOTE_USERNAME", "admin")  # 填写你的登录用户名
REMOTE_PASSWORD = os.getenv("REMOTE_PASSWORD", "123456") # 填写你的登录密码
REMOTE_TIMEOUT = float(os.getenv("REMOTE_TIMEOUT", "15"))
REMOTE_ALLOW_CREATE_SCHEDULE = os.getenv("REMOTE_ALLOW_CREATE_SCHEDULE", "1") == "1"
REMOTE_SCHEDULE_TEMPLATE = os.getenv("REMOTE_SCHEDULE_TEMPLATE", "请添加作息")
REMOTE_TASKINFO_DURATION_AS_SECONDS = os.getenv("REMOTE_TASKINFO_DURATION_AS_SECONDS", "0") == "1"
REMOTE_TASKINFO_TWO = os.getenv("REMOTE_TASKINFO_TWO", "1") == "1"
REMOTE_TASKINFO_TWO_PATH = os.getenv("REMOTE_TASKINFO_TWO_PATH", "/task/taskinfotwo").strip() or "/task/taskinfotwo"
REMOTE_TASKINFO_TWO_BROADCAST_ID = os.getenv("REMOTE_TASKINFO_TWO_BROADCAST_ID", "2")
REMOTE_TASKINFO_TWO_LIVECAST_ID= os.getenv("REMOTE_TASKINFO_TWO_LIVECAST_ID", "3")
REMOTE_BROADCAST_TASK_TYPE = os.getenv("REMOTE_BROADCAST_TASK_TYPE", "2")
REMOTE_LIVECAST_TASK_TYPE = os.getenv("REMOTE_LIVECAST_TASK_TYPE", "3")
REMOTE_POST_AS_FORM = os.getenv("REMOTE_POST_AS_FORM", "1") == "1"
REMOTE_CACHE_SECONDS = float(os.getenv("REMOTE_CACHE_SECONDS", "8"))
REMOTE_FETCH_WORKERS = max(1, int(os.getenv("REMOTE_FETCH_WORKERS", "6")))
REMOTE_SCHEDULES_PATH = os.getenv("REMOTE_SCHEDULES_PATH", "/task/sechinfoall").strip() or "/task/sechinfo"
REMOTE_SCHEDULES_FALLBACK_PATH = os.getenv("REMOTE_SCHEDULES_FALLBACK_PATH", "/task/sechinfo").strip() or "/task/sechinfo"
REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY = os.getenv("REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY", "1") == "1"
REMOTE_LOOKUP_CACHE_SECONDS = float(os.getenv("REMOTE_LOOKUP_CACHE_SECONDS", "60"))
INSTANT_PLAY_MEDIA_FOLDER_ID = 3
# Runtime-play listing is deployment-specific. When no list endpoint is configured,
# /data/runtime_play_tasks falls back to the in-process recent cache and task-state
# lookups only; after a process restart, tasks created elsewhere cannot be enumerated.
REMOTE_TEMP_TASK_PATHS = [
    item.strip()
    for item in os.getenv(
        "REMOTE_TEMP_TASK_PATHS",
        "",
    ).split(",")
    if item.strip()
]
RUNTIME_PLAY_CACHE_SECONDS = max(30.0, float(os.getenv("RUNTIME_PLAY_CACHE_SECONDS", "600")))
RUNTIME_PLAY_RECENT_LIMIT = max(1, int(os.getenv("RUNTIME_PLAY_RECENT_LIMIT", "20")))
REMOTE_ZONE_VERIFY_ATTEMPTS = max(1, int(os.getenv("REMOTE_ZONE_VERIFY_ATTEMPTS", "4")))
REMOTE_ZONE_VERIFY_DELAY_SECONDS = max(0.0, float(os.getenv("REMOTE_ZONE_VERIFY_DELAY_SECONDS", "0.2")))
REMOTE_TASKINFO_FILL_MEDIA = os.getenv("REMOTE_TASKINFO_FILL_MEDIA", "1") == "1"
REMOTE_TASKINFO_FILL_TERMINAL = os.getenv("REMOTE_TASKINFO_FILL_TERMINAL", "1") == "1"
REMOTE_TASKINFO_CREATE_LOOKUP_RETRIES = max(1, int(os.getenv("REMOTE_TASKINFO_CREATE_LOOKUP_RETRIES", "3")))
REMOTE_TASKINFO_CREATE_LOOKUP_DELAY_SECONDS = max(0.0, float(os.getenv("REMOTE_TASKINFO_CREATE_LOOKUP_DELAY_SECONDS", "0.2")))
REMOTE_AUTO_SYNC_SECONDS = _load_remote_auto_sync_seconds()
REMOTE_ENABLETASK_BATCH_SIZE = max(1, int(os.getenv("REMOTE_ENABLETASK_BATCH_SIZE", "90")))
REMOTE_TASKTERMINAL_BATCH_SIZE = max(1, int(os.getenv("REMOTE_TASKTERMINAL_BATCH_SIZE", "8")))
REMOTE_TOKEN: Optional[str] = os.getenv("REMOTE_TOKEN") or None
REMOTE_LOGIN_LOCK = threading.Lock()
LOCAL_AUTH_SESSIONS: Dict[str, Dict[str, Any]] = {}
LOCAL_AUTH_LOCK = threading.Lock()
LOCAL_AUTH_COOKIE_NAME = "vue_admin_template_token"
CURRENT_REMOTE_TOKEN: ContextVar[Optional[str]] = ContextVar("current_remote_token", default=None)
CURRENT_REMOTE_BASE_URL = _remote_runtime.CURRENT_REMOTE_BASE_URL
CURRENT_PENDING_SCOPE: ContextVar[Optional[str]] = ContextVar("current_pending_scope", default=None)
STARTUP_LOAD_LOCK = threading.Lock()
STARTUP_LOAD_DONE = False
AUTO_SYNC_THREAD_LOCK = threading.Lock()
AUTO_SYNC_THREAD_STARTED = False
AUTO_SYNC_THREAD: Optional[threading.Thread] = None
AUTO_SYNC_STOP_EVENT = threading.Event()
ONCE_CLEANUP_LOCK = threading.Lock()
SERVICE_STARTED_AT = time.time()
SERVICE_STARTED_AT_TEXT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
REMOTE_SYNC_STATUS_LOCK = threading.Lock()
REMOTE_SYNC_STATUS: Dict[str, object] = {
    "thread_started": False,
    "stop_requested": False,
    "last_attempt_at": "",
    "last_success_at": "",
    "last_error": "",
    "consecutive_failures": 0,
    "last_duration_ms": None,
}
AUTH_PUBLIC_PATHS = frozenset((
    "/",
    "/index.html",
    "/favicon.ico",
    "/openapi.json",
    "/docs",
    "/docs/",
    "/redoc",
    "/redoc/",
    "/healthz",
    "/readyz",
    "/ops/status",
))
AUTH_PUBLIC_PREFIXES = ("/static/", "/auth/", "/docs/", "/redoc/")

# 👇👇👇 必须加上这一行,否则代码会报错说找不到 templates.json 👇👇👇

TEMPLATES_PATH = DATA_DIR / "templates.json"
PHASE1_TEMPLATE_MANIFEST_PATH = DEFAULT_DATA_DIR / "schedule_template_manifest.json"
PHASE1_TEMPLATE_CATALOG_PATH = DEFAULT_DATA_DIR / "schedule_template_catalog.json"
PHASE1_TEMPLATE_RESOURCE_DIR = DEFAULT_DATA_DIR / "schedule_templates"
LEGACY_PHASE1_TEMPLATE_MANIFEST_PATH = LEGACY_ROOT_DATA_DIR / "schedule_template"
LEGACY_PHASE1_TEMPLATE_CATALOG_PATH = LEGACY_ROOT_DATA_DIR / "broadcast_schedules.json"
PHASE1_TEMPLATE_DEFAULT_NAME = "夏季作息"
PHASE1_INTENTS = {
    "move_schedule",
    "swap_schedule",
    "cancel_schedule",
    "create_schedule",
    "broadcast_emergency",
    "play_task",
    "stop_task",
    "task_pause",
    "task_resume",
    "pause_task",
    "resume_task",
    "play_media",
    "enable_schedule",
    "disable_schedule",
    "shift_schedule_later",
    "shift_schedule_earlier",
    "delete_schedule",
    "replace_media_in_task",
    "query_terminal",
    "enable_terminal",
    "disable_terminal",
    "sync_terminal_time",
    "check_terminal",
    "create_zone",
    "delete_zone",
    "add_terminal_to_zone",
    "remove_terminal_from_zone",
    "add_terminal_to_task",
    "remove_terminal_from_task",
    "query_task",
    "adjust_volume",
    "stop_media",
}
DEBUG_REMOTE = os.getenv("DEBUG_REMOTE", "1") == "1"
LOGGER = logging.getLogger("ai_speaker_api")

_HIGH_PERSONA_FOLLOWUP_INTENTS = {
    "create_schedule",
    "play_media",
    "adjust_volume",
    "query_task",
    "query_terminal",
}


def _normalize_high_persona_intent(intent: str) -> str:
    intent_name = str(intent or "").strip()
    if intent_name.startswith("adjust_volume"):
        return "adjust_volume"
    return intent_name


def _append_key_intent_followup(intent: str, reply: str) -> str:
    if _normalize_high_persona_intent(intent) not in _HIGH_PERSONA_FOLLOWUP_INTENTS:
        return reply
    return _append_runtime_followup(reply, _DEFAULT_RUNTIME_FOLLOWUP)


def _strip_key_intent_followup(reply: str) -> str:
    text = str(reply or "").strip()
    followup = _DEFAULT_RUNTIME_FOLLOWUP.strip()
    if not text or not followup:
        return text
    spaced_followup = f" {followup}"
    if text.endswith(spaced_followup):
        return text[: -len(spaced_followup)].rstrip()
    if text.endswith(followup):
        return text[: -len(followup)].rstrip()
    return text


def _append_inline_reply_detail(reply: str, detail: str) -> str:
    main = str(reply or "").strip()
    extra = str(detail or "").strip().strip("。")
    if not main or not extra:
        return main or extra
    return f"{main.rstrip('。！？；，、,.!?;:')}，{extra}。"


def _finalize_key_intent_reply(intent: str, reply: str, *detail_lines: object) -> str:
    merged = _strip_key_intent_followup(reply)
    for detail in detail_lines:
        text = str(detail or "").strip()
        if text:
            merged = _append_inline_reply_detail(merged, text)
    return _append_key_intent_followup(intent, merged)
if DEBUG_REMOTE and not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LAST_IGNORED_UNNAMED_SCHEDULE_LOG = ""
_RUNTIME_PLAY_LISTING_MODE_LOGGED = False
_PHASE1_LEGACY_TEMPLATE_WARNING_EMITTED = False

PENDING_ACTION: Optional[Dict[str, Any]] = None
PENDING_ACTIONS_BY_SCOPE: Dict[str, Dict[str, Any]] = {}
PENDING_ACTIONS_LOCK = threading.Lock()
PENDING_EXPIRE_SECONDS = 180
REMOTE_CACHE: Dict[str, Tuple[float, object]] = {}
TTL_CACHE: Dict[str, Tuple[float, float, object]] = {}
DATA_STORE_LOCK = threading.Lock()
DATA_STORE: Dict[str, Dict[str, object]] = {
    "all_audio": {"path": ALL_AUDIO_PATH, "payload": None, "loaded": False},
    "all_loc": {"path": ALL_LOC_PATH, "payload": None, "loaded": False},
    "all_task": {"path": ALL_TASK_PATH, "payload": None, "loaded": False},
    "broadcast_schedules": {"path": SCHEDULES_PATH, "payload": None, "loaded": False},
    "task_overrides": {"path": OVERRIDES_PATH, "payload": None, "loaded": False},
    "assistant_command_logs": {"path": ASSISTANT_COMMAND_LOGS_PATH, "payload": None, "loaded": False},
    "assistant_settings": {"path": ASSISTANT_SETTINGS_PATH, "payload": None, "loaded": False},
    "calendar_holidays_cn": {"path": CALENDAR_HOLIDAYS_CN_PATH, "payload": None, "loaded": False},
    "remote_settings": {"path": REMOTE_SETTINGS_PATH, "payload": None, "loaded": False},
    "remote_sync_meta": {"path": REMOTE_SYNC_META_PATH, "payload": None, "loaded": False},
}
READY_REQUIRED_DATA_KEYS = tuple(DATA_STORE.keys())


def _read_json(path: Path) -> object:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing file: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read {path.name}") from exc


def _read_json_optional(path: Path) -> Optional[object]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _backup_file(path: Path, keep: int = 20) -> None:
    if not path.exists():
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = HISTORY_DIR / f"{path.stem}-{stamp}.json"
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    apply_shared_json_permissions(backup)
    backups = sorted(HISTORY_DIR.glob(f"{path.stem}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup_file(path)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))
        apply_shared_json_permissions(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _write_cache_json(path: Path, payload: object) -> None:
    try:
        _write_json(path, payload)
    except PermissionError:
        return


def _sync_now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _thread_is_alive(thread: object) -> bool:
    is_alive = getattr(thread, "is_alive", None)
    if not callable(is_alive):
        return False
    try:
        return bool(is_alive())
    except Exception:
        return False


def _reset_remote_sync_status() -> None:
    with REMOTE_SYNC_STATUS_LOCK:
        REMOTE_SYNC_STATUS["last_attempt_at"] = ""
        REMOTE_SYNC_STATUS["last_success_at"] = ""
        REMOTE_SYNC_STATUS["last_error"] = ""
        REMOTE_SYNC_STATUS["consecutive_failures"] = 0
        REMOTE_SYNC_STATUS["last_duration_ms"] = None


def _update_remote_sync_status(**changes: object) -> None:
    with REMOTE_SYNC_STATUS_LOCK:
        REMOTE_SYNC_STATUS.update(changes)


def _record_remote_sync_success(*, attempt_at: str, duration_ms: float) -> None:
    with REMOTE_SYNC_STATUS_LOCK:
        REMOTE_SYNC_STATUS["last_attempt_at"] = attempt_at
        REMOTE_SYNC_STATUS["last_success_at"] = attempt_at
        REMOTE_SYNC_STATUS["last_error"] = ""
        REMOTE_SYNC_STATUS["consecutive_failures"] = 0
        REMOTE_SYNC_STATUS["last_duration_ms"] = duration_ms


def _record_remote_sync_failure(*, attempt_at: str, duration_ms: float, detail: str) -> None:
    with REMOTE_SYNC_STATUS_LOCK:
        failures = int(REMOTE_SYNC_STATUS.get("consecutive_failures") or 0) + 1
        REMOTE_SYNC_STATUS["last_attempt_at"] = attempt_at
        REMOTE_SYNC_STATUS["last_error"] = str(detail or "")
        REMOTE_SYNC_STATUS["consecutive_failures"] = failures
        REMOTE_SYNC_STATUS["last_duration_ms"] = duration_ms


def _remote_sync_status_snapshot() -> dict:
    with REMOTE_SYNC_STATUS_LOCK:
        snapshot = dict(REMOTE_SYNC_STATUS)
    snapshot["thread_started"] = bool(AUTO_SYNC_THREAD_STARTED)
    snapshot["thread_alive"] = _thread_is_alive(AUTO_SYNC_THREAD)
    snapshot["stop_requested"] = bool(AUTO_SYNC_STOP_EVENT.is_set())
    snapshot["interval_seconds"] = float(REMOTE_AUTO_SYNC_SECONDS)
    return snapshot


def _loaded_data_keys() -> List[str]:
    with DATA_STORE_LOCK:
        return sorted(key for key, entry in DATA_STORE.items() if entry.get("loaded"))


def _missing_ready_data_keys() -> List[str]:
    with DATA_STORE_LOCK:
        return sorted(key for key in READY_REQUIRED_DATA_KEYS if not DATA_STORE.get(key, {}).get("loaded"))


def _pending_action_count() -> int:
    with PENDING_ACTIONS_LOCK:
        return len(PENDING_ACTIONS_BY_SCOPE) + (1 if PENDING_ACTION else 0)


def _runtime_data_dir_write_check() -> Tuple[bool, str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = -1
    temp_name = ""
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=".readyz-",
            suffix=".tmp",
            dir=str(DATA_DIR),
        )
        return True, ""
    except Exception as exc:
        return False, str(exc)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def _store_get(key: str) -> Optional[object]:
    entry = DATA_STORE.get(key)
    if not entry:
        return None
    with DATA_STORE_LOCK:
        if not entry.get("loaded"):
            return None
        return entry.get("payload")


def _store_set(key: str, payload: object) -> None:
    entry = DATA_STORE.get(key)
    if not entry:
        return
    with DATA_STORE_LOCK:
        entry["payload"] = payload
        entry["loaded"] = True
        entry["updated_at"] = time.time()


def _store_require(key: str, label: str, status_code: int) -> object:
    payload = _store_get(key)
    if payload is None:
        raise HTTPException(status_code=status_code, detail=f"{label} is not available yet.")
    return payload


def _store_load_from_file(
    key: str,
    normalize: Optional[Callable[[object], object]] = None,
    default: Optional[object | Callable[[], object]] = None,
    *,
    persist_default: bool = False,
) -> bool:
    entry = DATA_STORE.get(key)
    if not entry:
        return False
    path = entry.get("path")
    if not isinstance(path, Path):
        return False
    payload = _read_json_optional(path)
    missing = payload is None
    if payload is None:
        if default is None:
            return False
        payload = default() if callable(default) else _clone_payload(default)
    if normalize:
        try:
            payload = normalize(payload)
        except Exception:
            return False
    if missing and persist_default:
        _write_json(path, payload)
    _store_set(key, payload)
    return True


def _clone_payload(payload: object) -> object:
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return payload


class _RemoteBatchDispatchError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        dispatched_payloads: List[dict],
        failed_payload: dict,
        enstate: int,
        start_dt: datetime,
        phase: str = "",
    ) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = str(detail)
        self.dispatched_payloads = _clone_payload(dispatched_payloads) or []
        self.failed_payload = _clone_payload(failed_payload) or {}
        self.enstate = int(enstate)
        self.start_dt = start_dt
        self.phase = str(phase or "")


class _CreateScheduleTemplateMediaError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        user_reason: str,
        suggestion: str,
        failure_code: str,
        retryable: bool = True,
        missing_media_names: Optional[List[str]] = None,
        ambiguous_media_names: Optional[List[str]] = None,
        invalid_media_tasks: Optional[List[str]] = None,
        template_media_rebound: Optional[List[dict]] = None,
        template_media_source: str = "",
        template_media_remote_expected: Optional[bool] = None,
        template_media_remote_fetch_ok: Optional[bool] = None,
        template_media_fallback_used: Optional[bool] = None,
    ) -> None:
        super().__init__(detail)
        self.detail = str(detail or "")
        self.user_reason = str(user_reason or "")
        self.suggestion = str(suggestion or "")
        self.failure_code = str(failure_code or "")
        self.retryable = bool(retryable)
        self.missing_media_names = list(missing_media_names or [])
        self.ambiguous_media_names = list(ambiguous_media_names or [])
        self.invalid_media_tasks = list(invalid_media_tasks or [])
        self.template_media_rebound = list(template_media_rebound or [])
        self.template_media_source = str(template_media_source or "")
        self.template_media_remote_expected = template_media_remote_expected
        self.template_media_remote_fetch_ok = template_media_remote_fetch_ok
        self.template_media_fallback_used = template_media_fallback_used


def _new_diagnostic_id() -> str:
    return f"diag-{uuid.uuid4().hex[:12]}"


def _parse_remote_body_text(raw: object) -> object:
    if isinstance(raw, (dict, list)):
        return _clone_payload(raw)
    text = str(raw or "")
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return text
    return text


def _new_remote_phase_diagnostic(
    diagnostics: Optional[List[dict]],
    *,
    diagnostic_id: str,
    action: str,
    phase: str,
    path: str,
    request_payload: Optional[dict],
) -> Optional[dict]:
    if diagnostics is None:
        return None
    entry = {
        "diagnostic_id": str(diagnostic_id or ""),
        "action": str(action or ""),
        "phase": str(phase or ""),
        "path": str(path or ""),
        "request_payload": None if request_payload is None else _redact_payload(_clone_payload(request_payload) or {}),
        "status_code": None,
        "elapsed_ms": None,
        "ok": False,
        "response_body": None,
        "error_detail": "",
        "timeout": False,
    }
    diagnostics.append(entry)
    return entry


def _remote_phase_log_fields(diagnostic: dict, *, include_request: bool = False, include_response: bool = False) -> dict:
    fields = {
        "diagnostic_id": diagnostic.get("diagnostic_id"),
        "action": diagnostic.get("action"),
        "phase": diagnostic.get("phase"),
        "path": diagnostic.get("path"),
        "status_code": diagnostic.get("status_code"),
        "elapsed_ms": diagnostic.get("elapsed_ms"),
        "ok": diagnostic.get("ok"),
        "timeout": diagnostic.get("timeout"),
        "error_detail": diagnostic.get("error_detail"),
    }
    if include_request:
        fields["request_payload"] = _clone_payload(diagnostic.get("request_payload"))
    if include_response:
        fields["response_body"] = _clone_payload(diagnostic.get("response_body"))
    return fields


def _log_remote_phase_request(diagnostic: Optional[dict]) -> None:
    if not diagnostic or not DEBUG_REMOTE:
        return
    LOGGER.info("remote phase request %s", _remote_phase_log_fields(diagnostic, include_request=True))


def _log_remote_phase_result(diagnostic: Optional[dict]) -> None:
    if not diagnostic:
        return
    if diagnostic.get("ok"):
        if DEBUG_REMOTE:
            LOGGER.info("remote phase response %s", _remote_phase_log_fields(diagnostic, include_response=True))
        return
    LOGGER.warning("remote phase failure %s", _remote_phase_log_fields(diagnostic, include_request=True, include_response=True))


def _public_remote_diagnostics(diagnostics: List[dict]) -> List[dict]:
    public_items: List[dict] = []
    for item in diagnostics or []:
        if not isinstance(item, dict):
            continue
        normalized = {
            "diagnostic_id": str(item.get("diagnostic_id") or ""),
            "action": str(item.get("action") or ""),
            "phase": str(item.get("phase") or ""),
            "path": str(item.get("path") or ""),
            "request_payload": _clone_payload(item.get("request_payload")),
            "status_code": item.get("status_code"),
            "elapsed_ms": item.get("elapsed_ms"),
            "ok": bool(item.get("ok")),
            "response_body": _clone_payload(item.get("response_body")),
            "error_detail": str(item.get("error_detail") or ""),
            "timeout": bool(item.get("timeout")),
        }
        if normalized["ok"]:
            normalized["request_payload"] = None
            normalized["response_body"] = None
            normalized["error_detail"] = ""
        public_items.append(normalized)
    return public_items


def _looks_like_timeout_error(error: object) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    text = str(error or "").lower()
    return "timed out" in text or "timeout" in text


def _remote_timeout_detail(method: str, path: str) -> str:
    return f"Remote request timed out after {REMOTE_TIMEOUT}s: {method} {path}"


def _legacy_remote_path_unsupported(path: object) -> bool:
    text = str(path or "").strip()
    return text == "/authorizations" or text.startswith(("/task/", "/terminal/", "/server/"))


def _raise_legacy_remote_protocol_error(path: object) -> None:
    raise HTTPException(
        status_code=501,
        detail=f"当前已切换到航天广电 action 协议，不再支持旧远端接口：{path}",
    )


def _remote_enabled() -> bool:
    return bool(_resolve_remote_base_url())


def _cache_get(key: str) -> Optional[object]:
    if REMOTE_CACHE_SECONDS <= 0:
        return None
    cached = REMOTE_CACHE.get(key)
    if not cached:
        return None
    ts, payload = cached
    if time.time() - ts > REMOTE_CACHE_SECONDS:
        return None
    return payload


def _cache_set(key: str, payload: object) -> None:
    if REMOTE_CACHE_SECONDS <= 0:
        return
    REMOTE_CACHE[key] = (time.time(), payload)


def _ttl_cache_get(key: str) -> Optional[object]:
    cached = TTL_CACHE.get(key)
    if not cached:
        return None
    ts, ttl_seconds, payload = cached
    if ttl_seconds <= 0:
        return payload
    if time.time() - ts > ttl_seconds:
        return None
    return payload


def _ttl_cache_set(key: str, payload: object, ttl_seconds: float) -> None:
    TTL_CACHE[key] = (time.time(), ttl_seconds, payload)


def _unique_list(values: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _normalize_str_list(values: object) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned = [str(value).strip() for value in values if value not in (None, "")]
    cleaned = [value for value in cleaned if value]
    cleaned = [value for value in cleaned if value.lower() != "string"]
    return _unique_list(cleaned)


def _normalize_terminal_ids(values: object) -> List[str]:
    if isinstance(values, list):
        source = values
    elif values in (None, "", 0, "0"):
        return []
    else:
        source = [values]
    cleaned: List[str] = []
    for value in source:
        if value in (None, "", 0, "0"):
            continue
        text = str(value).strip()
        if not text or text == "0":
            continue
        if text.lower() == "string":
            continue
        cleaned.append(text)
    return _unique_list(cleaned)


def _join_media_names(values: object, separator: str = " / ") -> str:
    cleaned = _normalize_str_list(values)
    if not cleaned:
        return ""
    return separator.join(cleaned)


def _clean_media_name(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return _join_media_names(value)
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


def _submit_with_current_remote_token(executor: ThreadPoolExecutor, func, *args, **kwargs):
    remote_token = CURRENT_REMOTE_TOKEN.get()
    remote_base_url, remote_base_url_source = _resolve_remote_base_url_details()
    func_name = getattr(func, "__name__", func.__class__.__name__)
    _debug_remote(
        "submit remote worker",
        func=func_name,
        resolved_remote_base_url=remote_base_url,
        remote_base_url_source=remote_base_url_source,
        thread_name=threading.current_thread().name,
        thread_pool_task=True,
    )

    def runner():
        reset_token = None
        reset_base_url = None
        if remote_token:
            reset_token = CURRENT_REMOTE_TOKEN.set(remote_token)
        if remote_base_url:
            reset_base_url = CURRENT_REMOTE_BASE_URL.set(remote_base_url)
        try:
            return func(*args, **kwargs)
        finally:
            if reset_token is not None:
                CURRENT_REMOTE_TOKEN.reset(reset_token)
            if reset_base_url is not None:
                CURRENT_REMOTE_BASE_URL.reset(reset_base_url)

    return executor.submit(runner)


def _parallel_map(values: List[str], func) -> List[Optional[object]]:
    if REMOTE_FETCH_WORKERS <= 1 or len(values) <= 1:
        return [func(value) for value in values]
    results: List[Optional[object]] = [None] * len(values)
    with ThreadPoolExecutor(max_workers=REMOTE_FETCH_WORKERS) as executor:
        future_map = {_submit_with_current_remote_token(executor, func, value): idx for idx, value in enumerate(values)}
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = None
    return results


def _redact_payload(payload: Optional[dict]) -> Optional[dict]:
    if not isinstance(payload, dict):
        return payload
    redacted = dict(payload)
    for key in ("userpwd", "password", "Authorization", "token"):
        if key in redacted:
            redacted[key] = "***"
    return redacted


def _debug_remote(message: str, **fields: object) -> None:
    if not DEBUG_REMOTE:
        return
    LOGGER.info("%s %s", message, fields)


def _debug_payload_preview(value: object, *, form: bool = False) -> object:
    if value is None:
        return None
    if form:
        if isinstance(value, dict):
            return urllib.parse.urlencode(value, doseq=True)
        return str(value)
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return value


def _debug_timing(message: str, elapsed_ms: float, **fields: object) -> None:
    if not DEBUG_REMOTE:
        return
    LOGGER.info("%s %s", message, {"elapsed_ms": round(elapsed_ms, 2), **fields})


def _remote_url(path: str, remote_base_url: object = None) -> str:
    remote_base_url = _resolve_remote_base_url(remote_base_url)
    if not remote_base_url:
        return ""
    if not path:
        return remote_base_url
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{remote_base_url}{path}"


async def _extract_text_from_request(request: Request) -> Optional[str]:
    if request.query_params:
        for key in ("text", "message", "query", "content", "input"):
            value = request.query_params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    try:
        data = await request.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        for key in ("text", "message", "query", "content", "input"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    try:
        form = await request.form()
    except Exception:
        form = None
    if form:
        for key in ("text", "message", "query", "content", "input"):
            value = form.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raw = await request.body()
    if raw:
        text = raw.decode("utf-8", errors="ignore").strip()
        if text:
            if "=" in text:
                parsed = urllib.parse.parse_qs(text)
                for key in ("text", "message", "query", "content", "input"):
                    value = parsed.get(key)
                    if value:
                        return str(value[0]).strip()
            return text
    return None


def _normalize_remote_access_token(token: object) -> str:
    text = str(token or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return text


def _activate_remote_session_token(token: object) -> str:
    normalized = _normalize_remote_access_token(token)
    if not normalized:
        raise HTTPException(status_code=401, detail="Remote token is missing.")
    return normalized


def _extract_local_session_token(request: Request) -> str:
    for key in ("X-Token", "x-token"):
        value = request.headers.get(key)
        if value:
            return str(value).strip()
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    cookie_token = request.cookies.get(LOCAL_AUTH_COOKIE_NAME)
    if cookie_token:
        return str(cookie_token).strip()
    return ""


def _auth_response(data: dict) -> dict:
    return {"code": 20000, "data": data}


def _build_local_session_payload(session: dict) -> dict:
    return {
        "authenticated": True,
        "token": str(session.get("token") or ""),
        "name": str(session.get("name") or "Remote User"),
        "avatar": str(session.get("avatar") or ""),
        "login_method": str(session.get("login_method") or ""),
        "remote_username": str(session.get("remote_username") or ""),
        "remote_base_url": str(session.get("remote_base_url") or ""),
    }


def _create_local_session(
    remote_token: object,
    username: str,
    login_method: str,
    remote_base_url: object = None,
) -> dict:
    normalized_remote_token = _activate_remote_session_token(remote_token)
    normalized_remote_base_url = _resolve_remote_base_url(remote_base_url)
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_token = uuid.uuid4().hex + uuid.uuid4().hex
    session = {
        "token": session_token,
        "name": username.strip() or "Remote User",
        "avatar": "",
        "login_method": login_method.strip() or "password",
        "remote_username": username.strip(),
        "remote_token": normalized_remote_token,
        "remote_base_url": normalized_remote_base_url,
        "created_at": now_text,
        "last_active_at": now_text,
    }
    with LOCAL_AUTH_LOCK:
        LOCAL_AUTH_SESSIONS[session_token] = session
    return session


def _get_local_session_from_request(request: Request) -> Optional[dict]:
    token = _extract_local_session_token(request)
    if not token:
        return None
    with LOCAL_AUTH_LOCK:
        session = LOCAL_AUTH_SESSIONS.get(token)
        if not session:
            return None
        remote_token = _normalize_remote_access_token(session.get("remote_token"))
        if not remote_token:
            LOCAL_AUTH_SESSIONS.pop(token, None)
            _clear_pending_action_for_scope(token)
            return None
        session["remote_token"] = remote_token
        session["last_active_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return dict(session)


def _delete_local_session_from_request(request: Request) -> None:
    token = _extract_local_session_token(request)
    if not token:
        return
    with LOCAL_AUTH_LOCK:
        LOCAL_AUTH_SESSIONS.pop(token, None)
    _clear_pending_action_for_scope(token)


def _current_request_remote_token() -> Optional[str]:
    token = _normalize_remote_access_token(CURRENT_REMOTE_TOKEN.get())
    return token or None


def _current_request_remote_base_url() -> Optional[str]:
    value = CURRENT_REMOTE_BASE_URL.get()
    if not value:
        return None
    return _normalize_remote_base_url(value)


def _current_pending_scope() -> Optional[str]:
    scope = str(CURRENT_PENDING_SCOPE.get() or "").strip()
    return scope or None


def _set_current_pending_scope(scope: object) -> object:
    normalized = str(scope or "").strip() or None
    return CURRENT_PENDING_SCOPE.set(normalized)


def _reset_current_pending_scope(token: object) -> None:
    CURRENT_PENDING_SCOPE.reset(token)


def _get_pending_action(scope: object = None) -> Optional[dict]:
    global PENDING_ACTION
    scope_key = str(scope if scope is not None else (_current_pending_scope() or "")).strip()
    if not scope_key:
        return PENDING_ACTION
    with PENDING_ACTIONS_LOCK:
        action = PENDING_ACTIONS_BY_SCOPE.get(scope_key)
        if action is None:
            return None
        return action


def _snapshot_pending_action(scope: object = None) -> Optional[dict]:
    return _clone_payload(_get_pending_action(scope))


def _set_pending_action_for_scope(action: dict, scope: object = None) -> None:
    global PENDING_ACTION
    scope_key = str(scope if scope is not None else (_current_pending_scope() or "")).strip()
    action["created_at"] = _now_str()
    if not scope_key:
        PENDING_ACTION = action
        return
    with PENDING_ACTIONS_LOCK:
        PENDING_ACTIONS_BY_SCOPE[scope_key] = action


def _clear_pending_action_for_scope(scope: object = None) -> None:
    global PENDING_ACTION
    scope_key = str(scope if scope is not None else (_current_pending_scope() or "")).strip()
    if not scope_key:
        PENDING_ACTION = None
        return
    with PENDING_ACTIONS_LOCK:
        PENDING_ACTIONS_BY_SCOPE.pop(scope_key, None)


def _resolve_remote_auth_token() -> Tuple[Optional[str], str]:
    session_remote_token = _current_request_remote_token()
    if session_remote_token:
        return session_remote_token, "session"
    if REMOTE_TOKEN:
        return REMOTE_TOKEN, "default"
    return None, "none"


def _is_public_auth_path(path: str) -> bool:
    if path in AUTH_PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in AUTH_PUBLIC_PREFIXES)


@app.middleware("http")
async def enforce_auth_request(request: Request, call_next):
    path = request.url.path or "/"
    local_session = None
    reset_token = None
    reset_base_url = None
    reset_pending_scope = None
    if request.method.upper() != "OPTIONS" and not _is_public_auth_path(path):
        local_session = _get_local_session_from_request(request)
        if not local_session:
            return JSONResponse(status_code=401, content={"detail": "Login required."})
    if local_session:
        request.state.local_session = local_session
        pending_scope = str(local_session.get("token") or "").strip()
        remote_token = _normalize_remote_access_token(local_session.get("remote_token"))
        remote_base_url = _normalize_remote_base_url(local_session.get("remote_base_url"))
        if pending_scope:
            reset_pending_scope = _set_current_pending_scope(pending_scope)
        if remote_token:
            reset_token = CURRENT_REMOTE_TOKEN.set(remote_token)
        if remote_base_url:
            reset_base_url = CURRENT_REMOTE_BASE_URL.set(remote_base_url)
    try:
        return await call_next(request)
    finally:
        if reset_pending_scope is not None:
            _reset_current_pending_scope(reset_pending_scope)
        if reset_token is not None:
            CURRENT_REMOTE_TOKEN.reset(reset_token)
        if reset_base_url is not None:
            CURRENT_REMOTE_BASE_URL.reset(reset_base_url)


def _remote_request_with_explicit_token(
    method: str,
    path: str,
    remote_token: object,
    params: Optional[dict] = None,
    remote_base_url: object = None,
) -> object:
    if _legacy_remote_path_unsupported(path):
        _raise_legacy_remote_protocol_error(path)
    resolved_remote_base_url, remote_base_url_source = _resolve_remote_base_url_details(remote_base_url)
    if not resolved_remote_base_url:
        raise HTTPException(status_code=500, detail="未配置远端地址。")
    normalized_token = _normalize_remote_access_token(remote_token)
    if not normalized_token:
        raise HTTPException(status_code=401, detail="Remote token is missing.")
    url = _remote_url(path, resolved_remote_base_url)
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {normalized_token}",
    }
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as resp:
            raw_bytes = resp.read()
            raw = raw_bytes.decode("utf-8", errors="ignore")
            parsed_body = _parse_remote_body_text(raw)
            if isinstance(parsed_body, (dict, list)):
                return parsed_body
            return {"raw": raw}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        if exc.code in {401, 403}:
            raise HTTPException(status_code=401, detail="Remote token is invalid or expired.") from exc
        raise HTTPException(status_code=exc.code, detail=f"Remote request failed: {detail}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise HTTPException(status_code=504, detail=_remote_timeout_detail(method, path)) from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Remote request failed: {exc}") from exc


def _remote_login_with_credentials(username: str, password: str, remote_base_url: object = None) -> str:
    username_text = str(username or "").strip()
    password_text = str(password or "")
    if not username_text or not password_text:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    resolved_remote_base_url = _resolve_remote_base_url(remote_base_url)
    resp = _light_action.login_with_credentials(resolved_remote_base_url, username_text, password_text)
    if resp.get("success") is False:
        raise HTTPException(status_code=401, detail=resp.get("message") or "远端登录失败。")
    return f"action-session:{uuid.uuid4().hex}"


def _remote_token() -> Optional[str]:
    token, _ = _resolve_remote_auth_token()
    return token


def _remote_request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    form_body: Optional[dict] = None,
    include_auth: bool = True,
    allow_retry: bool = True,
    allow_form_retry: bool = True,
    diagnostic: Optional[dict] = None,
    remote_base_url: object = None,
) -> object:
    if _legacy_remote_path_unsupported(path):
        _raise_legacy_remote_protocol_error(path)
    resolved_remote_base_url, remote_base_url_source = _resolve_remote_base_url_details(remote_base_url)
    if not resolved_remote_base_url:
        raise HTTPException(status_code=500, detail="未配置远端地址。")
    url = _remote_url(path, resolved_remote_base_url)
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    _debug_remote(
        "remote request",
        method=method,
        url=url,
        resolved_remote_base_url=resolved_remote_base_url,
        remote_base_url_source=remote_base_url_source,
        thread_name=threading.current_thread().name,
        thread_pool_task="ThreadPoolExecutor" in threading.current_thread().name,
        params=params,
        json_body=_debug_payload_preview(_redact_payload(json_body)),
        form_body=_debug_payload_preview(_redact_payload(form_body), form=True),
    )
    if isinstance(diagnostic, dict):
        diagnostic["path"] = str(path or diagnostic.get("path") or "")
        if diagnostic.get("request_payload") is None:
            payload_preview = form_body if form_body is not None else json_body
            diagnostic["request_payload"] = _redact_payload(_clone_payload(payload_preview) or {})
        _log_remote_phase_request(diagnostic)
    start = time.perf_counter()
    data = None
    headers = {"Accept": "application/json"}
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form_body is not None:
        data = urllib.parse.urlencode(form_body, doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    token_source = "none"
    if include_auth:
        token, token_source = _resolve_remote_auth_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as resp:
            raw_bytes = resp.read()
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            raw = raw_bytes.decode("utf-8", errors="ignore")
            parsed_body = _parse_remote_body_text(raw)
            _debug_remote("remote response", status=resp.getcode(), bytes=len(raw_bytes))
            _debug_timing("remote request time", elapsed_ms, method=method, url=url)
            if isinstance(diagnostic, dict):
                diagnostic["status_code"] = int(resp.getcode())
                diagnostic["elapsed_ms"] = elapsed_ms
                diagnostic["ok"] = True
                diagnostic["response_body"] = _clone_payload(parsed_body)
                diagnostic["error_detail"] = ""
                diagnostic["timeout"] = False
                _log_remote_phase_result(diagnostic)
            if isinstance(parsed_body, (dict, list)):
                return parsed_body
            return {"raw": raw}
    except (TimeoutError, socket.timeout) as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        detail = _remote_timeout_detail(method, path)
        _debug_remote("remote timeout", reason=str(exc))
        _debug_timing("remote request time", elapsed_ms, method=method, url=url)
        if isinstance(diagnostic, dict):
            diagnostic["status_code"] = 504
            diagnostic["elapsed_ms"] = elapsed_ms
            diagnostic["ok"] = False
            diagnostic["response_body"] = None
            diagnostic["error_detail"] = detail
            diagnostic["timeout"] = True
            _log_remote_phase_result(diagnostic)
        raise HTTPException(status_code=504, detail=detail) from exc
    except HTTPError as exc:
        _debug_remote("remote http error", status=exc.code, reason=str(exc))
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        parsed_body = _parse_remote_body_text(detail)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        if exc.code in {401, 403} and include_auth and token_source == "session":
            raise HTTPException(status_code=401, detail="Remote token is invalid or expired.") from exc
        if exc.code == 502:
            LOGGER.error(
                "REMOTE 502 REQUEST >>> method=%s url=%s params=%s json_body=%s form_body=%s response=%s",
                method,
                url,
                _debug_payload_preview(_redact_payload(params)),
                _debug_payload_preview(_redact_payload(json_body)),
                _debug_payload_preview(_redact_payload(form_body), form=True),
                _debug_payload_preview(parsed_body),
            )
        _debug_timing("remote request time", elapsed_ms, method=method, url=url)
        if isinstance(diagnostic, dict):
            diagnostic["status_code"] = int(exc.code)
            diagnostic["elapsed_ms"] = elapsed_ms
            diagnostic["ok"] = False
            diagnostic["response_body"] = _clone_payload(parsed_body)
            diagnostic["error_detail"] = str(detail)
            diagnostic["timeout"] = False
            _log_remote_phase_result(diagnostic)
        extra = ""
        if DEBUG_REMOTE:
            payload_hint = {
                "json_body": _debug_payload_preview(_redact_payload(json_body)),
                "form_body": _debug_payload_preview(_redact_payload(form_body), form=True),
            }
            extra = f" | method={method} url={url} payload={payload_hint}"
        raise HTTPException(status_code=exc.code, detail=f"Remote request failed: {detail}{extra}") from exc
    except URLError as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        if _looks_like_timeout_error(getattr(exc, "reason", exc)):
            detail = _remote_timeout_detail(method, path)
            _debug_remote("remote timeout", reason=str(exc))
            _debug_timing("remote request time", elapsed_ms, method=method, url=url)
            if isinstance(diagnostic, dict):
                diagnostic["status_code"] = 504
                diagnostic["elapsed_ms"] = elapsed_ms
                diagnostic["ok"] = False
                diagnostic["response_body"] = None
                diagnostic["error_detail"] = detail
                diagnostic["timeout"] = True
                _log_remote_phase_result(diagnostic)
            raise HTTPException(status_code=504, detail=detail) from exc
        _debug_remote("remote url error", reason=str(exc))
        _debug_timing("remote request time", elapsed_ms, method=method, url=url)
        if isinstance(diagnostic, dict):
            diagnostic["status_code"] = 502
            diagnostic["elapsed_ms"] = elapsed_ms
            diagnostic["ok"] = False
            diagnostic["response_body"] = None
            diagnostic["error_detail"] = str(exc.reason if getattr(exc, "reason", None) else exc)
            diagnostic["timeout"] = False
            _log_remote_phase_result(diagnostic)
        raise HTTPException(status_code=502, detail=f"Remote request failed: {exc}") from exc


def _remote_data_list(payload: object) -> list:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        schedules = payload.get("schedules")
        if isinstance(schedules, list):
            return schedules
    if isinstance(payload, list):
        return payload
    return []


def _remote_fetch_schedule_source() -> object:
    primary = REMOTE_SCHEDULES_PATH
    fallback = REMOTE_SCHEDULES_FALLBACK_PATH or "/task/sechinfo"
    if primary == fallback:
        return _remote_request("GET", primary)
    try:
        raw = _remote_request("GET", primary)
        if _remote_data_list(raw):
            return raw
    except HTTPException as exc:
        if exc.status_code not in {404, 405}:
            raise
    return _remote_request("GET", fallback)


def _remote_fetch_schedule_sources(force: bool = False) -> List[object]:
    del force  # keep force signature for sync pipeline compatibility
    primary = REMOTE_SCHEDULES_PATH
    fallback = REMOTE_SCHEDULES_FALLBACK_PATH or "/task/sechinfo"
    paths = _unique_list([path for path in [primary, fallback] if path])
    results: List[object] = []
    last_error: Optional[HTTPException] = None
    for idx, path in enumerate(paths):
        try:
            raw = _remote_request("GET", path)
            raw_items = _remote_data_list(raw)
            if raw_items:
                if idx == 0:
                    return [raw]
                results.append(raw)
            elif idx == 0 and len(paths) == 1:
                results.append(raw)
        except HTTPException as exc:
            if idx == 0 and exc.status_code in {404, 405}:
                continue
            last_error = exc
    if results:
        return results
    if last_error:
        raise last_error
    return [_remote_fetch_schedule_source()]


def _media_folder_id_text(folder_id: Optional[int] = None) -> str:
    if folder_id in (None, ""):
        return ""
    try:
        return str(int(folder_id))
    except (TypeError, ValueError):
        return str(folder_id).strip()


def _media_folder_cache_key(base_key: str, folder_id: Optional[int] = None) -> str:
    folder_text = _media_folder_id_text(folder_id)
    return f"{base_key}:{folder_text}" if folder_text else base_key


def _invalidate_media_runtime_caches() -> None:
    for key in list(TTL_CACHE.keys()):
        key_text = str(key)
        if key_text == "mediainfo_payload" or key_text.startswith("mediainfo_payload:"):
            TTL_CACHE.pop(key, None)
        elif key_text == "media_map" or key_text.startswith("media_map:"):
            TTL_CACHE.pop(key, None)
    for key in list(REMOTE_CACHE.keys()):
        key_text = str(key)
        if key_text == "media_lookup" or key_text.startswith("media_lookup:"):
            REMOTE_CACHE.pop(key, None)


def _remote_mediainfo_payload(force: bool = False, folder_id: Optional[int] = None) -> object:
    cache_key = _media_folder_cache_key("mediainfo_payload", folder_id)
    if not force:
        cached = _ttl_cache_get(cache_key)
        if cached is not None:
            return cached
    folder_text = _media_folder_id_text(folder_id)
    path = f"/terminal/mediainfo/{folder_text}" if folder_text else "/terminal/mediainfo"
    payload = _remote_request("GET", path)
    _ttl_cache_set(cache_key, payload, REMOTE_LOOKUP_CACHE_SECONDS)
    return payload


def _remote_terminalinfo_payload(force: bool = False) -> object:
    if not force:
        cached = _ttl_cache_get("terminalinfo_payload")
        if cached is not None:
            return cached
    payload = _remote_request("GET", "/terminal/terminalinfo")
    _ttl_cache_set("terminalinfo_payload", payload, REMOTE_LOOKUP_CACHE_SECONDS)
    return payload


def _remote_mediainfo_items(folder_id: Optional[int] = None) -> list:
    return _remote_data_list(_remote_mediainfo_payload(folder_id=folder_id))


def _remote_terminalinfo_items() -> list:
    try:
        items = _remote_data_list(_remote_terminalinfo_payload())
    except HTTPException:
        items = []
    if not items:
        items = _store_terminalinfo_items()
    return items



def _fetch_remote_all_audio(force: bool = False, folder_id: Optional[int] = None) -> object:
    return _remote_mediainfo_payload(force=force, folder_id=folder_id)


def _fetch_remote_all_loc(force: bool = False) -> object:
    return _remote_terminalinfo_payload(force=force)



def _schedule_name_from_remote(item: dict, index: int) -> str:
    del index
    if not isinstance(item, dict):
        return ""
    name = item.get("sechename") or item.get("schedule_name")
    if name:
        return str(name or "").strip()
    if _looks_like_task(item):
        return ""
    return str(item.get("name") or "").strip()


AI_ONCE_SCHEDULE_SUFFIXES = {
    "migrate": "(AI迁移版)",
    "swap": "(AI互换版)",
}

AI_ONCE_ACTION_LABELS = {
    "migrate": "一次性迁移后",
    "swap": "一次性互换后",
}


def _once_remote_schedule_name(schedule_name: object, once_action: object) -> str:
    base_name = str(schedule_name or "").strip()
    action_name = str(once_action or "").strip()
    if not base_name:
        return ""
    suffix = AI_ONCE_SCHEDULE_SUFFIXES.get(action_name)
    if not suffix:
        return ""
    return f"{base_name}{suffix}"


def _is_ai_once_schedule_name(schedule_name: object) -> bool:
    name = str(schedule_name or "").strip()
    if not name:
        return False
    return any(name.endswith(suffix) for suffix in AI_ONCE_SCHEDULE_SUFFIXES.values())


def _known_ai_once_schedule_names_from_overrides(payload: Optional[dict] = None) -> set[str]:
    if payload is None:
        payload = _store_get("task_overrides")
        if not isinstance(payload, dict):
            try:
                payload = _load_overrides_payload()
            except Exception:
                payload = {}
    if not isinstance(payload, dict):
        return set()
    names: set[str] = set()
    overrides = payload.get("overrides") if isinstance(payload.get("overrides"), list) else []
    for entry in overrides:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("mode") or "").strip() != "once":
            continue
        if str(entry.get("cleanup_state") or "").strip() == "cleaned":
            continue
        if entry.get("active") is False:
            continue
        entry_name = str(entry.get("once_schedule_name") or "").strip()
        if _is_ai_once_schedule_name(entry_name):
            names.add(entry_name)
        for spec in entry.get("once_task_specs") or []:
            if not isinstance(spec, dict):
                continue
            spec_name = str(spec.get("once_schedule_name") or "").strip()
            if _is_ai_once_schedule_name(spec_name):
                names.add(spec_name)
    return names


def _hidden_ai_once_schedule_names(known_ai_names: Optional[Collection[object]] = None) -> set[str]:
    if known_ai_names is None:
        return _known_ai_once_schedule_names_from_overrides()
    return {
        str(name or "").strip()
        for name in known_ai_names
        if _is_ai_once_schedule_name(str(name or "").strip())
    }


def _is_hidden_ai_once_schedule_name(schedule_name: object, known_ai_names: Optional[Collection[object]] = None) -> bool:
    name = str(schedule_name or "").strip()
    return bool(name and name in _hidden_ai_once_schedule_names(known_ai_names))


def _filter_visible_schedule_names(
    schedule_names: Collection[object],
    known_ai_names: Optional[Collection[object]] = None,
) -> List[str]:
    hidden_names = _hidden_ai_once_schedule_names(known_ai_names)
    return [
        name
        for name in _unique_list([str(item or "").strip() for item in (schedule_names or []) if str(item or "").strip()])
        if name not in hidden_names
    ]


def _filter_visible_schedule_status_map(
    status_by_name: Dict[str, str],
    known_ai_names: Optional[Collection[object]] = None,
) -> Dict[str, str]:
    hidden_names = _hidden_ai_once_schedule_names(known_ai_names)
    return {
        str(name): status
        for name, status in (status_by_name or {}).items()
        if str(name) not in hidden_names
    }


def _format_once_remote_task_name(
    source_task: dict,
    once_start: datetime,
    *,
    once_action: str,
) -> str:
    base_name = str(
        source_task.get("customName")
        or source_task.get("taskname")
        or source_task.get("name")
        or "临时任务"
    ).strip() or "临时任务"
    action_label = AI_ONCE_ACTION_LABELS.get(str(once_action or "").strip(), "一次性任务")
    source_task_id = _task_id(source_task)
    suffix = once_start.strftime("%Y%m%d%H%M%S")
    if source_task_id:
        return f"{base_name}_{action_label}_{source_task_id}_{suffix}"
    return f"{base_name}_{action_label}_{suffix}"


def _is_known_non_schedule_remote_task(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if _schedule_name_from_remote(item, 0):
        return False
    normalized = _normalize_remote_task(item)
    name_candidates: List[str] = []
    seen: set[str] = set()
    for source in (item, normalized):
        if not isinstance(source, dict):
            continue
        for key in ("taskname", "name", "medianame", "customName", "audio", "title"):
            value = source.get(key)
            text = str(value or "").strip().lower()
            if not text or text in seen:
                continue
            seen.add(text)
            name_candidates.append(text)
    if not name_candidates:
        return False
    reset_aliases = {"reset", "重启"}
    if any(candidate in reset_aliases for candidate in name_candidates):
        return True
    task_id = _task_id(normalized) or _task_id(item)
    return str(task_id or "").strip() == "7000" and any(candidate in reset_aliases for candidate in name_candidates)


def _append_ignored_unnamed_schedule_info(
    payload: dict,
    ignored_items: List[dict],
    *,
    total_count: Optional[int] = None,
) -> dict:
    global _LAST_IGNORED_UNNAMED_SCHEDULE_LOG
    if not isinstance(payload, dict):
        return payload
    normalized_items: List[dict] = []
    for item in ignored_items or []:
        if not isinstance(item, dict):
            continue
        normalized_items.append(
            {
                "index": _coerce_int(item.get("index"), 0),
                "task_id": str(item.get("task_id") or "").strip(),
                "task_name": str(item.get("task_name") or "").strip(),
                "raw_name": str(item.get("raw_name") or "").strip(),
            }
        )
    normalized_count = len(normalized_items)
    if total_count is not None:
        normalized_count = max(_coerce_int(total_count, 0), normalized_count)
    if not normalized_count and not normalized_items:
        payload.pop("ignored_unnamed_schedules", None)
        payload.pop("ignored_unnamed_schedule_samples", None)
        return payload
    payload["ignored_unnamed_schedules"] = normalized_count
    payload["ignored_unnamed_schedule_samples"] = normalized_items[:5]
    log_payload = {
        "count": normalized_count,
        "samples": normalized_items[:5],
    }
    log_signature = json.dumps(log_payload, ensure_ascii=False, sort_keys=True)
    if log_signature != _LAST_IGNORED_UNNAMED_SCHEDULE_LOG:
        LOGGER.warning("ignored remote schedules without names %s", log_payload)
        _LAST_IGNORED_UNNAMED_SCHEDULE_LOG = log_signature
    else:
        LOGGER.info("ignored remote schedules without names %s", log_payload)
    return payload


def _remote_schedule_delete_supported() -> bool:
    if not REMOTE_ALLOW_DELETE_SCHEDULE_ENTRY:
        return False
    payload = _load_remote_sync_meta_payload()
    if payload.get("schedule_delete_checked") and not payload.get("schedule_delete_supported", True):
        return False
    return True


def _filter_tombstoned_empty_schedules(payload: dict) -> dict:
    schedules = payload.get("schedules") if isinstance(payload, dict) else None
    if not isinstance(schedules, list):
        return payload
    filtered: List[dict] = []
    for schedule in schedules:
        if not isinstance(schedule, dict):
            continue
        schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or "").strip()
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        if schedule_name and not tasks and _is_schedule_tombstoned(schedule_name):
            continue
        filtered.append(schedule)
    payload["schedules"] = filtered
    return payload


def _status_label(value: object) -> str:
    value_str = str(value)
    if value_str in {"0", "启用", "执行中", "enabled", "true", "True"}:
        return "启用"
    if value_str in {"1", "停用", "禁用", "disabled", "false", "False"}:
        return "停用"
    return "启用"


def _status_from_remote(item: dict) -> str:
    value = item.get("status")
    if value in (None, ""):
        value = item.get("projectstate")
    if value in (None, ""):
        value = item.get("state")
    return _status_label(value)


def _status_enabled(value: object) -> bool:
    return _status_label(value) == "启用"


def _merge_schedule_status(current: Optional[str], incoming: object) -> str:
    if current in (None, ""):
        return _status_label(incoming)
    if not _status_enabled(current) or not _status_enabled(incoming):
        return "停用"
    return "启用"


def _task_status_from_remote(item: dict) -> str:
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


def _task_state_from_label(value: object) -> int:
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


def _task_display_status(state: int, fallback: Optional[str] = None) -> str:
    if state in {1, 3}:
        return "执行中"
    if state == 2:
        return "暂停"
    if state == 0:
        return "停止"
    if fallback:
        return str(fallback)
    return "待执行"


def _extract_schedule_tasks(item: dict) -> list:
    for key in ("tasks", "tasklist", "taskList", "task_list", "taskinfo", "taskInfo", "sechetask"):
        value = item.get(key)
        if isinstance(value, list):
            return value
    return []


def _runtime_play_items_from_payload(payload: object) -> list:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        for key in ("tasks", "tasklist", "taskList", "task_list", "taskinfo", "taskInfo", "sechetask", "rows", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for key in ("result", "obj", "item"):
            nested = payload.get(key)
            if isinstance(nested, (dict, list)):
                nested_items = _runtime_play_items_from_payload(nested)
                if nested_items:
                    return nested_items
    if isinstance(payload, list):
        return payload
    return []


def _normalize_runtime_id_list(values: object) -> List[str]:
    if isinstance(values, list):
        source = values
    elif values in (None, "", 0, "0"):
        return []
    else:
        text = str(values).strip()
        if not text:
            return []
        if any(sep in text for sep in (",", "，", ";", "|")):
            normalized = text.replace("，", ",").replace(";", ",").replace("|", ",")
            source = [item.strip() for item in normalized.split(",")]
        else:
            source = [text]
    cleaned: List[str] = []
    for value in source:
        if value in (None, "", 0, "0"):
            continue
        text = str(value).strip()
        if not text or text == "0" or text.lower() == "string":
            continue
        cleaned.append(text)
    return _unique_list(cleaned)


def _runtime_play_media_ids_from_item(item: dict) -> List[str]:
    if not isinstance(item, dict):
        return []
    ids = _normalize_runtime_id_list(item.get("mediaids") or item.get("media_ids"))
    if ids:
        return ids
    task_media = item.get("taskmedia") or item.get("taskMedia")
    if isinstance(task_media, list):
        extracted: List[str] = []
        for media_item in task_media:
            if not isinstance(media_item, dict):
                continue
            media_id = media_item.get("mediaid") or media_item.get("media_id") or media_item.get("id")
            if media_id not in (None, "", 0, "0"):
                extracted.append(str(media_id).strip())
        extracted = _unique_list([value for value in extracted if value])
        if extracted:
            return extracted
    media_id = item.get("mediaid") or item.get("media_id") or item.get("id")
    return _normalize_runtime_id_list(media_id)


def _runtime_play_terminal_ids_from_item(item: dict) -> List[str]:
    if not isinstance(item, dict):
        return []
    ids = _normalize_runtime_id_list(
        item.get("terminalids") or item.get("terminal_ids") or item.get("liveterminalids")
    )
    if ids:
        return ids
    task_terminal = item.get("taskterminal") or item.get("taskTerminal")
    if isinstance(task_terminal, list):
        extracted: List[str] = []
        for terminal_item in task_terminal:
            if not isinstance(terminal_item, dict):
                continue
            terminal_id = (
                terminal_item.get("terminalid")
                or terminal_item.get("terminal_id")
                or terminal_item.get("liveterminalid")
                or terminal_item.get("id")
            )
            if terminal_id not in (None, "", 0, "0"):
                extracted.append(str(terminal_id).strip())
        extracted = _unique_list([value for value in extracted if value])
        if extracted:
            return extracted
    return _normalize_runtime_id_list(item.get("liveterminalid") or item.get("terminalid") or item.get("terminal_id"))


def _looks_like_task(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    return any(key in item for key in ("starttime", "start_time", "taskname", "mediaid", "terminalid"))


def _normalize_remote_task(task: dict) -> dict:
    if not isinstance(task, dict):
        return {}
    mapped = dict(task)
    if mapped.get("taskid") is None:
        for key in ("taskid", "id", "task_id", "taskId", "sechetaskid"):
            if key in mapped and mapped.get(key) is not None:
                mapped["taskid"] = mapped.get(key)
                break
    if "taskname" not in mapped:
        for key in ("taskname", "name", "medianame", "media_name", "title"):
            if mapped.get(key):
                mapped["taskname"] = mapped.get(key)
                break
    if "customName" not in mapped:
        mapped["customName"] = mapped.get("taskname") or ""
    if "audio" not in mapped:
        mapped["audio"] = mapped.get("taskname") or mapped.get("medianame") or mapped.get("media") or ""
    if "starttime" not in mapped:
        for key in ("start_time", "time", "stime"):
            if mapped.get(key):
                mapped["starttime"] = mapped.get(key)
                break
    if "startdate" not in mapped:
        for key in ("start_date", "startDate"):
            if mapped.get(key):
                mapped["startdate"] = mapped.get(key)
                break
    if "enddate" not in mapped:
        for key in ("end_date", "endDate"):
            if mapped.get(key):
                mapped["enddate"] = mapped.get(key)
                break
    if "timelength" not in mapped and mapped.get("duration") is not None:
        mapped["timelength"] = mapped.get("duration")
    if "timelength" not in mapped and mapped.get("length") is not None:
        mapped["timelength"] = mapped.get("length")
    if "timelengthtype" not in mapped and mapped.get("timelength") is not None:
        mapped["timelengthtype"] = 1
    if "timelengthtype" not in mapped and mapped.get("lengthtype") is not None:
        mapped["timelengthtype"] = mapped.get("lengthtype")
    if mapped.get("mediaid") is None:
        task_media = mapped.get("taskmedia") or mapped.get("taskMedia")
        if isinstance(task_media, list) and task_media:
            media_item = task_media[0]
            if isinstance(media_item, dict):
                media_id = media_item.get("mediaid") or media_item.get("media_id") or media_item.get("id")
                if media_id is not None:
                    mapped["mediaid"] = media_id
                if not mapped.get("medianame") and media_item.get("medianame"):
                    mapped["medianame"] = media_item.get("medianame")
    task_terminal = mapped.get("taskterminal") or mapped.get("taskTerminal")
    terminal_ids = _terminal_ids_from_taskterminal(task_terminal)
    terminal_names = _terminal_names_from_taskterminal(task_terminal)
    if terminal_ids:
        mapped["terminalids"] = terminal_ids
    if terminal_names:
        mapped["terminalnames"] = terminal_names
    if mapped.get("terminalid") is None and mapped.get("liveterminalid") is None:
        if terminal_ids:
            mapped["terminalid"] = terminal_ids[0]
        if terminal_names and not mapped.get("terminalname"):
            mapped["terminalname"] = terminal_names[0]
    if mapped.get("medianame") and (
        not mapped.get("audio")
        or mapped.get("audio") in {mapped.get("taskname"), mapped.get("customName"), ""}
    ):
        mapped["audio"] = mapped.get("medianame")
    if not isinstance(mapped.get("weekdays"), list):
        weekdays = _weekdays_from_execmode(mapped.get("execmode"))
        if weekdays:
            mapped["weekdays"] = weekdays
            if len(weekdays) >= 7:
                startdate = mapped.get("startdate")
                enddate = mapped.get("enddate")
                if startdate and enddate and startdate == enddate and startdate != "0-00-00":
                    mapped["startdate"] = "0-00-00"
                    mapped["enddate"] = "0-00-00"
    return mapped


def _task_dedupe_key(task: dict) -> str:
    if not isinstance(task, dict):
        return ""
    for key in ("taskid", "id", "task_id", "taskId", "sechetaskid"):
        value = task.get(key)
        if value is not None:
            return f"id:{value}"
    parts = [
        task.get("starttime"),
        task.get("taskname"),
        task.get("customName"),
        task.get("audio"),
        task.get("startdate"),
        task.get("enddate"),
    ]
    return "|".join(str(part or "") for part in parts)


def _merge_tasks(existing: list, incoming: list) -> list:
    merged: List[dict] = []
    seen: set[str] = set()
    for task in (existing or []) + (incoming or []):
        if not isinstance(task, dict):
            continue
        key = _task_dedupe_key(task)
        if key in seen:
            continue
        seen.add(key)
        merged.append(task)
    return merged


def _has_task_details(task: dict) -> bool:
    if not isinstance(task, dict):
        return False
    for key in (
        "starttime",
        "start_time",
        "taskname",
        "customName",
        "audio",
        "mediaid",
        "medianame",
        "ttsterminal",
        "liveterminalid",
        "terminalid",
    ):
        value = task.get(key)
        if value not in (None, ""):
            return True
    return False


def _remote_fetch_schedule_tasks(schedule_name: str) -> list:
    resolved_remote_base_url, remote_base_url_source = _resolve_remote_base_url_details()
    _debug_remote(
        "fetch remote schedule tasks",
        schedule_name=schedule_name,
        resolved_remote_base_url=resolved_remote_base_url,
        remote_base_url_source=remote_base_url_source,
        thread_name=threading.current_thread().name,
        thread_pool_task="ThreadPoolExecutor" in threading.current_thread().name,
    )
    payload = {"name": schedule_name}
    resp = _remote_request(
        "POST",
        "/task/sechetaskinfo",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )
    return _remote_data_list(resp)


def _adapt_remote_schedules(raw: object) -> dict:
    if isinstance(raw, dict) and isinstance(raw.get("schedules"), list):
        return raw
    items = _remote_data_list(raw)
    if not items:
        return {"version": "remote", "generated_at": _now_str(), "schedules": [], "broadcasts": [], "livecasts": []}
    ignored_unnamed: List[dict] = []
    if _looks_like_task(items[0]):
        grouped: Dict[str, List[dict]] = {}
        status_by_name: Dict[str, str] = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            name = _schedule_name_from_remote(item, index)
            if not name:
                if _is_known_non_schedule_remote_task(item):
                    continue
                ignored_unnamed.append(
                    {
                        "index": index,
                        "task_id": _task_id(item),
                        "task_name": item.get("taskname") or item.get("name") or item.get("medianame"),
                        "raw_name": item.get("sechename") or item.get("schedule_name") or item.get("name"),
                    }
                )
                continue
            normalized = _normalize_remote_task(item)
            if _is_once_ephemeral_task_name(normalized.get("taskname") or normalized.get("name") or normalized.get("customName")):
                continue
            if not _has_task_details(normalized):
                continue
            grouped[name] = _merge_tasks(grouped.get(name, []), [normalized])
            status_by_name[name] = _merge_schedule_status(status_by_name.get(name), _status_from_remote(item))
        schedules = [
            {"schedule_name": name, "status": status_by_name.get(name, "启用"), "tasks": tasks}
            for name, tasks in grouped.items()
        ]
        return _append_ignored_unnamed_schedule_info(
            {"version": "remote", "generated_at": _now_str(), "schedules": schedules, "broadcasts": [], "livecasts": []},
            ignored_unnamed,
        )
    schedules_by_name: Dict[str, dict] = {}
    tasks_cache: Dict[str, list] = {}
    schedule_rows: List[Tuple[str, str, list]] = []
    schedule_names_to_fetch: List[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = _schedule_name_from_remote(item, index)
        if not name:
            if _is_known_non_schedule_remote_task(item):
                continue
            ignored_unnamed.append(
                {
                    "index": index,
                    "task_id": _task_id(item),
                    "task_name": item.get("taskname") or item.get("name") or item.get("medianame"),
                    "raw_name": item.get("sechename") or item.get("schedule_name") or item.get("name"),
                }
            )
            continue
        if _is_hidden_ai_once_schedule_name(name):
            continue
        status = _status_from_remote(item)
        tasks = _extract_schedule_tasks(item)
        if not tasks and name:
            schedule_names_to_fetch.append(name)
        schedule_rows.append((name, status, tasks))
    unique_names = _unique_list(schedule_names_to_fetch)
    if unique_names:
        fetched = _parallel_map(unique_names, _remote_fetch_schedule_tasks)
        for name, tasks in zip(unique_names, fetched):
            tasks_cache[name] = tasks or []
    for name, status, tasks in schedule_rows:
        if not tasks and name:
            tasks = tasks_cache.get(name, [])
        tasks = [_normalize_remote_task(task) for task in tasks if isinstance(task, dict)]
        tasks = _filter_once_ephemeral_schedule_tasks(tasks)
        tasks = [task for task in tasks if _has_task_details(task)]
        if name in schedules_by_name:
            existing = schedules_by_name[name]
            existing["tasks"] = _merge_tasks(existing.get("tasks"), tasks)
            existing["status"] = _merge_schedule_status(existing.get("status"), status)
        else:
            schedules_by_name[name] = {"schedule_name": name, "status": status, "tasks": tasks}
    schedules = list(schedules_by_name.values())
    return _append_ignored_unnamed_schedule_info(
        {"version": "remote", "generated_at": _now_str(), "schedules": schedules, "broadcasts": [], "livecasts": []},
        ignored_unnamed,
    )


def _load_local_broadcasts() -> dict:
    payload = _store_get("broadcast_schedules")
    if isinstance(payload, dict):
        return {
            "broadcasts": payload.get("broadcasts", []) if isinstance(payload.get("broadcasts"), list) else [],
            "livecasts": payload.get("livecasts", []) if isinstance(payload.get("livecasts"), list) else [],
        }
    return {"broadcasts": [], "livecasts": []}


def _merge_schedule_payloads(payloads: List[dict]) -> dict:
    merged_by_name: Dict[str, dict] = {}
    ignored_unnamed: List[dict] = []
    ignored_unnamed_total = 0
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        upstream_count = payload.get("ignored_unnamed_schedules")
        if upstream_count is None:
            upstream_count = len(
                [item for item in (payload.get("ignored_unnamed_schedule_samples") or []) if isinstance(item, dict)]
            )
        ignored_unnamed_total += _coerce_int(upstream_count, 0)
        ignored_unnamed.extend(
            [item for item in (payload.get("ignored_unnamed_schedule_samples") or []) if isinstance(item, dict)]
        )
        schedules = payload.get("schedules")
        if not isinstance(schedules, list):
            continue
        for index, schedule in enumerate(schedules):
            if not isinstance(schedule, dict):
                continue
            name = str(schedule.get("schedule_name") or schedule.get("name") or "").strip()
            if not name:
                ignored_unnamed.append(
                    {
                        "index": index,
                        "task_id": "",
                        "task_name": "",
                        "raw_name": schedule.get("schedule_name") or schedule.get("name"),
                    }
                )
                ignored_unnamed_total += 1
                continue
            if _is_hidden_ai_once_schedule_name(name):
                continue
            status = _status_from_remote(schedule)
            tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
            tasks = [_normalize_remote_task(task) for task in tasks if isinstance(task, dict)]
            tasks = [task for task in tasks if _has_task_details(task)]
            if name in merged_by_name:
                existing = merged_by_name[name]
                existing["tasks"] = _merge_tasks(existing.get("tasks"), tasks)
                existing["status"] = _merge_schedule_status(existing.get("status"), status)
            else:
                merged_by_name[name] = {"schedule_name": name, "status": status, "tasks": tasks}
    return _append_ignored_unnamed_schedule_info({
        "version": "remote",
        "generated_at": _now_str(),
        "schedules": list(merged_by_name.values()),
        "broadcasts": [],
        "livecasts": [],
    }, ignored_unnamed, total_count=ignored_unnamed_total)


def _fetch_remote_schedule_payload(
    force: bool = False,
    *,
    reuse_prefetched_media: bool = False,
    reuse_prefetched_terminal: bool = False,
) -> dict:
    start = time.perf_counter()
    resolved_remote_base_url, remote_base_url_source = _resolve_remote_base_url_details()
    _debug_remote(
        "fetch remote schedule payload",
        force=force,
        resolved_remote_base_url=resolved_remote_base_url,
        remote_base_url_source=remote_base_url_source,
        thread_name=threading.current_thread().name,
        thread_pool_task="ThreadPoolExecutor" in threading.current_thread().name,
    )
    if force:
        if not reuse_prefetched_media:
            _invalidate_media_runtime_caches()
        if not reuse_prefetched_terminal:
            REMOTE_CACHE.pop("terminal_lookup", None)
            TTL_CACHE.pop("terminalinfo_payload", None)
            TTL_CACHE.pop("enriched_terzone_items", None)
    raws = _remote_fetch_schedule_sources(force=force)
    adapted_payloads = [_adapt_remote_schedules(raw) for raw in raws]
    if len(adapted_payloads) <= 1:
        payload = adapted_payloads[0] if adapted_payloads else _adapt_remote_schedules({})
    else:
        payload = _merge_schedule_payloads(adapted_payloads)

    # 补充:从 /task/sechinfo 获取完整方案名列表,补入缺失的空方案
    try:
        all_names = _remote_schedule_names()
    except HTTPException:
        all_names = []
    known_ai_once_names = _known_ai_once_schedule_names_from_overrides()
    if all_names:
        existing_names = {
            str(s.get("schedule_name") or s.get("name") or "")
            for s in payload.get("schedules", [])
            if isinstance(s, dict)
        }
        for name in all_names:
            if name and not _is_hidden_ai_once_schedule_name(name, known_ai_once_names) and name not in existing_names:
                payload.setdefault("schedules", []).append(
                    {"schedule_name": name, "status": "\u542f\u7528", "tasks": []}
                )
    payload = _filter_hidden_ai_once_schedules_payload(payload, known_ai_once_names)
    payload = _filter_tombstoned_empty_schedules(payload)

    local = _load_local_broadcasts()
    media_lookup = {}
    terminal_lookup = {}
    try:
        media_lookup = _remote_media_lookup()
    except HTTPException:
        media_lookup = {}
    try:
        if reuse_prefetched_terminal:
            terminal_lookup = _terminal_lookup_from_items(
                _remote_data_list(_remote_terminalinfo_payload(force=False))
            )
        else:
            terminal_lookup = _remote_terminal_lookup()
    except HTTPException:
        terminal_lookup = {}
    _apply_media_lookup_to_schedules(payload.get("schedules", []), media_lookup)
    _apply_terminal_lookup_to_schedules(payload.get("schedules", []), terminal_lookup)
    broadcasts = None
    livecasts = None
    try:
        broadcasts = _fetch_remote_taskinfo_list("broadcast", str(REMOTE_BROADCAST_TASK_TYPE))
    except HTTPException:
        broadcasts = None
    try:
        livecasts = _fetch_remote_taskinfo_list("livecast", str(REMOTE_LIVECAST_TASK_TYPE))
    except HTTPException:
        livecasts = None
 
    payload["broadcasts"] = broadcasts if broadcasts is not None else local.get("broadcasts", [])
    payload["livecasts"] = livecasts if livecasts is not None else local.get("livecasts", [])
    payload["generated_at"] = _now_str()
    _debug_timing("fetch remote schedules payload", (time.perf_counter() - start) * 1000)
    return payload


def _fetch_remote_schedule_summary() -> dict:
    start = time.perf_counter()
    sources = _remote_fetch_schedule_sources()
    items: List[dict] = []
    for raw in sources:
        source_items = _remote_data_list(raw)
        if isinstance(source_items, list):
            items.extend(source_items)
    if not items:
        payload = {"version": "remote", "generated_at": _now_str(), "schedules": [], "broadcasts": [], "livecasts": []}
        _debug_timing("fetch remote schedules summary", (time.perf_counter() - start) * 1000)
        return payload
    ignored_unnamed: List[dict] = []
    if _looks_like_task(items[0]):
        grouped: Dict[str, List[dict]] = {}
        status_by_name: Dict[str, str] = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            name = _schedule_name_from_remote(item, index)
            if not name:
                if _is_known_non_schedule_remote_task(item):
                    continue
                ignored_unnamed.append(
                    {
                        "index": index,
                        "task_id": _task_id(item),
                        "task_name": item.get("taskname") or item.get("name") or item.get("medianame"),
                        "raw_name": item.get("sechename") or item.get("schedule_name") or item.get("name"),
                    }
                )
                continue
            grouped[name] = _merge_tasks(grouped.get(name, []), [item])
            status_by_name[name] = _merge_schedule_status(status_by_name.get(name), _status_from_remote(item))
        schedules = []
        for name, tasks in grouped.items():
            schedules.append({
                "schedule_name": name,
                "status": status_by_name.get(name, "启用"),
                "tasks": [],
                "tasks_loaded": False,
                "task_count": len(tasks),
            })
        payload = _append_ignored_unnamed_schedule_info(
            {"version": "remote", "generated_at": _now_str(), "schedules": schedules, "broadcasts": [], "livecasts": []},
            ignored_unnamed,
        )
        _debug_timing("fetch remote schedules summary", (time.perf_counter() - start) * 1000)
        return payload
    schedules_map: Dict[str, dict] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = _schedule_name_from_remote(item, index)
        if not name:
            if _is_known_non_schedule_remote_task(item):
                continue
            ignored_unnamed.append(
                {
                    "index": index,
                    "task_id": _task_id(item),
                    "task_name": item.get("taskname") or item.get("name") or item.get("medianame"),
                    "raw_name": item.get("sechename") or item.get("schedule_name") or item.get("name"),
                }
            )
            continue
        status = _status_from_remote(item)
        task_count = item.get("taskcount")
        if task_count is None:
            task_count = item.get("count")
        if task_count is None:
            task_count = item.get("all")
        count_value = int(task_count) if str(task_count).isdigit() else task_count
        existing = schedules_map.get(name)
        if existing:
            existing["status"] = _merge_schedule_status(existing.get("status"), status)
            if isinstance(count_value, int):
                prior = existing.get("task_count")
                if not isinstance(prior, int) or count_value > prior:
                    existing["task_count"] = count_value
            continue
        schedules_map[name] = {
            "schedule_name": name,
            "status": status,
            "tasks": [],
            "tasks_loaded": False,
            "task_count": count_value,
        }
    payload = _append_ignored_unnamed_schedule_info({
        "version": "remote",
        "generated_at": _now_str(),
        "schedules": list(schedules_map.values()),
        "broadcasts": [],
        "livecasts": []
    }, ignored_unnamed)
    _debug_timing("fetch remote schedules summary", (time.perf_counter() - start) * 1000)
    return payload


def _fetch_remote_taskinfo_list(kind: str, task_type: str) -> list:
    media_lookup = {}
    terminal_lookup = {}
    try:
        media_lookup = _remote_media_lookup()
    except HTTPException:
        media_lookup = {}
    try:
        terminal_lookup = _remote_terminal_lookup()
    except HTTPException:
        terminal_lookup = {}
    path = _remote_taskinfo_path(task_type)
    raw_response = _remote_request("GET", path)
    items = _remote_data_list(raw_response)
    LOGGER.debug("远端原始返回: %s", raw_response)
    LOGGER.debug("第一条任务: %s", items[0] if items else 'empty')
    return _map_remote_taskinfo_items(items, media_lookup, terminal_lookup, kind)


def _load_remote_taskinfo(kind: str, task_type: str) -> list:
    cache_key = f"taskinfo:{kind}"
    cached = _cache_get(cache_key)
    if isinstance(cached, list):
        return cached
    try:
        items = _fetch_remote_taskinfo_list(kind, task_type)
    except HTTPException:
        items = []
    _cache_set(cache_key, items)
    return items
def _remote_taskinfo_path(task_type: object) -> str:
    task_id = str(task_type)
    if REMOTE_TASKINFO_TWO:
        if task_id == str(REMOTE_BROADCAST_TASK_TYPE):
            task_id = str(REMOTE_TASKINFO_TWO_BROADCAST_ID)
        elif task_id == str(REMOTE_LIVECAST_TASK_TYPE):
            task_id = str(REMOTE_TASKINFO_TWO_LIVECAST_ID)

        base = REMOTE_TASKINFO_TWO_PATH.rstrip("/")
        return f"{base}/{task_id}"
    return f"/task/taskinfotwo/{task_id}"


def _remote_schedule_names() -> List[str]:
    raw = _remote_request("GET", REMOTE_SCHEDULES_FALLBACK_PATH or "/task/sechinfo")
    items = _remote_data_list(raw)
    names: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("sechename") or item.get("schedule_name") or item.get("name")
        if name:
            names.append(str(name))
    return names


def _remote_schedule_catalog_snapshot() -> Tuple[set[str], Dict[str, str]]:
    raw = _remote_request("GET", REMOTE_SCHEDULES_FALLBACK_PATH or "/task/sechinfo")
    items = _remote_data_list(raw)
    names: set[str] = set()
    status_by_name: Dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("sechename") or item.get("schedule_name") or item.get("name")
        if not name:
            continue
        name_str = str(name)
        names.add(name_str)
        status_by_name[name_str] = _status_from_remote(item)
    return names, status_by_name


def _remote_ensure_schedule(schedule_name: str, *, catalog_names: Optional[Collection[str]] = None) -> None:
    if not schedule_name or not REMOTE_ALLOW_CREATE_SCHEDULE:
        return
    template = str(REMOTE_SCHEDULE_TEMPLATE or "").strip()
    known_names = _unique_list(
        [str(name).strip() for name in (catalog_names or []) if str(name).strip()]
    )
    if not template:
        names = known_names
        if not names:
            try:
                names = _remote_schedule_names()
            except HTTPException:
                names = []
        for name in names:
            if name != schedule_name:
                template = name
                break
        if not template and names:
            template = names[0]
    if not template:
        raise HTTPException(status_code=502, detail="Remote schedule template not found; set REMOTE_SCHEDULE_TEMPLATE.")
    payload = {"fromtaskname": template, "totaskname": schedule_name}
    try:
        _remote_request(
            "POST",
            "/task/sechinfo",
            json_body=payload,
            form_body=None,
            allow_form_retry=False,
        )
    except HTTPException as exc:
        if exc.status_code in {400, 404, 405, 409}:
            return
        raise

    if catalog_names is not None:
        return

    try:
        names = _remote_schedule_names()
    except HTTPException:
        names = []
    if schedule_name not in names:
        LOGGER.warning(
            "Remote schedule %s not found after immediate confirmation; will rely on task creation.",
            schedule_name,
        )


def _remote_delete_schedule_entry(schedule_name: str) -> None:
    if not schedule_name:
        return
    if not _remote_schedule_delete_supported():
        _add_schedule_tombstone(schedule_name)
        return
    payload = {"name": schedule_name}
    try:
        _remote_request(
            "DELETE",
            "/task/sechinfo",
            json_body=payload,
            form_body=None,
            allow_form_retry=False,
        )
        _update_remote_schedule_delete_capability(supported=True, checked=True)
        _add_schedule_tombstone(schedule_name)
        return
    except HTTPException as exc:
        if exc.status_code == 404:
            _update_remote_schedule_delete_capability(supported=True, checked=True)
            _add_schedule_tombstone(schedule_name)
            return
        if exc.status_code == 405:
            _update_remote_schedule_delete_capability(supported=False, checked=True)
            _add_schedule_tombstone(schedule_name)
            return
        raise


def _remote_rename_schedule_entry(source_name: str, target_name: str) -> None:
    if not source_name or not target_name or source_name == target_name:
        return
    payload = {"fromtaskname": source_name, "totaskname": target_name}
    _remote_request(
        "PUT",
        "/task/sechinfo",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )


def _remote_set_schedule_status(schedule_name: str, enabled: bool) -> None:
    payload = {"sechename": schedule_name, "state": 0 if enabled else 1}
    _remote_request(
        "POST",
        "/task/sechenableordisable",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )
def _remote_set_task_state(task_id: str, state: int) -> None:
    task_id_value = _numeric_task_id(task_id)
    if task_id_value <= 0:
        raise HTTPException(status_code=400, detail="Invalid task id for remote task state.")
    if state == 1:
        path = "/action/taskstart"
    elif state == 0:
        path = "/action/taskstop"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported task state value: {state}")
    from backend.routes.light import action_request as _light_action_request
    resp = _light_action_request("POST", path, form={"taskid": str(task_id_value)}, body_mode="urlencoded")
    if not resp.get("success"):
        raise HTTPException(status_code=502, detail=f"Remote task state change failed: {resp.get('message', '')}")


def _remote_find_task_id_by_name(task_name: str) -> Optional[Tuple[str, str, float]]:
    """Live fallback when local broadcast_schedules cache misses.

    Only the currently-activated schedule's tasks are visible via /action/gettaskinfo,
    which matches the business rule "play/stop named task" — users address tasks in
    the running schedule. Single HTTP call keeps latency bounded (one LIGHT_REMOTE_TIMEOUT).

    Returns (task_id, matched_task_name, score) where score is:
      - 1.0   for exact / normalized matches (always safe to execute)
      - 0.7-0.95 for fuzzy match (caller should require confirmation, NOT auto-execute)
      - ≥ 0.95 for high-confidence fuzzy match (treated as exact-equivalent)
    Returns None when there is no acceptable candidate.

    Filters out disabled (enable=0) tasks so we never start a deactivated entry.
    """
    name_text = str(task_name or "").strip()
    if not name_text or not _remote_enabled():
        return None
    from backend.routes.light import action_request as _light_action_request

    try:
        resp = _light_action_request("POST", "/action/gettaskinfo", body_mode="none")
    except Exception as exc:
        LOGGER.warning("remote task fallback: gettaskinfo raised %s", exc)
        return None
    if resp.get("success") is False:
        LOGGER.warning(
            "remote task fallback: gettaskinfo returned success=False (msg=%s, raw=%s)",
            resp.get("message"), str(resp.get("raw") or "")[:200],
        )
        return None

    data = resp.get("data")
    rows: List[dict] = []
    if isinstance(data, dict):
        for key in ("rows", "item", "items", "list"):
            value = data.get(key)
            if isinstance(value, list):
                rows = [row for row in value if isinstance(row, dict)]
                break
    elif isinstance(data, list):
        rows = [row for row in data if isinstance(row, dict)]

    candidates: List[Tuple[str, str]] = []
    for task in rows:
        # R2: skip tasks that are disabled on the device
        enable = str(task.get("enable") or "1").strip()
        if enable == "0":
            continue
        tid = str(task.get("id") or task.get("taskid") or task.get("task_id") or "").strip()
        tname = str(task.get("taskname") or task.get("name") or task.get("title") or "").strip()
        if tid and tname:
            candidates.append((tid, tname))

    if not candidates:
        LOGGER.warning(
            "remote task fallback: no enabled candidates in active schedule (raw=%s)",
            str(resp.get("raw") or "")[:200],
        )
        return None

    # 1. exact
    for tid, tname in candidates:
        if tname == name_text:
            return (tid, tname, 1.0)
    # 2. normalized (whitespace/punctuation-insensitive)
    compact_query = _compact_text(name_text)
    if compact_query:
        for tid, tname in candidates:
            if _compact_text(tname) == compact_query:
                return (tid, tname, 1.0)

    # 3. strip 口语噪声词 (任务/广播/播放/执行 等) 后重新尝试 exact + substring
    # 例：用户说"起床铃声任务"，实际任务名"起床铃声"，应直接命中
    stripped = _strip_task_noise(name_text)
    if stripped and stripped != name_text:
        for tid, tname in candidates:
            if tname == stripped:
                return (tid, tname, 1.0)
        compact_stripped = _compact_text(stripped)
        if compact_stripped:
            for tid, tname in candidates:
                if _compact_text(tname) == compact_stripped:
                    return (tid, tname, 1.0)

    # 4. substring 关系（任一方向）— 用 strip 后版本，避免噪声词干扰
    sub_query = stripped or name_text
    if sub_query:
        for tid, tname in candidates:
            if not tname:
                continue
            if sub_query in tname or tname in sub_query:
                return (tid, tname, 1.0)

    # 5. fuzzy（用 strip 后的版本算 ratio，更准）
    fuzzy_query = stripped or name_text
    best_score = 0.0
    best: Optional[Tuple[str, str, float]] = None
    for tid, tname in candidates:
        score = difflib.SequenceMatcher(None, fuzzy_query, tname).ratio()
        if score >= 0.7 and score > best_score:
            best_score = score
            best = (tid, tname, score)
    return best


_TASK_NOISE_SUFFIXES = ("铃声广播", "广播任务", "任务", "广播")
_TASK_NOISE_PREFIXES = ("马上", "立刻", "现在", "请", "帮我", "把", "播放", "执行", "启动", "停止", "结束", "关闭", "暂停", "中止")


def _strip_task_noise(text: str) -> str:
    """剥掉用户口语里的"任务/广播/播放"等噪声词，使模糊匹配更稳。

    例：「播放起床铃声任务」→ 「起床铃声」
        「停止午休任务」    →  「午休」
    剥掉后跟远端实际 taskname 做 exact / substring 匹配概率大幅提升。
    """
    s = str(text or "").strip()
    if not s:
        return s
    # 反复剥后缀
    changed = True
    while changed and s:
        changed = False
        for suffix in _TASK_NOISE_SUFFIXES:
            if s.endswith(suffix) and len(s) > len(suffix):
                s = s[: -len(suffix)].strip()
                changed = True
                break
    # 反复剥前缀
    changed = True
    while changed and s:
        changed = False
        for prefix in _TASK_NOISE_PREFIXES:
            if s.startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix):].strip()
                changed = True
                break
    return s


def _remote_add_temp_task(
    media_ids: List[str],
    terminal_ids: List[str],
    volume: int,
    playtype: int,
    playlength: int,
    playpriority: int = 10,
) -> Optional[str]:
    clean_media_ids = [str(item).strip() for item in media_ids if str(item).strip() and str(item).strip() != "0"]
    clean_terminal_ids = [str(item).strip() for item in terminal_ids if str(item).strip() and str(item).strip() != "0"]
    if not clean_media_ids:
        raise HTTPException(status_code=400, detail="Missing media id for remote temp task.")
    if not clean_terminal_ids:
        raise HTTPException(status_code=400, detail="Missing terminal id for remote temp task.")

    volume_value = max(0, min(100, _coerce_int(volume, 50)))
    playtype_value = 2 if _coerce_int(playtype, 2) == 2 else 1
    playlength_value = max(1, _coerce_int(playlength, 1))
    playpriority_value = max(10, min(109, _coerce_int(playpriority, 10)))
    params = {
        "volume": volume_value,
        "playtype": playtype_value,
        "playlength": playlength_value,
        "playpriority": playpriority_value,
        "mediacount": len(clean_media_ids),
        "mediaids": ",".join(clean_media_ids),
        "terminalcount": len(clean_terminal_ids),
        "terminalids": ",".join(clean_terminal_ids),
    }
    resp = _remote_request("POST", "/task/addtemptask", params=params, allow_retry=False)
    return _remote_extract_taskid(resp)


def _remote_stop_temp_tasks(task_ids: List[str]) -> List[str]:
    normalized_ids = [str(item).strip() for item in task_ids if str(item).strip()]
    if not normalized_ids:
        raise HTTPException(status_code=400, detail="Missing task id for remote temp task stop.")
    payload = {"id": ",".join(normalized_ids)}
    resp = _remote_request(
        "POST",
        "/task/stoptemptask",
        json_body=payload,
        form_body=None,
        allow_retry=False,
        allow_form_retry=False,
    )
    _ensure_remote_write_ack(resp, "stop temp task")
    return normalized_ids


def _remote_set_task_volume(task_id: str, volume: int) -> None:
    task_id_value = _numeric_task_id(task_id)
    if task_id_value <= 0:
        raise HTTPException(status_code=400, detail="Invalid task id for remote task volume.")
    volume_value = _coerce_int(volume, 0)
    volume_value = max(0, min(100, volume_value))
    payload = {"id": str(task_id_value), "state": volume_value}
    resp = _remote_request(
        "POST",
        "/task/taskvolume",
        json_body=payload,
        form_body=None,
        allow_retry=False,
        allow_form_retry=False,
    )
    _ensure_remote_write_ack(resp, "task volume change")


def _remote_set_terminal_volume(terminal_id: str, volume: int) -> None:
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    terminal_id_str = str(terminal_id).strip()
    if not terminal_id_str:
        raise HTTPException(status_code=400, detail="Invalid terminal id for remote setvolume.")
    volume_value = _coerce_int(volume, 0)
    volume_value = max(0, min(100, volume_value))
    payload = {
        "DEVICE_ID": terminal_id_str,
        "DEVICE_IP": "",
        "VOLUME": str(volume_value),
    }
    resp = _remote_request(
        "POST",
        "/setvolume",
        json_body=payload,
        form_body=None,
        allow_retry=False,
        allow_form_retry=False,
    )
    _ensure_remote_write_ack(resp, "terminal volume change")




def _sync_livecasts_independent(desired_tasks: list, *, raise_on_failure: bool) -> Optional[str]:
    if not _remote_enabled():
        return None
    try:
        _sync_remote_taskinfo("livecast", REMOTE_LIVECAST_TASK_TYPE, desired_tasks)
        return None
    except HTTPException as exc:
        detail = str(exc.detail)
        LOGGER.warning("independent livecast sync failed | detail=%s", detail)
        if raise_on_failure:
            raise
        return detail
    except Exception as exc:
        detail = str(exc)
        LOGGER.warning("independent livecast sync failed | detail=%s", detail)
        if raise_on_failure:
            raise HTTPException(status_code=500, detail=f"Livecast sync failed: {detail}") from exc
        return detail


def _save_schedules_payload(
    payload: dict,
    sync_schedules: bool = True,
    sync_broadcasts: bool = True,
    sync_livecasts: bool = True,
    update_all_task: bool = True,
    target_schedule_names: Optional[List[str]] = None,
    schedule_sync_delta: Optional[dict] = None,
) -> None:
    payload = _normalize_schedules_payload(payload)
    schedule_names_in_payload = _available_schedule_names(payload)
    _clear_schedule_tombstones_for_names(schedule_names_in_payload)
    _inherit_schedule_task_terminal_bindings(payload.get("schedules"))
    _normalize_schedule_task_terminals(payload.get("schedules"))
    changed_or_added_names = _unique_list(list((schedule_sync_delta or {}).get("changed_or_added_names") or []))
    removed_names = _unique_list(list((schedule_sync_delta or {}).get("removed_names") or []))
    renamed = list((schedule_sync_delta or {}).get("renamed") or [])
    validation_schedule_names: Optional[List[str]] = None
    if schedule_sync_delta is not None:
        validation_schedule_names = changed_or_added_names
    elif target_schedule_names:
        validation_schedule_names = _unique_list(
            [str(name).strip() for name in (target_schedule_names or []) if str(name).strip()]
        )
    def persist_payload(use_cache_json: bool) -> None:
        _store_set("broadcast_schedules", payload)
        if use_cache_json:
            _write_cache_json(SCHEDULES_PATH, payload)
        else:
            _write_json(SCHEDULES_PATH, payload)
        _write_engine_schedules(payload)
        if update_all_task:
            all_task_payload = _build_all_task_payload(payload)
            _store_set("all_task", all_task_payload)
            if use_cache_json:
                _write_cache_json(ALL_TASK_PATH, all_task_payload)
            else:
                _write_json(ALL_TASK_PATH, all_task_payload)
            _write_engine_all_task(all_task_payload)

    if _remote_enabled():
        if sync_schedules:
            try:
                _validate_schedule_task_terminal_bindings(
                    payload.get("schedules"),
                    schedule_names=validation_schedule_names,
                )
            except TypeError as exc:
                if "unexpected keyword argument 'schedule_names'" not in str(exc):
                    raise
                _validate_schedule_task_terminal_bindings(payload.get("schedules"))
        if sync_schedules:
            if schedule_sync_delta is not None:
                failed_renames = _sync_remote_schedule_renames(renamed) if renamed else []
                if failed_renames:
                    removed_names = _unique_list([*removed_names, *failed_renames])
                LOGGER.info(
                    "schedule sync delta | changed_or_added=%s removed=%s renamed=%s",
                    changed_or_added_names,
                    removed_names,
                    renamed,
                )
                if changed_or_added_names:
                    _sync_remote_schedules_targeted(payload, changed_or_added_names)
                if removed_names:
                    _sync_remote_schedules_removed(removed_names)
            elif target_schedule_names:
                _sync_remote_schedules_targeted(payload, target_schedule_names)
            else:
                _sync_remote_schedules(payload)
        if sync_broadcasts:
            _sync_remote_taskinfo("broadcast", REMOTE_BROADCAST_TASK_TYPE, payload.get("broadcasts") or [])
        livecast_only_sync = sync_livecasts and not (sync_schedules or sync_broadcasts)
        if livecast_only_sync:
            _sync_livecasts_independent(payload.get("livecasts") or [], raise_on_failure=True)
        persist_payload(use_cache_json=True)
        if sync_livecasts and not livecast_only_sync:
            _sync_livecasts_independent(payload.get("livecasts") or [], raise_on_failure=False)
    else:
        persist_payload(use_cache_json=False)
    _reload_engine_assets()


def _reload_engine_schedules() -> None:
    ENGINE.schedule_map = {}
    ENGINE.schedule_names = []
    payload = _store_get("broadcast_schedules")
    if not isinstance(payload, dict):
        cfg = ENGINE.cfg
        if not cfg.schedule_path.exists():
            return
        try:
            payload = json.loads(cfg.schedule_path.read_text(encoding="utf-8"))
        except Exception:
            ENGINE.schedule_map = {}
            return
    ENGINE.schedule_map = _clone_payload(payload)
    schedules = ENGINE.schedule_map.get("schedules", [])
    if isinstance(schedules, list):
        for item in schedules:
            if isinstance(item, dict):
                name = str(item.get("schedule_name", "")).strip()
                if name:
                    ENGINE.schedule_names.append(name)


def _reload_engine_assets() -> None:
    LOGGER.info("【AI热重载】正在同步路径并重新加载资源...")
    
    # 强制转换 Path 对象为字符串,防止某些库不支持 Path 对象
    # ALL_AUDIO_PATH, ALL_LOC_PATH, ALL_TASK_PATH 是你在 main.py 开头定义的那个正确的路径
    media_path = str(ALL_AUDIO_PATH)
    loc_path = str(ALL_LOC_PATH)
    task_path = str(ALL_TASK_PATH)
    
    # 打印出来确认一下,这就是你要的 "backend/data/..."
    LOGGER.debug("AI 正在读取: %s", task_path)

    # 使用 API 定义的路径传给 AI 引擎
    ENGINE.media_index, ENGINE.loc_index, ENGINE.task_index, ENGINE.zone_index = load_adaptation_assets(
        media_path,  # 音频路径
        loc_path,    # 终端/区域路径
        task_path,   # 任务路径 (最关键的！)
        loc_path     # 区域路径 (通常和终端是同一个文件)
    )
    
    # 打印一下结果验证
    count = len(ENGINE.task_index) if ENGINE.task_index else 0
    LOGGER.info(f"【AI热重载】完成！当前加载任务数: {count}")

    _reload_engine_schedules()


def _normalize_schedules_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Invalid schedules payload")
    schedules = payload.get("schedules")
    if not isinstance(schedules, list):
        payload["schedules"] = []
    if not isinstance(payload.get("broadcasts"), list):
        payload["broadcasts"] = []
    if not isinstance(payload.get("livecasts"), list):
        payload["livecasts"] = []
    if not isinstance(payload.get("directories"), list):
        payload["directories"] = []
    return payload


def _task_to_all_task_row(
    task: dict,
    schedule_name: str,
    terminal_map: Optional[dict] = None,
    terminal_lookup: Optional[dict] = None,
) -> dict:
    if not isinstance(task, dict):
        return {}
    starttime = _format_hhmmss(task.get("starttime") or task.get("time") or "")
    terminal_ids = _get_task_terminal_ids(task, terminal_map=terminal_map)
    terminal_names = _normalize_str_list(task.get("terminalnames"))
    if not terminal_names and task.get("liveterminalname"):
        terminal_names = [str(task.get("liveterminalname"))]
    fallback_terminal = task.get("liveterminalid") or task.get("terminalid")
    media_id = task.get("mediaid")
    if terminal_ids:
        liveterminalid = _coerce_int(terminal_ids[0], 0)
    else:
        liveterminalid = _coerce_int(fallback_terminal, 0)
    if terminal_ids and isinstance(terminal_lookup, dict):
        resolved_terminal_names: List[str] = []
        for terminal_id in terminal_ids:
            lookup = terminal_lookup.get(str(terminal_id))
            if isinstance(lookup, dict) and lookup.get("name"):
                resolved_terminal_names.append(str(lookup.get("name")))
        resolved_terminal_names = _unique_list([value for value in resolved_terminal_names if value])
        if resolved_terminal_names and not terminal_names:
            terminal_names = resolved_terminal_names
    payload = {
        "taskid": str(task.get("taskid") or task.get("id") or ""),
        "prepower": _coerce_int(task.get("prepower"), 0),
        "level": _coerce_int(task.get("level"), 0),
        "volume": _coerce_int(task.get("volume"), 50),
        "priority": _coerce_int(task.get("priority"), 0),
        "datasendmodel": _coerce_int(task.get("datasendmodel") or task.get("datasendmode"), 0),
        "startdate": str(task.get("startdate") or "0-00-00"),
        "enddate": str(task.get("enddate") or "0-00-00"),
        "execmode": _coerce_int(task.get("execmode"), 0),
        "tasktype": _coerce_int(task.get("tasktype"), 1),
        "taskname": str(task.get("taskname") or task.get("customName") or task.get("audio") or ""),
        "starttime": starttime,
        "timelength": str(task.get("timelength") or task.get("length") or "1"),
        "timelengthtype": str(task.get("timelengthtype") or task.get("lengthtype") or "1"),
        "israndomplay": _coerce_int(task.get("israndomplay"), 0),
        "medianame": str(_clean_media_name(task.get("medianame") or task.get("audio") or "")),
        "sechename": str(schedule_name or ""),
        "cmd": _coerce_int(task.get("cmd"), 0),
        "cmdargs": str(task.get("cmdargs") or ""),
        "bandrate": _coerce_int(task.get("bandrate"), 0),
        "liveterminalid": liveterminalid,
        "liveterminalname": str(task.get("liveterminalname") or ""),
        "samplerate": _coerce_int(task.get("samplerate"), 0),
        "caiboprepower": _coerce_int(task.get("caiboprepower"), 0),
        "taskstate": task.get("taskstate"),
        "state": task.get("state"),
        "enablestate": _coerce_int(task.get("enablestate"), 1),
    }
    if media_id not in (None, "", 0, "0"):
        payload["mediaid"] = str(media_id)
    if terminal_ids:
        payload["terminalids"] = terminal_ids
    if terminal_names:
        payload["terminalnames"] = terminal_names
    if isinstance(task.get("location"), list):
        payload["location"] = _clone_payload(task.get("location"))
    elif terminal_ids and isinstance(terminal_lookup, dict):
        locations = _location_paths_from_terminals(terminal_ids, terminal_lookup)
        if locations:
            payload["location"] = locations
    return payload

def _row_to_all_task_row(row: dict, task_type: int) -> dict:
    if not isinstance(row, dict):
        return {}
    
    # 1. 状态处理 (保持不变)
    state_value = row.get("taskstate")
    if state_value is None:
        state_value = row.get("state")
    if state_value is None and row.get("status"):
        state_value = _task_state_from_label(row.get("status"))
    state_value = None if state_value is None else _coerce_int(state_value, _task_state_from_label(row.get("status") or ""))

    # 👇👇👇【核心修复:时长/循环参数保卫战】👇👇👇
    # 先尝试获取原始值 (防止被误杀)
    timelength = row.get("timelength")
    timelengthtype = row.get("timelengthtype")

    # 如果有前端的 View 字段,则以 View 字段为准进行覆盖
    duration_mode = row.get("durationMode")
    if duration_mode:
        if duration_mode == "loop":
            timelength = row.get("loop") or 1
            timelengthtype = "2" # 类型2 = 次数
        else:
            timelength = _coerce_duration_int(row.get("duration"), 1)
            timelengthtype = "1" # 类型1 = 时长
    
    # 兜底:如果啥都没有,才给默认值
    if timelength is None: timelength = 1
    if timelengthtype is None: timelengthtype = 1
    # 👆👆👆 =========================================

    # 3. 媒体名处理 (保持不变)
    medianame = _join_media_names(row.get("medianames")) or row.get("medianame") or row.get("audio") or ""
    medianame = _clean_media_name(medianame)
    if str(medianame).strip().lower() == "string":
        medianame = ""
    if not medianame:
        candidate = row.get("audio") or row.get("name") or row.get("taskname")
        if candidate:
            medianame = str(candidate)
        else:
            media_id = row.get("mediaid")
            if media_id is not None:
                lookup = _store_media_lookup()
                resolved = lookup.get(str(media_id))
                if resolved:
                    medianame = str(resolved)
    
    # 4. 终端ID处理 (保留刚才修好的逻辑)
    terminal_id = _coerce_int(row.get("liveterminalid") or row.get("terminalid"), 0)
    terminal_name = str(row.get("liveterminalname") or row.get("terminalname") or "")
    terminal_ids: List[str] = []
    terminal_names: List[str] = []
    value_list = row.get("terminalids") or row.get("terminal_ids") or row.get("liveterminalids")
    if isinstance(value_list, list):
        terminal_ids.extend(value_list)
    if terminal_id:
        terminal_ids.append(str(terminal_id))
    terminal_ids = _unique_list([str(value) for value in terminal_ids if value not in (None, "")])
    name_list = row.get("terminalnames") or row.get("terminal_names") or row.get("liveterminalnames")
    if isinstance(name_list, list):
        terminal_names.extend(name_list)
    if terminal_name:
        terminal_names.append(terminal_name)
    terminal_names = _unique_list([str(value) for value in terminal_names if value not in (None, "")])

    payload = {
        "taskid": str(row.get("id") or ""),
        "prepower": 0,
        "level": 0,
        "volume": _coerce_int(row.get("volume"), 50),
        "priority": 0,
        "datasendmodel": 0,
        "startdate": "0-00-00",
        "enddate": "0-00-00",
        "execmode": 0,
        "tasktype": _coerce_int(task_type, 1),
        "taskname": str(row.get("name") or row.get("audio") or ""),
        "starttime": _format_hhmmss(row.get("time") or row.get("starttime") or ""),
        "timelength": str(timelength),          # ✅ 使用修复后的值
        "timelengthtype": str(timelengthtype),  # ✅ 使用修复后的值
        "israndomplay": 0,
        "medianame": str(medianame or ""),
        "sechename": "",
        "cmd": 0,
        "cmdargs": "",
        "bandrate": 0,
        "liveterminalid": terminal_id,
        "liveterminalname": terminal_name,
        "samplerate": 0,
        "caiboprepower": 0,
        "taskstate": state_value,
        "state": state_value,
        "enablestate": state_value if state_value is not None else 1,
    }
    if terminal_ids:
        payload["terminalids"] = terminal_ids
    if terminal_names:
        payload["terminalnames"] = terminal_names
    if isinstance(row.get("location"), list):
        payload["location"] = row.get("location")
    return payload
def _build_all_task_payload(payload: dict) -> dict:
    rows: List[dict] = []
    terminal_items = _store_terminalinfo_items()
    terminal_map = _terminal_map_from_items(terminal_items)
    terminal_lookup = _terminal_lookup_from_items(terminal_items)
    if _remote_enabled():
        try:
            zone_items = _fetch_enriched_zone_items()
            _enrich_lookup_zones_from_terzone(terminal_lookup, zone_items)
        except Exception:
            pass
    schedules = payload.get("schedules") if isinstance(payload, dict) else []
    if isinstance(schedules, list):
        for schedule in schedules:
            if not isinstance(schedule, dict):
                continue
            schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or "").strip()
            tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
            for task in tasks:
                mapped = _task_to_all_task_row(
                    task,
                    schedule_name,
                    terminal_map=terminal_map,
                    terminal_lookup=terminal_lookup,
                )
                if mapped:
                    rows.append(mapped)
    broadcasts = payload.get("broadcasts") if isinstance(payload, dict) else []
    if isinstance(broadcasts, list):
        for row in broadcasts:
            mapped = _row_to_all_task_row(row, _coerce_int(REMOTE_BROADCAST_TASK_TYPE, 2))
            if mapped:
                rows.append(mapped)
    livecasts = payload.get("livecasts") if isinstance(payload, dict) else []
    if isinstance(livecasts, list):
        for row in livecasts:
            mapped = _row_to_all_task_row(row, _coerce_int(REMOTE_LIVECAST_TASK_TYPE, 3))
            if mapped:
                rows.append(mapped)
    return {"data": rows}


def _engine_all_task_path() -> Optional[Path]:
    cfg = getattr(ENGINE, "cfg", None)
    path = getattr(cfg, "all_task_path", None)
    if not isinstance(path, Path):
        return None
    if path.suffix:
        return path
    return path.with_suffix(".json")


def _engine_asset_path(path: Optional[Path]) -> Optional[Path]:
    if not isinstance(path, Path):
        return None
    if path.suffix:
        return path
    return path.with_suffix(".json")


def _write_engine_asset(path: Optional[Path], payload: object) -> None:
    resolved = _engine_asset_path(path)
    if not resolved:
        return
    if resolved in {ALL_AUDIO_PATH, ALL_LOC_PATH, ALL_TASK_PATH, SCHEDULES_PATH}:
        return
    _write_cache_json(resolved, payload)


def _write_engine_all_audio(payload: object) -> None:
    cfg = getattr(ENGINE, "cfg", None)
    path = getattr(cfg, "all_media_path", None)
    _write_engine_asset(path, payload)


def _write_engine_all_loc(payload: object) -> None:
    cfg = getattr(ENGINE, "cfg", None)
    path = getattr(cfg, "all_zone_path", None)
    _write_engine_asset(path, payload)


def _write_engine_all_task(payload: object) -> None:
    path = _engine_all_task_path()
    if not path or path == ALL_TASK_PATH:
        return
    _write_cache_json(path, payload)


def _write_engine_schedules(payload: object) -> None:
    cfg = getattr(ENGINE, "cfg", None)
    path = getattr(cfg, "schedule_path", None)
    _write_engine_asset(path, payload)


def _ensure_all_task_payload() -> None:
    payload = _store_get("all_task")
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return
    schedules_payload = _store_get("broadcast_schedules")
    if not isinstance(schedules_payload, dict):
        return
    all_task_payload = _build_all_task_payload(schedules_payload)
    _store_set("all_task", all_task_payload)
    _write_cache_json(ALL_TASK_PATH, all_task_payload)
    _write_engine_all_task(all_task_payload)


def _normalize_overrides_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {"overrides": []}
    if not isinstance(payload.get("overrides"), list):
        payload["overrides"] = []
    normalized_overrides: List[dict] = []
    for item in payload.get("overrides") or []:
        if not isinstance(item, dict):
            continue
        entry = _clone_payload(item) or {}
        for key in (
            "task_ids",
            "source_task_ids",
            "target_task_ids",
            "shadow_task_ids",
            "once_task_ids",
            "once_task_specs",
            "commands",
            "enable_once_commands",
            "cleanup_attempts",
            "cleaned_task_ids",
            "shadow_failures",
            "once_task_failures",
            "rollback_attempts",
            "remote_diagnostics",
        ):
            if not isinstance(entry.get(key), list):
                entry[key] = []
        if entry.get("cleanup_state") in (None, ""):
            entry["cleanup_state"] = "pending" if str(entry.get("mode") or "") == "once" else ""
        if entry.get("cleaned_at") in (None,):
            entry["cleaned_at"] = ""
        normalized_overrides.append(entry)
    payload["overrides"] = normalized_overrides
    return payload


def _normalize_assistant_command_logs_payload(payload: object) -> dict:
    items: list = []
    if isinstance(payload, dict):
        raw_items = payload.get("items")
        if isinstance(raw_items, list):
            items = raw_items
    elif isinstance(payload, list):
        items = payload

    normalized_items: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized_items.append(
            {
                "text": str(item.get("text") or ""),
                "reply": str(item.get("reply") or ""),
            }
        )
    if len(normalized_items) > ASSISTANT_COMMAND_LOG_LIMIT:
        normalized_items = normalized_items[-ASSISTANT_COMMAND_LOG_LIMIT:]
    return {"items": normalized_items}


def _normalize_assistant_settings_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    default_schedule_kind = str(payload.get("default_schedule_kind") or "").strip()
    if default_schedule_kind not in ALLOWED_SCHEDULE_KINDS:
        default_schedule_kind = ""
    default_schedule_season = str(payload.get("default_schedule_season") or "").strip()
    if default_schedule_season not in ALLOWED_SCHEDULE_SEASONS:
        default_schedule_season = ""
    return {
        "default_schedule_kind": default_schedule_kind,
        "default_schedule_season": default_schedule_season,
    }


def _default_schedules_payload() -> dict:
    return {
        "version": "runtime",
        "generated_at": _now_str(),
        "schedules": [],
        "broadcasts": [],
        "livecasts": [],
        "directories": [],
    }


def _default_assistant_settings_payload() -> dict:
    return {
        "default_schedule_kind": "",
        "default_schedule_season": "",
    }


def _normalize_remote_base_url(value: object) -> str:
    return _remote_runtime.normalize_remote_base_url(value)


def _normalize_remote_settings_payload(payload: object) -> dict:
    return _remote_runtime.normalize_remote_settings_payload(payload)


def _normalize_remote_sync_meta_payload(payload: object) -> dict:
    raw_payload = payload if isinstance(payload, dict) else {}
    raw_tombstones = (
        raw_payload.get("schedule_tombstones")
        if isinstance(raw_payload.get("schedule_tombstones"), list)
        else raw_payload.get("tombstones")
    )
    tombstones: List[str] = []
    if isinstance(raw_tombstones, list):
        for item in raw_tombstones:
            name = str(item or "").strip()
            if name and name not in tombstones:
                tombstones.append(name)
    schedule_delete_supported = raw_payload.get("schedule_delete_supported")
    if schedule_delete_supported is None:
        schedule_delete_supported = True
    schedule_delete_checked = raw_payload.get("schedule_delete_checked")
    if schedule_delete_checked is None:
        schedule_delete_checked = False
    return {
        "schedule_delete_supported": bool(schedule_delete_supported),
        "schedule_delete_checked": bool(schedule_delete_checked),
        "schedule_tombstones": tombstones,
    }


def _load_remote_sync_meta_payload() -> dict:
    payload = _store_get("remote_sync_meta")
    normalized = _normalize_remote_sync_meta_payload(payload)
    if payload != normalized:
        _store_set("remote_sync_meta", normalized)
    return normalized


def _save_remote_sync_meta_payload(payload: object) -> dict:
    normalized = _normalize_remote_sync_meta_payload(payload)
    _store_set("remote_sync_meta", normalized)
    _write_cache_json(REMOTE_SYNC_META_PATH, normalized)
    return normalized


def _schedule_tombstones() -> List[str]:
    payload = _load_remote_sync_meta_payload()
    return list(payload.get("schedule_tombstones") or [])


def _is_schedule_tombstoned(schedule_name: object) -> bool:
    name = str(schedule_name or "").strip()
    if not name:
        return False
    return name in set(_schedule_tombstones())


def _add_schedule_tombstone(schedule_name: object) -> None:
    name = str(schedule_name or "").strip()
    if not name:
        return
    payload = _load_remote_sync_meta_payload()
    tombstones = list(payload.get("schedule_tombstones") or [])
    if name in tombstones:
        return
    tombstones.append(name)
    payload["schedule_tombstones"] = _unique_list(tombstones)
    _save_remote_sync_meta_payload(payload)


def _clear_schedule_tombstone(schedule_name: object) -> None:
    name = str(schedule_name or "").strip()
    if not name:
        return
    payload = _load_remote_sync_meta_payload()
    tombstones = [item for item in (payload.get("schedule_tombstones") or []) if str(item) != name]
    if list(payload.get("schedule_tombstones") or []) == tombstones:
        return
    payload["schedule_tombstones"] = tombstones
    _save_remote_sync_meta_payload(payload)


def _clear_schedule_tombstones_for_names(schedule_names: List[str]) -> None:
    normalized_names = {
        str(name or "").strip()
        for name in (schedule_names or [])
        if str(name or "").strip()
    }
    if not normalized_names:
        return
    payload = _load_remote_sync_meta_payload()
    tombstones = [item for item in (payload.get("schedule_tombstones") or []) if str(item) not in normalized_names]
    if list(payload.get("schedule_tombstones") or []) == tombstones:
        return
    payload["schedule_tombstones"] = tombstones
    _save_remote_sync_meta_payload(payload)


def _update_remote_schedule_delete_capability(*, supported: bool, checked: bool = True) -> dict:
    payload = _load_remote_sync_meta_payload()
    payload["schedule_delete_supported"] = bool(supported)
    payload["schedule_delete_checked"] = bool(checked)
    return _save_remote_sync_meta_payload(payload)


def _normalize_calendar_holidays_payload(payload: object) -> dict:
    raw_years: dict = {}
    if isinstance(payload, dict):
        if isinstance(payload.get("years"), dict):
            raw_years = payload.get("years") or {}
        else:
            raw_years = payload

    years: Dict[str, dict] = {}
    for year_key, year_payload in raw_years.items():
        year_text = str(year_key or "").strip()
        if not re.fullmatch(r"\d{4}", year_text):
            continue
        days_payload = year_payload.get("days") if isinstance(year_payload, dict) else year_payload
        if not isinstance(days_payload, dict):
            years[year_text] = {"days": {}}
            continue

        normalized_days: Dict[str, dict] = {}
        for day_key, item in days_payload.items():
            date_key = _normalize_date_for_compare(day_key)
            if not re.fullmatch(rf"{year_text}-\d{{2}}-\d{{2}}", date_key):
                continue

            name = ""
            entry_type = "holiday"
            is_workday = False
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                entry_type = str(item.get("type") or "holiday").strip() or "holiday"
                is_workday = bool(item.get("isWorkday"))
            elif isinstance(item, str):
                name = item.strip()

            if entry_type not in {"holiday", "makeup_workday"}:
                entry_type = "holiday"
            if entry_type == "makeup_workday":
                is_workday = True

            normalized_days[date_key] = {
                "name": name or date_key,
                "type": entry_type,
                "isWorkday": is_workday,
            }

        years[year_text] = {"days": normalized_days}

    return {"years": years}


def _build_schedules_summary_payload(payload: dict) -> dict:
    schedules = payload.get("schedules")
    if not isinstance(schedules, list):
        schedules = []
    summary = []
    for index, schedule in enumerate(schedules):
        if not isinstance(schedule, dict):
            continue
        name = str(schedule.get("schedule_name") or schedule.get("name") or "").strip()
        if not name:
            continue
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        summary.append({
            "schedule_name": name,
            "status": schedule.get("status") or "启用",
            "tasks": [],
            "tasks_loaded": False,
            "task_count": len(tasks),
        })
    response = {
        "version": payload.get("version") or "1.0",
        "generated_at": payload.get("generated_at") or _now_str(),
        "schedules": summary,
        "broadcasts": [],
        "livecasts": [],
    }
    if payload.get("ignored_unnamed_schedules"):
        response["ignored_unnamed_schedules"] = _coerce_int(payload.get("ignored_unnamed_schedules"), 0)
        response["ignored_unnamed_schedule_samples"] = [
            item for item in (payload.get("ignored_unnamed_schedule_samples") or []) if isinstance(item, dict)
        ][:5]
    return response


def _sync_remote_data(force: bool = False, keys: Optional[List[str]] = None) -> Dict[str, bool]:
    if not _remote_enabled():
        return {}
    targets = {
        "all_audio": {
            "fetcher": _fetch_remote_all_audio,
            "path": ALL_AUDIO_PATH,
            "normalize": None,
            "force": True,
        },
        "all_loc": {
            "fetcher": _fetch_remote_all_loc,
            "path": ALL_LOC_PATH,
            "normalize": None,
            "force": True,
        },
        "broadcast_schedules": {
            "fetcher": _fetch_remote_schedule_payload,
            "path": SCHEDULES_PATH,
            "normalize": _normalize_schedules_payload,
            "force": True,
        },
    }
    if keys is None:
        keys = list(targets.keys())
    results: Dict[str, bool] = {}
    for key in keys:
        target = targets.get(key)
        if not target:
            continue
        fetcher = target["fetcher"]
        try:
            if force and target["force"]:
                if key == "broadcast_schedules":
                    payload = fetcher(
                        force=True,
                        reuse_prefetched_media=True,
                        reuse_prefetched_terminal=True,
                    )
                else:
                    payload = fetcher(force=True)
            else:
                payload = fetcher()
        except HTTPException as exc:
            LOGGER.warning("Remote sync failed for %s: %s", key, exc)
            results[key] = False
            continue
        if not isinstance(payload, (dict, list)):
            LOGGER.warning("Remote sync returned invalid payload for %s", key)
            results[key] = False
            continue
        normalize = target.get("normalize")
        if normalize:
            payload = normalize(payload)
        _store_set(key, payload)
        path = target.get("path")
        if isinstance(path, Path):
            _write_cache_json(path, payload)
        if key == "broadcast_schedules":
            if isinstance(payload, dict):
                all_task_payload = _build_all_task_payload(payload)
                _store_set("all_task", all_task_payload)
                _write_cache_json(ALL_TASK_PATH, all_task_payload)
                _write_engine_all_task(all_task_payload)
                _write_engine_schedules(payload)
            _reload_engine_schedules()
        if key == "all_audio":
            _write_engine_all_audio(payload)
        if key == "all_loc":
            _write_engine_all_loc(payload)
            REMOTE_CACHE.pop("terminal_map", None)
            REMOTE_CACHE.pop("terminal_lookup", None)
            TTL_CACHE.pop("terminalinfo_payload", None)
            TTL_CACHE.pop("enriched_terzone_items", None)
        results[key] = True
    return results


def _init_data_store() -> None:
    _store_load_from_file("all_audio")
    _store_load_from_file("all_loc")
    _store_load_from_file("all_task")
    _store_load_from_file(
        "broadcast_schedules",
        normalize=_normalize_schedules_payload,
        default=_default_schedules_payload,
        persist_default=True,
    )
    _store_load_from_file("task_overrides", normalize=_normalize_overrides_payload, default={"overrides": []})
    _store_load_from_file(
        "assistant_command_logs",
        normalize=_normalize_assistant_command_logs_payload,
        default={"items": []},
    )
    _store_load_from_file(
        "assistant_settings",
        normalize=_normalize_assistant_settings_payload,
        default=_default_assistant_settings_payload,
        persist_default=True,
    )
    _store_load_from_file(
        "calendar_holidays_cn",
        normalize=_normalize_calendar_holidays_payload,
        default={"years": {}},
    )
    _store_load_from_file(
        "remote_settings",
        normalize=_normalize_remote_settings_payload,
        default={"remote_base_url": "", "last_verified_at": "", "last_verified_ip": ""},
    )
    _store_load_from_file(
        "remote_sync_meta",
        normalize=_normalize_remote_sync_meta_payload,
        default={"schedule_delete_supported": True, "schedule_delete_checked": False, "schedule_tombstones": []},
    )
    _ensure_all_task_payload()


def _run_remote_sync_cycle(*, force: bool = True, source: str = "auto") -> Dict[str, bool]:
    attempt_at = _sync_now_str()
    started_at = time.time()
    _update_remote_sync_status(last_attempt_at=attempt_at)
    try:
        results = _sync_remote_data(force=force)
    except Exception as exc:
        duration_ms = round((time.time() - started_at) * 1000, 2)
        _record_remote_sync_failure(
            attempt_at=attempt_at,
            duration_ms=duration_ms,
            detail=str(exc),
        )
        raise
    duration_ms = round((time.time() - started_at) * 1000, 2)
    failed_keys = sorted(key for key, ok in results.items() if not ok)
    if failed_keys:
        detail = f"remote sync incomplete ({source}): {', '.join(failed_keys)}"
        _record_remote_sync_failure(
            attempt_at=attempt_at,
            duration_ms=duration_ms,
            detail=detail,
        )
        LOGGER.warning("Remote sync incomplete during %s: %s", source, ", ".join(failed_keys))
        _ensure_once_overrides_cleaned()
        return results
    _record_remote_sync_success(attempt_at=attempt_at, duration_ms=duration_ms)
    _ensure_once_overrides_cleaned()
    return results


def _run_startup_remote_sync() -> None:
    if not _remote_enabled():
        _ensure_once_overrides_cleaned()
        return
    try:
        _run_remote_sync_cycle(force=True, source="startup")
    except Exception as exc:
        LOGGER.warning("Startup remote sync failed: %s", exc)
    _ensure_once_overrides_cleaned()


def _start_remote_auto_sync_thread() -> None:
    global AUTO_SYNC_THREAD, AUTO_SYNC_THREAD_STARTED, AUTO_SYNC_STOP_EVENT, REMOTE_AUTO_SYNC_SECONDS
    interval = _load_remote_auto_sync_seconds()
    REMOTE_AUTO_SYNC_SECONDS = interval
    if interval <= 0:
        _update_remote_sync_status(thread_started=False, stop_requested=False)
        return
    with AUTO_SYNC_THREAD_LOCK:
        if AUTO_SYNC_THREAD_STARTED and _thread_is_alive(AUTO_SYNC_THREAD):
            return
        AUTO_SYNC_STOP_EVENT = threading.Event()
        stop_event = AUTO_SYNC_STOP_EVENT

    def _background_sync() -> None:
        while not stop_event.wait(interval):
            try:
                _run_remote_sync_cycle(force=True, source="auto")
            except Exception as exc:
                LOGGER.warning("Auto sync failed: %s", exc)
        _update_remote_sync_status(stop_requested=True)

    thread = threading.Thread(target=_background_sync, daemon=True)
    with AUTO_SYNC_THREAD_LOCK:
        AUTO_SYNC_THREAD = thread
        AUTO_SYNC_THREAD_STARTED = True
    _update_remote_sync_status(thread_started=True, stop_requested=False)
    thread.start()


def _stop_remote_auto_sync_thread(join_timeout: float = 5.0) -> None:
    global AUTO_SYNC_THREAD, AUTO_SYNC_THREAD_STARTED, AUTO_SYNC_STOP_EVENT
    with AUTO_SYNC_THREAD_LOCK:
        thread = AUTO_SYNC_THREAD
        stop_event = AUTO_SYNC_STOP_EVENT
        if thread is None and not AUTO_SYNC_THREAD_STARTED:
            _update_remote_sync_status(thread_started=False, stop_requested=False)
            return
        stop_event.set()
    join = getattr(thread, "join", None)
    if callable(join):
        try:
            join(timeout=join_timeout)
        except Exception:
            pass
    with AUTO_SYNC_THREAD_LOCK:
        if not _thread_is_alive(AUTO_SYNC_THREAD):
            AUTO_SYNC_THREAD = None
            AUTO_SYNC_THREAD_STARTED = False
            AUTO_SYNC_STOP_EVENT = threading.Event()
    _update_remote_sync_status(
        thread_started=bool(AUTO_SYNC_THREAD_STARTED),
        stop_requested=bool(stop_event.is_set()),
    )



@app.on_event("startup")
def _startup_load_data() -> None:
    global STARTUP_LOAD_DONE
    if STARTUP_LOAD_DONE:
        return
    with STARTUP_LOAD_LOCK:
        if STARTUP_LOAD_DONE:
            return
        _init_data_store()
        _run_startup_remote_sync()
        _start_remote_auto_sync_thread()
        STARTUP_LOAD_DONE = True


@app.on_event("shutdown")
def _shutdown_runtime() -> None:
    _stop_remote_auto_sync_thread()


def _remote_media_map(folder_id: Optional[int] = None) -> dict:
    cache_key = _media_folder_cache_key("media_map", folder_id)
    cached = _ttl_cache_get(cache_key)
    if isinstance(cached, dict):
        return cached
    items = _remote_mediainfo_items(folder_id=folder_id)
    mapping = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("medianame") or item.get("media_name")
        media_id = item.get("mediaid") or item.get("id") or item.get("media_id")
        if name and media_id is not None:
            mapping[str(name)] = str(media_id)
    _ttl_cache_set(cache_key, mapping, REMOTE_LOOKUP_CACHE_SECONDS)
    return mapping


def _local_media_map() -> Dict[str, str]:
    media_map: Dict[str, str] = {}
    for item in _remote_data_list(_store_get("all_audio")):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("medianame") or item.get("media_name")
        media_id = item.get("mediaid") or item.get("id") or item.get("media_id")
        if name and media_id is not None:
            media_map[str(name)] = str(media_id)
    return media_map


def _safe_media_map() -> dict:
    local_map = _local_media_map()
    if not _remote_enabled():
        return local_map
    try:
        remote_map = _remote_media_map()
        if remote_map:
            return remote_map
        if local_map:
            return local_map
        return remote_map
    except HTTPException:
        if local_map:
            return local_map
        raise


def _remote_media_lookup(folder_id: Optional[int] = None) -> dict:
    cache_key = _media_folder_cache_key("media_lookup", folder_id)
    cached = _cache_get(cache_key)
    if isinstance(cached, dict):
        return cached
    items = _remote_mediainfo_items(folder_id=folder_id)
    lookup = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        media_id = item.get("mediaid") or item.get("id") or item.get("media_id")
        name = item.get("name") or item.get("medianame") or item.get("media_name")
        if media_id is not None and name:
            lookup[str(media_id)] = str(name)
    _cache_set(cache_key, lookup)
    return lookup


def _store_media_lookup() -> dict:
    payload = _store_get("all_audio")
    items = _remote_data_list(payload)
    lookup = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        media_id = item.get("mediaid") or item.get("id") or item.get("media_id")
        name = item.get("name") or item.get("medianame") or item.get("media_name")
        if media_id is not None and name:
            lookup[str(media_id)] = str(name)
    return lookup


def _filter_media_payload_by_folderid(payload: object, folder_id: Optional[int]) -> object:
    folder_text = _media_folder_id_text(folder_id)
    if not folder_text:
        return payload

    def filter_items(items: object) -> List[dict]:
        filtered: List[dict] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            item_folder = _media_folder_id_text(item.get("folderid"))
            if item_folder == folder_text:
                filtered.append(dict(item))
        return filtered

    if isinstance(payload, list):
        return filter_items(payload)
    if isinstance(payload, dict):
        cleaned = dict(payload)
        for key in ("data", "rows", "list", "items"):
            if isinstance(cleaned.get(key), list):
                cleaned[key] = filter_items(cleaned.get(key))
                return cleaned
    return payload


def _play_media_folder_items() -> List[dict]:
    items = _remote_mediainfo_items(folder_id=INSTANT_PLAY_MEDIA_FOLDER_ID)
    cleaned_items: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        media_id = item.get("mediaid") or item.get("id") or item.get("media_id")
        media_name = item.get("name") or item.get("medianame") or item.get("media_name")
        if media_id in (None, "") or not str(media_name or "").strip():
            continue
        cleaned_items.append(dict(item))
    return cleaned_items


def _play_media_folder_exact_match(
    slots: dict,
    query: str,
    *,
    slot_key: str = "media_name",
) -> Optional[Tuple[str, str]]:
    folder_error: Optional[HTTPException] = None
    try:
        items = _play_media_folder_items()
    except HTTPException as exc:
        folder_error = exc
        items = []
    matched_id = _slot_text(slots, f"{slot_key}_id", "media_id", "mediaid")
    if matched_id:
        target_id = str(matched_id).strip()
        for item in items:
            media_id = str(item.get("mediaid") or item.get("id") or item.get("media_id") or "").strip()
            if media_id == target_id:
                media_name = str(item.get("name") or item.get("medianame") or item.get("media_name") or "").strip()
                if media_name:
                    return (media_id, media_name)
        fallback_lookup = _safe_media_map()
        fallback_name = str(next((name for name, media_id in fallback_lookup.items() if str(media_id) == target_id), "")).strip()
        if fallback_name:
            return (target_id, fallback_name)
        if folder_error is not None:
            raise folder_error
        return None

    target_names = [
        _compact_text(_clean_media_name(candidate))
        for candidate in (_slot_text(slots, f"{slot_key}_matched"), query)
        if str(candidate or "").strip()
    ]
    target_names = [value for value in target_names if value]
    if not target_names:
        return None
    for item in items:
        media_name = str(item.get("name") or item.get("medianame") or item.get("media_name") or "").strip()
        compact_name = _compact_text(_clean_media_name(media_name))
        if compact_name and compact_name in target_names:
            media_id = str(item.get("mediaid") or item.get("id") or item.get("media_id") or "").strip()
            if media_id:
                return (media_id, media_name)
    query_text = str(query or "").strip()
    if query_text.isdigit():
        target_id = query_text
        for item in items:
            media_id = str(item.get("mediaid") or item.get("id") or item.get("media_id") or "").strip()
            if media_id == target_id:
                media_name = str(item.get("name") or item.get("medianame") or item.get("media_name") or "").strip()
                if media_name:
                    return (media_id, media_name)
    fallback_lookup = _safe_media_map()
    for media_name, media_id in fallback_lookup.items():
        compact_name = _compact_text(_clean_media_name(media_name))
        if compact_name and compact_name in target_names:
            return (str(media_id), str(media_name))
    if query_text.isdigit():
        fallback_name = str(next((name for name, media_id in fallback_lookup.items() if str(media_id) == query_text), "")).strip()
        if fallback_name:
            return (query_text, fallback_name)
    if folder_error is not None:
        raise folder_error
    return None


def _runtime_play_cache_key() -> str:
    return "runtime_play_tasks_recent"


def _recent_runtime_play_entries() -> List[dict]:
    cached = _ttl_cache_get(_runtime_play_cache_key())
    if isinstance(cached, list):
        return _clone_payload(cached) or []
    return []


def _store_recent_runtime_play_entry(entry: dict) -> None:
    if not isinstance(entry, dict):
        return
    merged = [entry]
    seen = {str(entry.get("task_id") or entry.get("id") or "").strip() or json.dumps(entry, ensure_ascii=False, sort_keys=True)}
    for item in _recent_runtime_play_entries():
        if not isinstance(item, dict):
            continue
        item_key = str(item.get("task_id") or item.get("id") or "").strip() or json.dumps(item, ensure_ascii=False, sort_keys=True)
        if item_key in seen:
            continue
        seen.add(item_key)
        merged.append(item)
    _ttl_cache_set(_runtime_play_cache_key(), merged[:RUNTIME_PLAY_RECENT_LIMIT], RUNTIME_PLAY_CACHE_SECONDS)
    REMOTE_CACHE.pop("runtime_play_rows", None)


def _update_recent_runtime_play_entry(task_id: object, **updates: object) -> None:
    task_id_text = str(task_id or "").strip()
    if not task_id_text:
        return
    entries = _recent_runtime_play_entries()
    next_entries: List[dict] = []
    updated = False
    for item in entries:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("task_id") or item.get("id") or "").strip()
        if item_id == task_id_text:
            next_item = copy.deepcopy(item)
            next_item.update({key: value for key, value in updates.items() if value is not None})
            next_entries.append(next_item)
            updated = True
        else:
            next_entries.append(item)
    if not updated:
        next_entries.insert(0, {"task_id": task_id_text, "id": task_id_text, **updates})
    _ttl_cache_set(_runtime_play_cache_key(), next_entries[:RUNTIME_PLAY_RECENT_LIMIT], RUNTIME_PLAY_CACHE_SECONDS)
    REMOTE_CACHE.pop("runtime_play_rows", None)


def _record_light_instant_play_runtime_entry(form: dict, response: dict) -> None:
    """Record successful /api/light/instant-play calls for the runtime status view."""
    if not isinstance(form, dict) or not isinstance(response, dict) or not response.get("success"):
        return

    task_id = _remote_extract_taskid(response) or f"light-temp-{uuid.uuid4().hex}"
    media_ids = _normalize_terminal_ids(form.get("media"))
    terminal_ids = _normalize_terminal_ids(form.get("terminal"))
    media_name = str(form.get("medianame") or form.get("media_name") or "").strip()
    if not media_name and media_ids:
        media_name = media_ids[0]

    playlength = 0
    if str(form.get("playmode") or "").strip() == "0":
        playlength = (
            max(0, _coerce_int(form.get("timehour"), 0)) * 3600
            + max(0, _coerce_int(form.get("timeminute"), 0)) * 60
            + max(0, _coerce_int(form.get("timesecond"), 0))
        )

    _store_recent_runtime_play_entry(
        {
            "task_id": str(task_id),
            "id": str(task_id),
            "task_name": media_name or "instant-play",
            "media_id": media_ids[0] if media_ids else "",
            "media_ids": media_ids,
            "media_name": media_name,
            "media_names": [media_name] if media_name else [],
            "terminal_ids": terminal_ids,
            "terminal_names": [],
            "volume": _coerce_int(form.get("volume"), 50),
            "playtype": _coerce_int(form.get("playmode"), 0),
            "playlength": playlength,
            "remote_state": 0,
            "status": "执行中",
            "created_at": _now_str(),
            "source": "runtime_play",
        }
    )


def _mark_recent_light_instant_play_entries_stopped() -> None:
    """Reflect /api/light/instant-play/stop immediately in runtime task state."""
    for entry in _recent_runtime_play_entries():
        if not isinstance(entry, dict):
            continue
        task_id = str(entry.get("task_id") or entry.get("id") or "").strip()
        if not task_id:
            continue
        _update_recent_runtime_play_entry(task_id, remote_state=-1, status="停止")
    REMOTE_CACHE.pop("runtime_play_rows", None)


def _runtime_play_remote_state_value(payload: object) -> Optional[int]:
    candidates = [payload]
    if isinstance(payload, dict):
        for key in ("data", "result", "item", "obj"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif isinstance(value, dict):
                candidates.append(value)
    for item in candidates:
        if isinstance(item, dict):
            for key in ("remote_state", "state", "taskstate"):
                value = item.get(key)
                if value in (None, ""):
                    continue
                try:
                    return int(str(value).strip())
                except Exception:
                    continue
        elif item not in (None, ""):
            try:
                return int(str(item).strip())
            except Exception:
                continue
    return None


def _runtime_play_status_from_remote_state(remote_state: Optional[int], fallback: object = None) -> str:
    if remote_state == 0:
        return "执行中"
    if remote_state == -1:
        return "停止"
    fallback_text = str(fallback or "").strip()
    if fallback_text:
        return fallback_text
    return "待确认"


def _runtime_play_status_text(item: dict) -> str:
    if not isinstance(item, dict):
        return "待执行"
    fallback = str(item.get("status") or item.get("display_status") or item.get("state_text") or "").strip() or None
    remote_state = _runtime_play_remote_state_value(item)
    if remote_state in {0, -1}:
        return _runtime_play_status_from_remote_state(remote_state, fallback=fallback)
    state_value = item.get("state")
    if state_value is None:
        state_value = item.get("taskstate")
    if state_value is None:
        state_value = item.get("enablestate")
    coerced = _coerce_int(state_value, -1)
    if coerced in {0, -1}:
        return _runtime_play_status_from_remote_state(coerced, fallback=fallback)
    return _task_display_status(coerced, fallback=fallback)


def _map_runtime_play_item(
    item: dict,
    *,
    media_lookup: Optional[dict] = None,
    terminal_lookup: Optional[dict] = None,
) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    normalized = _normalize_remote_task(item)
    task_id = _remote_extract_taskid(normalized, explicit_only=True) or str(
        normalized.get("taskid") or normalized.get("id") or ""
    ).strip()
    media_ids = _runtime_play_media_ids_from_item(normalized)
    terminal_ids = _runtime_play_terminal_ids_from_item(normalized)
    media_names = _normalize_str_list(normalized.get("media_names") or normalized.get("medianames"))
    if not media_names:
        media_name_text = str(
            normalized.get("medianame") or normalized.get("media_name") or normalized.get("name") or ""
        ).strip()
        if media_name_text and media_name_text.lower() != "string":
            media_names = [media_name_text]
    if not media_names and media_ids and isinstance(media_lookup, dict):
        media_names = [str(media_lookup.get(str(media_id)) or "").strip() for media_id in media_ids]
        media_names = [value for value in media_names if value]
    terminal_names = _normalize_str_list(normalized.get("terminal_names"))
    if not terminal_names:
        terminal_name_text = str(
            normalized.get("terminalnames") or normalized.get("terminal_name") or normalized.get("liveterminalname") or ""
        ).strip()
        if terminal_name_text and terminal_name_text.lower() != "string":
            terminal_names = [terminal_name_text]
    if not terminal_names and terminal_ids and isinstance(terminal_lookup, dict):
        resolved_names: List[str] = []
        for terminal_id in terminal_ids:
            lookup_item = terminal_lookup.get(str(terminal_id))
            if isinstance(lookup_item, dict):
                name = str(lookup_item.get("name") or "").strip()
                if name:
                    resolved_names.append(name)
        terminal_names = _unique_list(resolved_names)
    media_name = media_names[0] if media_names else str(
        normalized.get("medianame") or normalized.get("media_name") or normalized.get("name") or ""
    ).strip()
    created_at = str(
        normalized.get("created_at")
        or normalized.get("createtime")
        or normalized.get("create_time")
        or normalized.get("addtime")
        or normalized.get("starttime")
        or normalized.get("time")
        or ""
    ).strip()
    playtype = _coerce_int(normalized.get("playtype"), 0)
    playlength = _coerce_int(normalized.get("playlength"), 0)
    volume = _coerce_int(normalized.get("volume"), 50)
    remote_state = _runtime_play_remote_state_value(normalized)
    display_status = _runtime_play_status_text(normalized)
    task_name = str(normalized.get("taskname") or normalized.get("name") or media_name or "").strip()
    row = {
        "task_id": task_id,
        "id": task_id,
        "task_name": task_name,
        "media_id": media_ids[0] if media_ids else "",
        "media_ids": media_ids,
        "media_name": media_name,
        "media_names": media_names,
        "terminal_ids": terminal_ids,
        "terminal_names": terminal_names,
        "volume": volume,
        "playtype": playtype,
        "playlength": playlength,
        "remote_state": remote_state,
        "status": display_status,
        "created_at": created_at,
        "source": "runtime_play",
    }
    if not row["task_id"] and not row["media_name"] and not row["terminal_ids"]:
        return None
    return row


def _merge_runtime_play_rows(primary_rows: List[dict], fallback_rows: List[dict]) -> List[dict]:
    merged: List[dict] = []
    seen_index: dict[str, int] = {}
    for source in (primary_rows, fallback_rows):
        for item in source:
            if not isinstance(item, dict):
                continue
            key = str(item.get("task_id") or item.get("id") or "").strip()
            if not key:
                key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            existing_index = seen_index.get(key)
            if existing_index is None:
                seen_index[key] = len(merged)
                merged.append(item)
                continue
            existing = merged[existing_index]
            incoming_state = _runtime_play_remote_state_value(item)
            existing_state = _runtime_play_remote_state_value(existing)
            if incoming_state == -1 and existing_state != -1:
                merged[existing_index] = item
    return merged


def _fetch_remote_runtime_play_rows() -> List[dict]:
    global _RUNTIME_PLAY_LISTING_MODE_LOGGED
    if not _remote_enabled():
        return []
    if not REMOTE_TEMP_TASK_PATHS:
        if not _RUNTIME_PLAY_LISTING_MODE_LOGGED:
            LOGGER.info(
                "remote temp task listing unsupported; using recent cache fallback %s",
                {"configured_paths": [], "mode": "recent_cache"},
            )
            _RUNTIME_PLAY_LISTING_MODE_LOGGED = True
        return []
    last_error: Optional[HTTPException] = None
    media_lookup: dict = {}
    terminal_lookup: dict = {}
    try:
        media_lookup = _remote_media_lookup(folder_id=INSTANT_PLAY_MEDIA_FOLDER_ID)
    except HTTPException:
        media_lookup = {}
    try:
        terminal_lookup = _remote_terminal_lookup()
    except HTTPException:
        terminal_lookup = {}
    for path in REMOTE_TEMP_TASK_PATHS:
        try:
            payload = _remote_request("GET", path)
        except HTTPException as exc:
            if exc.status_code in {404, 405}:
                last_error = exc
                continue
            raise
        items = _runtime_play_items_from_payload(payload)
        if not items:
            continue
        rows: List[dict] = []
        for item in items:
            row = _map_runtime_play_item(item, media_lookup=media_lookup, terminal_lookup=terminal_lookup)
            if row:
                rows.append(row)
        if rows:
            return rows
    if last_error:
        if not _RUNTIME_PLAY_LISTING_MODE_LOGGED:
            LOGGER.info(
                "remote temp task listing unavailable; using recent cache fallback %s",
                {
                    "configured_paths": list(REMOTE_TEMP_TASK_PATHS),
                    "status_code": getattr(last_error, "status_code", ""),
                    "mode": "recent_cache",
                },
            )
            _RUNTIME_PLAY_LISTING_MODE_LOGGED = True
        return []
    return []


def _runtime_play_state_cache_key(task_id: object) -> str:
    return f"runtime_play_state:{str(task_id or '').strip()}"


def _refresh_runtime_play_rows_remote_state(rows: List[dict], *, force: bool = False) -> List[dict]:
    refreshed: List[dict] = []
    for item in rows:
        row = _clone_payload(item) or {}
        if not isinstance(row, dict):
            continue
        task_id_text = str(row.get("task_id") or row.get("id") or "").strip()
        if not task_id_text:
            refreshed.append(row)
            continue
        if task_id_text.startswith("light-temp-"):
            refreshed.append(row)
            continue
        cached_state = None if force else _cache_get(_runtime_play_state_cache_key(task_id_text))
        remote_state = _runtime_play_remote_state_value(cached_state)
        if remote_state is None:
            try:
                state_payload = _fetch_remote_task_state(_coerce_int(task_id_text, 0), 2)
            except HTTPException:
                state_payload = None
            remote_state = _runtime_play_remote_state_value(state_payload)
            if remote_state is not None:
                _cache_set(_runtime_play_state_cache_key(task_id_text), {"state": remote_state})
        if remote_state is not None:
            row["remote_state"] = remote_state
            row["status"] = _runtime_play_status_from_remote_state(remote_state, fallback=row.get("status"))
            if remote_state == -1:
                _update_recent_runtime_play_entry(
                    task_id_text,
                    remote_state=-1,
                    status="停止",
                )
            elif remote_state == 0:
                _update_recent_runtime_play_entry(
                    task_id_text,
                    remote_state=0,
                    status="执行中",
                )
        else:
            row["remote_state"] = ""
            row["status"] = "待确认"
            _update_recent_runtime_play_entry(
                task_id_text,
                remote_state="",
                status="待确认",
            )
        refreshed.append(row)
    return refreshed


def _store_terminalinfo_items() -> list:
    payload = _store_get("all_loc")
    if payload is None:
        payload = _read_json_optional(ALL_LOC_PATH)
    return _remote_data_list(payload)


def _remote_terminal_map() -> dict:
    cached = _ttl_cache_get("terminal_map")
    if isinstance(cached, dict):
        return cached
    items = _remote_terminalinfo_items()
    mapping = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        name = item.get("name")
        ip = item.get("ip")
        if terminal_id is None:
            continue
        if name:
            name_str = str(name)
            mapping[name_str] = str(terminal_id)
            compact = _compact_text(name_str)
            if compact:
                mapping[compact] = str(terminal_id)
        if ip:
            ip_str = str(ip)
            mapping[ip_str] = str(terminal_id)
            compact = _compact_text(ip_str)
            if compact:
                mapping[compact] = str(terminal_id)
    _ttl_cache_set("terminal_map", mapping, REMOTE_LOOKUP_CACHE_SECONDS)
    return mapping
def _check_terminal_online_status(terminal_ids: List[str]) -> Tuple[List[str], List[str]]:
    """
    检查终端的网络连接状态
    返回: (在线终端ID列表, 离线终端名称列表)
    """
    if not terminal_ids:
        return [], []
    
    # 获取终端信息
    try:
        items = _remote_terminalinfo_items()
    except HTTPException:
        # 如果获取失败,假设全部在线,不阻断播放
        return terminal_ids, []
    
    # 建立 ID -> 终端信息 的映射
    terminal_info_map: Dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        term_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if term_id is not None:
            terminal_info_map[str(term_id)] = item
    
    online_ids: List[str] = []
    offline_names: List[str] = []
    
    for term_id in terminal_ids:
        term_id_str = str(term_id)
        info = terminal_info_map.get(term_id_str)
        
        if not info:
            # 【修复问题#4】找不到终端信息时的保守策略:记为离线而非假设在线
            # 这样可以更早地发现问题并告知用户
            offline_names.append(f"终端{term_id_str}(未找到)")
            continue
        
        # 检查 netstate: 1=连接, 0=未连接
        netstate = info.get("netstate")
        name = info.get("name") or info.get("ip") or f"终端{term_id_str}"
        
        if str(netstate) == "0":
            # 终端离线
            offline_names.append(str(name))
        else:
            # 终端在线
            online_ids.append(term_id_str)
    
    return online_ids, offline_names


def _terminal_runtime_rows(terminal_ids: List[str], info_items: list) -> dict:
    info_map: Dict[str, dict] = {}
    for item in info_items:
        if not isinstance(item, dict):
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if terminal_id in (None, "", 0, "0"):
            continue
        info_map[str(terminal_id)] = item

    rows: List[dict] = []
    online_ids: List[str] = []
    offline_names: List[str] = []
    unknown_names: List[str] = []
    for terminal_id in terminal_ids:
        item = info_map.get(str(terminal_id))
        item = item if isinstance(item, dict) else {}
        name = str(item.get("name") or item.get("ip") or f"终端{terminal_id}")
        if item.get("netstate") in (None, ""):
            netstate = "unknown"
            unknown_names.append(name)
        elif str(item.get("netstate")) == "0":
            netstate = "0"
            offline_names.append(name)
        else:
            netstate = str(item.get("netstate"))
            online_ids.append(str(terminal_id))
        rows.append(
            {
                "terminal_id": str(terminal_id),
                "terminal_name": name,
                "zone": item.get("zone"),
                "netstate": netstate,
                "devicestate": item.get("devicestate"),
                "taskstate": item.get("taskstate"),
                "status": _terminal_runtime_status(netstate, item.get("taskstate"), item.get("devicestate")),
            }
        )

    return {
        "rows": rows,
        "online_ids": _unique_list(online_ids),
        "offline_names": _unique_list(offline_names),
        "unknown_names": _unique_list(unknown_names),
    }


def _get_task_terminal_ids(task: dict, terminal_map: Optional[dict] = None) -> List[str]:
    """
    从任务中提取所有终端ID
    """
    task_terminal_ids = _normalize_terminal_ids(
        _terminal_ids_from_taskterminal(task.get("taskterminal") or task.get("taskTerminal"))
    )
    if task_terminal_ids:
        return task_terminal_ids
    terminal_ids: List[str] = []
    
    # 1. 从 terminalids 列表获取
    value_list = task.get("terminalids") or task.get("terminal_ids") or task.get("liveterminalids")
    if isinstance(value_list, list):
        terminal_ids.extend([str(v) for v in value_list if v not in (None, "", "0")])
    
    # 2. 从单个终端ID字段获取
    for key in ("liveterminalid", "terminalid", "terminal_id"):
        value = task.get(key)
        if value not in (None, "", 0, "0"):
            terminal_ids.append(str(value))
    
    # 3. 从 location 中提取(如果是数字ID)
    location = task.get("location")
    if isinstance(location, list):
        for entry in location:
            if isinstance(entry, list) and entry:
                candidate = entry[-1]  # 取最后一个元素(通常是终端名或ID)
            else:
                candidate = entry
            if candidate is None:
                continue
            candidate_str = str(candidate).strip()
            if not candidate_str:
                continue
            if candidate_str.isdigit():
                terminal_ids.append(candidate_str)
                continue
            if terminal_map:
                mapped = terminal_map.get(candidate_str)
                if mapped is None:
                    compact = _compact_text(candidate_str)
                    if compact:
                        mapped = terminal_map.get(compact)
                if mapped is not None:
                    terminal_ids.append(str(mapped))
    
    return _unique_list([v for v in terminal_ids if v])

def _terminal_lookup_from_items(items: list) -> dict:
    lookup: Dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if terminal_id is None:
            continue
        zone = item.get("zone")
        name = item.get("name") or item.get("ip") or str(terminal_id)
        zone_name = item.get("zonename") or item.get("zone_name") or ""
        lookup[str(terminal_id)] = {
            "zone": zone,
            "name": str(name),
            "zone_name": str(zone_name).strip(),
            "zone_candidates": [],
            "zone_ambiguous": False,
        }
    return lookup


def _zone_candidate_entry(zone_id: object, zone_name: object) -> dict:
    normalized_zone_name = str(zone_name or "").strip()
    return {
        "zone": "" if zone_id in (None, "") else str(zone_id),
        "zone_name": normalized_zone_name or _zone_label(zone_id),
    }


def _zone_candidate_signature(candidate: object) -> str:
    if not isinstance(candidate, dict):
        return ""
    zone_value = str(candidate.get("zone") or "").strip()
    zone_name = _compact_text(str(candidate.get("zone_name") or "").strip())
    return f"{zone_value}|{zone_name}"


def _lookup_zone_candidates(lookup_item: object) -> List[dict]:
    if not isinstance(lookup_item, dict):
        return []
    candidates = lookup_item.get("zone_candidates")
    if not isinstance(candidates, list):
        return []
    deduped: List[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        signature = _zone_candidate_signature(candidate)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        deduped.append(
            {
                "zone": str(candidate.get("zone") or "").strip(),
                "zone_name": str(candidate.get("zone_name") or "").strip(),
            }
        )
    return deduped


def _zone_candidate_sort_key(candidate: object) -> tuple[int, str, str]:
    if not isinstance(candidate, dict):
        return (10**9, "", "")
    zone_value = str(candidate.get("zone") or "").strip()
    try:
        zone_rank = int(zone_value)
    except Exception:
        zone_rank = 10**9
    zone_name = str(candidate.get("zone_name") or "").strip()
    return (zone_rank, zone_value, zone_name)


def _lookup_zone_is_ambiguous(lookup_item: object) -> bool:
    if not isinstance(lookup_item, dict):
        return False
    if bool(lookup_item.get("zone_ambiguous")):
        return True
    return len(_lookup_zone_candidates(lookup_item)) > 1


def _zone_item_id(zone_item: object) -> str:
    if not isinstance(zone_item, dict):
        return ""
    zone_id = zone_item.get("id") or zone_item.get("zone") or zone_item.get("zoneid")
    return "" if zone_id in (None, "") else str(zone_id)


def _terminal_members_from_zone_item(zone_item: object) -> List[dict]:
    if not isinstance(zone_item, dict):
        return []
    terminal_items = zone_item.get("terminal")
    if not isinstance(terminal_items, list):
        return []
    members: List[dict] = []
    for item in terminal_items:
        if isinstance(item, dict):
            members.append(dict(item))
    return members


def _zone_terminal_member_identity(item: object) -> Tuple[str, str, str]:
    if not isinstance(item, dict):
        return "", "", ""
    terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
    terminal_name = str(item.get("name") or item.get("terminalname") or "").strip()
    terminal_ip = str(item.get("ip") or "").strip()
    terminal_id_text = "" if terminal_id in (None, "") else str(terminal_id).strip()
    return terminal_id_text, terminal_name, terminal_ip


def _is_valid_zone_terminal_member(item: object) -> bool:
    terminal_id, terminal_name, terminal_ip = _zone_terminal_member_identity(item)
    return bool(terminal_id or terminal_name or terminal_ip)


def _is_visible_terminal_for_ui(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if not _is_valid_zone_terminal_member(item):
        return False
    return str(item.get("type")).strip() != "0"


def _filter_terminal_payload_for_ui(payload: object) -> object:
    if isinstance(payload, dict):
        cleaned = dict(payload)
        data = cleaned.get("data")
        if isinstance(data, list):
            cleaned["data"] = [dict(item) for item in data if _is_visible_terminal_for_ui(item)]
        return cleaned
    if isinstance(payload, list):
        return [dict(item) for item in payload if _is_visible_terminal_for_ui(item)]
    return payload


def _normalize_zone_item_for_ui(item: object) -> object:
    if not isinstance(item, dict):
        return item
    cleaned = dict(item)
    zone_name = str(
        cleaned.get("name")
        or cleaned.get("zonename")
        or cleaned.get("zone_name")
        or cleaned.get("description")
        or ""
    ).strip()
    if zone_name and not str(cleaned.get("name") or "").strip():
        cleaned["name"] = zone_name
    return cleaned


def _normalize_zone_payload_for_ui(payload: object) -> object:
    if isinstance(payload, dict):
        cleaned = dict(payload)
        for key in ("data", "zone", "zones", "items"):
            values = cleaned.get(key)
            if isinstance(values, list):
                cleaned[key] = [_normalize_zone_item_for_ui(item) for item in values]
        return cleaned
    if isinstance(payload, list):
        return [_normalize_zone_item_for_ui(item) for item in payload]
    return payload


def _clean_zone_terminal_payload(payload: object) -> object:
    return _filter_terminal_payload_for_ui(payload)


def _merge_zone_terminal_members(existing: object, incoming: object) -> List[dict]:
    merged: List[dict] = []
    seen: set[str] = set()
    for source in (existing, incoming):
        items = source if isinstance(source, list) else []
        for item in items:
            if not isinstance(item, dict) or not _is_valid_zone_terminal_member(item):
                continue
            terminal_id, terminal_name, terminal_ip = _zone_terminal_member_identity(item)
            name_signature = _compact_text(terminal_name)
            ip_signature = _compact_text(terminal_ip)
            signature = terminal_id or name_signature or ip_signature
            if not signature or signature in seen:
                continue
            seen.add(signature)
            merged.append(dict(item))
    return merged


def _enrich_lookup_zones_from_terzone(lookup: dict, zone_items: list) -> dict:
    """用 terzone 的分区归属覆盖 lookup 中不可靠的 zone 值。"""
    if not zone_items or not lookup:
        return lookup
    warned_ambiguous: set[str] = set()
    warning_cache_key = "ambiguous_zone_warning_cache"
    cached_warning_signatures = _ttl_cache_get(warning_cache_key)
    cached_warning_signatures = (
        set(cached_warning_signatures)
        if isinstance(cached_warning_signatures, list)
        else set()
    )
    for zone_item in zone_items:
        if not isinstance(zone_item, dict):
            continue
        zone_id = zone_item.get("id") or zone_item.get("zoneid")
        if zone_id is None:
            continue
        zone_name = str(zone_item.get("name") or zone_item.get("zonename") or "").strip()
        candidate = _zone_candidate_entry(zone_id, zone_name)
        terminals = zone_item.get("terminal")
        if not isinstance(terminals, list):
            continue
        for term in terminals:
            if not isinstance(term, dict):
                continue
            term_id = term.get("id") or term.get("terminalid")
            if term_id is None:
                continue
            key = str(term_id)
            if key not in lookup:
                term_name = term.get("name") or term.get("terminalname") or str(term_id)
                lookup[key] = {
                    "zone": None,
                    "name": str(term_name),
                    "zone_name": "",
                    "zone_candidates": [],
                    "zone_ambiguous": False,
                }
            entry = lookup[key]
            if not isinstance(entry.get("zone_candidates"), list):
                entry["zone_candidates"] = []
            existing_signatures = {
                _zone_candidate_signature(item)
                for item in entry["zone_candidates"]
                if isinstance(item, dict)
            }
            candidate_signature = _zone_candidate_signature(candidate)
            if candidate_signature and candidate_signature not in existing_signatures:
                entry["zone_candidates"].append(dict(candidate))
            candidates = sorted(_lookup_zone_candidates(entry), key=_zone_candidate_sort_key)
            entry["zone_candidates"] = candidates
            if len(candidates) <= 1:
                entry["zone"] = zone_id
                entry["zone_name"] = candidate["zone_name"]
                entry["zone_ambiguous"] = False
                continue
            primary_candidate = candidates[0]
            entry["zone"] = primary_candidate.get("zone")
            entry["zone_name"] = str(primary_candidate.get("zone_name") or "").strip()
            entry["zone_ambiguous"] = True
            if key in warned_ambiguous:
                continue
            warned_ambiguous.add(key)
            warning_signature = json.dumps(
                {
                    "terminal_id": key,
                    "zone_candidates": _clone_payload(candidates),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if warning_signature in cached_warning_signatures:
                continue
            cached_warning_signatures.add(warning_signature)
            LOGGER.warning(
                "ambiguous terminal zone mapping %s",
                {
                    "terminal_id": key,
                    "terminal_name": str(entry.get("name") or term.get("name") or ""),
                    "zone_candidates": _clone_payload(candidates),
                },
            )
    _ttl_cache_set(
        warning_cache_key,
        sorted(cached_warning_signatures),
        _ZONETERMINAL_CACHE_TTL,
    )
    return lookup


def _fetch_enriched_zone_items(force: bool = False) -> List[dict]:
    cache_key = "enriched_terzone_items"
    if not force:
        cached = _ttl_cache_get(cache_key)
        if isinstance(cached, list):
            return _clone_payload(cached)
    zone_items = _remote_data_list(_remote_terzone_cached(force=force))
    if not zone_items:
        _ttl_cache_set(cache_key, [], _ZONETERMINAL_CACHE_TTL)
        return []
    zone_ids = [_zone_item_id(item) for item in zone_items if _zone_item_id(item)]
    zone_terminal_payloads: Dict[str, object] = {}
    if zone_ids:
        fetched = _parallel_map(zone_ids, lambda zone_id: _remote_zoneterminal_cached(zone_id, force=force))
        for zone_id, payload in zip(zone_ids, fetched):
            zone_terminal_payloads[str(zone_id)] = payload
    enriched: List[dict] = []
    for zone_item in zone_items:
        if not isinstance(zone_item, dict):
            continue
        zone_id = _zone_item_id(zone_item)
        payload = zone_terminal_payloads.get(zone_id)
        raw_terminals = _remote_data_list(payload) if payload is not None else []
        terminals = [dict(item) for item in raw_terminals if _is_valid_zone_terminal_member(item)]
        merged_item = dict(zone_item)
        merged_item["terminal"] = _merge_zone_terminal_members(
            _terminal_members_from_zone_item(zone_item),
            terminals,
        )
        enriched.append(merged_item)
    _ttl_cache_set(cache_key, _clone_payload(enriched), _ZONETERMINAL_CACHE_TTL)
    return enriched


def _schedule_terminal_context(force: bool = False) -> Tuple[dict, dict]:
    items: list = []
    if _remote_enabled():
        try:
            if force:
                items = _remote_data_list(_remote_terminalinfo_payload(force=True))
            else:
                items = _remote_terminalinfo_items()
        except Exception:
            items = []
    if not items:
        try:
            items = _store_terminalinfo_items()
        except Exception:
            items = []
    lookup = _terminal_lookup_from_items(items)
    if _remote_enabled():
        try:
            zone_items = _fetch_enriched_zone_items(force=force)
            _enrich_lookup_zones_from_terzone(lookup, zone_items)
        except Exception:
            pass
    return lookup, _terminal_map_from_items(items)


def _remote_terminal_lookup() -> dict:
    cached = _cache_get("terminal_lookup")
    if isinstance(cached, dict):
        return cached
    items = _remote_terminalinfo_items()
    lookup = _terminal_lookup_from_items(items)
    try:
        zone_items = _fetch_enriched_zone_items()
        _enrich_lookup_zones_from_terzone(lookup, zone_items)
    except Exception:
        pass
    _cache_set("terminal_lookup", lookup)
    return lookup


def _task_location_binding_entries(task: Optional[dict]) -> List[dict]:
    if not isinstance(task, dict):
        return []
    location = task.get("location")
    if not isinstance(location, list):
        return []
    entries: List[dict] = []
    for raw_entry in location:
        if isinstance(raw_entry, list):
            parts = [str(value).strip() for value in raw_entry if str(value).strip()]
        elif isinstance(raw_entry, str):
            text = raw_entry.strip()
            parts = [text] if text else []
        else:
            parts = []
        if not parts:
            continue
        zone_name = str(parts[-2]).strip() if len(parts) >= 2 else ""
        terminal_token = str(parts[-1]).strip()
        entries.append(
            {
                "zone_name": zone_name,
                "terminal_token": terminal_token,
                "raw": parts,
            }
        )
    return entries


def _task_location_entry_for_terminal(
    task: Optional[dict],
    terminal_id: str,
    terminal_lookup: Optional[dict] = None,
) -> Optional[dict]:
    entries = _task_location_binding_entries(task)
    if not entries:
        return None
    lookup = terminal_lookup if isinstance(terminal_lookup, dict) else {}
    lookup_item = lookup.get(str(terminal_id), {}) if lookup else {}
    terminal_name = ""
    if isinstance(lookup_item, dict):
        terminal_name = str(lookup_item.get("name") or "").strip()
    compact_terminal_name = _compact_text(terminal_name)
    for entry in entries:
        token = str(entry.get("terminal_token") or "").strip()
        if not token:
            continue
        if token.isdigit() and token == str(terminal_id):
            return entry
        if compact_terminal_name and _compact_text(token) == compact_terminal_name:
            return entry
    if len(entries) == 1:
        return entries[0]
    return None


def _task_has_explicit_location_for_terminals(
    task: Optional[dict],
    terminal_ids: List[str],
    terminal_lookup: Optional[dict] = None,
) -> bool:
    if not isinstance(task, dict):
        return False
    has_explicit_terminal_ids = False
    value_list = task.get("terminalids") or task.get("terminal_ids") or task.get("liveterminalids")
    if isinstance(value_list, list) and any(value not in (None, "", 0, "0") for value in value_list):
        has_explicit_terminal_ids = True
    if not has_explicit_terminal_ids:
        for key in ("liveterminalid", "terminalid", "terminal_id"):
            if task.get(key) not in (None, "", 0, "0"):
                has_explicit_terminal_ids = True
                break
    if not has_explicit_terminal_ids:
        return False
    if not isinstance(task.get("location"), list):
        return False
    normalized_ids = _normalize_terminal_ids(terminal_ids)
    if not normalized_ids:
        return False
    for terminal_id in normalized_ids:
        if _task_location_entry_for_terminal(task, terminal_id, terminal_lookup) is None:
            return False
    return True


def _terzone_item_for_location_name(zone_name: str, zone_items: list) -> Optional[dict]:
    target = _compact_text(str(zone_name or ""))
    if not target:
        return None
    for item in zone_items:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("name") or item.get("zonename") or "").strip()
        item_id = item.get("id") or item.get("zone") or item.get("zoneid")
        aliases = [item_name]
        if item_id not in (None, ""):
            aliases.append(_zone_label(item_id))
        for alias in aliases:
            if _compact_text(alias) == target:
                return item
    return None


def _zone_item_contains_terminal(zone_item: dict, terminal_id: str, terminal_name: str = "") -> bool:
    terminals = zone_item.get("terminal")
    if not isinstance(terminals, list):
        return False
    compact_terminal_name = _compact_text(terminal_name)
    for item in terminals:
        if not isinstance(item, dict):
            continue
        item_terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if item_terminal_id is not None and str(item_terminal_id) == str(terminal_id):
            return True
        item_name = str(item.get("name") or "").strip()
        if compact_terminal_name and _compact_text(item_name) == compact_terminal_name:
            return True
    return False


def _zone_item_for_groupid(groupid: object, zone_items: object) -> Optional[dict]:
    target = str(_coerce_int(groupid, -1)).strip()
    if target in {"", "-1"}:
        return None
    for item in zone_items if isinstance(zone_items, list) else []:
        if not isinstance(item, dict):
            continue
        if _zone_item_id(item) == target:
            return item
    return None


def _terminal_name_from_binding(binding: object, terminal_lookup: Optional[dict] = None) -> str:
    if not isinstance(binding, dict):
        return ""
    terminal_name = str(binding.get("terminalname") or "").strip()
    if terminal_name:
        return terminal_name
    terminal_id = str(binding.get("terminalid") or "").strip()
    if terminal_id and isinstance(terminal_lookup, dict):
        lookup = terminal_lookup.get(terminal_id)
        if isinstance(lookup, dict) and lookup.get("name"):
            return str(lookup.get("name")).strip()
    return terminal_id


def _terminal_names_from_bindings(bindings: object, terminal_lookup: Optional[dict] = None) -> List[str]:
    names: List[str] = []
    for binding in _normalize_taskterminal_bindings(bindings):
        name = _terminal_name_from_binding(binding, terminal_lookup)
        if name:
            names.append(name)
    return _unique_list(names)


def _location_paths_from_taskterminal_bindings(
    bindings: object,
    terminal_lookup: Optional[dict] = None,
    zone_items: Optional[list] = None,
) -> list:
    normalized_bindings = _normalize_taskterminal_bindings(bindings)
    if not normalized_bindings:
        return []
    items = zone_items if isinstance(zone_items, list) else None
    if items is None and _remote_enabled():
        try:
            items = _fetch_enriched_zone_items()
        except Exception:
            items = []
    locations: List[list] = []
    seen: set[str] = set()
    for binding in normalized_bindings:
        terminal_name = _terminal_name_from_binding(binding, terminal_lookup)
        if not terminal_name:
            continue
        groupid = _coerce_int(binding.get("groupid"), 0)
        if not bool(binding.get("groupid_present")):
            lookup_item = (
                terminal_lookup.get(str(binding.get("terminalid")))
                if isinstance(terminal_lookup, dict)
                else None
            )
            if isinstance(lookup_item, dict):
                if _lookup_zone_is_ambiguous(lookup_item):
                    return []
                lookup_zone = lookup_item.get("zone")
                if lookup_zone not in (None, ""):
                    groupid = _coerce_int(lookup_zone, 0)
        if groupid == 0:
            zone_name = _zone_label(0)
        else:
            zone_item = _zone_item_for_groupid(groupid, items or [])
            if isinstance(zone_item, dict):
                zone_name = str(zone_item.get("name") or zone_item.get("zonename") or "").strip() or _zone_label(groupid)
            else:
                zone_name = _zone_label(groupid)
        entry = [zone_name, terminal_name]
        signature = json.dumps(entry, ensure_ascii=False)
        if signature in seen:
            continue
        seen.add(signature)
        locations.append(entry)
    return locations


def _format_hhmm(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) >= 5:
        return text[:5]
    return text


def _duration_minutes(value: object) -> int:
    parsed_seconds = _parse_hms_duration_seconds(value)
    if parsed_seconds is not None:
        number = float(parsed_seconds)
    else:
        try:
            number = float(value)
        except Exception:
            return 0
    if number >= 60:
        return max(1, round(number / 60))
    return max(1, round(number))


def _parse_clock_duration_seconds(text: str) -> Optional[int]:
    parts = [part.strip() for part in text.split(":")]
    if len(parts) not in {2, 3}:
        return None
    try:
        numbers = [int(part) for part in parts]
    except Exception:
        return None
    if any(number < 0 for number in numbers):
        return None
    if len(numbers) == 2:
        hours = 0
        minutes, seconds = numbers
    else:
        hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def _parse_hms_duration_seconds(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if " " in text and "-" in text:
        prefix, clock = text.split(" ", 1)
        day_parts = [part.strip() for part in prefix.split("-")]
        if len(day_parts) == 3:
            try:
                prefix_numbers = [int(part) for part in day_parts]
            except Exception:
                prefix_numbers = []
            if len(prefix_numbers) == 3 and all(number >= 0 for number in prefix_numbers):
                if prefix_numbers[0] >= 1 and prefix_numbers[1] >= 1 and prefix_numbers[2] >= 1:
                    clock_seconds = _parse_clock_duration_seconds(clock.strip())
                    if clock_seconds is not None:
                        try:
                            anchor = datetime(2000, 1, 1, 0, 0, 0)
                            target = datetime(
                                prefix_numbers[0],
                                prefix_numbers[1],
                                prefix_numbers[2],
                            ) + timedelta(seconds=clock_seconds)
                            delta = int((target - anchor).total_seconds())
                            if delta >= 0:
                                return delta
                        except Exception:
                            pass
                clock_seconds = _parse_clock_duration_seconds(clock.strip())
                if clock_seconds is not None:
                    return prefix_numbers[2] * 86400 + clock_seconds
    if ":" not in text:
        return None
    return _parse_clock_duration_seconds(text)


def _coerce_duration_int(value: object, default: int = 0) -> int:
    parsed_seconds = _parse_hms_duration_seconds(value)
    if parsed_seconds is not None:
        return max(1, parsed_seconds)
    try:
        return int(value)
    except Exception:
        return default


def _format_remote_duration_string(value: object, default_seconds: int = 1) -> str:
    total_seconds = _coerce_duration_int(value, default_seconds)
    total_seconds = max(1, total_seconds)
    return str(total_seconds)


def _location_paths_from_terminals(terminal_ids: list, terminal_lookup: dict) -> list:
    locations = []
    ambiguous = False
    for term_id in terminal_ids:
        lookup = terminal_lookup.get(str(term_id)) if terminal_lookup else None
        if not lookup:
            continue
        if _lookup_zone_is_ambiguous(lookup):
            ambiguous = True
            continue
        name = lookup.get("name")
        zone = lookup.get("zone")
        zone_name = str(lookup.get("zone_name") or "").strip() if isinstance(lookup, dict) else ""
        if name is None:
            continue
        if zone is not None and zone != "":
            locations.append([zone_name or _zone_label(zone), str(name)])
        else:
            locations.append([str(name)])
    if ambiguous:
        return []
    return locations


def _schedule_task_binding_match_keys(task: Optional[dict]) -> List[str]:
    if not isinstance(task, dict):
        return []
    task_name = _compact_text(
        str(task.get("taskname") or task.get("customName") or task.get("audio") or task.get("name") or "").strip()
    )
    starttime = _format_hhmmss(str(task.get("starttime") or task.get("time") or ""))
    if not task_name or not starttime:
        return []
    keys = [f"name_time:{task_name}|{starttime}"]
    media_id = task.get("mediaid") or task.get("media_id")
    if media_id not in (None, "", 0, "0"):
        keys.insert(0, f"name_time_mediaid:{task_name}|{starttime}|{media_id}")
    media_name = _compact_text(_clean_media_name(task.get("medianame") or task.get("audio") or ""))
    if media_name:
        keys.insert(1 if media_id not in (None, "", 0, "0") else 0, f"name_time_medianame:{task_name}|{starttime}|{media_name}")
    return _unique_list([key for key in keys if key])


def _schedule_task_terminal_binding_snapshot(task: Optional[dict]) -> Optional[dict]:
    if not isinstance(task, dict):
        return None
    terminal_ids = _normalize_terminal_ids(task.get("terminalids") or task.get("terminal_ids") or task.get("liveterminalids"))
    direct_terminal = task.get("liveterminalid") or task.get("terminalid") or task.get("terminal_id")
    if not terminal_ids and direct_terminal not in (None, "", 0, "0"):
        terminal_ids = [str(direct_terminal)]
    terminal_names = _normalize_str_list(task.get("terminalnames") or task.get("terminal_names") or task.get("liveterminalnames"))
    liveterminalname = str(
        task.get("liveterminalname") or task.get("terminalname") or task.get("terminal_name") or ""
    ).strip()
    if liveterminalname and not terminal_names:
        terminal_names = [liveterminalname]
    location = _clone_payload(task.get("location")) if isinstance(task.get("location"), list) else []
    if not terminal_ids and not location and not terminal_names and not liveterminalname:
        return None
    liveterminalid = ""
    if terminal_ids:
        liveterminalid = terminal_ids[0]
    elif direct_terminal not in (None, "", 0, "0"):
        liveterminalid = str(direct_terminal).strip()
    return {
        "terminalids": terminal_ids,
        "terminalnames": terminal_names,
        "liveterminalid": liveterminalid,
        "liveterminalname": liveterminalname or (terminal_names[0] if terminal_names else ""),
        "location": location,
    }


def _apply_schedule_task_terminal_binding_snapshot(task: dict, snapshot: dict) -> bool:
    if not isinstance(task, dict) or not isinstance(snapshot, dict):
        return False
    changed = False
    terminal_ids = _normalize_terminal_ids(snapshot.get("terminalids"))
    terminal_names = _normalize_str_list(snapshot.get("terminalnames"))
    liveterminalid = str(snapshot.get("liveterminalid") or "").strip()
    liveterminalname = str(snapshot.get("liveterminalname") or "").strip()
    location = _clone_payload(snapshot.get("location")) if isinstance(snapshot.get("location"), list) else []
    if terminal_ids and _normalize_terminal_ids(task.get("terminalids")) != terminal_ids:
        task["terminalids"] = terminal_ids
        changed = True
    if terminal_names and _normalize_str_list(task.get("terminalnames")) != terminal_names:
        task["terminalnames"] = terminal_names
        changed = True
    if liveterminalid and str(task.get("liveterminalid") or "").strip() != liveterminalid:
        task["liveterminalid"] = liveterminalid
        changed = True
    if liveterminalname and str(task.get("liveterminalname") or "").strip() != liveterminalname:
        task["liveterminalname"] = liveterminalname
        changed = True
    if location and (_clone_payload(task.get("location")) if isinstance(task.get("location"), list) else []) != location:
        task["location"] = location
        changed = True
    return changed


def _index_schedule_task_terminal_binding(task: Optional[dict], bindings_by_id: dict, bindings_by_key: dict) -> None:
    snapshot = _schedule_task_terminal_binding_snapshot(task)
    if not snapshot:
        return
    task_id = _task_real_id(task or {}) or _task_id(task or {})
    if task_id and task_id not in bindings_by_id:
        bindings_by_id[task_id] = snapshot
    for key in _schedule_task_binding_match_keys(task):
        bindings_by_key.setdefault(key, snapshot)


def _inherit_schedule_task_terminal_bindings(schedules: object) -> None:
    if not isinstance(schedules, list):
        return
    bindings_by_id: Dict[str, dict] = {}
    bindings_by_key: Dict[str, dict] = {}
    source_payload = _store_get("broadcast_schedules")
    source_schedules = source_payload.get("schedules") if isinstance(source_payload, dict) else []
    if isinstance(source_schedules, list):
        for schedule in source_schedules:
            tasks = schedule.get("tasks") if isinstance(schedule, dict) else None
            if not isinstance(tasks, list):
                continue
            for task in tasks:
                _index_schedule_task_terminal_binding(task, bindings_by_id, bindings_by_key)
    source_all_task = _store_get("all_task")
    source_rows = _remote_data_list(source_all_task) if isinstance(source_all_task, (dict, list)) else []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        if not str(row.get("sechename") or "").strip():
            continue
        _index_schedule_task_terminal_binding(row, bindings_by_id, bindings_by_key)
    for schedule in schedules:
        tasks = schedule.get("tasks") if isinstance(schedule, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if _task_has_explicit_terminal_binding(task):
                continue
            snapshot = None
            task_id = _task_real_id(task or {}) or _task_id(task or {})
            if task_id:
                snapshot = bindings_by_id.get(task_id)
            if snapshot is None:
                for key in _schedule_task_binding_match_keys(task):
                    snapshot = bindings_by_key.get(key)
                    if snapshot is not None:
                        break
            if snapshot is None:
                continue
            if _apply_schedule_task_terminal_binding_snapshot(task, snapshot):
                LOGGER.info(
                    "schedule task terminal binding inherited %s",
                    {
                        "schedule_name": _schedule_display_name(schedule) if isinstance(schedule, dict) else "",
                        "task_name": str(task.get("taskname") or task.get("customName") or task.get("audio") or ""),
                        "starttime": _format_hhmmss(str(task.get("starttime") or task.get("time") or "")),
                        "terminalids": _normalize_terminal_ids(task.get("terminalids")),
                    },
                )


def _validate_schedule_task_terminal_bindings(
    schedules: object,
    schedule_names: Optional[Collection[str]] = None,
) -> None:
    if not isinstance(schedules, list):
        return
    target_names = None
    if schedule_names is not None:
        target_names = {
            str(name).strip()
            for name in schedule_names
            if str(name).strip()
        }
        if not target_names:
            return
    missing: List[str] = []
    for schedule in schedules:
        schedule_name = _schedule_display_name(schedule) if isinstance(schedule, dict) else ""
        if target_names is not None and schedule_name not in target_names:
            continue
        tasks = schedule.get("tasks") if isinstance(schedule, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            terminal_ids = _normalize_terminal_ids(task.get("terminalids"))
            if not terminal_ids:
                direct_terminal = task.get("liveterminalid") or task.get("terminalid") or task.get("terminal_id")
                if direct_terminal not in (None, "", 0, "0"):
                    terminal_ids = [str(direct_terminal)]
            if terminal_ids:
                continue
            task_name = str(task.get("taskname") or task.get("customName") or task.get("audio") or "").strip() or "未命名任务"
            starttime = _format_hhmmss(str(task.get("starttime") or task.get("time") or ""))
            missing.append(f"{schedule_name}/{task_name}@{starttime or '00:00:00'}")
            LOGGER.warning(
                "schedule task missing terminal binding before remote sync %s",
                {
                    "schedule_name": schedule_name,
                    "task_name": task_name,
                    "starttime": starttime,
                    "terminalids": _normalize_terminal_ids(task.get("terminalids")),
                    "liveterminalid": str(task.get("liveterminalid") or ""),
                    "location": _clone_payload(task.get("location")) if isinstance(task.get("location"), list) else [],
                },
            )
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Missing terminal binding for schedule tasks: " + "; ".join(missing),
        )


def _apply_task_terminal_fields(
    task: dict,
    terminal_ids: List[str],
    terminal_lookup: dict,
    zone_items: Optional[list] = None,
) -> bool:
    if not isinstance(task, dict):
        return False
    before = {
        "terminalids": _normalize_terminal_ids(task.get("terminalids")),
        "liveterminalid": _coerce_int(task.get("liveterminalid"), 0),
        "liveterminalname": str(task.get("liveterminalname") or ""),
        "location": _clone_payload(task.get("location")) if isinstance(task.get("location"), list) else [],
    }
    normalized_ids = _normalize_terminal_ids(terminal_ids)
    preserve_explicit_location = _task_has_explicit_location_for_terminals(task, normalized_ids, terminal_lookup or {})
    binding_names = _terminal_names_from_bindings(task.get("taskterminal") or task.get("taskTerminal"), terminal_lookup)
    binding_location = _location_paths_from_taskterminal_bindings(
        task.get("taskterminal") or task.get("taskTerminal"),
        terminal_lookup,
        zone_items,
    )
    task["terminalids"] = normalized_ids
    if normalized_ids:
        first_id = normalized_ids[0]
        task["liveterminalid"] = _coerce_int(first_id, 0)
        resolved_liveterminalname = binding_names[0] if binding_names else ""
        lookup = terminal_lookup.get(str(first_id), {}) if isinstance(terminal_lookup, dict) else {}
        if not resolved_liveterminalname and isinstance(lookup, dict) and lookup.get("name"):
            resolved_liveterminalname = str(lookup.get("name"))
        if resolved_liveterminalname:
            task["liveterminalname"] = resolved_liveterminalname
        elif not task.get("liveterminalname"):
            task["liveterminalname"] = ""
        if binding_names:
            task["terminalnames"] = binding_names
        if binding_location:
            task["location"] = binding_location
        elif not preserve_explicit_location:
            location = _location_paths_from_terminals(normalized_ids, terminal_lookup)
            if location:
                task["location"] = location
            elif not isinstance(task.get("location"), list):
                task["location"] = []
    else:
        task["liveterminalid"] = 0
        task["liveterminalname"] = ""
        task["location"] = []
    after = {
        "terminalids": _normalize_terminal_ids(task.get("terminalids")),
        "liveterminalid": _coerce_int(task.get("liveterminalid"), 0),
        "liveterminalname": str(task.get("liveterminalname") or ""),
        "location": _clone_payload(task.get("location")) if isinstance(task.get("location"), list) else [],
    }
    return before != after


def _normalize_schedule_task_terminal(task: dict, terminal_lookup: dict, terminal_map: dict) -> bool:
    if not isinstance(task, dict):
        return False
    resolved_ids = _normalize_terminal_ids(
        _resolve_terminal_ids(
            task,
            terminal_map or {},
            remote_fallback=task,
            allow_default_fallback=False,
        )
    )
    if not resolved_ids:
        return False
    changed = _apply_task_terminal_fields(task, resolved_ids, terminal_lookup or {})
    resolved_names: List[str] = []
    for terminal_id in resolved_ids:
        lookup = terminal_lookup.get(str(terminal_id)) if isinstance(terminal_lookup, dict) else None
        if isinstance(lookup, dict) and lookup.get("name"):
            resolved_names.append(str(lookup.get("name")))
    resolved_names = _unique_list([value for value in resolved_names if value])
    existing_names = _normalize_str_list(task.get("terminalnames"))
    if resolved_names and existing_names != resolved_names:
        task["terminalnames"] = resolved_names
        changed = True
    if resolved_names and str(task.get("liveterminalname") or "") != resolved_names[0]:
        task["liveterminalname"] = resolved_names[0]
        changed = True
    return changed


def _normalize_schedule_task_terminals(
    schedules: object,
    *,
    terminal_lookup: Optional[dict] = None,
    terminal_map: Optional[dict] = None,
    force_terminal_lookup: bool = False,
) -> None:
    if not isinstance(schedules, list):
        return
    lookup = terminal_lookup if isinstance(terminal_lookup, dict) else None
    mapping = terminal_map if isinstance(terminal_map, dict) else None
    if lookup is None or mapping is None:
        lookup, mapping = _schedule_terminal_context(force=force_terminal_lookup)
    if not lookup and not mapping:
        return
    for schedule in schedules:
        tasks = schedule.get("tasks") if isinstance(schedule, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            _normalize_schedule_task_terminal(task, lookup or {}, mapping or {})


def _zone_label(zone: object) -> str:
    text = str(zone).strip()
    mapping = {
        "1": "区域一",
        "2": "区域二",
        "3": "区域三",
        "4": "区域四",
        "5": "区域五",
        "6": "区域六",
        "7": "区域七",
        "8": "区域八",
        "9": "区域九",
    }
    if not text or text == "0":
        return "无分区终端"
    if text in mapping:
        return mapping[text]
    return f"区域{text}"
def _terminal_ids_from_taskterminal(task_terminal: object) -> List[str]:
    """从 taskterminal 列表中提取所有终端ID"""
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
    return _unique_list([value for value in ids if value not in (None, "")])


def _terminal_names_from_taskterminal(task_terminal: object) -> List[str]:
    """从 taskterminal 列表中提取所有终端名称"""
    if not isinstance(task_terminal, list):
        return []
    names: List[str] = []
    for terminal_item in task_terminal:
        if not isinstance(terminal_item, dict):
            continue
        name = terminal_item.get("terminalname") or terminal_item.get("name")
        if name:
            names.append(str(name))
    return _unique_list([value for value in names if value])


def _taskterminal_binding_signature(binding: object) -> str:
    if not isinstance(binding, dict):
        return ""
    terminal_id = str(binding.get("terminalid") or binding.get("terminal_id") or binding.get("id") or "").strip()
    if not terminal_id or terminal_id == "0":
        return ""
    groupid = _coerce_int(
        binding.get("groupid")
        if binding.get("groupid") is not None
        else binding.get("group_id")
        if binding.get("group_id") is not None
        else binding.get("zone")
        if binding.get("zone") is not None
        else binding.get("zoneid"),
        0,
    )
    return f"{terminal_id}|{groupid}"


def _normalize_taskterminal_bindings(task_terminal: object) -> List[dict]:
    if not isinstance(task_terminal, list):
        return []
    bindings: List[dict] = []
    seen: set[str] = set()
    for terminal_item in task_terminal:
        if not isinstance(terminal_item, dict):
            continue
        terminal_id = (
            terminal_item.get("terminalid")
            or terminal_item.get("terminal_id")
            or terminal_item.get("id")
        )
        if terminal_id in (None, "", 0, "0"):
            continue
        if "groupid_present" in terminal_item:
            groupid_present = bool(terminal_item.get("groupid_present"))
        else:
            groupid_present = any(
                terminal_item.get(key) is not None
                for key in ("groupid", "group_id", "zone", "zoneid")
            )
        groupid = _coerce_int(
            terminal_item.get("groupid")
            if terminal_item.get("groupid") is not None
            else terminal_item.get("group_id")
            if terminal_item.get("group_id") is not None
            else terminal_item.get("zone")
            if terminal_item.get("zone") is not None
            else terminal_item.get("zoneid"),
            0,
        )
        binding = {
            "terminalid": str(terminal_id),
            "groupid": groupid,
            "groupid_present": groupid_present,
        }
        terminal_name = terminal_item.get("terminalname") or terminal_item.get("name")
        if terminal_name:
            binding["terminalname"] = str(terminal_name)
        signature = _taskterminal_binding_signature(binding)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        bindings.append(binding)
    bindings.sort(key=lambda item: (_coerce_int(item.get("terminalid"), 0), _coerce_int(item.get("groupid"), 0)))
    return bindings


def _explicit_taskterminal_bindings_for_terminal_ids_checked(
    task: Optional[dict],
    terminal_ids: list,
) -> Tuple[List[dict], str]:
    if not isinstance(task, dict):
        return [], "task-not-dict"
    normalized_terminal_ids = _unique_list([
        str(terminal_id)
        for terminal_id in (terminal_ids or [])
        if terminal_id not in (None, "", 0, "0")
    ])
    if not normalized_terminal_ids:
        return [], "no-target-terminals"
    bindings = _normalize_taskterminal_bindings(task.get("taskterminal") or task.get("taskTerminal"))
    if not bindings:
        return [], "missing-taskterminal"
    if any(not bool(binding.get("groupid_present")) for binding in bindings):
        return [], "missing-groupid-present"
    binding_terminal_ids = _unique_list([
        str(binding.get("terminalid"))
        for binding in bindings
        if binding.get("terminalid") not in (None, "", 0, "0")
    ])
    required_terminal_ids = set(normalized_terminal_ids)
    if not required_terminal_ids.issubset(set(binding_terminal_ids)):
        return [], "missing-target-coverage"
    filtered = [
        binding
        for binding in bindings
        if str(binding.get("terminalid")) in required_terminal_ids
    ]
    if not filtered:
        return [], "empty-filtered-bindings"
    return filtered, "covered"


def _explicit_taskterminal_bindings_for_terminal_ids(task: Optional[dict], terminal_ids: list) -> List[dict]:
    bindings, _ = _explicit_taskterminal_bindings_for_terminal_ids_checked(task, terminal_ids)
    return bindings


def _taskterminal_binding_signatures(task_terminal: object) -> List[str]:
    return [_taskterminal_binding_signature(binding) for binding in _normalize_taskterminal_bindings(task_terminal)]


def _remote_taskterminal_bindings_checked(task_id: str) -> Tuple[List[dict], bool]:
    if not task_id:
        return [], False
    try:
        resp = _remote_request("GET", f"/task/taskterminal/{task_id}")
        LOGGER.debug("查任务 %s 的终端,结果: %s", task_id, resp)
    except HTTPException:
        return [], False
    items = _remote_data_list(resp)
    return _normalize_taskterminal_bindings(items), True


def _remote_taskterminal_bindings(task_id: str) -> List[dict]:
    bindings, ok = _remote_taskterminal_bindings_checked(task_id)
    if not ok:
        return []
    return bindings

def _remote_task_terminal_ids_checked(task_id: str) -> Tuple[List[str], bool]:
    bindings, ok = _remote_taskterminal_bindings_checked(task_id)
    if not ok:
        return [], False
    ids = [binding.get("terminalid") for binding in bindings if binding.get("terminalid")]
    return _normalize_terminal_ids(ids), True


def _remote_task_terminal_ids(task_id: str) -> list:
    ids, ok = _remote_task_terminal_ids_checked(task_id)
    if not ok:
        return []
    return ids


def _remote_task_media_ids(task_id: str) -> list:
    if not task_id:
        return []
    try:
        resp = _remote_request("GET", f"/task/taskmusic/{task_id}")
    except HTTPException:
        return []
    items = _remote_data_list(resp)
    ids = []
    for item in items:
        if not isinstance(item, dict):
            continue
        media_id = item.get("mediaid") or item.get("id") or item.get("media_id")
        if media_id is not None:
            ids.append(media_id)
    return ids


def _remote_taskinfo_items_with_links(
    task_type: int,
    fill_media: bool = True,
    fill_terminal: bool = True,
) -> list:
    items = _remote_taskinfo_items(task_type)
    if not items:
        return []
    media_missing: List[str] = []
    terminal_missing: List[str] = []
    item_map: Dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        task_id = item.get("taskid") or item.get("id")
        if not task_id:
            continue
        if item.get("mediaid") is None:
            task_media = item.get("taskmedia") or item.get("taskMedia")
            if isinstance(task_media, list) and task_media:
                media_item = task_media[0]
                if isinstance(media_item, dict):
                    media_id = media_item.get("mediaid") or media_item.get("media_id") or media_item.get("id")
                    if media_id is not None:
                        item["mediaid"] = media_id
        task_id_str = str(task_id)
        item_map[task_id_str] = item
        if fill_media and item.get("mediaid") is None:
            media_missing.append(task_id_str)
        direct_terminal = (
            item.get("terminalid")
            or item.get("liveterminalid")
            or item.get("terminal_id")
            or item.get("ttsterminal")
        )
        if direct_terminal is None:
            task_terminal = item.get("taskterminal") or item.get("taskTerminal")
            if isinstance(task_terminal, list) and task_terminal:
                terminal_item = task_terminal[0]
                if isinstance(terminal_item, dict):
                    terminal_id = (
                        terminal_item.get("terminalid")
                        or terminal_item.get("terminal_id")
                        or terminal_item.get("id")
                    )
                    if terminal_id is not None:
                        item["liveterminalid"] = terminal_id
                        direct_terminal = terminal_id
        if fill_terminal and direct_terminal is None:
            terminal_missing.append(task_id_str)
    unique_media = _unique_list(media_missing)
    if unique_media and fill_media:
        fetched_media = _parallel_map(unique_media, _remote_task_media_ids)
        for task_id, media_ids in zip(unique_media, fetched_media):
            if not media_ids:
                continue
            item = item_map.get(task_id)
            if item is not None and item.get("mediaid") is None:
                item["mediaid"] = media_ids[0]
    unique_terminal = _unique_list(terminal_missing)
    if unique_terminal and fill_terminal:
        fetched_terminal = _parallel_map(unique_terminal, _remote_task_terminal_ids)
        for task_id, terminal_ids in zip(unique_terminal, fetched_terminal):
            if not terminal_ids:
                continue
            item = item_map.get(task_id)
            if not item:
                continue
            if (
                item.get("liveterminalid") is None
                and item.get("terminalid") is None
                and item.get("terminal_id") is None
            ):
                item["liveterminalid"] = terminal_ids[0]
    return items


def _apply_media_lookup_to_schedules(schedules: list, media_lookup: dict) -> None:
    if not isinstance(schedules, list):
        return

    # --- 建立本地备份索引(与 _map_remote_taskinfo_items 一致) ---
    local_backup: Dict[str, dict] = {}
    try:
        local_payload = _store_get("all_task")
        if isinstance(local_payload, dict):
            for t in local_payload.get("data", []):
                if isinstance(t, dict) and t.get("taskid"):
                    local_backup[str(t["taskid"])] = t
    except Exception:
        pass

    store_media = _store_media_lookup()

    # 收集所有需要远程深抓的 task_id
    media_fetch_ids: List[str] = []
    # task_id -> task 引用,方便后续回填
    task_index: Dict[str, dict] = {}

    for sched in schedules:
        tasks = sched.get("tasks") if isinstance(sched, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("taskid") or task.get("id") or "")

            # --- 阶段 1:本地备份回填 mediaid ---
            remote_mid = task.get("mediaid")
            if (remote_mid is None or str(remote_mid) == "0") and task_id and task_id in local_backup:
                local_mid = local_backup[task_id].get("mediaid")
                if local_mid and str(local_mid) != "0":
                    task["mediaid"] = local_mid
                if not task.get("medianame"):
                    local_name = local_backup[task_id].get("medianame")
                    if local_name:
                        task["medianame"] = local_name

            # --- 阶段 2:解析 taskmedia 列表 ---
            task_media = task.get("taskmedia") or task.get("taskMedia")
            if isinstance(task_media, list) and task_media:
                for media_item in task_media:
                    if not isinstance(media_item, dict):
                        continue
                    m_id = media_item.get("mediaid") or media_item.get("media_id") or media_item.get("id")
                    if m_id is not None and (task.get("mediaid") is None or str(task.get("mediaid")) == "0"):
                        task["mediaid"] = m_id
                    if not task.get("medianame"):
                        m_name = media_item.get("medianame") or media_item.get("name") or media_item.get("media_name")
                        if m_name:
                            task["medianame"] = str(m_name)

            # --- 阶段 3:如果仍缺 mediaid,加入远程深抓队列 ---
            check_mid = task.get("mediaid")
            if task_id and ((check_mid is None or str(check_mid) == "0") or REMOTE_TASKINFO_FILL_MEDIA):
                has_taskmedia = isinstance(task_media, list) and len(task_media) > 0
                if not has_taskmedia and (check_mid is None or str(check_mid) == "0"):
                    media_fetch_ids.append(task_id)
                    task_index[task_id] = task

    # --- 批量远程深抓媒体 ---
    unique_media = _unique_list(media_fetch_ids)
    if unique_media:
        fetched_media = _parallel_map(unique_media, _remote_task_media_ids)
        for tid, m_ids in zip(unique_media, fetched_media):
            normalized = _normalize_str_list(m_ids)
            if normalized and tid in task_index:
                task_index[tid]["mediaid"] = normalized[0]
                if len(normalized) > 1:
                    task_index[tid]["mediaids"] = normalized

    # --- 最终遍历:补全 medianame / audio ---
    for sched in schedules:
        tasks = sched.get("tasks") if isinstance(sched, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            mid = task.get("mediaid")
            mid_str = str(mid) if mid is not None else ""

            # 解析 medianame
            if not task.get("medianame") and mid_str and mid_str != "0":
                resolved = store_media.get(mid_str) or (media_lookup.get(mid_str) if media_lookup else None)
                if resolved:
                    task["medianame"] = str(resolved)

            # 解析 audio(与原逻辑兼容:只在 audio 缺失或等于 taskname 时覆盖)
            audio = task.get("audio")
            if audio and audio not in {task.get("taskname"), task.get("customName")}:
                continue
            media_name = task.get("medianame") or (media_lookup.get(mid_str, "") if media_lookup and mid_str else "")
            if media_name:
                task["audio"] = media_name
def _apply_terminal_lookup_to_schedules(schedules: list, terminal_lookup: dict) -> None:
    """为调度任务填充多终端信息(terminalids + location),含深度补全"""
    if not isinstance(schedules, list):
        return

    # --- 建立本地备份索引 ---
    zone_items: List[dict] = []
    if _remote_enabled():
        try:
            zone_items = _fetch_enriched_zone_items()
        except Exception:
            zone_items = []
    zone_items: List[dict] = []
    if _remote_enabled():
        try:
            zone_items = _fetch_enriched_zone_items()
        except Exception:
            zone_items = []
    local_backup: Dict[str, dict] = {}
    try:
        local_payload = _store_get("all_task")
        if isinstance(local_payload, dict):
            for t in local_payload.get("data", []):
                if isinstance(t, dict) and t.get("taskid"):
                    local_backup[str(t["taskid"])] = t
    except Exception:
        pass

    # 收集需要远程深抓终端的 task_id
    terminal_fetch_ids: List[str] = []
    task_index: Dict[str, dict] = {}

    for sched in schedules:
        tasks = sched.get("tasks") if isinstance(sched, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("taskid") or task.get("id") or "")

            # --- 阶段 1:从已有字段收集 terminal_ids ---
            terminal_ids: List[str] = []
            # 标记是否有可靠的多终端来源(terminalids列表或taskterminal)
            has_multi_source = False
            value_list = task.get("terminalids") or task.get("terminal_ids") or task.get("liveterminalids")
            if isinstance(value_list, list) and value_list:
                terminal_ids.extend(value_list)
                has_multi_source = True
            task_terminal = task.get("taskterminal") or task.get("taskTerminal")
            normalized_bindings = _normalize_taskterminal_bindings(task_terminal)
            if normalized_bindings:
                task["_resolved_taskterminal_bindings"] = normalized_bindings
            tt_ids = _terminal_ids_from_taskterminal(task_terminal)
            if tt_ids:
                terminal_ids.extend(tt_ids)
                has_multi_source = True
            for key in ("liveterminalid", "terminalid", "terminal_id", "ttsterminal"):
                value = task.get(key)
                if value not in (None, "") and str(value) != "0":
                    terminal_ids.append(value)
            terminal_ids = _unique_list([
                str(value)
                for value in terminal_ids
                if value not in (None, "") and str(value) != "0"
            ])

            # --- 阶段 2:本地备份回填 ---
            if not terminal_ids and task_id and task_id in local_backup:
                local_tid = local_backup[task_id].get("liveterminalid")
                if local_tid and str(local_tid) != "0":
                    terminal_ids.append(str(local_tid))
                local_tids = local_backup[task_id].get("terminalids")
                if isinstance(local_tids, list):
                    terminal_ids.extend([str(v) for v in local_tids if v not in (None, "") and str(v) != "0"])
                terminal_ids = _unique_list(terminal_ids)
                if len(terminal_ids) > 1:
                    has_multi_source = True

            # --- 阶段 3:远程深抓终端 ---
            # 触发条件: 完全没有终端 OR 只有单个liveterminalid但没有可靠的多终端来源
            # (远端 /task/sechetaskinfo 只返回 liveterminalid,不含完整终端绑定列表,
            #  必须通过 GET /task/taskterminal/{task_id} 获取真实绑定)
            needs_deep_fetch = (
                not terminal_ids
                or (not has_multi_source and len(terminal_ids) == 1)
            )
            if needs_deep_fetch and task_id and REMOTE_TASKINFO_FILL_TERMINAL:
                terminal_fetch_ids.append(task_id)
                task_index[task_id] = task
                # 保留已有的单终端作为兜底
                if terminal_ids:
                    task["_fallback_terminal_ids"] = terminal_ids
            elif terminal_ids:
                # 先暂存,后续统一处理名称
                task["_resolved_terminal_ids"] = terminal_ids

    # --- 批量远程深抓终端 ---
    unique_terminal = _unique_list(terminal_fetch_ids)
    if unique_terminal:
        fetched_terminal = _parallel_map(unique_terminal, _remote_taskterminal_bindings)
        for tid, bindings in zip(unique_terminal, fetched_terminal):
            normalized_bindings = _normalize_taskterminal_bindings(bindings)
            normalized = [
                str(binding.get("terminalid"))
                for binding in normalized_bindings
                if binding.get("terminalid") not in (None, "")
            ]
            if tid in task_index:
                if normalized:
                    task_index[tid]["_resolved_taskterminal_bindings"] = normalized_bindings
                    task_index[tid]["_resolved_terminal_ids"] = _unique_list(normalized)
                else:
                    # 远程深抓无结果,使用兜底的单终端
                    fallback = task_index[tid].pop("_fallback_terminal_ids", None)
                    if fallback:
                        task_index[tid]["_resolved_terminal_ids"] = fallback

    # --- 最终遍历:统一填充 terminalids / liveterminalid / location / terminalnames ---
    for sched in schedules:
        tasks = sched.get("tasks") if isinstance(sched, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("taskid") or task.get("id") or "")
            backup_task = local_backup.get(task_id) if task_id else None
            task.pop("_fallback_terminal_ids", None)
            resolved_bindings = _normalize_taskterminal_bindings(task.pop("_resolved_taskterminal_bindings", None))
            terminal_ids = task.pop("_resolved_terminal_ids", None)
            if not terminal_ids:
                # 最后兜底:从本地备份读 location
                if isinstance(backup_task, dict):
                    bak_loc = backup_task.get("location")
                    if bak_loc:
                        task["location"] = _clone_payload(bak_loc)
                    bak_tnames = backup_task.get("terminalnames")
                    if bak_tnames:
                        task["terminalnames"] = _clone_payload(bak_tnames)
                    bak_ltid = backup_task.get("liveterminalid")
                    if bak_ltid:
                        task["liveterminalid"] = bak_ltid
                    bak_tids = backup_task.get("terminalids")
                    if bak_tids:
                        task["terminalids"] = _clone_payload(bak_tids)
                continue
            task["terminalids"] = terminal_ids
            if task.get("liveterminalid") in (None, "", 0, "0"):
                task["liveterminalid"] = terminal_ids[0]
            binding_location = _location_paths_from_taskterminal_bindings(
                resolved_bindings,
                terminal_lookup,
                zone_items,
            )
            binding_terminal_names = _terminal_names_from_bindings(resolved_bindings, terminal_lookup)
            if terminal_lookup:
                source_task = _clone_payload(task)
                if not isinstance(source_task, dict):
                    source_task = dict(task)
                if isinstance(backup_task, dict):
                    if not isinstance(source_task.get("location"), list) and isinstance(backup_task.get("location"), list):
                        source_task["location"] = _clone_payload(backup_task.get("location"))
                    if not _normalize_terminal_ids(source_task.get("terminalids")):
                        backup_terminal_ids = _normalize_terminal_ids(backup_task.get("terminalids"))
                        if backup_terminal_ids:
                            source_task["terminalids"] = backup_terminal_ids
                    if source_task.get("liveterminalid") in (None, "", 0, "0"):
                        backup_terminal_id = backup_task.get("liveterminalid")
                        if backup_terminal_id not in (None, "", 0, "0"):
                            source_task["liveterminalid"] = backup_terminal_id
                preserve_explicit_location = _task_has_explicit_location_for_terminals(
                    source_task,
                    terminal_ids,
                    terminal_lookup,
                )
                if binding_location:
                    task["location"] = binding_location
                elif preserve_explicit_location:
                    if not isinstance(task.get("location"), list) and isinstance(backup_task, dict):
                        backup_location = backup_task.get("location")
                        if isinstance(backup_location, list):
                            task["location"] = _clone_payload(backup_location)
                else:
                    location = _location_paths_from_terminals(terminal_ids, terminal_lookup)
                    if location:
                        task["location"] = location
                    elif isinstance(backup_task, dict):
                        backup_location = backup_task.get("location")
                        if isinstance(backup_location, list):
                            task["location"] = _clone_payload(backup_location)
                terminal_names: List[str] = []
                for terminal_id_value in terminal_ids:
                    lookup = terminal_lookup.get(str(terminal_id_value))
                    if isinstance(lookup, dict) and lookup.get("name"):
                        terminal_names.append(str(lookup.get("name")))
                terminal_names = _unique_list([*binding_terminal_names, *terminal_names])
                terminal_names = _unique_list([value for value in terminal_names if value])
                if terminal_names:
                    task["terminalnames"] = terminal_names
                    task["liveterminalname"] = terminal_names[0]


def _task_backup_map_for_kind(kind: str) -> Dict[str, dict]:
    backup: Dict[str, dict] = {}
    payload = _store_get("broadcast_schedules")
    list_key = ""
    if kind == "broadcast":
        list_key = "broadcasts"
    elif kind == "livecast":
        list_key = "livecasts"
    if list_key and isinstance(payload, dict):
        items = payload.get(list_key)
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                task_id = _task_id(item)
                if task_id:
                    backup[str(task_id)] = item
    local_payload = _store_get("all_task")
    if isinstance(local_payload, dict):
        local_items = local_payload.get("data")
        if isinstance(local_items, list):
            for item in local_items:
                if not isinstance(item, dict):
                    continue
                task_id = _task_id(item)
                if task_id and str(task_id) not in backup:
                    backup[str(task_id)] = item
    return backup


def _normalize_view_task(task: dict, kind: str = "") -> dict:
    """
    前端视图数据清洗器:把数据库的 Raw 字段翻译成前端 Vue 需要的 View 字段
    """
    if not isinstance(task, dict):
        return {}
    
    # 1. 翻译名字 (taskname -> name)
    if not task.get("name") and task.get("taskname"):
        task["name"] = str(task.get("taskname"))
    
    # 2. 翻译音频 (medianame -> audio)
    if not task.get("audio"):
        task["audio"] = str(task.get("medianame") or task.get("taskname") or "")

    # 3. 翻译时间 (starttime -> time)
    if not task.get("time") and task.get("starttime"):
        task["time"] = _format_hhmm(task.get("starttime"))

    # 4. 翻译时长模式 (timelengthtype -> durationMode)
    if not task.get("durationMode"):
        # 默认值处理
        tl_type = str(task.get("timelengthtype", "1"))
        tl_val = _coerce_duration_int(task.get("timelength"), 1)
        
        if tl_type == "2": # 类型2代表循环次数
            task["durationMode"] = "loop"
            task["loop"] = tl_val
            task["duration"] = "1"
        else: # 其他代表时长
            task["durationMode"] = "duration"
            if kind == "broadcast":
                task["duration"] = str(max(1, tl_val))
            else:
                task["duration"] = str(_duration_minutes(tl_val))
            task["loop"] = 1
            
    # 5. 确保 id 存在
    if not task.get("id") and task.get("taskid"):
        task["id"] = task.get("taskid")

    return task
def _enrich_task_links(tasks: list, media_lookup: dict, terminal_lookup: dict) -> None:
    if not isinstance(tasks, list):
        return
    resolved_media_lookup = media_lookup if isinstance(media_lookup, dict) else {}
    resolved_terminal_lookup = terminal_lookup if isinstance(terminal_lookup, dict) else {}
    backup_map: Dict[str, dict] = {}
    try:
        backup_payload = _store_get("all_task")
        if isinstance(backup_payload, dict):
            for row in backup_payload.get("data") or []:
                if not isinstance(row, dict):
                    continue
                task_id = str(row.get("taskid") or row.get("id") or "").strip()
                if task_id:
                    backup_map[task_id] = row
    except Exception:
        backup_map = {}

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("taskid") or task.get("id") or "").strip()
        backup_task = backup_map.get(task_id)

        media_ids = _normalize_str_list(task.get("mediaids"))
        media_names = _normalize_str_list(task.get("medianames"))
        task_media = task.get("taskmedia") or task.get("taskMedia")
        if isinstance(task_media, list):
            for media_item in task_media:
                if not isinstance(media_item, dict):
                    continue
                media_id = media_item.get("mediaid") or media_item.get("media_id") or media_item.get("id")
                if media_id not in (None, "", 0, "0"):
                    media_ids.append(str(media_id))
                media_name = media_item.get("medianame") or media_item.get("name") or media_item.get("media_name")
                if media_name:
                    media_names.append(str(media_name))
        if not media_ids and task_id:
            try:
                media_ids = _normalize_str_list(_remote_task_media_ids(task_id))
            except Exception:
                media_ids = []
        if not media_ids and isinstance(backup_task, dict):
            backup_media_id = backup_task.get("mediaid")
            if backup_media_id not in (None, "", 0, "0"):
                media_ids = [str(backup_media_id)]
        if task.get("medianame"):
            media_names.append(str(task.get("medianame")))
        for media_id in media_ids:
            resolved_name = resolved_media_lookup.get(str(media_id))
            if resolved_name:
                media_names.append(str(resolved_name))
        if isinstance(backup_task, dict) and backup_task.get("medianame"):
            media_names.append(str(backup_task.get("medianame")))
        media_ids = _normalize_str_list(media_ids)
        media_names = _normalize_str_list(media_names)
        if media_ids:
            task["mediaid"] = media_ids[0]
            if len(media_ids) > 1:
                task["mediaids"] = media_ids
        if media_names:
            task["medianame"] = media_names[0]
            task["audio"] = _join_media_names(media_names)

        terminal_ids = _normalize_terminal_ids(task.get("terminalids"))
        terminal_names = _normalize_str_list(task.get("terminalnames"))
        task_terminal = task.get("taskterminal") or task.get("taskTerminal")
        terminal_ids.extend(_terminal_ids_from_taskterminal(task_terminal))
        terminal_names.extend(_terminal_names_from_taskterminal(task_terminal))
        direct_terminal_id = task.get("liveterminalid") or task.get("terminalid") or task.get("terminal_id")
        if direct_terminal_id not in (None, "", 0, "0"):
            terminal_ids.append(str(direct_terminal_id))
        direct_terminal_name = task.get("liveterminalname") or task.get("terminalname") or task.get("terminal_name")
        if direct_terminal_name:
            terminal_names.append(str(direct_terminal_name))
        terminal_ids = _normalize_terminal_ids(terminal_ids)
        if not terminal_ids and task_id:
            try:
                terminal_ids = _normalize_terminal_ids(_remote_task_terminal_ids(task_id))
            except Exception:
                terminal_ids = []
        if not terminal_ids and isinstance(backup_task, dict):
            backup_terminal_ids = _normalize_terminal_ids(backup_task.get("terminalids"))
            if backup_terminal_ids:
                terminal_ids = backup_terminal_ids
            else:
                backup_terminal_id = backup_task.get("liveterminalid")
                if backup_terminal_id not in (None, "", 0, "0"):
                    terminal_ids = [str(backup_terminal_id)]
        for terminal_id in terminal_ids:
            lookup_item = resolved_terminal_lookup.get(str(terminal_id))
            if isinstance(lookup_item, dict):
                terminal_name = str(lookup_item.get("name") or "").strip()
                if terminal_name:
                    terminal_names.append(terminal_name)
        if isinstance(backup_task, dict):
            terminal_names.extend(_normalize_str_list(backup_task.get("terminalnames")))
            backup_terminal_name = str(backup_task.get("liveterminalname") or "").strip()
            if backup_terminal_name:
                terminal_names.append(backup_terminal_name)
        terminal_ids = _normalize_terminal_ids(terminal_ids)
        terminal_names = _normalize_str_list(terminal_names)
        if terminal_ids:
            task["terminalids"] = terminal_ids
            task["liveterminalid"] = terminal_ids[0]
        if terminal_names:
            task["terminalnames"] = terminal_names
            task["liveterminalname"] = terminal_names[0]

        if isinstance(task.get("location"), list) and task.get("location"):
            continue
        location = _location_paths_from_terminals(terminal_ids, resolved_terminal_lookup)
        if not location and isinstance(backup_task, dict) and isinstance(backup_task.get("location"), list):
            location = _clone_payload(backup_task.get("location"))
        if location:
            task["location"] = location


def _map_remote_taskinfo_items(items: list, media_lookup: dict, terminal_lookup: dict, kind: str) -> list:
    LOGGER.debug("终端字典内容: %s", terminal_lookup)
    rows = []
    media_cache: Dict[str, list] = {}
    media_name_cache: Dict[str, list] = {}
    terminal_cache: Dict[str, list] = {}
    terminal_binding_cache: Dict[str, list] = {}
    media_fetch_ids: List[str] = []
    terminal_missing: List[str] = []
    store_media_lookup = _store_media_lookup()
    zone_items: List[dict] = []
    if _remote_enabled():
        try:
            zone_items = _fetch_enriched_zone_items()
        except Exception:
            zone_items = []

    # === 【新增步骤 1】建立本地数据备份索引 ===
    # 目的:如果远端返回的 ID 是 0,我们就去本地找找看有没有旧数据,用来填补空白
    local_backup: Dict[str, dict] = {}
    try:
        local_backup = _task_backup_map_for_kind(kind)
    except Exception:
        local_backup = {}

    # === 第一轮遍历:检查缺失数据并尝试从本地回填 ===
    for item in items or []:
        if not isinstance(item, dict) or not _has_task_details(item):
            continue
        
        task_id = str(item.get("taskid") or item.get("id") or "")
        if not task_id:
            continue

        # 1. 尝试回填 Media ID (如果远端是 0 或 None)
        remote_mid = item.get("mediaid")
        if remote_mid is None or str(remote_mid) == "0":
            # 远端没数据,查查本地备份
            if task_id in local_backup:
                local_mid = local_backup[task_id].get("mediaid")
                if local_mid and str(local_mid) != "0":
                    item["mediaid"] = local_mid # 回填成功！
                # 【修复问题#2】级联回填其他媒体信息字段
                if not item.get("medianame"):
                    local_name = local_backup[task_id].get("medianame")
                    if local_name:
                        item["medianame"] = local_name
        
        # 2. 尝试回填 Terminal ID
        remote_tid = item.get("terminalid") or item.get("liveterminalid") or item.get("terminal_id")
        if remote_tid is None or str(remote_tid) == "0":
            # 远端没数据,查查本地备份
            if task_id in local_backup:
                local_tid = local_backup[task_id].get("liveterminalid")
                if local_tid and str(local_tid) != "0":
                    item["liveterminalid"] = local_tid # 回填成功！
                # 【修复问题#2】级联回填其他终端信息字段
                if not item.get("liveterminalname"):
                    local_term_name = local_backup[task_id].get("liveterminalname")
                    if local_term_name:
                        item["liveterminalname"] = local_term_name
                # 回填终端列表
                if not item.get("terminalids"):
                    local_term_ids = local_backup[task_id].get("terminalids")
                    if local_term_ids:
                        item["terminalids"] = local_term_ids

        # 3. 处理 taskmedia 列表 (你原本的逻辑)
        task_media = item.get("taskmedia") or item.get("taskMedia")
        task_media_ids = []
        task_media_names = []
        if isinstance(task_media, list) and task_media:
            for media_item in task_media:
                if not isinstance(media_item, dict):
                    continue
                m_id = media_item.get("mediaid") or media_item.get("media_id") or media_item.get("id")
                if m_id is not None:
                    task_media_ids.append(m_id)
                m_name = media_item.get("medianame") or media_item.get("name") or media_item.get("media_name")
                if m_name:
                    task_media_names.append(str(m_name))
                if not item.get("medianame") and media_item.get("medianame"):
                    item["medianame"] = media_item.get("medianame")
        
        if task_media_ids:
            media_cache[task_id] = task_media_ids
            if item.get("mediaid") is None:
                item["mediaid"] = task_media_ids[0]
        
        if task_media_names:
            media_name_cache[task_id] = task_media_names

        # 4. 如果还是没有 Media ID,加入待抓取列表 (Deep Fetch)
        if not task_media_ids:
            if item.get("mediaid") is not None and str(item.get("mediaid")) != "0":
                media_cache[task_id] = [item.get("mediaid")]
            
            # 检查是否需要远程抓取
            check_mid = item.get("mediaid")
            if (check_mid is None or str(check_mid) == "0") or REMOTE_TASKINFO_FILL_MEDIA:
                media_fetch_ids.append(task_id)

        # 5. If terminal list missing, fetch from remote
        value_list = item.get("terminalids") or item.get("terminal_ids") or item.get("liveterminalids")
        list_ids: List[str] = []
        if isinstance(value_list, list):
            list_ids.extend([str(value) for value in value_list if value not in (None, "")])
        task_terminal = item.get("taskterminal") or item.get("taskTerminal")
        normalized_bindings = _normalize_taskterminal_bindings(task_terminal)
        if normalized_bindings:
            terminal_binding_cache[task_id] = normalized_bindings
        list_ids.extend(_terminal_ids_from_taskterminal(task_terminal))
        list_ids = _unique_list([str(value) for value in list_ids if value not in (None, "")])
        if REMOTE_TASKINFO_FILL_TERMINAL and not list_ids:
            terminal_missing.append(task_id)

    # === 批量抓取逻辑 (保持不变) ===
    unique_media = _unique_list(media_fetch_ids)
    if unique_media:
        fetched_media = _parallel_map(unique_media, _remote_task_media_ids)
        for task_id, m_ids in zip(unique_media, fetched_media):
            normalized = _normalize_str_list(m_ids)
            if not normalized: continue
            if task_id in media_cache:
                media_cache[task_id] = _normalize_str_list(media_cache[task_id] + normalized)
            else:
                media_cache[task_id] = normalized

    unique_terminal = _unique_list(terminal_missing)
    if unique_terminal:
        fetched_terminal = _parallel_map(unique_terminal, _remote_taskterminal_bindings)
        for task_id, bindings in zip(unique_terminal, fetched_terminal):
            normalized_bindings = _normalize_taskterminal_bindings(bindings)
            terminal_binding_cache[task_id] = normalized_bindings
            terminal_cache[task_id] = [
                str(binding.get("terminalid"))
                for binding in normalized_bindings
                if binding.get("terminalid") not in (None, "")
            ]

    # === 第二轮遍历:构建最终结果 ===
    for idx, item in enumerate(items or []):
        if not isinstance(item, dict) or not _has_task_details(item):
            continue
        
        task_id = item.get("taskid") or item.get("id") or f"{kind}-{idx}"
        task_id_str = str(task_id)
        
        # 1. 确定最终的 Media ID
        media_ids = _normalize_str_list(media_cache.get(task_id_str))
        if not media_ids:
            direct_media_id = item.get("mediaid")
            if direct_media_id is not None and str(direct_media_id) != "0":
                media_ids = _normalize_str_list([direct_media_id])
        
        # 2. 确定 Media Names (用于前端 audio 字段)
        media_names = []
        for media_id_value in media_ids:
            resolved = store_media_lookup.get(str(media_id_value)) or media_lookup.get(str(media_id_value))
            if resolved:
                media_names.append(str(resolved))
        
        cached_names = media_name_cache.get(task_id_str, [])
        if cached_names:
            media_names.extend(cached_names)
        
        item_medianame = item.get("medianame")
        if item_medianame:
            media_names.append(str(item_medianame))
            
        media_names = _normalize_str_list(media_names)
        
        # 如果还没找到名字,尝试从本地备份里找
        if not media_names and task_id_str in local_backup:
            bak_name = local_backup[task_id_str].get("medianame")
            if bak_name:
                media_names.append(str(bak_name))

        audio = _join_media_names(media_names)
        media_id = media_ids[0] if media_ids else None

        # 3. 确定最终的 Terminal IDs
        terminal_ids: List[str] = []
        value_list = item.get("terminalids") or item.get("terminal_ids") or item.get("liveterminalids")
        if isinstance(value_list, list):
            terminal_ids.extend([str(value) for value in value_list if value not in (None, "")])
        task_terminal = item.get("taskterminal") or item.get("taskTerminal")
        resolved_bindings = _normalize_taskterminal_bindings(
            terminal_binding_cache.get(task_id_str) or task_terminal
        )
        terminal_ids.extend(_terminal_ids_from_taskterminal(task_terminal))
        cache_ids = terminal_cache.get(task_id_str, [])
        if cache_ids:
            terminal_ids.extend([str(value) for value in cache_ids if value not in (None, "")])
        direct_terminal = (
            item.get("terminalid") or item.get("liveterminalid") 
            or item.get("terminal_id") or item.get("ttsterminal")
        )
        if direct_terminal is not None and str(direct_terminal) != "0":
            terminal_ids.append(str(direct_terminal))
        if resolved_bindings:
            terminal_ids.extend(
                [
                    str(binding.get("terminalid"))
                    for binding in resolved_bindings
                    if binding.get("terminalid") not in (None, "")
                ]
            )
        terminal_ids = _unique_list([str(value) for value in terminal_ids if value not in (None, "")])
        if not terminal_ids:
            terminal_ids = [str(value) for value in _remote_task_terminal_ids(task_id_str) if value not in (None, "")]
        terminal_ids = _unique_list([str(value) for value in terminal_ids if value not in (None, "")])
        
        # 4. 构建基础字段
        name = item.get("taskname") or item.get("name") or item.get("medianame") or f"任务{idx + 1}"
        starttime = item.get("starttime") or "00:00:00"
        time_str = _format_hhmm(starttime)
        timelength = item.get("timelength") or item.get("length") or 1
        timelengthtype = item.get("timelengthtype") or item.get("lengthtype")
        
        duration_mode = "loop" if str(timelengthtype) == "2" else "duration"
        loop = int(timelength) if duration_mode == "loop" else 1
        if duration_mode == "loop":
            duration = "1"
        elif kind == "broadcast":
            duration = str(_coerce_duration_int(timelength, 1))
        else:
            duration = str(_duration_minutes(timelength))
        volume = _coerce_int(item.get("volume"), 50)
        status = _task_status_from_remote(item)
        
        task_state_int = _coerce_int(item.get("taskstate"), 0) 
        enable_state_int = _coerce_int(item.get("enablestate"), 1)

        backup_task = local_backup.get(task_id_str) if task_id_str in local_backup else None
        source_task = _clone_payload(item)
        if not isinstance(source_task, dict):
            source_task = dict(item)
        if isinstance(backup_task, dict):
            if not isinstance(source_task.get("location"), list) and isinstance(backup_task.get("location"), list):
                source_task["location"] = _clone_payload(backup_task.get("location"))
            if not _normalize_terminal_ids(source_task.get("terminalids")):
                backup_terminal_ids = _normalize_terminal_ids(backup_task.get("terminalids"))
                if backup_terminal_ids:
                    source_task["terminalids"] = backup_terminal_ids
            if source_task.get("liveterminalid") in (None, "", 0, "0"):
                backup_terminal_id = backup_task.get("liveterminalid")
                if backup_terminal_id not in (None, "", 0, "0"):
                    source_task["liveterminalid"] = backup_terminal_id
            if not _normalize_str_list(source_task.get("terminalnames")):
                backup_terminal_names = _normalize_str_list(backup_task.get("terminalnames"))
                if backup_terminal_names:
                    source_task["terminalnames"] = backup_terminal_names
            if not str(source_task.get("liveterminalname") or "").strip():
                backup_terminal_name = str(backup_task.get("liveterminalname") or "").strip()
                if backup_terminal_name:
                    source_task["liveterminalname"] = backup_terminal_name
        preserve_explicit_location = _task_has_explicit_location_for_terminals(
            source_task,
            terminal_ids,
            terminal_lookup,
        )
        binding_location = _location_paths_from_taskterminal_bindings(
            resolved_bindings,
            terminal_lookup,
            zone_items,
        )
        binding_terminal_names = _terminal_names_from_bindings(resolved_bindings, terminal_lookup)
        location_source = "lookup"
        if binding_location:
            location = binding_location
            location_source = "taskterminal"
        elif preserve_explicit_location:
            if isinstance(backup_task, dict) and isinstance(backup_task.get("location"), list):
                location = _clone_payload(backup_task.get("location"))
                location_source = "backup"
            elif isinstance(item.get("location"), list):
                location = _clone_payload(item.get("location"))
                location_source = "item"
            else:
                location = _clone_payload(source_task.get("location")) if isinstance(source_task.get("location"), list) else []
                location_source = "item"
        else:
            location = _location_paths_from_terminals(terminal_ids, terminal_lookup)
            if not location and isinstance(backup_task, dict):
                backup_location = backup_task.get("location")
                if isinstance(backup_location, list):
                    location = _clone_payload(backup_location)
                    location_source = "backup"
        _debug_remote(
            "taskinfo location resolved",
            kind=kind,
            task_id=task_id_str,
            terminal_ids=_clone_payload(terminal_ids),
            preserve_explicit_location=preserve_explicit_location,
            location_source=location_source,
            final_location=_clone_payload(location),
        )
        row = {
            "id": task_id,
            "name": str(name),
            "status": status,
            "volume": volume,
            "audio": str(audio),
            "time": time_str,
            "duration": duration,
            "loop": loop,
            "durationMode": duration_mode,
            "location": location,
            "taskstate": task_state_int,
            "enablestate": enable_state_int,
        }
        
        if media_id is not None:
            row["mediaid"] = media_id
        if media_ids and len(media_ids) > 1:
            row["mediaids"] = media_ids
        if media_names:
            row["medianame"] = audio
            if len(media_names) > 1:
                row["medianames"] = media_names
        if terminal_ids:
            row["liveterminalid"] = terminal_ids[0]
            row["terminalids"] = terminal_ids
            terminal_names: List[str] = []
            for terminal_id_value in terminal_ids:
                lookup = terminal_lookup.get(str(terminal_id_value)) if terminal_lookup else None
                if isinstance(lookup, dict) and lookup.get("name"):
                    terminal_names.append(str(lookup.get("name")))
            terminal_names.extend(binding_terminal_names)
            item_terminal_name = item.get("terminalname") or item.get("liveterminalname")
            if item_terminal_name:
                terminal_names.append(str(item_terminal_name))
            terminal_names = _unique_list([value for value in terminal_names if value])
            if terminal_names:
                row["terminalnames"] = terminal_names
            _debug_remote(
                "taskinfo terminal resolved",
                kind=kind,
                task_id=task_id_str,
                task_name=str(name),
                terminal_ids=_clone_payload(terminal_ids),
                terminal_names=_clone_payload(terminal_names),
                liveterminalid=row.get("liveterminalid"),
                liveterminalname=str(item_terminal_name or (terminal_names[0] if terminal_names else "")),
                final_location=_clone_payload(location),
            )
        
        if kind == "broadcast":
            row["emergency"] = False
            
        rows.append(row)
        
    return rows

def _resolve_media_id(task: dict, media_map: dict) -> Optional[str]:
    media_id = task.get("mediaid") or task.get("media_id")
    if media_id is not None:
        return str(media_id)
    audio_name = (
        task.get("audio")
        or task.get("medianame")
        or task.get("taskname")
        or task.get("customName")
        or task.get("name")
    )
    match = _match_media_from_map(audio_name, media_map)
    if match:
        return str(match[0])
    return None


def _resolve_terminal_id(task: dict, terminal_map: dict) -> Optional[str]:
    terminal_ids = _resolve_terminal_ids(task or {}, terminal_map, allow_default_fallback=True)
    if terminal_ids:
        return str(terminal_ids[0])
    return None


def _compact_text(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[\s\-_.·•—~]+", "", value).lower()

def _best_text_match(text: str, candidates: List[str]) -> str:
    if not text:
        return ""
    text_lower = text.lower()
    compact_text = _compact_text(text)
    best = ""
    for candidate in candidates:
        cand = str(candidate or "").strip()
        if len(cand) < 2:
            continue
        if cand in text or cand.lower() in text_lower:
            if len(cand) > len(best):
                best = cand
            continue
        cand_compact = _compact_text(cand)
        if cand_compact and cand_compact in compact_text:
            if len(cand) > len(best):
                best = cand
    return best

def _match_media_from_map(audio_name: Optional[str], media_map: dict) -> Optional[Tuple[str, str]]:
    """
    【升级版】使用 difflib 进行高精度模糊匹配,解决"任务一"变"任务二"的问题。
    """
    LOGGER.debug("匹配侦探 - 正在寻找: '%s'", audio_name)
    if not audio_name or not media_map:
        return None
        
    target = str(audio_name).strip()
    target_lower = target.lower()
    
    # === 1. 第一轮:绝对精确匹配 (优先级最高) ===
    # 如果名字一模一样,直接返回,不要犹豫
    for name, media_id in media_map.items():
        if str(name) == target:
            return str(media_id), str(name)

    # === 2. 第二轮:相似度打分 (解决"一"和"二"混淆的问题) ===
    best_score = 0.0
    best_match = None
    
    for name, media_id in media_map.items():
        candidate = str(name)
        
        # 使用 Python 标准库 difflib 计算两个字符串的相似度 (0.0 ~ 1.0)
        # 例如:"测试任务一" vs "测试任务一" -> 1.0
        #       "测试任务一" vs "测试任务二" -> 0.8
        score = difflib.SequenceMatcher(None, target, candidate).ratio()
        
        # 只有相似度超过 0.4 (40%) 才算候选,避免匹配到完全不相干的东西
        if score > 0.4 and score > best_score:
            best_score = score
            best_match = (str(media_id), candidate)
            
    # === 3. 第三轮:包含匹配 (兜底) ===
    # 如果相似度都很低(比如用户只说了简称"任务一"),再试一次包含匹配
    if best_match is None:
        best_len_diff = 1000
        for name, media_id in media_map.items():
            candidate = str(name)
            candidate_lower = candidate.lower()
            
            # 双向包含检测
            if target_lower in candidate_lower or candidate_lower in target_lower:
                # 越短的长度差越好
                diff = abs(len(candidate) - len(target))
                if diff < best_len_diff:
                    best_len_diff = diff
                    best_match = (str(media_id), candidate)

    return best_match

def _resolve_media_id_with_fallback(
    task: dict,
    media_map: dict,
    remote_fallback: Optional[dict] = None,
) -> Optional[str]:
    media_id = _resolve_media_id(task, media_map)
    if media_id:
        return str(media_id)
    if not remote_fallback:
        return None
    media_id = remote_fallback.get("mediaid") or remote_fallback.get("media_id")
    if media_id is not None:
        return str(media_id)
    candidate = (
        remote_fallback.get("medianame")
        or remote_fallback.get("taskname")
        or remote_fallback.get("name")
    )
    match = _match_media_from_map(candidate, media_map)
    if match:
        return str(match[0])
    return None

def _weekdays_from_execmode(value: object) -> List[str]:
    """
    从远端的 execmode 位掩码中提取星期列表
    远端编码(7位二进制,从高位到低位):周日 周一 周二 周三 周四 周五 周六
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

    days = [label for bit, label in mapping if num & bit]
    return days


def _execmode_from_weekdays(weekdays: object) -> int:
    """
    将星期列表转换为远端的 execmode 位掩码
    远端编码(7位二进制,从高位到低位):周日 周一 周二 周三 周四 周五 周六
    即: bit6=周日(64), bit5=周一(32), bit4=周二(16), bit3=周三(8),
        bit2=周四(4), bit1=周五(2), bit0=周六(1)
    """
    if not isinstance(weekdays, list):
        return 0

    mapping = {
        "周一": 32,   # bit5
        "周二": 16,   # bit4
        "周三": 8,    # bit3
        "周四": 4,    # bit2
        "周五": 2,    # bit1
        "周六": 1,    # bit0
        "周日": 64,   # bit6
        "周天": 64,   # 周日别名
    }

    value = 0
    for day in weekdays:
        bit = mapping.get(str(day))
        if bit:
            value |= bit
    return value
def _resolve_terminal_ids(
    task: dict,
    terminal_map: dict,
    remote_fallback: Optional[dict] = None,
    allow_default_fallback: bool = True,
) -> list:
    explicit_taskterminal_ids = _normalize_terminal_ids(
        _terminal_ids_from_taskterminal(task.get("taskterminal") or task.get("taskTerminal"))
    ) if isinstance(task, dict) else []
    if explicit_taskterminal_ids:
        return explicit_taskterminal_ids
    fallback_taskterminal_ids = _normalize_terminal_ids(
        _terminal_ids_from_taskterminal(remote_fallback.get("taskterminal") or remote_fallback.get("taskTerminal"))
    ) if isinstance(remote_fallback, dict) else []
    if fallback_taskterminal_ids:
        return fallback_taskterminal_ids
    ids: List[str] = []
    # 👇 先处理 terminalids 列表
    value_list = task.get("terminalids") or task.get("terminal_ids") or task.get("liveterminalids")
    if isinstance(value_list, list):
        ids.extend([str(value) for value in value_list if value not in (None, "")])
    # 👇 再处理单个终端ID
    for key in ("liveterminalid", "terminalid", "terminal_id"):
        value = task.get(key)
        if value is not None:
            ids.append(str(value))
    if remote_fallback:
        # 👇 fallback 也要处理列表
        fallback_list = (
            remote_fallback.get("terminalids")
            or remote_fallback.get("terminal_ids")
            or remote_fallback.get("liveterminalids")
        )
        if isinstance(fallback_list, list):
            ids.extend([str(value) for value in fallback_list if value not in (None, "")])
        for key in ("liveterminalid", "terminalid", "terminal_id"):
            value = remote_fallback.get(key)
            if value is not None:
                ids.append(str(value))
    location = task.get("location")
    if isinstance(location, list):
        for entry in location:
            candidate = None
            if isinstance(entry, list) and entry:
                candidate = entry[-1]
            elif isinstance(entry, str):
                candidate = entry
            if not candidate:
                continue
            candidate_str = str(candidate)
            if terminal_map and candidate_str in terminal_map:
                ids.append(str(terminal_map[candidate_str]))
                continue
            if terminal_map:
                compact = _compact_text(candidate_str)
                if compact and compact in terminal_map:
                    ids.append(str(terminal_map[compact]))
                    continue
            if _is_numeric_id(candidate_str):
                ids.append(str(candidate))
    seen = set()
    ordered: List[str] = []
    for value in ids:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    if not ordered and terminal_map and remote_fallback:
        for key in ("liveterminalname", "terminalname", "terminal_name"):
            name_value = remote_fallback.get(key)
            if name_value is None:
                continue
            name_str = str(name_value)
            mapped = terminal_map.get(name_str)
            if mapped is None:
                compact = _compact_text(name_str)
                if compact:
                    mapped = terminal_map.get(compact)
            if mapped is not None:
                ordered.append(str(mapped))
                break
    if not ordered and terminal_map and allow_default_fallback:
        ordered.append(str(next(iter(terminal_map.values()))))
    return ordered


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _format_hhmmss(value: str) -> str:
    if not value:
        return ""
    parts = [part.zfill(2) for part in str(value).strip().split(":") if part != ""]
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}:00"
    if len(parts) >= 3:
        return f"{parts[0]}:{parts[1]}:{parts[2]}"
    return str(value)


def _encode_date_value(value: str) -> int:
    text = str(value or "").strip()
    if not text or text in {"0-00-00", "0000-00-00"}:
        return 0
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return _coerce_int(text.replace("-", ""), 0)
    return _coerce_int(text, 0)


def _encode_time_value(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    parts = [part for part in text.split(":") if part != ""]
    if len(parts) >= 2:
        hh = parts[0].zfill(2)
        mm = parts[1].zfill(2)
        ss = parts[2].zfill(2) if len(parts) >= 3 else "00"
        return _coerce_int(f"{hh}{mm}{ss}", 0)
    return _coerce_int(text, 0)


def _extract_date_range(task: dict) -> tuple[str, str]:
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


def _resolve_terminal_name(task: dict, remote_fallback: Optional[dict] = None) -> str:
    location = task.get("location")
    if isinstance(location, list) and location:
        entry = location[0]
        if isinstance(entry, list) and entry:
            return str(entry[-1])
        if isinstance(entry, str):
            return entry
    if remote_fallback:
        for key in ("liveterminalname", "terminalname", "terminal_name"):
            if remote_fallback.get(key):
                return str(remote_fallback.get(key))
    return ""


def _lookup_name_by_id(mapping: dict, target_id: object) -> str:
    if target_id is None:
        return ""
    target = str(target_id)
    for name, value in mapping.items():
        if str(value) == target:
            return str(name)
    return ""


def _coerce_schedule_duration_seconds(value: object, default: int = 1) -> int:
    if value in (None, ""):
        return default
    text = str(value).strip()
    if not text:
        return default
    clock_seconds = _parse_clock_duration_seconds(text) if ":" in text and " " not in text else None
    if clock_seconds is not None:
        return max(1, clock_seconds)
    try:
        return max(1, int(text))
    except Exception:
        return default


def _normalize_schedule_timelength(task: dict) -> tuple[str, str]:
    timelength = task.get("timelength")
    timelengthtype = task.get("timelengthtype")
    duration_mode = task.get("durationMode")
    if timelengthtype is None and duration_mode:
        timelengthtype = 2 if str(duration_mode) == "loop" else 1
    normalized_type = str(timelengthtype or 1)
    if timelength is None:
        timelength = task.get("loop") if normalized_type == "2" else task.get("duration")
    if normalized_type == "2":
        return str(_coerce_int(timelength, 1)), "2"
    return str(_coerce_schedule_duration_seconds(timelength, 1)), "1"


def _taskinfo_timelength(task: dict) -> tuple[int, int]:
    timelength = task.get("timelength")
    timelengthtype = task.get("timelengthtype")
    if timelength is not None:
        length_type = _coerce_int(timelengthtype, 1)
        if length_type == 2:
            return _coerce_int(timelength, 1), length_type
        return _coerce_duration_int(timelength, 1), length_type
    duration_mode = task.get("durationMode")
    if str(duration_mode) == "loop":
        return _coerce_int(task.get("loop"), 1), 2
    duration_raw = task.get("duration")
    value = _coerce_duration_int(duration_raw, 1)
    if REMOTE_TASKINFO_DURATION_AS_SECONDS and _parse_hms_duration_seconds(duration_raw) is None:
        value = max(1, value * 60)
    return value, 1


def _normalize_taskinfo_timelength(task: dict) -> tuple[str, str]:
    timelength, timelengthtype = _taskinfo_timelength(task)
    if timelengthtype == 2:
        return str(max(1, timelength)), "2"
    return _format_remote_duration_string(timelength, 1), "1"


def _build_remote_task_payload(
    schedule_name: str,
    task: dict,
    media_map: dict,
    terminal_map: dict,
    remote_fallback: Optional[dict] = None,
) -> dict:
    task_name = (task.get("customName") or task.get("taskname") or task.get("audio") or "").strip()
    if not task_name:
        task_name = f"{schedule_name} task"

    # 👇👇👇 【修改开始】给时间加个默认值,不再报错 👇👇👇
    raw_time = task.get("starttime") or task.get("time") or ""
    starttime = _format_hhmmss(raw_time)
    
    # 如果时间是空的,就默认给一个 "00:00:00",而不是抛出异常
    if not starttime:
        starttime = "00:00:00"

    # 🛑 删掉(或注释掉)下面这两行原来的报错代码:
    # if not starttime:
    #     raise HTTPException(status_code=400, detail="Missing starttime for remote task sync.")
    # 👆👆👆 【修改结束】 👆👆👆

    startdate, enddate = _extract_date_range(task)
    media_id = _resolve_media_id_with_fallback(task, media_map, remote_fallback)
    terminal_ids = _resolve_terminal_ids(task, terminal_map, remote_fallback=remote_fallback, allow_default_fallback=False)
    terminal_id = terminal_ids[0] if terminal_ids else None

    # Missing dates still need to satisfy the swagger date format.
    if not startdate and not enddate:
        startdate = date.today().strftime("%Y-%m-%d")
        enddate = startdate
    elif startdate and not enddate:
        enddate = startdate
    elif enddate and not startdate:
        startdate = enddate
    if not media_id or not terminal_id:
        LOGGER.warning(
            "schedule task remote sync blocked due to missing binding %s",
            {
                "schedule_name": schedule_name,
                "task_name": task_name,
                "starttime": starttime,
                "mediaid": media_id,
                "terminalids": _normalize_terminal_ids(task.get("terminalids")),
                "liveterminalid": str(task.get("liveterminalid") or ""),
                "location": _clone_payload(task.get("location")) if isinstance(task.get("location"), list) else [],
            },
        )
        raise HTTPException(
            status_code=400,
            detail=f"Missing mediaid or liveterminalid for schedule '{schedule_name}' task '{task_name}'.",
        )
    media_id_value = _coerce_int(media_id, -1)
    terminal_id_value = _coerce_int(terminal_id, -1)
    if media_id_value < 0 or terminal_id_value < 0:
        raise HTTPException(status_code=400, detail="Invalid mediaid or liveterminalid for remote task sync.")
    timelength, timelengthtype = _normalize_schedule_timelength(task)
    media_name = task.get("audio") or task.get("medianame") or task.get("taskname") or task_name
    if remote_fallback and not media_name:
        media_name = remote_fallback.get("medianame") or remote_fallback.get("taskname") or ""
    media_name = media_name or _lookup_name_by_id(media_map, media_id_value)
    terminal_name = _resolve_terminal_name(task, remote_fallback=remote_fallback)
    if not terminal_name:
        terminal_name = _lookup_name_by_id(terminal_map, terminal_id_value)
    cmdargs = task.get("cmdargs")
    if cmdargs in (None, ""):
        cmdargs = "0"
    execmode_value = task.get("execmode")
    if execmode_value in (None, "", 0, "0"):
        weekdays_value = task.get("weekdays")
        if isinstance(weekdays_value, list) and weekdays_value:
            execmode_value = _execmode_from_weekdays(weekdays_value)
    payload = {
        "taskname": task_name,
        "sechename": schedule_name,
        "starttime": starttime,
        "startdate": startdate,
        "enddate": enddate,
        "mediaid": media_id_value,
        "liveterminalid": terminal_id_value,
        "execmode": _coerce_int(execmode_value, 0),
        "tasktype": _coerce_int(task.get("tasktype"), 1),
        "volume": _coerce_int(task.get("volume"), 50),
        "priority": _coerce_int(task.get("priority"), 10),
        "datasendmodel": _coerce_int(task.get("datasendmodel"), 0),
        "prepower": _coerce_int(task.get("prepower"), 15),
        "level": _coerce_int(task.get("level"), 10),
        "israndomplay": _coerce_int(task.get("israndomplay"), 0),
        "medianame": str(media_name or "0"),
        "liveterminalname": str(terminal_name or "0"),
        "timelength": str(timelength or "0"),
        "timelengthtype": str(timelengthtype or "0"),
        "cmd": _coerce_int(task.get("cmd"), 0),
        "cmdargs": str(cmdargs),
        "bandrate": _coerce_int(task.get("bandrate"), 0),
        "samplerate": _coerce_int(task.get("samplerate"), 0),
        "caiboprepower": _coerce_int(task.get("caiboprepower"), 0),
    }
    projectstate_value = task.get("projectstate")
    if projectstate_value not in (None, ""):
        payload["projectstate"] = _coerce_int(projectstate_value, 1)
    return payload

def _remote_extract_taskid(payload: object, *, explicit_only: bool = False) -> Optional[str]:
    def _normalize_id_value(value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text in {"0", "null", "None"}:
            return None
        return text

    def _extract_from_mapping(obj: object) -> Optional[str]:
        if not isinstance(obj, dict):
            return None
        for key in ("taskid", "task_id", "taskId", "id", "ID"):
            value = _normalize_id_value(obj.get(key))
            if value:
                return value
        return None

    def _extract_scalar_id(obj: object) -> Optional[str]:
        if isinstance(obj, bool) or obj is None:
            return None
        if isinstance(obj, int):
            return str(obj) if obj > 0 else None
        if isinstance(obj, float):
            if obj.is_integer() and obj > 0:
                return str(int(obj))
            return None
        text = str(obj).strip()
        if text.isdigit() and int(text) > 0:
            return text
        return None

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    value = _extract_from_mapping(item)
                    if value:
                        return value
                elif not explicit_only:
                    value = _extract_scalar_id(item)
                    if value:
                        return value
        elif isinstance(data, dict):
            value = _extract_from_mapping(data)
            if value:
                return value
        elif not explicit_only:
            value = _extract_scalar_id(data)
            if value:
                return value

        for key in ("result", "obj", "item"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                value = _extract_from_mapping(nested)
                if value:
                    return value
            elif not explicit_only:
                value = _extract_scalar_id(nested)
                if value:
                    return value

        value = _extract_from_mapping(payload)
        if value:
            return value
    elif not explicit_only:
        value = _extract_scalar_id(payload)
        if value:
            return value
    return None


def _normalize_schedule_task_name_for_compare(value: object) -> str:
    return _compact_text(str(value or "").strip())


def _schedule_task_matches_created_payload(remote_task: dict, payload: dict) -> bool:
    if not isinstance(remote_task, dict) or not isinstance(payload, dict):
        return False
    want_name = _normalize_schedule_task_name_for_compare(payload.get("taskname"))
    want_time = _format_hhmmss(str(payload.get("starttime") or ""))
    want_start = _normalize_date_for_compare(payload.get("startdate"))
    want_end = _normalize_date_for_compare(payload.get("enddate"))
    if not want_name or not want_time or not want_start:
        return False

    item_name = _normalize_schedule_task_name_for_compare(
        remote_task.get("taskname") or remote_task.get("name") or remote_task.get("customName")
    )
    item_time = _format_hhmmss(str(remote_task.get("starttime") or remote_task.get("time") or ""))
    item_start = _normalize_date_for_compare(remote_task.get("startdate"))
    item_end = _normalize_date_for_compare(remote_task.get("enddate"))
    if item_name != want_name or item_time != want_time or item_start != want_start:
        return False
    if want_end and item_end and item_end != want_end:
        return False

    want_media_id = str(payload.get("mediaid") or "").strip()
    item_media_id = str(remote_task.get("mediaid") or "").strip()
    if want_media_id and item_media_id and want_media_id != item_media_id:
        return False
    return True


def _normalize_schedule_task_snapshot(snapshot: Optional[list]) -> List[dict]:
    normalized: List[dict] = []
    for item in snapshot or []:
        if not isinstance(item, dict):
            continue
        normalized_item = _normalize_remote_task(item)
        if normalized_item:
            normalized.append(normalized_item)
    return normalized


def _schedule_task_snapshot_ids(snapshot: Optional[list]) -> set[str]:
    before_ids: set[str] = set()
    for item in _normalize_schedule_task_snapshot(snapshot):
        task_id = _task_real_id(item)
        if task_id:
            before_ids.add(task_id)
    return before_ids


def _collect_created_schedule_task_matches(remote_tasks: list, payload: dict) -> Tuple[List[str], List[str]]:
    all_matches: List[str] = []
    for remote_task in remote_tasks or []:
        if not _schedule_task_matches_created_payload(remote_task, payload):
            continue
        found_id = _remote_extract_taskid(remote_task, explicit_only=True) or _task_real_id(remote_task)
        if found_id:
            all_matches.append(found_id)
    all_matches = _unique_list(all_matches)
    return all_matches, all_matches


def _validate_created_schedule_task_candidate(
    raw_direct_id: str,
    payload: dict,
    remote_tasks: list,
    before_ids: Optional[set[str]] = None,
) -> bool:
    if not raw_direct_id:
        return False
    if raw_direct_id in (before_ids or set()):
        return False
    for remote_task in remote_tasks or []:
        remote_task_id = _remote_extract_taskid(remote_task, explicit_only=True) or _task_real_id(remote_task)
        if remote_task_id != raw_direct_id:
            continue
        if _schedule_task_matches_created_payload(remote_task, payload):
            return True
    return False


def _build_created_schedule_snapshot_entry(task: dict, task_id: str) -> dict:
    snapshot_entry = _normalize_remote_task(_clone_payload(task) or {})
    if task_id:
        snapshot_entry["taskid"] = task_id
    return snapshot_entry


def _resolve_created_schedule_task_id(
    schedule_name: str,
    payload: dict,
    response_payload: object,
    pre_create_snapshot: Optional[list] = None,
) -> str:
    raw_direct_id = _remote_extract_taskid(response_payload, explicit_only=True) or ""
    validated_direct_id = ""
    resolution_mode = ""
    lookup_reason = ""
    fallback_reason = "missing_direct_id"
    lookup_match_count = 0
    all_match_count = 0
    new_match_count = 0
    remote_tasks: list = []
    before_ids = _schedule_task_snapshot_ids(pre_create_snapshot)
    raw_direct_id_seen_in_snapshot = bool(raw_direct_id and raw_direct_id in before_ids)
    direct_id_value = _coerce_int(raw_direct_id, 0)

    if raw_direct_id and direct_id_value > 0 and not raw_direct_id_seen_in_snapshot:
        validated_direct_id = str(direct_id_value)
        resolution_mode = "direct"
        fallback_reason = "direct_id_accepted"
    elif raw_direct_id:
        if direct_id_value <= 0:
            fallback_reason = "direct_id_invalid"
        elif raw_direct_id_seen_in_snapshot:
            LOGGER.warning(
                "schedule task create id candidate rejected | schedule=%s task=%s raw_direct_id=%s reason=pre_create_snapshot_conflict before_snapshot_count=%s",
                schedule_name,
                str(payload.get("taskname") or "").strip(),
                raw_direct_id,
                len(before_ids),
            )
            fallback_reason = "direct_id_seen_in_snapshot"
        else:
            fallback_reason = "direct_id_requires_lookup"

    if not validated_direct_id:
        resolution_mode = "lookup_fallback"
        lookup_reason = fallback_reason or "lookup_required"
        if not remote_tasks:
            try:
                remote_tasks = [_normalize_remote_task(item) for item in _remote_fetch_schedule_tasks(schedule_name)]
            except HTTPException as exc:
                if raw_direct_id:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Remote create schedule task returned candidate taskid={raw_direct_id} and lookup failed: {exc.detail}",
                    ) from exc
                raise HTTPException(
                    status_code=502,
                    detail=f"Remote create schedule task did not return taskid and lookup failed: {exc.detail}",
                ) from exc
        all_matches, _ = _collect_created_schedule_task_matches(remote_tasks, payload)
        all_match_count = len(all_matches)
        new_matches = [task_id for task_id in all_matches if task_id not in before_ids]
        new_matches = _unique_list(new_matches)
        lookup_match_count = len(new_matches)
        new_match_count = len(new_matches)
        if len(new_matches) != 1:
            preview = {
                "taskname": payload.get("taskname"),
                "startdate": payload.get("startdate"),
                "enddate": payload.get("enddate"),
                "starttime": payload.get("starttime"),
                "mediaid": payload.get("mediaid"),
            }
            LOGGER.warning(
                "schedule task create id unresolved | schedule=%s raw_direct_id=%s validated_direct_id=%s resolution_mode=%s lookup_reason=%s fallback_reason=%s before_snapshot_count=%s all_match_count=%s new_match_count=%s raw_direct_id_seen_in_snapshot=%s request=%s response=%s all_matches=%s new_matches=%s",
                schedule_name,
                raw_direct_id,
                validated_direct_id,
                resolution_mode,
                lookup_reason,
                fallback_reason,
                len(before_ids),
                all_match_count,
                new_match_count,
                raw_direct_id_seen_in_snapshot,
                preview,
                _clone_payload(response_payload),
                all_matches,
                new_matches,
            )
            if all_matches and not new_matches:
                raise HTTPException(
                    status_code=502,
                    detail="Remote create schedule task matched only pre-existing tasks; no new created task was found.",
                )
            if not new_matches:
                raise HTTPException(
                    status_code=502,
                    detail="Remote create schedule task could not be validated and lookup found no unique created task.",
                )
            raise HTTPException(
                status_code=502,
                detail="Remote create schedule task could not be validated and lookup matched multiple tasks.",
            )
        validated_direct_id = new_matches[0]
        fallback_reason = f"{fallback_reason}_lookup_unique_match" if fallback_reason else "lookup_unique_match"
    LOGGER.info(
        "schedule task create id resolved | schedule=%s task=%s raw_direct_id=%s validated_direct_id=%s resolution_mode=%s lookup_reason=%s fallback_reason=%s before_snapshot_count=%s all_match_count=%s new_match_count=%s raw_direct_id_seen_in_snapshot=%s lookup_match_count=%s task_id=%s",
        schedule_name,
        str(payload.get("taskname") or "").strip(),
        raw_direct_id,
        validated_direct_id,
        resolution_mode or "direct",
        lookup_reason,
        fallback_reason,
        len(before_ids),
        all_match_count,
        new_match_count,
        raw_direct_id_seen_in_snapshot,
        lookup_match_count,
        validated_direct_id,
    )
    if not validated_direct_id or validated_direct_id == "0":
        raise HTTPException(status_code=502, detail="Remote create schedule task returned an invalid taskid.")
    return validated_direct_id


def _remote_write_ack_ok(payload: object, *, require_explicit: bool = False) -> bool:
    if payload in (None, "", [], {}):
        return False if require_explicit else False
    if isinstance(payload, bool):
        return bool(payload)
    if isinstance(payload, (int, float)):
        return str(int(payload)).strip() in {"1", "200"}
    if isinstance(payload, str):
        text = payload.strip().lower()
        if not text:
            return False
        if any(token in text for token in ("fail", "error", "失败", "错误")):
            return False
        return any(token in text for token in ("ok", "success", "成功", "true", "200", "1"))
    if not isinstance(payload, dict):
        return False
    if "ok" in payload and payload.get("ok") is False:
        return False
    if "success" in payload and payload.get("success") is False:
        return False
    code = payload.get("code")
    if code is not None:
        code_text = str(code).strip().lower()
        if code_text:
            return code_text in {"0", "1", "200", "ok", "success", "true"}
    status = payload.get("status")
    if status is not None:
        status_text = str(status).strip().lower()
        if status_text:
            return status_text in {"0", "1", "200", "ok", "success", "true"}
    message = str(payload.get("msg") or payload.get("message") or payload.get("detail") or payload.get("raw") or "").strip().lower()
    if message:
        if any(token in message for token in ("fail", "error", "失败", "错误")):
            return False
        if any(token in message for token in ("ok", "success", "成功", "true")):
            return True
    for key in ("data", "result", "item", "obj"):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return True
    if payload.get("ok") is True or payload.get("success") is True:
        return True
    return False


def _remote_write_error_detail(payload: object) -> str:
    if isinstance(payload, str):
        return _short_error_text(payload)
    if not isinstance(payload, dict):
        return ""
    parts: List[str] = []
    for key in ("message", "msg", "detail", "raw"):
        value = str(payload.get(key) or "").strip()
        if value:
            parts.append(_short_error_text(value, limit=180))
            break
    exception_name = str(payload.get("exception") or "").strip()
    if exception_name:
        parts.append(f"exception={_short_error_text(exception_name, limit=80)}")
    file_name = str(payload.get("file") or "").strip()
    if file_name:
        parts.append(f"file={Path(file_name).name or _short_error_text(file_name, limit=80)}")
    return " | ".join(parts)


def _ensure_remote_write_ack(payload: object, action: str, *, require_explicit: bool = False) -> None:
    if _remote_write_ack_ok(payload, require_explicit=require_explicit):
        return
    detail = _remote_write_error_detail(payload)
    if detail:
        raise HTTPException(status_code=502, detail=f"Remote {action} was not acknowledged: {detail}")
    raise HTTPException(status_code=502, detail=f"Remote {action} was not acknowledged.")


def _remote_schedule_task_ids(schedule_name: str) -> List[str]:
    if not schedule_name:
        return []
    try:
        tasks = _remote_fetch_schedule_tasks(schedule_name)
    except HTTPException:
        return []
    task_ids: List[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        if task_id and _is_numeric_id(task_id) and task_id != "0":
            task_ids.append(task_id)
    return _unique_list(task_ids)

def _build_remote_taskinfo_payload(
    kind: str,
    task: dict,
    media_map: dict,
    terminal_map: dict,
    remote_fallback: Optional[dict] = None,
) -> tuple[dict, list, str]:
    # 1. Basic Name & Time Extraction
    task_name = (task.get("taskname") or task.get("name") or task.get("customName") or task.get("audio") or "").strip()
    if not task_name:
        task_name = f"{kind} task"
    
    # 👇👇👇 【修改开始】给时间加个默认值,不再报错 👇👇👇
    raw_time = task.get("time") or task.get("starttime") or ""
    starttime = _format_hhmmss(raw_time)
    
    # 如果时间为空,自动填补为 00:00:00,防止报错
    if not starttime:
        starttime = "00:00:00"

    # 🛑 删掉原来这行报错代码:
    # if not starttime:
    #    raise HTTPException(status_code=400, detail="Missing starttime for remote task sync.")
    # 👆👆👆 【修改结束】 👆👆👆

    # 3. Handle IDs
    media_id = _resolve_media_id_with_fallback(task, media_map, remote_fallback)
    if not media_id:
        raise HTTPException(status_code=400, detail=f"Missing mediaid for {kind} task '{task_name}'.")
    
    terminal_ids = _resolve_terminal_ids(task, terminal_map, remote_fallback=remote_fallback)
    if not terminal_ids:
        raise HTTPException(status_code=400, detail="Missing terminalid for remote task sync.")
    
    media_id_value = _coerce_int(media_id, -1)
    terminal_id_value = _coerce_int(terminal_ids[0], -1)

    if media_id_value < 0 or terminal_id_value < 0:
        raise HTTPException(status_code=400, detail="Invalid mediaid or terminalid for remote task sync.")

    # 4. Handle Dates (Keep as String "YYYY-MM-DD", do not convert to Int)
    startdate, enddate = _extract_date_range(task)
    if not startdate or startdate == "0-00-00":
        startdate = datetime.now().strftime("%Y-%m-%d") # Default to today if missing
    if not enddate or enddate == "0-00-00":
        enddate = startdate

    # 5. Resolve Names
    media_name = task.get("audio") or task.get("medianame") or task.get("taskname") or task_name
    if remote_fallback and not media_name:
        media_name = remote_fallback.get("medianame") or remote_fallback.get("taskname") or ""
    media_name = media_name or _lookup_name_by_id(media_map, media_id_value)

    terminal_name = _resolve_terminal_name(task, remote_fallback=remote_fallback)
    if not terminal_name:
        terminal_name = _lookup_name_by_id(terminal_map, terminal_id_value)

    # 6. Helper for safe integer picking
    def pick_int(key: str, default: int) -> int:
        value = task.get(key)
        if value is None and remote_fallback:
            value = remote_fallback.get(key)
        return _coerce_int(value, default)

    # 7. Task Type Logic
    if kind == "broadcast":
        task_type_default = _coerce_int(REMOTE_BROADCAST_TASK_TYPE, 2)
    elif kind == "livecast":
        task_type_default = _coerce_int(REMOTE_LIVECAST_TASK_TYPE, 3)
    else:
        task_type_default = 2
    
    task_type_value = task.get("tasktype")
    if task_type_value is None and remote_fallback:
        task_type_value = remote_fallback.get("tasktype")
    task_type = _coerce_int(task_type_value, task_type_default)

    timelength, timelengthtype = _normalize_taskinfo_timelength(task)

    cmdargs_value = task.get("cmdargs")
    if cmdargs_value is None and remote_fallback:
        cmdargs_value = remote_fallback.get("cmdargs")
    cmdargs = "0" if cmdargs_value in (None, "") else str(cmdargs_value)

    # 8. Construct Payload (Using Strings for Dates/Times, Removing State fields)
    payload = {
        "taskname": task_name,
        "tasktype": task_type,
        "starttime": starttime,   # Fixed: String
        "startdate": startdate,   # Fixed: String
        "enddate": enddate,       # Fixed: String
        "mediaid": media_id_value,
        "timelength": str(timelength),
        "timelengthtype": str(timelengthtype),
        "medianame": str(media_name or "0"),
        "liveterminalid": terminal_id_value,
        "liveterminalname": str(terminal_name or "0"),
        "volume": pick_int("volume", 50),
        "priority": pick_int("priority", 0),
        "execmode": pick_int("execmode", 0),
        "datasendmodel": pick_int("datasendmodel", 0),
        "prepower": pick_int("prepower", 0),
        "level": pick_int("level", 0),
        "israndomplay": pick_int("israndomplay", 0),
        "cmd": pick_int("cmd", 0),
        "cmdargs": cmdargs,
        "bandrate": pick_int("bandrate", 0),
        "samplerate": pick_int("samplerate", 0),
        "caiboprepower": pick_int("caiboprepower", 0),
        # Some remote deployments directly read these keys in taskinfoset.
        "interval_s": pick_int("interval_s", 0),
        "intplaylength": pick_int("intplaylength", 0),
        "intplaylengthtype": pick_int("intplaylengthtype", 1),
        # REMOVED: "state", "taskstate", "enablestate" -> These confuse the remote server on POST/PUT
    }

    schedule_name = task.get("sechename") or task.get("schedule_name") or task.get("scheduleName")
    if schedule_name:
        payload["sechename"] = str(schedule_name)

    return payload, terminal_ids, str(media_id_value)
def _fetch_remote_task_state(task_id: int, task_type: int) -> dict:
    task_id_value = _coerce_int(task_id, 0)
    if task_id_value <= 0:
        raise HTTPException(status_code=400, detail="Invalid task id for remote task state.")
    payload = {
        "taskid": task_id_value,
        "tasktype": _coerce_int(task_type, 2),
    }
    resp = _remote_request(
        "POST",
        "/task/gettasktatus",
        json_body=payload,
        form_body=None,
        allow_retry=False,
        allow_form_retry=False,
    )
    if isinstance(resp, dict):
        return resp
    return {"data": _remote_data_list(resp)}

def _remote_delete_task(task_id: str) -> None:
    task_id_value = _coerce_int(task_id, 0)
    payload = {"id": task_id_value}
    _remote_request(
        "DELETE",
        "/task/sechetask",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )


def _remote_add_task(
    schedule_name: str,
    task: dict,
    media_map: dict,
    terminal_map: dict,
    pre_create_snapshot: Optional[list] = None,
) -> Optional[str]:
    payload = _build_remote_task_payload(schedule_name, task, media_map, terminal_map)
    terminal_ids = _resolve_terminal_ids(task, terminal_map, allow_default_fallback=False)
    desired_bindings, explicit_binding_reason = _explicit_taskterminal_bindings_for_terminal_ids_checked(task, terminal_ids)
    if pre_create_snapshot is None:
        try:
            pre_create_snapshot = [_normalize_remote_task(item) for item in _remote_fetch_schedule_tasks(schedule_name)]
        except HTTPException as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch pre-create schedule task snapshot: {exc.detail}",
            ) from exc
    payload["taskid"] = "0"
    resp = _remote_request(
        "POST",
        "/task/sechetask",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )
    task_id = _resolve_created_schedule_task_id(
        schedule_name,
        payload,
        resp,
        pre_create_snapshot=pre_create_snapshot,
    )
    task["taskid"] = task_id
    if terminal_ids:
        LOGGER.info(
            "schedule task terminal rebind prepared | schedule=%s taskid=%s task=%s terminal_ids=%s explicit_reason=%s desired_bindings=%s",
            schedule_name,
            task_id,
            str(task.get("customName") or task.get("taskname") or "").strip(),
            terminal_ids,
            explicit_binding_reason,
            _clone_payload(desired_bindings),
        )
        try:
            try:
                _remote_replace_taskterminals(
                    task_id,
                    terminal_ids,
                    previous_terminal_ids=[],
                    task=task,
                    desired_bindings=desired_bindings or None,
                    skip_existing_fetch=True,
                )
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise
                _remote_replace_taskterminals(
                    task_id,
                    terminal_ids,
                    previous_terminal_ids=[],
                    task=task,
                    desired_bindings=desired_bindings or None,
                )
        except Exception as exc:
            LOGGER.warning(
                "schedule task terminal rebind failed | schedule=%s taskid=%s task=%s terminal_ids=%s explicit_reason=%s explicit_signatures=%s detail=%s",
                schedule_name,
                task_id,
                str(task.get("customName") or task.get("taskname") or "").strip(),
                terminal_ids,
                explicit_binding_reason,
                _taskterminal_binding_signatures(desired_bindings),
                _short_error_text(getattr(exc, "detail", exc)),
            )
            try:
                _remote_delete_task(task_id)
            except Exception as cleanup_exc:
                LOGGER.warning("failed to cleanup newly created schedule task %s after terminal bind error: %s", task_id, cleanup_exc)
            raise
    return task_id


def _remote_update_task(
    task_id: str,
    schedule_name: str,
    task: dict,
    media_map: dict,
    terminal_map: dict,
    remote_fallback: dict,
    task_changed: Optional[bool] = None,
    terminals_changed: Optional[bool] = None,
) -> None:
    remote_snapshot = remote_fallback
    if _task_has_explicit_terminal_binding(task):
        remote_snapshot = _hydrate_remote_taskterminal_snapshot(remote_fallback)
    payload = _build_remote_task_payload(schedule_name, task, media_map, terminal_map, remote_fallback=remote_snapshot)
    terminal_ids = _schedule_task_terminal_ids(task, terminal_map)
    desired_bindings, explicit_binding_reason = _explicit_taskterminal_bindings_for_terminal_ids_checked(task, terminal_ids)
    if terminals_changed is None:
        terminals_changed = _schedule_task_terminals_changed(task, remote_snapshot, terminal_map)
    previous_terminal_ids = _schedule_task_terminal_ids(remote_snapshot or {}, terminal_map)
    task_id_value = _coerce_int(task_id, 0)
    payload["taskid"] = str(task_id_value)
    if task_changed is None:
        task_changed = _remote_task_changed(task, remote_snapshot, payload)
    if task_changed:
        _remote_request(
            "PUT",
            "/task/sechetask",
            json_body=payload,
            form_body=None,
            allow_form_retry=False,
        )
    if terminals_changed:
        try:
            _remote_replace_taskterminals(
                task_id,
                terminal_ids,
                previous_terminal_ids=previous_terminal_ids,
                task=task,
                previous_task=remote_snapshot,
                desired_bindings=desired_bindings or None,
            )
        except Exception as exc:
            LOGGER.warning(
                "schedule task terminal rebind failed | schedule=%s taskid=%s task=%s terminal_ids=%s explicit_reason=%s explicit_signatures=%s detail=%s",
                schedule_name,
                task_id,
                str(task.get("customName") or task.get("taskname") or "").strip(),
                terminal_ids,
                explicit_binding_reason,
                _taskterminal_binding_signatures(desired_bindings),
                _short_error_text(getattr(exc, "detail", exc)),
            )
            raise


def _remote_taskinfo_items(task_type: int) -> list:
    resp = _remote_request("GET", f"/task/taskinfo/{task_type}")
    return _remote_data_list(resp)



def _remote_delete_taskinfo(task_id: str) -> None:
    task_id_value = _coerce_int(task_id, 0)
    payload = {"id": task_id_value}
    _remote_request(
        "DELETE",
        "/task/taskinfo",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )


def _batch_delete_parallel(task_ids, delete_fn, label: str = "batch_delete") -> None:
    """Parallel batch delete using ThreadPoolExecutor. Converts serial O(n*timeout) to O(timeout)."""
    if not task_ids:
        return
    ids = list(task_ids)
    if len(ids) == 1:
        delete_fn(ids[0])
        return
    workers = min(len(ids), REMOTE_FETCH_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {_submit_with_current_remote_token(executor, delete_fn, tid): tid for tid in ids}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                LOGGER.warning(f"[{label}] failed to delete task {futures[fut]}")


def _batch_add_parallel(
    schedule_name: str,
    tasks: list,
    media_map: dict,
    terminal_map: dict,
    label: str = "batch_add",
) -> None:
    """Serial batch add tasks while keeping the legacy helper signature unchanged."""
    if not tasks:
        return
    try:
        current_snapshot = [_normalize_remote_task(item) for item in _remote_fetch_schedule_tasks(schedule_name)]
    except HTTPException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch pre-create schedule task snapshot for batch add: {exc.detail}",
        ) from exc
    failed_count = 0
    for task in tasks:
        try:
            new_task_id = _remote_add_task(
                schedule_name,
                task,
                media_map,
                terminal_map,
                pre_create_snapshot=current_snapshot,
            )
            if new_task_id:
                current_snapshot.append(_build_created_schedule_snapshot_entry(task, new_task_id))
        except Exception:
            failed_count += 1
            tid = task.get("taskid") or task.get("id") or "?"
            LOGGER.warning(f"[{label}] failed to add task {tid}")
    if failed_count:
        LOGGER.error(f"[{label}] {failed_count}/{len(tasks)} tasks failed to add")


def _remote_replace_taskmusic(task_id: str, media_ids: list) -> None:
    task_id_value = _coerce_int(task_id, 0)
    existing_media_ids = _unique_list([
        str(_coerce_int(media_id, 0))
        for media_id in _remote_task_media_ids(task_id)
        if media_id not in (None, "")
    ])
    if not existing_media_ids:
        existing_media_ids = ["0"]
    delete_payload = {
        "data": [
            {
                "id": task_id_value,
                "mediaid": _coerce_int(media_id, 0),
            }
            for media_id in existing_media_ids
        ]
    }
    _remote_request(
        "DELETE",
        "/task/taskmusic",
        json_body=delete_payload,
        form_body=None,
        allow_form_retry=False,
    )
    normalized_media_ids = _unique_list([
        str(_coerce_int(media_id, 0))
        for media_id in (media_ids or [])
        if media_id not in (None, "")
    ])
    if not normalized_media_ids:
        normalized_media_ids = ["0"]
    body = {
        "data": [
            {
                "id": task_id_value,
                "mediaid": _coerce_int(media_id, 0),
            }
            for media_id in normalized_media_ids
        ]
    }
    _remote_request(
        "POST",
        "/task/taskmusic",
        json_body=body,
        form_body=None,
        allow_form_retry=False,
    )


def _remote_replace_taskterminals(
    task_id: str,
    terminal_ids: list,
    previous_terminal_ids: Optional[list] = None,
    task: Optional[dict] = None,
    previous_task: Optional[dict] = None,
    desired_bindings: Optional[list] = None,
    skip_existing_fetch: bool = False,
) -> None:
    terminal_lookup = _remote_terminal_lookup()
    zone_items: List[dict] = []
    needs_zone_items = (
        isinstance(task, dict)
        and isinstance(task.get("location"), list)
    ) or (
        isinstance(previous_task, dict)
        and isinstance(previous_task.get("location"), list)
    )
    if needs_zone_items:
        try:
            zone_items = _fetch_enriched_zone_items()
        except Exception as exc:
            LOGGER.warning("failed to fetch terzone while diffing task terminals: %s", exc)
    desired_bindings = (
        _normalize_taskterminal_bindings(desired_bindings)
        if isinstance(desired_bindings, list)
        else _desired_taskterminal_bindings(task, terminal_ids, terminal_lookup, zone_items)
    )
    if skip_existing_fetch:
        previous_bindings, previous_ok = [], True
    else:
        previous_bindings, previous_ok = _remote_taskterminal_bindings_checked(task_id)
    if not previous_ok:
        previous_bindings = _normalize_taskterminal_bindings(
            (previous_task or {}).get("taskterminal") or (previous_task or {}).get("taskTerminal")
        )
    if not previous_bindings and previous_terminal_ids:
        previous_bindings = _desired_taskterminal_bindings(
            previous_task,
            previous_terminal_ids,
            terminal_lookup,
            zone_items,
        )
    previous_signatures = {
        signature
        for signature in _taskterminal_binding_signatures(previous_bindings)
        if signature
    }
    desired_signatures = {
        signature
        for signature in _taskterminal_binding_signatures(desired_bindings)
        if signature
    }
    to_remove = [
        binding
        for binding in previous_bindings
        if _taskterminal_binding_signature(binding) not in desired_signatures
    ]
    to_add = [
        binding
        for binding in desired_bindings
        if _taskterminal_binding_signature(binding) not in previous_signatures
    ]
    if not to_remove and not to_add:
        return
    try:
        if to_remove:
            _remote_remove_taskterminals(task_id, [], task=previous_task, bindings=to_remove)
        if to_add:
            try:
                _remote_set_taskterminals(
                    task_id,
                    [],
                    task=task,
                    bindings=to_add,
                    existing_bindings=previous_bindings,
                )
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise
                _remote_set_taskterminals(task_id, [], task=task, bindings=to_add)
    except Exception:
        restoration_errors: List[str] = []
        try:
            if to_add:
                _remote_remove_taskterminals(task_id, [], task=task, bindings=to_add)
        except Exception as restore_exc:
            restoration_errors.append(f"cleanup_new:{restore_exc}")
        if to_remove:
            try:
                try:
                    _remote_set_taskterminals(
                        task_id,
                        [],
                        task=previous_task,
                        bindings=to_remove,
                        existing_bindings=[],
                    )
                except TypeError as exc:
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    _remote_set_taskterminals(task_id, [], task=previous_task, bindings=to_remove)
            except Exception as restore_exc:
                restoration_errors.append(f"restore_old:{restore_exc}")
        if restoration_errors:
            LOGGER.warning(
                "failed to fully restore terminals for task %s after rebind error: %s",
                task_id,
                "; ".join(restoration_errors),
            )
        raise


def _remote_add_taskterminal(task_id: str, terminal_id: str) -> None:
    _remote_set_taskterminals(task_id, [terminal_id])


def _terminal_group_id_for_binding(terminal_id: str, terminal_lookup: Optional[dict] = None) -> int:
    lookup = terminal_lookup if isinstance(terminal_lookup, dict) else {}
    item = lookup.get(str(terminal_id), {}) if lookup else {}
    if isinstance(item, dict):
        zone = item.get("zone")
        if zone not in (None, ""):
            return _coerce_int(zone, 0)
    return 0


def _resolve_binding_group_context(
    task: Optional[dict],
    terminal_id: str,
    terminal_lookup: Optional[dict] = None,
    zone_items: Optional[list] = None,
) -> dict:
    lookup = terminal_lookup if isinstance(terminal_lookup, dict) else {}
    fallback_groupid = _terminal_group_id_for_binding(terminal_id, lookup)
    fallback = {
        "groupid": fallback_groupid,
        "zone_name": "",
        "source": "lookup",
    }
    lookup_item = lookup.get(str(terminal_id), {}) if lookup else {}
    entry = _task_location_entry_for_terminal(task, terminal_id, lookup)
    if not entry:
        if _lookup_zone_is_ambiguous(lookup_item):
            raise HTTPException(
                status_code=400,
                detail=f"Terminal {terminal_id} belongs to multiple zones; explicit location is required.",
            )
        return fallback
    zone_name = str(entry.get("zone_name") or "").strip()
    if not zone_name:
        if _lookup_zone_is_ambiguous(lookup_item):
            raise HTTPException(
                status_code=400,
                detail=f"Terminal {terminal_id} belongs to multiple zones; explicit location is required.",
            )
        return fallback
    if _compact_text(zone_name) == _compact_text(_zone_label(0)):
        return {
            "groupid": 0,
            "zone_name": zone_name,
            "source": "location-unassigned",
        }
    items = zone_items if isinstance(zone_items, list) else []
    zone_item = _terzone_item_for_location_name(zone_name, items)
    if not isinstance(zone_item, dict):
        LOGGER.warning(
            "failed to resolve task terminal binding zone by location | terminalid=%s location_zone_name=%s fallback_groupid=%s",
            terminal_id,
            zone_name,
            fallback_groupid,
        )
        return fallback
    terminal_name = ""
    if isinstance(lookup_item, dict):
        terminal_name = str(lookup_item.get("name") or "").strip()
    if not _zone_item_contains_terminal(zone_item, terminal_id, terminal_name):
        detail = (
            f"Terminal {terminal_id} does not belong to zone '{zone_name}' "
            "from task location."
        )
        LOGGER.warning(
            "task terminal binding rejected | terminalid=%s location_zone_name=%s task_location=%s",
            terminal_id,
            zone_name,
            entry.get("raw"),
        )
        raise HTTPException(status_code=400, detail=detail)
    resolved_groupid = _coerce_int(zone_item.get("id") or zone_item.get("zone") or zone_item.get("zoneid"), 0)
    return {
        "groupid": resolved_groupid,
        "zone_name": zone_name,
        "source": "location",
    }


def _desired_taskterminal_bindings(
    task: Optional[dict],
    terminal_ids: list,
    terminal_lookup: Optional[dict] = None,
    zone_items: Optional[list] = None,
) -> List[dict]:
    normalized_terminal_ids = _unique_list([
        str(terminal_id)
        for terminal_id in (terminal_ids or [])
        if terminal_id not in (None, "", 0, "0")
    ])
    if not normalized_terminal_ids:
        return []
    explicit_bindings, explicit_reason = _explicit_taskterminal_bindings_for_terminal_ids_checked(task, normalized_terminal_ids)
    if explicit_bindings:
        return explicit_bindings
    normalized_task_bindings = _normalize_taskterminal_bindings(
        (task or {}).get("taskterminal") or (task or {}).get("taskTerminal")
    ) if isinstance(task, dict) else []
    if normalized_task_bindings:
        LOGGER.warning(
            "explicit taskterminal bindings ignored; falling back to location | task=%s terminal_ids=%s reason=%s signatures=%s",
            str((task or {}).get("customName") or (task or {}).get("taskname") or "").strip(),
            normalized_terminal_ids,
            explicit_reason,
            _taskterminal_binding_signatures(normalized_task_bindings),
        )
    lookup = terminal_lookup if isinstance(terminal_lookup, dict) else _remote_terminal_lookup()
    items = zone_items if isinstance(zone_items, list) else []
    if not items and isinstance(task, dict) and isinstance(task.get("location"), list):
        try:
            items = _remote_data_list(_remote_terzone_cached())
            if not items:
                items = _fetch_enriched_zone_items()
        except Exception as exc:
            LOGGER.warning("failed to fetch terzone while resolving desired taskterminal bindings: %s", exc)
            items = []
    bindings: List[dict] = []
    for terminal_id in normalized_terminal_ids:
        group_context = _resolve_binding_group_context(task, terminal_id, lookup, items)
        binding = {
            "terminalid": str(terminal_id),
            "groupid": _coerce_int(group_context.get("groupid"), 0),
        }
        lookup_item = lookup.get(str(terminal_id), {}) if isinstance(lookup, dict) else {}
        terminal_name = str(lookup_item.get("name") or "").strip() if isinstance(lookup_item, dict) else ""
        if terminal_name:
            binding["terminalname"] = terminal_name
        bindings.append(binding)
    return _normalize_taskterminal_bindings(bindings)


def _apply_remote_taskterminal_snapshot(task: Optional[dict], bindings: list) -> dict:
    mapped = dict(task) if isinstance(task, dict) else {}
    normalized_bindings = _normalize_taskterminal_bindings(bindings)
    mapped["taskterminal"] = [
        {
            "terminalid": binding.get("terminalid"),
            "groupid": binding.get("groupid"),
            **({"terminalname": binding.get("terminalname")} if binding.get("terminalname") else {}),
        }
        for binding in normalized_bindings
    ]
    mapped["terminalids"] = [binding.get("terminalid") for binding in normalized_bindings if binding.get("terminalid")]
    terminal_names = [binding.get("terminalname") for binding in normalized_bindings if binding.get("terminalname")]
    if terminal_names:
        mapped["terminalnames"] = _unique_list([str(name) for name in terminal_names if name])
    elif "terminalnames" in mapped:
        mapped.pop("terminalnames", None)
    if mapped["terminalids"]:
        mapped["liveterminalid"] = mapped["terminalids"][0]
    if terminal_names:
        mapped["liveterminalname"] = terminal_names[0]
    return mapped


def _hydrate_remote_taskterminal_snapshot(task: Optional[dict]) -> dict:
    mapped = dict(task) if isinstance(task, dict) else {}
    task_id = _task_real_id(mapped) or _task_id(mapped)
    if not task_id or not _is_numeric_id(task_id):
        return mapped
    bindings, ok = _remote_taskterminal_bindings_checked(task_id)
    if not ok:
        return mapped
    return _apply_remote_taskterminal_snapshot(mapped, bindings)


def _remote_set_taskterminals(
    task_id: str,
    terminal_ids: list,
    task: Optional[dict] = None,
    bindings: Optional[list] = None,
    existing_bindings: Optional[list] = None,
) -> None:
    normalized_terminal_ids = _unique_list([
        str(terminal_id)
        for terminal_id in (terminal_ids or [])
        if terminal_id not in (None, "", 0, "0")
    ])
    terminal_lookup = _remote_terminal_lookup()
    zone_items: List[dict] = []
    if isinstance(task, dict) and isinstance(task.get("location"), list):
        try:
            zone_items = _fetch_enriched_zone_items()
            _enrich_lookup_zones_from_terzone(terminal_lookup, zone_items)
        except Exception:
            zone_items = []
    normalized_bindings = (
        _normalize_taskterminal_bindings(bindings)
        if isinstance(bindings, list)
        else _desired_taskterminal_bindings(task, normalized_terminal_ids, terminal_lookup, zone_items)
    )
    if not normalized_bindings:
        return
    existing = (
        _normalize_taskterminal_bindings(existing_bindings)
        if isinstance(existing_bindings, list)
        else _remote_taskterminal_bindings(task_id)
    )
    existing_signatures = {signature for signature in _taskterminal_binding_signatures(existing) if signature}
    bindings_to_add = [
        binding
        for binding in normalized_bindings
        if _taskterminal_binding_signature(binding) not in existing_signatures
    ]
    if not bindings_to_add:
        return
    _remote_post_taskterminal_bindings(task_id, bindings_to_add)


def _remote_taskterminal_bind_payload(task_id: str, bindings: list) -> dict:
    task_id_value = _coerce_int(task_id, 0)
    body = {"data": []}
    for binding in _normalize_taskterminal_bindings(bindings):
        terminal_id = str(binding.get("terminalid") or "").strip()
        groupid = _coerce_int(binding.get("groupid"), 0)
        LOGGER.info(
            "task terminal bind resolved group | taskid=%s terminalid=%s location_zone_name=%s resolved_groupid=%s source=%s",
            task_id,
            terminal_id,
            "",
            groupid,
            "binding-diff",
        )
        body["data"].append(
            {
                "id": task_id_value,
                "terminalid": _coerce_int(terminal_id, 0),
                "area": 255,
                "groupid": groupid,
            }
        )
    return body


def _is_retryable_taskterminal_bind_error(exc: HTTPException) -> bool:
    status_code = _coerce_int(getattr(exc, "status_code", 0), 0)
    if status_code in {502, 503, 504}:
        return True
    detail = str(getattr(exc, "detail", "") or "").lower()
    return "bad gateway" in detail or "gateway" in detail or "timeout" in detail


def _remote_post_taskterminal_bindings(task_id: str, bindings: list) -> None:
    normalized_bindings = _normalize_taskterminal_bindings(bindings)
    if not normalized_bindings:
        return
    fallback_cap = max(1, _coerce_int(REMOTE_TASKTERMINAL_BATCH_SIZE, 1))
    total_start = time.perf_counter()

    LOGGER.info(
        "task jsontaskterminal submit start | taskid=%s binding_count=%s strategy=single_payload fallback_cap=%s",
        task_id,
        len(normalized_bindings),
        fallback_cap,
    )

    def submit_chunk(chunk: list, *, depth: int = 0) -> None:
        if not chunk:
            return
        body = _remote_taskterminal_bind_payload(task_id, chunk)
        chunk_start = time.perf_counter()
        try:
            _remote_request(
                "POST",
                "/task/jsontaskterminal",
                json_body=body,
                form_body=None,
                allow_form_retry=False,
            )
            _debug_timing(
                "task jsontaskterminal submit",
                (time.perf_counter() - chunk_start) * 1000,
                taskid=task_id,
                binding_count=len(chunk),
                depth=depth,
                fallback_cap=fallback_cap,
            )
            return
        except HTTPException as exc:
            elapsed_ms = (time.perf_counter() - chunk_start) * 1000
            _debug_timing(
                "task jsontaskterminal submit failed",
                elapsed_ms,
                taskid=task_id,
                binding_count=len(chunk),
                depth=depth,
                fallback_cap=fallback_cap,
                status=getattr(exc, "status_code", ""),
            )
            if len(chunk) > 1 and _is_retryable_taskterminal_bind_error(exc):
                if len(chunk) > fallback_cap:
                    split_size = fallback_cap
                    split_chunks = [
                        chunk[start : start + split_size]
                        for start in range(0, len(chunk), split_size)
                    ]
                else:
                    split_size = max(1, len(chunk) // 2)
                    split_chunks = [chunk[:split_size], chunk[split_size:]]
                split_chunks = [part for part in split_chunks if part]
                LOGGER.warning(
                    "task jsontaskterminal batch failed; retrying smaller chunks | taskid=%s chunk_size=%s depth=%s split_size=%s split_count=%s status=%s detail=%s",
                    task_id,
                    len(chunk),
                    depth,
                    split_size,
                    len(split_chunks),
                    getattr(exc, "status_code", ""),
                    str(getattr(exc, "detail", "") or ""),
                )
                for split_chunk in split_chunks:
                    submit_chunk(split_chunk, depth=depth + 1)
                return
            raise

    submit_chunk(normalized_bindings)
    _debug_timing(
        "task jsontaskterminal submit total",
        (time.perf_counter() - total_start) * 1000,
        taskid=task_id,
        binding_count=len(normalized_bindings),
        fallback_cap=fallback_cap,
    )


def _remote_remove_taskterminal(task_id: str, terminal_id: str) -> None:
    _remote_remove_taskterminals(task_id, [terminal_id])


def _remote_remove_taskterminals(
    task_id: str,
    terminal_ids: list,
    task: Optional[dict] = None,
    bindings: Optional[list] = None,
) -> None:
    task_id_value = _coerce_int(task_id, 0)
    normalized_terminal_ids = _unique_list([
        str(terminal_id)
        for terminal_id in (terminal_ids or [])
        if terminal_id not in (None, "", 0, "0")
    ])
    normalized_bindings = (
        _normalize_taskterminal_bindings(bindings)
        if isinstance(bindings, list)
        else _desired_taskterminal_bindings(task, normalized_terminal_ids)
    )
    if not normalized_bindings:
        return
    data_payload = {"data": []}
    for binding in normalized_bindings:
        terminal_id = str(binding.get("terminalid") or "").strip()
        groupid = _coerce_int(binding.get("groupid"), 0)
        LOGGER.info(
            "task terminal remove resolved group | taskid=%s terminalid=%s location_zone_name=%s resolved_groupid=%s source=%s",
            task_id,
            terminal_id,
            "",
            groupid,
            "binding-diff",
        )
        data_payload["data"].append(
            {
                "id": _coerce_int(terminal_id, 0),
                "taskid": task_id_value,
                "groupid": groupid,
            }
        )
    delete_attempts = [
        {
            "json_body": data_payload,
            "allow_form_retry": False,
        },
    ]
    last_error: Optional[HTTPException] = None
    for index, attempt in enumerate(delete_attempts):
        try:
            _remote_request("DELETE", "/task/taskterminal", **attempt)
            return
        except HTTPException as exc:
            last_error = exc
            raise
    if last_error:
        raise last_error


def _normalize_date_for_compare(value: object) -> str:
    """Normalize a date value to ``YYYY-MM-DD`` for comparison.

    Handles integer ``20260322``, string ``"2026-03-22"`` or ``"20260322"``.
    """
    text = str(value or "").strip().replace("/", "-")
    if not text or text in ("0", "0-00-00", "0000-00-00"):
        return ""
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _remote_find_created_taskinfo(kind: str, payload: dict) -> dict:
    """Query remote task list to locate a just-created taskinfo entry.

    Returns a dict containing status + candidate ids so callers can distinguish
    not found vs ambiguous matches.
    """
    task_type = _coerce_int(payload.get("tasktype"), 2)
    want_name = str(payload.get("taskname") or "").strip()
    want_date = _normalize_date_for_compare(payload.get("startdate"))
    want_time = _format_hhmmss(str(payload.get("starttime") or ""))
    if not want_name or not want_date or not want_time:
        return {"status": "missing", "match_ids": [], "reason": "lookup_fields_missing"}
    try:
        items = _remote_taskinfo_items(task_type)
    except HTTPException as exc:
        return {"status": "error", "match_ids": [], "reason": str(exc.detail)}

    primary: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("taskname") or item.get("name") or "").strip()
        item_date = _normalize_date_for_compare(item.get("startdate"))
        item_time = _format_hhmmss(str(item.get("starttime") or item.get("time") or ""))
        if item_name == want_name and item_date == want_date and item_time == want_time:
            primary.append(item)

    match_basis = "taskname+startdate+starttime"
    filtered = list(primary)

    desired_tasktype = _coerce_int(payload.get("tasktype"), 0)
    if len(filtered) > 1 and desired_tasktype > 0:
        by_type = [item for item in filtered if _coerce_int(item.get("tasktype"), 0) == desired_tasktype]
        if by_type:
            filtered = by_type
            match_basis += "+tasktype"

    desired_mediaid = _strict_numeric_task_id_text(payload.get("mediaid"))
    if len(filtered) > 1 and desired_mediaid:
        by_media = [
            item for item in filtered
            if _strict_numeric_task_id_text(item.get("mediaid") or item.get("media_id")) == desired_mediaid
        ]
        if by_media:
            filtered = by_media
            match_basis += "+mediaid"

    desired_terminalid = _strict_numeric_task_id_text(
        payload.get("liveterminalid") or payload.get("terminalid") or payload.get("terminal_id")
    )
    if len(filtered) > 1 and desired_terminalid:
        by_terminal = [
            item for item in filtered
            if _strict_numeric_task_id_text(
                item.get("liveterminalid") or item.get("terminalid") or item.get("terminal_id") or item.get("ttsterminal")
            ) == desired_terminalid
        ]
        if by_terminal:
            filtered = by_terminal
            match_basis += "+terminal"

    match_ids = _unique_list([
        found_id
        for item in filtered
        for found_id in [_remote_extract_taskid(item)]
        if found_id
    ])
    if len(match_ids) == 1:
        LOGGER.info(
            "taskinfo fallback found id=%s | kind=%s taskname=%s startdate=%s starttime=%s basis=%s",
            match_ids[0], kind, want_name, want_date, want_time, match_basis,
        )
        return {"status": "resolved", "task_id": match_ids[0], "match_ids": match_ids, "match_basis": match_basis}
    if len(match_ids) > 1:
        return {"status": "ambiguous", "match_ids": match_ids, "match_basis": match_basis}
    return {"status": "missing", "match_ids": [], "match_basis": match_basis}


def _remote_add_taskinfo(
    kind: str,
    task: dict,
    media_map: dict,
    terminal_map: dict,
    diagnostic: Optional[dict] = None,
    diagnostics: Optional[dict] = None,
    lookup_retries: Optional[int] = None,
    lookup_delay_seconds: Optional[float] = None,
) -> Optional[str]:
    if diagnostic is None and diagnostics is not None:
        diagnostic = diagnostics
    payload, terminal_ids, media_id = _build_remote_taskinfo_payload(kind, task, media_map, terminal_map)
    task_id_value = _numeric_task_id(task.get("taskid") or task.get("id"))
    if task_id_value:
        payload["taskid"] = str(task_id_value)
    else:
        payload.pop("taskid", None)
    resp = _remote_request(
        "POST",
        "/task/taskinfo",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
        diagnostic=diagnostic,
    )
    task_id = _remote_extract_taskid(resp)
    if isinstance(diagnostic, dict):
        diagnostic.setdefault("lookup_attempts", [])
        diagnostic.setdefault("failure_code", "")
        diagnostic.setdefault("reason", "")
        diagnostic.setdefault("match_ids", [])
        diagnostic["request_payload_preview"] = {
            "taskname": payload.get("taskname"),
            "startdate": payload.get("startdate"),
            "starttime": payload.get("starttime"),
        }
        diagnostic["remote_response_preview"] = _clone_payload(resp)
        diagnostic["response_body"] = _clone_payload(resp)
    rejection_reason = ""
    rejection_code = ""
    response_items = _remote_data_list(resp)
    for item in response_items:
        if not isinstance(item, dict):
            continue
        state_value = item.get("state")
        extracted_id = _remote_extract_taskid(item)
        state_text = str(state_value).strip() if state_value not in (None, "") else ""
        if state_text and state_text not in {"0", "200", "success", "ok", "true", "True"} and not extracted_id:
            rejection_reason = (
                f"Remote task creation rejected by state={state_value} | "
                f"response={json.dumps(_clone_payload(item), ensure_ascii=False)}"
            )
            rejection_code = "taskinfo_remote_rejected"
            break
    # Fallback: some remote APIs return 200 OK without the new task ID in
    # the response body.  Query the task list to locate the just-created
    # task by matching taskname + startdate + starttime.
    if not task_id and not rejection_reason:
        retry_count = max(
            1,
            _coerce_int(
                REMOTE_TASKINFO_CREATE_LOOKUP_RETRIES if lookup_retries is None else lookup_retries,
                REMOTE_TASKINFO_CREATE_LOOKUP_RETRIES,
            ),
        )
        delay_seconds = (
            REMOTE_TASKINFO_CREATE_LOOKUP_DELAY_SECONDS
            if lookup_delay_seconds is None or float(lookup_delay_seconds) < 0
            else float(lookup_delay_seconds)
        )
        for attempt in range(1, retry_count + 1):
            lookup_result = _remote_find_created_taskinfo(kind, payload)
            matches = list(lookup_result.get("match_ids") or [])
            lookup_status = str(lookup_result.get("status") or "")
            if isinstance(diagnostic, dict):
                diagnostic.setdefault("lookup_attempts", []).append(
                    {
                        "attempt": attempt,
                        "status": lookup_status or "ok",
                        "match_count": len(matches),
                        "match_basis": str(lookup_result.get("match_basis") or ""),
                        "reason": str(lookup_result.get("reason") or ""),
                    }
                )
            if lookup_status == "resolved" and matches:
                task_id = str(lookup_result.get("task_id") or matches[-1])
                break
            if lookup_status == "ambiguous":
                if isinstance(diagnostic, dict):
                    diagnostic["failure_code"] = "taskinfo_lookup_ambiguous"
                    diagnostic["reason"] = "Remote task creation returned multiple candidate task ids."
                    diagnostic["match_ids"] = _clone_payload(matches)
                break
            if attempt < retry_count and delay_seconds > 0:
                time.sleep(delay_seconds)
    if not task_id and DEBUG_REMOTE:
        try:
            resp_preview = json.dumps(resp, ensure_ascii=False)
        except Exception:
            resp_preview = str(resp)
        if len(resp_preview) > 1200:
            resp_preview = f"{resp_preview[:1200]}...(truncated)"
        data_type = ""
        if isinstance(resp, dict):
            data_type = type(resp.get("data")).__name__
        LOGGER.warning(
            "taskinfo create missing taskid | kind=%s taskname=%s startdate=%s starttime=%s data_type=%s resp=%s",
            kind,
            payload.get("taskname"),
            payload.get("startdate"),
            payload.get("starttime"),
            data_type,
            resp_preview,
        )
    if not task_id and isinstance(diagnostic, dict):
        if rejection_reason:
            diagnostic["failure_code"] = rejection_code or "taskinfo_remote_rejected"
            diagnostic["reason"] = rejection_reason
        elif diagnostic.get("failure_code") == "taskinfo_lookup_ambiguous":
            diagnostic.setdefault("reason", "Remote task creation returned multiple candidate task ids.")
        elif diagnostic.get("lookup_attempts"):
            diagnostic["failure_code"] = "taskinfo_lookup_not_found"
            diagnostic["reason"] = "Remote taskinfo succeeded but the system could not confirm the new task id."
        else:
            diagnostic["failure_code"] = "taskinfo_no_taskid"
            diagnostic["reason"] = "Remote taskinfo succeeded but returned no taskid."
        diagnostic["ok"] = False
        diagnostic["error_detail"] = str(diagnostic.get("reason") or rejection_reason or "")
    if task_id:
        task["id"] = task_id
        task["taskid"] = task_id
        _remote_replace_taskmusic(task_id, [media_id])
        try:
            _remote_replace_taskterminals(task_id, terminal_ids, task=task)
        except TypeError as exc:
            if "unexpected keyword argument 'task'" not in str(exc):
                raise
            _remote_replace_taskterminals(task_id, terminal_ids)
    return task_id


def _remote_add_taskinfo_with_diagnostic(
    kind: str,
    task: dict,
    media_map: dict,
    terminal_map: dict,
    diagnostic: Optional[dict] = None,
) -> Optional[str]:
    try:
        return _remote_add_taskinfo(kind, task, media_map, terminal_map, diagnostics=diagnostic)
    except TypeError as exc:
        if "unexpected keyword argument 'diagnostics'" not in str(exc):
            raise
    try:
        return _remote_add_taskinfo(kind, task, media_map, terminal_map, diagnostic=diagnostic)
    except TypeError as exc:
        if "unexpected keyword argument 'diagnostic'" not in str(exc):
            raise
    return _remote_add_taskinfo(kind, task, media_map, terminal_map)


def _remote_update_taskinfo(
    task_id: str,
    kind: str,
    task: dict,
    media_map: dict,
    terminal_map: dict,
    remote_fallback: dict,
) -> None:
    payload, terminal_ids, media_id = _build_remote_taskinfo_payload(
        kind,
        task,
        media_map,
        terminal_map,
        remote_fallback=remote_fallback,
    )
    task_id_value = _coerce_int(task_id, 0)
    payload["taskid"] = str(task_id_value)
    _remote_request(
        "PUT",
        "/task/taskinfo",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )
    _remote_replace_taskmusic(task_id, [media_id])
    previous_terminal_ids = _terminal_ids_from_taskterminal(remote_fallback.get("taskterminal"))
    if not previous_terminal_ids:
        previous_terminal_ids = _schedule_task_terminal_ids(remote_fallback or {}, terminal_map)
    try:
        _remote_replace_taskterminals(
            task_id,
            terminal_ids,
            previous_terminal_ids=previous_terminal_ids,
            task=task,
            previous_task=remote_fallback,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        _remote_replace_taskterminals(task_id, terminal_ids)


def _is_numeric_id(value: str) -> bool:
    return str(value).isdigit()


def _numeric_task_id(value: object) -> int:
    text = _strict_numeric_task_id_text(value)
    return int(text) if text else 0


def _task_id(task: dict) -> str:
    for key in ("taskid", "id", "task_id", "taskId", "sechetaskid"):
        if task.get(key) is not None:
            return str(task.get(key))
    return ""


def _real_schedule_task_id(value: object) -> str:
    text = str(value or "").strip()
    if text.isdigit() and text != "0":
        return text
    return ""


def _task_real_id(task: dict) -> str:
    if not isinstance(task, dict):
        return ""
    for key in ("taskid", "task_id", "taskId", "sechetaskid"):
        task_id = _real_schedule_task_id(task.get(key))
        if task_id:
            return task_id
    return ""


def _resolve_remote_delete_task_ids(schedule_name: str, tasks: List[dict]) -> Tuple[List[str], List[str]]:
    if not schedule_name:
        return [], ["未指定方案名称"]
    try:
        remote_tasks = [_normalize_remote_task(item) for item in _remote_fetch_schedule_tasks(schedule_name)]
    except HTTPException as exc:
        raise HTTPException(status_code=502, detail=f"读取远端方案任务失败:{exc.detail}") from exc

    resolved_ids: List[str] = []
    unresolved: List[str] = []
    used_remote_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        direct_id = _task_real_id(task)
        if direct_id:
            resolved_ids.append(direct_id)
            used_remote_ids.add(direct_id)
            continue

        local_id = _task_id(task)
        matched_id = ""
        if local_id and _is_numeric_id(local_id):
            for remote_task in remote_tasks:
                remote_id = _task_real_id(remote_task) or _task_id(remote_task)
                if remote_id and remote_id == local_id and remote_id not in used_remote_ids:
                    matched_id = remote_id
                    break
        if not matched_id:
            want_name = str(task.get("taskname") or task.get("name") or task.get("customName") or "").strip()
            want_date = _normalize_date_for_compare(task.get("startdate"))
            want_end = _normalize_date_for_compare(task.get("enddate"))
            want_time = _format_hhmmss(str(task.get("starttime") or task.get("time") or ""))
            for remote_task in remote_tasks:
                remote_id = _task_real_id(remote_task) or _task_id(remote_task)
                if not remote_id or remote_id in used_remote_ids:
                    continue
                remote_name = str(
                    remote_task.get("taskname") or remote_task.get("name") or remote_task.get("customName") or ""
                ).strip()
                remote_date = _normalize_date_for_compare(remote_task.get("startdate"))
                remote_end = _normalize_date_for_compare(remote_task.get("enddate"))
                remote_time = _format_hhmmss(str(remote_task.get("starttime") or remote_task.get("time") or ""))
                if (
                    want_name == remote_name
                    and want_date == remote_date
                    and want_time == remote_time
                    and want_end == remote_end
                ):
                    matched_id = remote_id
                    break
        if matched_id:
            resolved_ids.append(matched_id)
            used_remote_ids.add(matched_id)
            continue
        unresolved.append(str(task.get("taskname") or local_id or "未命名任务"))
    return _unique_list(resolved_ids), _unique_list(unresolved)


def _task_has_explicit_terminal_binding(task: dict) -> bool:
    if not isinstance(task, dict):
        return False
    bindings = _normalize_taskterminal_bindings(task.get("taskterminal") or task.get("taskTerminal"))
    return bool(bindings) and all(bool(binding.get("groupid_present")) for binding in bindings)


def _schedule_task_terminal_ids(task: dict, terminal_map: dict) -> List[str]:
    return [item for item in _get_task_terminal_ids(task or {}, terminal_map) if item and str(item) != "0"]


def _schedule_task_binding_signatures(
    task: dict,
    terminal_map: dict,
    terminal_lookup: Optional[dict] = None,
    zone_items: Optional[list] = None,
) -> List[str]:
    terminal_ids = _schedule_task_terminal_ids(task or {}, terminal_map)
    bindings = _desired_taskterminal_bindings(task, terminal_ids, terminal_lookup, zone_items)
    return _sorted_unique_signatures([
        signature
        for signature in _taskterminal_binding_signatures(bindings)
        if signature
    ])


def _schedule_task_terminals_changed(
    desired_task: dict,
    remote_task: dict,
    terminal_map: dict,
    terminal_lookup: Optional[dict] = None,
    zone_items: Optional[list] = None,
) -> bool:
    desired_signatures = _schedule_task_binding_signatures(desired_task, terminal_map, terminal_lookup, zone_items)
    if not desired_signatures:
        return False
    remote_bindings = _normalize_taskterminal_bindings(
        (remote_task or {}).get("taskterminal") or (remote_task or {}).get("taskTerminal")
    )
    if remote_bindings:
        remote_signatures = _sorted_unique_signatures([
            signature
            for signature in _taskterminal_binding_signatures(remote_bindings)
            if signature
        ])
    else:
        remote_signatures = _schedule_task_binding_signatures(remote_task or {}, terminal_map, terminal_lookup, zone_items)
    changed = remote_signatures != desired_signatures
    if changed:
        LOGGER.info(
            "schedule task terminal diff | schedule=%s taskid=%s task=%s desired=%s remote=%s",
            str(desired_task.get("sechename") or remote_task.get("sechename") or "").strip(),
            _task_real_id(desired_task) or _task_real_id(remote_task),
            str(desired_task.get("customName") or desired_task.get("taskname") or remote_task.get("taskname") or "").strip(),
            desired_signatures,
            remote_signatures,
        )
    return changed


def _sync_schedule_task_set(
    schedule_name: str,
    desired_tasks: list,
    remote_tasks: list,
    media_map: dict,
    terminal_map: dict,
) -> dict:
    remote_map = {
        task_id: task
        for task in remote_tasks
        if isinstance(task, dict)
        for task_id in [_task_real_id(task)]
        if task_id
    }
    desired_real_ids = set()
    tasks_to_create: List[dict] = []
    tasks_to_update: List[Tuple[str, dict, dict]] = []

    for task in desired_tasks:
        if not isinstance(task, dict):
            continue
        task_id = _task_real_id(task)
        if task_id and task_id in remote_map:
            desired_real_ids.add(task_id)
            tasks_to_update.append((task_id, task, remote_map[task_id]))
        else:
            tasks_to_create.append(task)

    stats = {
        "mutated": False,
        "unchanged_count": 0,
        "updated_count": 0,
        "created_count": 0,
        "deleted_count": 0,
        "terminal_rebind_count": 0,
    }

    terminal_lookup = _remote_terminal_lookup() if tasks_to_update else {}
    zone_items: List[dict] = []
    if tasks_to_update:
        try:
            zone_items = _fetch_enriched_zone_items()
        except Exception as exc:
            LOGGER.warning("failed to fetch terzone while syncing schedule task set: %s", exc)

    for task_id, desired_task, remote_task in tasks_to_update:
        remote_compare_task = remote_task
        if _task_has_explicit_terminal_binding(desired_task):
            remote_compare_task = _hydrate_remote_taskterminal_snapshot(remote_task)
        payload_task = _build_remote_task_payload(
            schedule_name,
            desired_task,
            media_map,
            terminal_map,
            remote_fallback=remote_compare_task,
        )
        terminals_changed = _schedule_task_terminals_changed(
            desired_task,
            remote_compare_task,
            terminal_map,
            terminal_lookup,
            zone_items,
        )
        task_changed = _remote_task_changed(desired_task, remote_compare_task, payload_task)
        if not task_changed and not terminals_changed:
            stats["unchanged_count"] += 1
            continue
        try:
            _remote_update_task(
                task_id,
                schedule_name,
                desired_task,
                media_map,
                terminal_map,
                remote_compare_task,
                task_changed=task_changed,
                terminals_changed=terminals_changed,
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            _remote_update_task(
                task_id,
                schedule_name,
                desired_task,
                media_map,
                terminal_map,
                remote_compare_task,
            )
        stats["mutated"] = True
        stats["updated_count"] += 1
        if terminals_changed:
            stats["terminal_rebind_count"] += 1
        LOGGER.info(
            "schedule task sync update | schedule=%s taskid=%s task=%s reason=%s",
            schedule_name,
            task_id,
            str(desired_task.get("customName") or desired_task.get("taskname") or "").strip(),
            "task+terminals" if task_changed and terminals_changed else ("task" if task_changed else "terminals"),
        )

    current_snapshot = [_normalize_remote_task(item) for item in remote_tasks if isinstance(item, dict)]
    for task in tasks_to_create:
        new_task_id = _remote_add_task(
            schedule_name,
            task,
            media_map,
            terminal_map,
            pre_create_snapshot=current_snapshot,
        )
        if not new_task_id:
            new_task_id = _task_real_id(task)
        if new_task_id:
            desired_real_ids.add(new_task_id)
            current_snapshot.append(_build_created_schedule_snapshot_entry(task, new_task_id))
        stats["mutated"] = True
        stats["created_count"] += 1

    for task_id in sorted(remote_map.keys()):
        if task_id in desired_real_ids:
            continue
        _remote_delete_task(task_id)
        stats["mutated"] = True
        stats["deleted_count"] += 1

    LOGGER.info(
        "schedule task sync summary | schedule=%s unchanged=%s updated=%s created=%s deleted=%s terminal_rebind=%s",
        schedule_name,
        stats["unchanged_count"],
        stats["updated_count"],
        stats["created_count"],
        stats["deleted_count"],
        stats["terminal_rebind_count"],
    )
    return stats


def _remote_task_changed(desired: dict, remote: dict, payload: dict) -> bool:
    time_fields = {"starttime"}
    date_fields = {"startdate", "enddate"}
    int_fields = {
        "mediaid",
        "volume",
        "priority",
        "execmode",
        "tasktype",
        "timelength",
        "timelengthtype",
    }
    compare_keys = (
        "taskname",
        "starttime",
        "startdate",
        "enddate",
        "mediaid",
        "volume",
        "priority",
        "execmode",
        "tasktype",
        "timelength",
        "timelengthtype",
    )
    task_id = _task_real_id(desired) or _task_real_id(remote) or str(payload.get("taskid") or "").strip()
    schedule_name = str(payload.get("sechename") or desired.get("sechename") or remote.get("sechename") or "").strip()
    task_name = str(payload.get("taskname") or desired.get("customName") or desired.get("taskname") or remote.get("taskname") or "").strip()
    for key in compare_keys:
        desired_raw = payload.get(key)
        if key == "taskname":
            desired_raw = desired_raw or desired.get("customName") or desired.get("taskname")
            remote_raw = remote.get("taskname") or remote.get("name") or remote.get("medianame")
            desired_norm = str(desired_raw or "").strip()
            remote_norm = str(remote_raw or "").strip()
        elif key in time_fields:
            remote_raw = remote.get(key)
            desired_norm = _encode_time_value(desired_raw)
            remote_norm = _encode_time_value(remote_raw)
        elif key in date_fields:
            remote_raw = remote.get(key)
            desired_norm = _encode_date_value(desired_raw)
            remote_norm = _encode_date_value(remote_raw)
        elif key in int_fields:
            remote_raw = remote.get("mediaid") if key == "mediaid" else remote.get(key)
            if key == "mediaid" and remote_raw in (None, ""):
                remote_raw = remote.get("media_id")
            desired_norm = _coerce_int(desired_raw, 0)
            remote_norm = _coerce_int(remote_raw, 0)
        else:
            remote_raw = remote.get(key)
            desired_norm = str(desired_raw or "").strip()
            remote_norm = str(remote_raw or "").strip()
        if key in time_fields | date_fields | int_fields:
            if desired_norm == 0 and remote_norm == 0:
                continue
        else:
            if not desired_norm and not remote_norm:
                continue
        if desired_norm != remote_norm:
            LOGGER.info(
                "schedule task field diff | schedule=%s taskid=%s task=%s field=%s desired=%s remote=%s",
                schedule_name,
                task_id,
                task_name,
                key,
                desired_norm,
                remote_norm,
            )
            return True
    return False


def _remote_taskinfo_changed(payload: dict, remote: dict) -> bool:
    def _pick_remote(keys: Tuple[str, ...]) -> Optional[object]:
        for key in keys:
            value = remote.get(key)
            if value not in (None, ""):
                return value
        return None

    checks = [
        ("taskname", ("taskname", "name", "medianame")),
        ("starttime", ("starttime", "start_time", "time", "stime")),
        ("startdate", ("startdate", "start_date", "startDate")),
        ("enddate", ("enddate", "end_date", "endDate")),
        ("mediaid", ("mediaid", "media_id")),
        ("liveterminalid", ("liveterminalid", "terminalid", "terminal_id", "ttsterminal")),
        ("timelength", ("timelength", "length")),
        ("timelengthtype", ("timelengthtype", "lengthtype")),
        ("volume", ("volume",)),
        ("tasktype", ("tasktype",)),
    ]
    for payload_key, remote_keys in checks:
        desired = payload.get(payload_key)
        if desired is None:
            continue
        remote_value = _pick_remote(remote_keys)
        if remote_value is None:
            continue
        if str(desired) != str(remote_value):
            return True
    desired_state = payload.get("state")
    if desired_state is not None:
        remote_state = _pick_remote(("taskstate", "state", "enablestate"))
        if remote_state is not None and str(desired_state) != str(remote_state):
            return True
    return False

def _extract_media_ids_from_task(task: dict) -> list:
    """
    【极简版】只提取单个 mediaid,兼容旧代码的列表接口。
    """
    if not isinstance(task, dict):
        return []
    
    # 只找最显眼的 mediaid
    media_id = task.get("mediaid") or task.get("media_id") or task.get("id")
    
    # 如果找到了,返回一个单元素列表(为了兼容其他函数)
    if media_id is not None and str(media_id) != "0":
        return [str(media_id)]
        
    return []

def _taskinfo_match_key(task: dict) -> Optional[str]:
    if not isinstance(task, dict):
        return None
    name = task.get("taskname") or task.get("name") or task.get("audio") or task.get("medianame") or ""
    name = str(name).strip()
    if not name:
        return None
    raw_time = task.get("starttime") or task.get("start_time") or task.get("time") or task.get("stime") or ""
    time_value = _format_hhmmss(str(raw_time)) if raw_time else ""
    media_id = task.get("mediaid") or task.get("media_id")
    media_name = _clean_media_name(task.get("medianame") or task.get("audio") or "")
    terminal_id = (
        task.get("liveterminalid")
        or task.get("terminalid")
        or task.get("terminal_id")
        or task.get("ttsterminal")
    )
    media_part = ""
    if media_id not in (None, "", 0, "0"):
        media_part = str(_coerce_int(media_id, 0))
    elif media_name:
        media_part = str(media_name)
    terminal_part = ""
    if terminal_id not in (None, "", 0, "0"):
        terminal_part = str(_coerce_int(terminal_id, 0))
    return "|".join([name, time_value, media_part, terminal_part])


def _sorted_unique_signatures(values: object) -> List[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(value).strip() for value in values if str(value or "").strip()})


def _canonicalize_schedule_task_locations_for_sync(task: dict) -> List[str]:
    entries = _task_location_binding_entries(task)
    signatures: List[str] = []
    for entry in entries:
        raw_parts = entry.get("raw")
        if not isinstance(raw_parts, list):
            continue
        compact_parts = [_compact_text(str(part or "").strip()) for part in raw_parts if str(part or "").strip()]
        if compact_parts:
            signatures.append("|".join(compact_parts))
    return _sorted_unique_signatures(signatures)


def _canonicalize_schedule_task_for_sync(task: dict) -> dict:
    if not isinstance(task, dict):
        return {}
    task_name = str(task.get("customName") or task.get("taskname") or task.get("audio") or "").strip()
    raw_time = task.get("starttime") or task.get("time") or ""
    starttime = _format_hhmmss(raw_time)
    startdate, enddate = _extract_date_range(task)
    timelength, timelengthtype = _normalize_schedule_timelength(task)
    media_name = _clean_media_name(task.get("audio") or task.get("medianame") or task.get("taskname") or task_name)
    terminal_values = _normalize_terminal_ids(task.get("terminalids") or task.get("terminal_ids") or [])
    if task.get("liveterminalid") not in (None, "", 0, "0"):
        terminal_values.extend(_normalize_terminal_ids([task.get("liveterminalid")]))
    terminal_ids = _normalize_terminal_ids(terminal_values)
    execmode_value = task.get("execmode")
    if execmode_value in (None, "", 0, "0"):
        weekdays_value = task.get("weekdays")
        if isinstance(weekdays_value, list) and weekdays_value:
            execmode_value = _execmode_from_weekdays(weekdays_value)
    canonical = {
        "task_name": task_name,
        "starttime": _encode_time_value(starttime),
        "startdate": _encode_date_value(startdate),
        "enddate": _encode_date_value(enddate),
        "mediaid": _coerce_int(task.get("mediaid") or task.get("media_id"), 0),
        "medianame": media_name,
        "execmode": _coerce_int(execmode_value, 0),
        "tasktype": _coerce_int(task.get("tasktype"), 1),
        "volume": _coerce_int(task.get("volume"), 50),
        "priority": _coerce_int(task.get("priority"), 0),
        "datasendmodel": _coerce_int(task.get("datasendmodel"), 0),
        "prepower": _coerce_int(task.get("prepower"), 0),
        "level": _coerce_int(task.get("level"), 0),
        "israndomplay": _coerce_int(task.get("israndomplay"), 0),
        "timelength": _coerce_int(timelength, 0),
        "timelengthtype": _coerce_int(timelengthtype, 0),
        "cmd": _coerce_int(task.get("cmd"), 0),
        "cmdargs": str(task.get("cmdargs") if task.get("cmdargs") not in (None, "") else "0"),
        "bandrate": _coerce_int(task.get("bandrate"), 0),
        "samplerate": _coerce_int(task.get("samplerate"), 0),
        "caiboprepower": _coerce_int(task.get("caiboprepower"), 0),
        "terminalids": sorted(set(terminal_ids)),
        "locations": _canonicalize_schedule_task_locations_for_sync(task),
    }
    return canonical


def _schedule_task_sync_identity(task: dict) -> str:
    real_id = _task_real_id(task)
    if real_id:
        return f"id:{real_id}"
    match_key = _taskinfo_match_key(task)
    if match_key:
        return f"match:{match_key}"
    canonical = _canonicalize_schedule_task_for_sync(task)
    return f"inline:{json.dumps(canonical, ensure_ascii=False, sort_keys=True)}"


def _canonicalize_schedule_for_sync(schedule: dict) -> dict:
    if not isinstance(schedule, dict):
        return {}
    tasks = schedule.get("tasks") or []
    canonical_tasks: List[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        canonical_task = _canonicalize_schedule_task_for_sync(task)
        canonical_tasks.append(
            {
                "identity": _schedule_task_sync_identity(task),
                **canonical_task,
            }
        )
    canonical_tasks.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return {
        "status_enabled": bool(_status_enabled(schedule.get("status") or "启用")),
        "tasks": canonical_tasks,
    }


def _schedule_payload_name(schedule: object) -> str:
    if not isinstance(schedule, dict):
        return ""
    return str(schedule.get("schedule_name") or schedule.get("name") or "").strip()


def _schedule_origin_name(schedule: object) -> str:
    if not isinstance(schedule, dict):
        return ""
    current_name = _schedule_payload_name(schedule)
    for key in ("origin_name", "originName", "original_name", "originalName"):
        value = str(schedule.get(key) or "").strip()
        if value and value != current_name:
            return value
    return ""


def _schedule_sync_delta(source_payload: dict, target_payload: dict) -> dict:
    source_map: Dict[str, dict] = {}
    target_map: Dict[str, dict] = {}
    for payload, mapping in ((source_payload, source_map), (target_payload, target_map)):
        schedules = payload.get("schedules") if isinstance(payload, dict) else []
        if not isinstance(schedules, list):
            continue
        for schedule in schedules:
            if not isinstance(schedule, dict):
                continue
            schedule_name = _schedule_payload_name(schedule)
            if not schedule_name:
                continue
            mapping[schedule_name] = {
                "canonical": _canonicalize_schedule_for_sync(schedule),
                "origin_name": _schedule_origin_name(schedule),
            }
    changed_or_added_names: List[str] = []
    renamed: List[dict] = []
    renamed_from_names: set[str] = set()
    for name, target_entry in target_map.items():
        target_canonical = target_entry.get("canonical")
        if source_map.get(name, {}).get("canonical") == target_canonical:
            continue
        rename_source = ""
        origin_name = str(target_entry.get("origin_name") or "").strip()
        if origin_name and origin_name in source_map and origin_name not in target_map:
            rename_source = origin_name
        elif name not in source_map:
            for source_name, source_entry in source_map.items():
                if source_name in renamed_from_names or source_name in target_map:
                    continue
                if str(source_entry.get("origin_name") or "").strip() == name:
                    rename_source = source_name
                    break
        if rename_source:
            renamed.append({"from": rename_source, "to": name})
            renamed_from_names.add(rename_source)
        if name not in changed_or_added_names:
            changed_or_added_names.append(name)
    removed_names = [
        name for name in source_map.keys()
        if name not in target_map and name not in renamed_from_names
    ]
    return {
        "changed_or_added_names": _unique_list(changed_or_added_names),
        "removed_names": _unique_list(removed_names),
        "renamed": renamed,
    }
def _sync_remote_taskinfo(kind: str, task_type: object, desired_tasks: list) -> None:
    if not isinstance(desired_tasks, list):
        return
    start = time.perf_counter()
    
    # 1. 确定任务类型 ID
    if kind == "livecast":
        task_type_default = _coerce_int(REMOTE_LIVECAST_TASK_TYPE, 3)
    elif kind == "broadcast":
        task_type_default = _coerce_int(REMOTE_BROADCAST_TASK_TYPE, 2)
    else:
        task_type_default = 2
    task_type_value = _coerce_int(task_type, task_type_default)

    # 2. 获取远端现有任务 (带链接信息)
    try:
        remote_items = _remote_taskinfo_items_with_links(
            task_type_value,
            fill_media=True,     # 依然需要,为了对比媒体ID
            fill_terminal=True,  # 依然需要,为了对比终端ID
        )
    except HTTPException:
        remote_items = []

    # 3. 建立索引映射
    remote_map = {str(_task_id(task)): task for task in remote_items if _task_id(task)}
    desired_map = {str(_task_id(task)): task for task in desired_tasks if _task_id(task)}
    
    desired_ids = {task_id for task_id in desired_map if _is_numeric_id(task_id)}
    remote_ids = {task_id for task_id in remote_map if _is_numeric_id(task_id)}

    desired_keys: set[str] = set()
    for task in desired_tasks:
        key = _taskinfo_match_key(task)
        if key:
            desired_keys.add(key)

    remote_keys: Dict[str, List[str]] = {}
    for task_id, task in remote_map.items():
        if not _is_numeric_id(task_id):
            continue
        key = _taskinfo_match_key(task)
        if not key:
            continue
        remote_keys.setdefault(key, []).append(task_id)

    media_map = _remote_media_map()
    terminal_map = _remote_terminal_map()

    # 音量提取小助手
    def _volume_value(task: dict) -> Optional[int]:
        if not isinstance(task, dict): return None
        value = task.get("volume")
        if value in (None, ""): return None
        try: return int(value)
        except: return None

    # 4. 核心同步循环
    for task in desired_tasks:
        task_id = _task_id(task)
        
        # A. 新增任务
        if not task_id or not _is_numeric_id(task_id) or task_id not in remote_map:
            _remote_add_taskinfo(kind, task, media_map, terminal_map)
            continue
            
        # B. 更新任务
        remote_task = remote_map.get(task_id) or {}
        
        # 构建期望的 Payload (这里面只包含单个 mediaid)
        payload, _, _ = _build_remote_taskinfo_payload(
            kind, task, media_map, terminal_map, remote_fallback=remote_task
        )
        
        # 检查1: 基础属性是否变更 (包含 mediaid, time, terminal 等)
        # 注意:这里不需要额外写 media_list_changed 了,因为 payload 里只有单个 mediaid
        # _remote_taskinfo_changed 会自动对比 payload['mediaid'] 和 remote_task['mediaid']
        basic_changed = _remote_taskinfo_changed(payload, remote_task)
        
        # 检查2: 音量是否变更
        desired_volume = _volume_value(task)
        remote_volume = _volume_value(remote_task)
        volume_changed = (desired_volume is not None) and (desired_volume != remote_volume)
        
        # 执行更新
        if basic_changed:
            try:
                _remote_update_taskinfo(task_id, kind, task, media_map, terminal_map, remote_task)
            except HTTPException:
                # 如果更新失败(比如远端被删了),尝试重建
                _remote_delete_taskinfo(task_id)
                _remote_add_taskinfo(kind, task, media_map, terminal_map)
        
        # 单独处理音量 (如果在更新基础信息时没能同步音量,或者只是音量变了)
        # 这里的逻辑是:如果需要改音量,就发一个专门的音量包,确保万无一失
        if volume_changed and desired_volume is not None:
            try:
                _remote_set_task_volume(task_id, desired_volume)
            except HTTPException:
                pass

    # 5. 删除多余任务
    keep_ids = set(desired_ids)
    if desired_keys:
        for key in desired_keys:
            ids = remote_keys.get(key)
            if ids:
                keep_ids.update(ids)
    # 【修复问题#1】修正删除逻辑:直接计算差集,只要有多余的任务就删除
    tasks_to_delete = remote_ids - keep_ids
    if tasks_to_delete:
        _batch_delete_parallel(tasks_to_delete, _remote_delete_taskinfo, label="sync_taskinfo")

    _debug_timing("sync remote taskinfo", (time.perf_counter() - start) * 1000, kind=kind)
    
# def _sync_remote_taskinfo(kind: str, task_type: object, desired_tasks: list) -> None:
#     if not isinstance(desired_tasks, list):
#         return
#     start = time.perf_counter()
#     if kind == "livecast":
#         task_type_default = _coerce_int(REMOTE_LIVECAST_TASK_TYPE, 3)
#     elif kind == "broadcast":
#         task_type_default = _coerce_int(REMOTE_BROADCAST_TASK_TYPE, 2)
#     else:
#         task_type_default = 2
#     task_type_value = _coerce_int(task_type, task_type_default)
#     try:
#         remote_items = _remote_taskinfo_items_with_links(
#             task_type_value,
#             fill_media=True,
#             fill_terminal=True,
#         )
#     except HTTPException:
#         remote_items = []
#     remote_map = {str(_task_id(task)): task for task in remote_items if _task_id(task)}
#     desired_map = {str(_task_id(task)): task for task in desired_tasks if _task_id(task)}
#     desired_ids = {task_id for task_id in desired_map if _is_numeric_id(task_id)}
#     remote_ids = {task_id for task_id in remote_map if _is_numeric_id(task_id)}
#     media_map = _remote_media_map()
#     terminal_map = _remote_terminal_map()
#     def _volume_value(task: dict) -> Optional[int]:
#         if not isinstance(task, dict):
#             return None
#         value = task.get("volume")
#         if value in (None, ""):
#             return None
#         try:
#             return int(value)
#         except Exception:
#             return None
#     for task in desired_tasks:
#         task_id = _task_id(task)
#         if not task_id or not _is_numeric_id(task_id) or task_id not in remote_map:
#             _remote_add_taskinfo(kind, task, media_map, terminal_map)
#             continue
#         remote_task = remote_map.get(task_id) or {}
#         payload, _, _ = _build_remote_taskinfo_payload(
#             kind, task, media_map, terminal_map, remote_fallback=remote_task
#         )
#         if _remote_taskinfo_changed(payload, remote_task):
#             try:
#                 _remote_update_taskinfo(task_id, kind, task, media_map, terminal_map, remote_task)
#             except HTTPException:
#                 _remote_delete_taskinfo(task_id)
#                 _remote_add_taskinfo(kind, task, media_map, terminal_map)
#     if desired_ids:
#         for task_id in remote_ids - desired_ids:
#             _remote_delete_taskinfo(task_id)
#     _debug_timing("sync remote taskinfo", (time.perf_counter() - start) * 1000, kind=kind, task_type=task_type_value)

def _sync_remote_schedules(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid schedules payload.")
    start = time.perf_counter()
    
    # 1. 获取远端数据
    remote_payload = _adapt_remote_schedules(_remote_fetch_schedule_source())
    remote_schedules = remote_payload.get("schedules", []) if isinstance(remote_payload, dict) else []
    
    remote_by_name: Dict[str, List[dict]] = {}
    remote_status_by_name: Dict[str, str] = {}
    
    for sched in remote_schedules:
        if not isinstance(sched, dict): continue
        name = sched.get("schedule_name") or sched.get("name") or sched.get("sechename")
        if not name: continue
        tasks = sched.get("tasks") or []
        remote_by_name[str(name)] = _filter_once_ephemeral_schedule_tasks(
            [_normalize_remote_task(t) for t in tasks if isinstance(t, dict)]
        )
        remote_status_by_name[str(name)] = sched.get("status") or "启用"

    media_map = _remote_media_map()
    terminal_map = _remote_terminal_map()
    try:
        remote_catalog_names, remote_catalog_status = _remote_schedule_catalog_snapshot()
    except Exception:
        remote_catalog_names = set(remote_by_name.keys())
        remote_catalog_status = {}
    known_ai_once_names = _known_ai_once_schedule_names_from_overrides()
    remote_catalog_names = set(_filter_visible_schedule_names(remote_catalog_names, known_ai_once_names))
    remote_catalog_status = _filter_visible_schedule_status_map(remote_catalog_status, known_ai_once_names)
    for name, status in remote_catalog_status.items():
        remote_status_by_name.setdefault(name, status)
    schedules = payload.get("schedules") or []
    local_schedule_names = {
        str((sched or {}).get("schedule_name") or (sched or {}).get("name"))
        for sched in schedules
        if isinstance(sched, dict) and ((sched.get("schedule_name") or sched.get("name")))
    }

    # 2. 遍历本地作息方案
    for sched in schedules:
        if not isinstance(sched, dict): continue
        schedule_name = sched.get("schedule_name") or sched.get("name")
        if not schedule_name: continue
        schedule_name = str(schedule_name)
        created_schedule = False

        # Ensure schedule catalog (/task/sechinfo) contains this schedule name.
        if schedule_name not in remote_catalog_names:
            _remote_ensure_schedule(schedule_name, catalog_names=remote_catalog_names)
            remote_catalog_names.add(schedule_name)
            created_schedule = True
        # Ensure we have remote task snapshot for this schedule.
        if schedule_name not in remote_by_name:
            try:
                fetched = _remote_fetch_schedule_tasks(schedule_name)
                remote_by_name[schedule_name] = _filter_once_ephemeral_schedule_tasks(
                    [_normalize_remote_task(t) for t in fetched if isinstance(t, dict)]
                )
            except HTTPException:
                remote_by_name.setdefault(schedule_name, [])

        desired_status = sched.get("status") or "启用"
        desired_enabled = _status_enabled(desired_status)
        mutated_tasks = False

        # 3. 同步具体任务
        remote_tasks = remote_by_name.get(schedule_name, [])
        desired_tasks = sched.get("tasks") or []
        task_sync_stats = _sync_schedule_task_set(schedule_name, desired_tasks, remote_tasks, media_map, terminal_map)
        if task_sync_stats.get("mutated"):
            mutated_tasks = True

        remote_status = remote_status_by_name.get(schedule_name)
        if created_schedule or mutated_tasks or remote_status is None or _status_enabled(remote_status) != desired_enabled:
            _remote_set_schedule_status(schedule_name, desired_enabled)
            remote_status_by_name[schedule_name] = "启用" if desired_enabled else "停用"

    # D. 删除远端多余作息(本地已删除方案时,清空远端该方案的任务)
    remote_only_names = [
        name for name in remote_by_name.keys()
        if name not in local_schedule_names and not _is_hidden_ai_once_schedule_name(name, known_ai_once_names)
    ]
    if remote_only_names:
        _sync_remote_schedules_removed(
            remote_only_names,
            remote_tasks_by_name={
                name: list(remote_by_name.get(name) or [])
                for name in remote_only_names
            },
        )

    _debug_timing("sync remote schedules", (time.perf_counter() - start) * 1000)


def _sync_remote_schedule_renames(rename_pairs: List[dict]) -> List[str]:
    failed_sources: List[str] = []
    for pair in rename_pairs or []:
        if not isinstance(pair, dict):
            continue
        source_name = str(pair.get("from") or "").strip()
        target_name = str(pair.get("to") or "").strip()
        if not source_name or not target_name or source_name == target_name:
            continue
        try:
            _remote_rename_schedule_entry(source_name, target_name)
        except Exception as exc:
            detail = getattr(exc, "detail", exc)
            LOGGER.warning(
                "remote schedule rename failed | source=%s target=%s detail=%s",
                source_name,
                target_name,
                _short_error_text(detail),
            )
            failed_sources.append(source_name)
    return _unique_list(failed_sources)


def _sync_remote_schedules_targeted(payload: dict, target_names: List[str]) -> None:
    """轻量版 _sync_remote_schedules:只同步指定的方案,不拉全量远端数据。"""
    if not isinstance(payload, dict) or not target_names:
        return
    start = time.perf_counter()
    target_set = set(target_names)

    # 1. 获取远端方案目录(轻量:只是名字列表)
    try:
        remote_catalog_names, remote_status_by_name = _remote_schedule_catalog_snapshot()
    except HTTPException:
        remote_catalog_names = set()
        remote_status_by_name = {}
    known_ai_once_names = _known_ai_once_schedule_names_from_overrides()
    remote_catalog_names = set(_filter_visible_schedule_names(remote_catalog_names, known_ai_once_names))
    remote_status_by_name = _filter_visible_schedule_status_map(remote_status_by_name, known_ai_once_names)

    # 2. 只拉目标方案的远端任务快照
    remote_by_name: Dict[str, List[dict]] = {}
    for name in target_set:
        if name in remote_catalog_names:
            try:
                fetched = _remote_fetch_schedule_tasks(name)
                remote_by_name[name] = [_normalize_remote_task(t) for t in fetched if isinstance(t, dict)]
            except HTTPException:
                remote_by_name[name] = []

    # 3. 惰性加载 media_map / terminal_map(仅在需要新增或更新任务时才拉取)
    _lazy_media_map: Dict[str, Optional[dict]] = {"v": None}
    _lazy_terminal_map: Dict[str, Optional[dict]] = {"v": None}

    def _get_media_map() -> dict:
        if _lazy_media_map["v"] is None:
            _lazy_media_map["v"] = _remote_media_map()
        return _lazy_media_map["v"]

    def _get_terminal_map() -> dict:
        if _lazy_terminal_map["v"] is None:
            _lazy_terminal_map["v"] = _remote_terminal_map()
        return _lazy_terminal_map["v"]

    # 4. 只遍历目标方案
    schedules = payload.get("schedules") or []
    for sched in schedules:
        if not isinstance(sched, dict):
            continue
        schedule_name = sched.get("schedule_name") or sched.get("name")
        if not schedule_name:
            continue
        schedule_name = str(schedule_name)
        if schedule_name not in target_set:
            continue
        created_schedule = False

        # 确保远端目录存在
        if schedule_name not in remote_catalog_names:
            _remote_ensure_schedule(schedule_name, catalog_names=remote_catalog_names)
            remote_catalog_names.add(schedule_name)
            created_schedule = True

        # 确保有远端任务快照
        if schedule_name not in remote_by_name:
            try:
                fetched = _remote_fetch_schedule_tasks(schedule_name)
                remote_by_name[schedule_name] = [
                    _normalize_remote_task(t) for t in fetched if isinstance(t, dict)
                ]
            except HTTPException:
                remote_by_name.setdefault(schedule_name, [])

        desired_status = sched.get("status") or "启用"
        desired_enabled = _status_enabled(desired_status)
        mutated_tasks = False

        # 同步具体任务
        remote_tasks = remote_by_name.get(schedule_name, [])
        desired_tasks = sched.get("tasks") or []
        task_sync_stats = _sync_schedule_task_set(
            schedule_name,
            desired_tasks,
            remote_tasks,
            _get_media_map(),
            _get_terminal_map(),
        )
        if task_sync_stats.get("mutated"):
            mutated_tasks = True

        remote_status = remote_status_by_name.get(schedule_name)
        if created_schedule or mutated_tasks or remote_status is None or _status_enabled(remote_status) != desired_enabled:
            _remote_set_schedule_status(schedule_name, desired_enabled)
            remote_status_by_name[schedule_name] = "启用" if desired_enabled else "停用"

    _debug_timing("sync remote schedules (targeted)", (time.perf_counter() - start) * 1000)


def _sync_remote_schedules_removed(
    schedule_names: List[str],
    *,
    remote_tasks_by_name: Optional[Dict[str, List[dict]]] = None,
) -> None:
    normalized_names = _unique_list([str(name).strip() for name in (schedule_names or []) if str(name).strip()])
    if not normalized_names:
        return
    LOGGER.info("schedule sync removed | removed=%s", normalized_names)
    for schedule_name in normalized_names:
        deleted_by_catalog = False
        try:
            _remote_delete_schedule_entry(schedule_name)
            try:
                deleted_by_catalog = schedule_name not in set(_remote_schedule_names())
            except HTTPException:
                deleted_by_catalog = False
        except HTTPException:
            deleted_by_catalog = False
        if deleted_by_catalog:
            continue
        known_tasks = []
        if isinstance(remote_tasks_by_name, dict):
            known_tasks = [
                task for task in (remote_tasks_by_name.get(schedule_name) or [])
                if isinstance(task, dict)
            ]
        if known_tasks:
            orphan_ids = [_task_real_id(task) for task in known_tasks if _task_real_id(task)]
            if orphan_ids:
                _batch_delete_parallel(orphan_ids, _remote_delete_task, label=f"delete_schedule_{schedule_name}")
            else:
                _delete_remote_schedule_tasks(schedule_name, [])
        else:
            _delete_remote_schedule_tasks(schedule_name, [])
        try:
            _remote_delete_schedule_entry(schedule_name)
        except HTTPException:
            pass


def _delete_remote_schedule_tasks(schedule_name: str, local_task_ids: List[str]) -> None:
    """Delete remote tasks for a schedule by querying the remote schedule tasks source of truth."""
    if not _remote_enabled():
        return
    del local_task_ids
    ids_to_delete = _remote_schedule_task_ids(schedule_name)
    if ids_to_delete:
        _batch_delete_parallel(ids_to_delete, _remote_delete_task, label=f"delete_schedule_{schedule_name}")


def _delete_remote_schedule_tasks_strict(schedule_name: str, tasks: List[dict]) -> List[str]:
    if not _remote_enabled():
        return []
    resolved_ids, unresolved = _resolve_remote_delete_task_ids(schedule_name, tasks)
    if unresolved:
        preview = "、".join(unresolved[:5])
        if len(unresolved) > 5:
            preview += f" 等{len(unresolved)}项"
        raise HTTPException(status_code=502, detail=f"无法确认远端任务ID:{preview}")
    deleted_ids: List[str] = []
    failures: List[str] = []
    for task_id in resolved_ids:
        try:
            _remote_delete_task(task_id)
            deleted_ids.append(task_id)
        except HTTPException as exc:
            failures.append(f"{task_id}:{_short_error_text(exc.detail)}")
        except Exception as exc:
            failures.append(f"{task_id}:{_short_error_text(exc)}")
    if failures:
        raise HTTPException(status_code=502, detail="远端任务删除未全部成功:" + "; ".join(failures[:5]))
    try:
        _remote_delete_schedule_entry(schedule_name)
    except HTTPException as exc:
        raise HTTPException(status_code=502, detail=f"远端方案目录删除失败:{exc.detail}") from exc
    return deleted_ids


def _cleanup_remote_created_schedule(schedule_name: str) -> str:
    if not schedule_name or not _remote_enabled():
        return ""
    errors: List[str] = []
    try:
        _delete_remote_schedule_tasks(schedule_name, [])
    except HTTPException as exc:
        errors.append(f"删除远端任务失败:{exc.detail}")
    except Exception as exc:
        errors.append(f"删除远端任务失败:{_short_error_text(exc)}")
    try:
        _remote_delete_schedule_entry(schedule_name)
    except HTTPException as exc:
        errors.append(f"删除远端方案失败:{exc.detail}")
    except Exception as exc:
        errors.append(f"删除远端方案失败:{_short_error_text(exc)}")
    return "；".join([item for item in errors if item])


def _raise_remote_created_schedule_failure(schedule_name: str, detail: str) -> None:
    cleanup_error = _cleanup_remote_created_schedule(schedule_name)
    if cleanup_error:
        raise HTTPException(status_code=502, detail=f"{detail}；且远端残留未清理:{cleanup_error}")
    raise HTTPException(status_code=502, detail=f"{detail}；已回滚远端新方案。")


def _repair_remote_schedule_catalog(payload: dict) -> dict:
    report = {
        "checked": 0,
        "missing_before": [],
        "created": [],
        "still_missing": [],
        "failed": [],
    }
    if not _remote_enabled():
        return report
    schedules = payload.get("schedules") if isinstance(payload, dict) else []
    if not isinstance(schedules, list):
        return report
    local_names = _unique_list(
        [
            str(item.get("schedule_name") or item.get("name") or "").strip()
            for item in schedules
            if isinstance(item, dict) and str(item.get("schedule_name") or item.get("name") or "").strip()
        ]
    )
    report["checked"] = len(local_names)
    try:
        remote_names_before = set(_remote_schedule_names())
    except HTTPException as exc:
        report["failed"].append({"stage": "list_before", "error": str(exc.detail)})
        return report
    missing = [name for name in local_names if name not in remote_names_before]
    report["missing_before"] = missing
    if not missing:
        return report
    for name in missing:
        try:
            _remote_ensure_schedule(name)
        except HTTPException as exc:
            report["failed"].append({"name": name, "error": str(exc.detail)})
    try:
        remote_names_after = set(_remote_schedule_names())
    except HTTPException as exc:
        report["failed"].append({"stage": "list_after", "error": str(exc.detail)})
        remote_names_after = remote_names_before
    report["created"] = [name for name in missing if name in remote_names_after]
    report["still_missing"] = [name for name in missing if name not in remote_names_after]
    return report


def _read_data_container(path: Path) -> tuple[dict, list]:
    payload = _read_json(path)
    if isinstance(payload, dict):
        items = payload.get("data")
        if isinstance(items, list):
            return payload, items
    if isinstance(payload, list):
        return {"data": payload}, payload
    raise HTTPException(status_code=500, detail=f"Invalid data format in {path.name}")


def _normalize_all_task_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid all_task payload")
    data = payload.get("data")
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Invalid all_task payload")
    payload["data"] = [item for item in data if isinstance(item, dict)]
    return payload


def _next_id(items: list, id_key: str) -> str:
    ids = []
    for item in items:
        if isinstance(item, dict) and item.get(id_key) is not None:
            try:
                ids.append(int(item[id_key]))
            except Exception:
                continue
    return str(max(ids or [0]) + 1)


def _find_item(items: list, id_key: str, item_id: str) -> tuple[int, dict]:
    for idx, item in enumerate(items):
        if isinstance(item, dict) and str(item.get(id_key)) == str(item_id):
            return idx, item
    raise HTTPException(status_code=404, detail=f"{id_key}={item_id} not found")


def _touch_generated_at(payload: dict) -> dict:
    payload["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return payload


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_schedules_payload() -> dict:
    if _store_get("broadcast_schedules") is None:
        _store_load_from_file(
            "broadcast_schedules",
            normalize=_normalize_schedules_payload,
            default=_default_schedules_payload,
            persist_default=True,
        )
    status_code = 503 if _remote_enabled() else 404
    payload = _store_require("broadcast_schedules", "broadcast_schedules", status_code)
    return _normalize_schedules_payload(payload)


def _load_schedules_summary_payload() -> dict:
    payload = _filter_hidden_ai_once_schedules_payload(_clone_payload(_load_schedules_payload()))
    return _build_schedules_summary_payload(payload)


def _load_overrides_payload() -> dict:
    payload = _store_get("task_overrides")
    if payload is None:
        payload = {"overrides": []}
        _store_set("task_overrides", payload)
    return _normalize_overrides_payload(payload)


def _save_overrides_payload(payload: dict) -> None:
    payload = _normalize_overrides_payload(payload)
    _write_json(OVERRIDES_PATH, payload)
    _store_set("task_overrides", payload)


def _remove_once_overrides_for_schedule(payload: dict, schedule_name: str) -> bool:
    schedule_name_text = str(schedule_name or "").strip()
    if not schedule_name_text or not isinstance(payload, dict):
        return False
    overrides = payload.get("overrides")
    if not isinstance(overrides, list):
        return False
    kept: List[Any] = []
    removed = 0
    for entry in overrides:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        if (
            str(entry.get("mode") or "").strip() == "once"
            and str(entry.get("schedule_name") or "").strip() == schedule_name_text
        ):
            removed += 1
            continue
        kept.append(entry)
    if not removed:
        return False
    payload["overrides"] = kept
    return True


def _removed_schedule_names(previous_payload: dict, next_payload: dict) -> List[str]:
    previous_names = _available_schedule_names(previous_payload)
    if not previous_names:
        return []
    next_name_set = {
        str(name or "").strip()
        for name in _available_schedule_names(next_payload)
        if str(name or "").strip()
    }
    return [
        name for name in previous_names
        if str(name or "").strip() and str(name or "").strip() not in next_name_set
    ]


def _remove_once_overrides_for_schedules(payload: dict, schedule_names: List[str]) -> bool:
    changed = False
    for schedule_name in _unique_list(
        [str(name or "").strip() for name in (schedule_names or []) if str(name or "").strip()]
    ):
        if _remove_once_overrides_for_schedule(payload, schedule_name):
            changed = True
    return changed


def _once_remote_schedule_name_from_spec(entry: Optional[dict], spec: Optional[dict]) -> str:
    if isinstance(spec, dict):
        for key in ("once_schedule_name",):
            value = str(spec.get(key) or "").strip()
            if value:
                return value
    if isinstance(entry, dict):
        value = str(entry.get("once_schedule_name") or "").strip()
        if value:
            return value
    if isinstance(entry, dict):
        return str(entry.get("schedule_name") or "").strip()
    return ""


def _has_explicit_once_remote_schedule_name(entry: Optional[dict], spec: Optional[dict]) -> bool:
    if isinstance(spec, dict) and str(spec.get("once_schedule_name") or "").strip():
        return True
    if isinstance(entry, dict) and str(entry.get("once_schedule_name") or "").strip():
        return True
    return False


def _legacy_once_remote_task_name(task_name: object, once_task_id: object) -> str:
    text = str(task_name or "").strip()
    if not text:
        return ""
    if _is_once_ephemeral_task_name(text):
        return text
    task_id = str(once_task_id or "").strip()
    if task_id:
        return f"{text}_once_legacy_{task_id}"
    return f"{text}_once_legacy"


def _collect_once_task_ids_for_override(entry: dict) -> List[str]:
    if not isinstance(entry, dict):
        return []
    collected: List[str] = []
    for spec in entry.get("once_task_specs") or []:
        if not isinstance(spec, dict):
            continue
        task_id = str(spec.get("taskid") or "").strip()
        if _is_numeric_id(task_id):
            collected.append(task_id)
    for key in ("once_task_ids", "source_once_task_ids", "target_once_task_ids"):
        for item in entry.get(key) or []:
            task_id = str(item or "").strip()
            if _is_numeric_id(task_id):
                collected.append(task_id)
    return _unique_list(collected)


def _collect_once_remote_schedule_names_for_override(entry: dict) -> List[str]:
    if not isinstance(entry, dict):
        return []
    collected: List[str] = []
    explicit_entry_name = str(entry.get("once_schedule_name") or "").strip()
    if explicit_entry_name:
        collected.append(explicit_entry_name)
    for spec in entry.get("once_task_specs") or []:
        if not isinstance(spec, dict):
            continue
        schedule_name = str(spec.get("once_schedule_name") or "").strip()
        if schedule_name:
            collected.append(schedule_name)
    return _unique_list(collected)


def _cleanup_empty_once_remote_schedules_for_override(entry: dict) -> None:
    for schedule_name in _collect_once_remote_schedule_names_for_override(entry):
        _cleanup_empty_once_remote_schedule(schedule_name)


def _cleanup_empty_once_remote_schedule(schedule_name: object) -> None:
    schedule_name_text = str(schedule_name or "").strip()
    if not schedule_name_text or not _remote_enabled() or not _is_ai_once_schedule_name(schedule_name_text):
        return
    try:
        remaining = [
            _normalize_remote_task(item)
            for item in _remote_fetch_schedule_tasks(schedule_name_text)
            if isinstance(item, dict)
        ]
    except HTTPException:
        return
    if remaining:
        return
    try:
        _remote_delete_schedule_entry(schedule_name_text)
    except HTTPException:
        return


def _cleanup_once_overrides_for_schedules(payload: dict, schedule_names: List[str]) -> bool:
    normalized_names = _unique_list(
        [str(name or "").strip() for name in (schedule_names or []) if str(name or "").strip()]
    )
    if not normalized_names or not isinstance(payload, dict):
        return False
    overrides = payload.get("overrides")
    if not isinstance(overrides, list):
        return False
    matching_entries = [
        entry for entry in overrides
        if isinstance(entry, dict)
        and str(entry.get("mode") or "").strip() == "once"
        and str(entry.get("schedule_name") or "").strip() in normalized_names
    ]
    if not matching_entries:
        return False
    if _remote_enabled():
        task_ids_to_delete: List[str] = []
        ai_schedule_names: List[str] = []
        for entry in matching_entries:
            task_ids_to_delete.extend(_collect_once_task_ids_for_override(entry))
            ai_schedule_names.extend(_collect_once_remote_schedule_names_for_override(entry))
        for task_id in _unique_list(task_ids_to_delete):
            _remote_delete_task(task_id)
        for schedule_name in _unique_list(ai_schedule_names):
            _cleanup_empty_once_remote_schedule(schedule_name)
    return _remove_once_overrides_for_schedules(payload, normalized_names)


def _commit_schedule_delete_with_once_cleanup(
    schedule_payload: dict,
    overrides_payload: dict,
    *,
    save_schedule_payload: Callable[[dict], None],
    overrides_changed: bool,
) -> tuple[Optional[str], Optional[str]]:
    try:
        save_schedule_payload(_touch_generated_at(schedule_payload))
    except HTTPException as exc:
        return "schedule", str(exc.detail)
    except Exception as exc:
        return "schedule", _short_error_text(exc)
    if not overrides_changed:
        return None, None
    try:
        _save_overrides_payload(_touch_generated_at(overrides_payload))
    except HTTPException as exc:
        return "override", str(exc.detail)
    except Exception as exc:
        return "override", _short_error_text(exc)
    return None, None


def _find_editable_once_override(payload: dict, override_id: str, once_task_id: str) -> tuple[int, dict, int, dict]:
    override_id_text = str(override_id or "").strip()
    once_task_id_text = str(once_task_id or "").strip()
    if not override_id_text or not once_task_id_text:
        raise HTTPException(status_code=400, detail="override_id and once_task_id are required.")
    overrides = payload.get("overrides") or []
    for override_index, entry in enumerate(overrides):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id") or "").strip() != override_id_text:
            continue
        if str(entry.get("mode") or "") != "once":
            raise HTTPException(status_code=400, detail="Override is not a once override.")
        if str(entry.get("execution_state") or "") != "scheduled":
            raise HTTPException(status_code=400, detail="Only scheduled once overrides can be edited.")
        if not bool(entry.get("active")):
            raise HTTPException(status_code=400, detail="Inactive once override cannot be edited.")
        if str(entry.get("cleanup_state") or "") == "cleaned":
            raise HTTPException(status_code=400, detail="Cleaned once override cannot be edited.")
        specs = entry.get("once_task_specs") or []
        for spec_index, spec in enumerate(specs):
            if not isinstance(spec, dict):
                continue
            if str(spec.get("taskid") or "").strip() == once_task_id_text:
                return override_index, entry, spec_index, spec
        raise HTTPException(status_code=404, detail="Once task not found in override.")
    raise HTTPException(status_code=404, detail="Once override not found.")


def _once_spec_timing_task(spec: dict) -> dict:
    return {
        "startdate": str(spec.get("startdate") or spec.get("once_date") or "").strip(),
        "enddate": str(spec.get("startdate") or spec.get("once_date") or "").strip(),
        "starttime": str(spec.get("starttime") or "").strip(),
        "timelength": str(spec.get("timelength") or "").strip(),
        "timelengthtype": str(spec.get("timelengthtype") or "").strip(),
    }


def _once_specs_window(specs: List[dict]) -> tuple[Optional[datetime], Optional[datetime]]:
    start_values: List[datetime] = []
    end_values: List[datetime] = []
    fallback = datetime.now()
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        timing_task = _once_spec_timing_task(spec)
        start_dt = _task_start_datetime(timing_task, fallback)
        end_dt = _task_end_datetime(timing_task, fallback)
        start_values.append(start_dt)
        end_values.append(end_dt)
    if not start_values or not end_values:
        return None, None
    return min(start_values), max(end_values)


def _once_override_non_enabletask_commands(entry: dict) -> List[dict]:
    commands = entry.get("commands") or []
    kept: List[dict] = []
    for item in commands:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") == "enabletask":
            continue
        kept.append(_clone_payload(item))
    return kept


def _refresh_once_override_schedule_commands(entry: dict, *, reschedule_remote: bool = False) -> None:
    if not isinstance(entry, dict):
        return
    action = str(entry.get("action") or "").strip()
    once_specs = [item for item in (entry.get("once_task_specs") or []) if isinstance(item, dict)]
    once_task_ids = _unique_list(
        [str(item.get("taskid") or "").strip() for item in once_specs if _is_numeric_id(str(item.get("taskid") or "").strip())]
    )
    entry["once_task_ids"] = list(once_task_ids)
    entry["shadow_task_ids"] = list(once_task_ids)
    commands = _once_override_non_enabletask_commands(entry)
    diagnostics: Optional[List[dict]] = [] if reschedule_remote else None
    if action == "migrate":
        old_start = _parse_action_datetime(entry.get("time_start"))
        old_end = _parse_action_datetime(entry.get("time_end"))
        new_start, new_end = _once_specs_window(once_specs)
        if not old_start or not old_end or not new_start or not new_end or not once_task_ids:
            entry["enable_once_commands"] = []
            entry["commands"] = commands
            return
        _dispatch_enabletask_phase(
            commands,
            "enable_once",
            once_task_ids,
            0,
            new_start - timedelta(seconds=10),
            dry_run=not reschedule_remote,
            diagnostics=diagnostics,
            action_name="migrate",
        )
        _dispatch_enabletask_phase(
            commands,
            "disable_source",
            _unique_list([str(item).strip() for item in (entry.get("task_ids") or []) if str(item).strip()]),
            1,
            old_start - timedelta(seconds=5),
            dry_run=not reschedule_remote,
            diagnostics=diagnostics,
            action_name="migrate",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore_source",
            _unique_list([str(item).strip() for item in (entry.get("task_ids") or []) if str(item).strip()]),
            0,
            old_end,
            dry_run=not reschedule_remote,
            diagnostics=diagnostics,
            action_name="migrate",
        )
        conflict_ids = _unique_list([str(item).strip() for item in (entry.get("conflict_task_ids") or []) if str(item).strip()])
        if conflict_ids:
            _dispatch_enabletask_phase(
                commands,
                "disable_conflict",
                conflict_ids,
                1,
                new_start - timedelta(seconds=5),
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="migrate",
            )
            _dispatch_enabletask_phase(
                commands,
                "restore_conflict",
                conflict_ids,
                0,
                new_end,
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="migrate",
            )
        entry["new_time_start"] = new_start.strftime("%Y-%m-%d %H:%M:%S")
        entry["new_time_end"] = new_end.strftime("%Y-%m-%d %H:%M:%S")
        entry["enable_once_commands"] = _collect_enabletask_phase_payloads(commands, "enable_once")
        entry["commands"] = commands
        return
    if action == "swap":
        source_specs = [item for item in once_specs if str(item.get("role") or "").strip() == "source_to_target"]
        target_specs = [item for item in once_specs if str(item.get("role") or "").strip() == "target_to_source"]
        source_once_ids = _unique_list(
            [str(item.get("taskid") or "").strip() for item in source_specs if _is_numeric_id(str(item.get("taskid") or "").strip())]
        )
        target_once_ids = _unique_list(
            [str(item.get("taskid") or "").strip() for item in target_specs if _is_numeric_id(str(item.get("taskid") or "").strip())]
        )
        entry["source_once_task_ids"] = list(source_once_ids)
        entry["target_once_task_ids"] = list(target_once_ids)
        a_start = _parse_action_datetime(entry.get("source_time_start"))
        a_end = _parse_action_datetime(entry.get("source_time_end"))
        b_start = _parse_action_datetime(entry.get("target_time_start"))
        b_end = _parse_action_datetime(entry.get("target_time_end"))
        source_target_start, _ = _once_specs_window(source_specs)
        target_source_start, _ = _once_specs_window(target_specs)
        if source_once_ids and source_target_start:
            _dispatch_enabletask_phase(
                commands,
                "enable_once_source_to_target",
                source_once_ids,
                0,
                source_target_start - timedelta(seconds=10),
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="swap",
            )
        if target_once_ids and target_source_start:
            _dispatch_enabletask_phase(
                commands,
                "enable_once_target_to_source",
                target_once_ids,
                0,
                target_source_start - timedelta(seconds=10),
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="swap",
            )
        if a_start and a_end:
            source_ids = _unique_list([str(item).strip() for item in (entry.get("source_task_ids") or []) if str(item).strip()])
            _dispatch_enabletask_phase(
                commands,
                "disable_source",
                source_ids,
                1,
                a_start - timedelta(seconds=5),
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="swap",
            )
            _dispatch_enabletask_phase(
                commands,
                "restore_source",
                source_ids,
                0,
                a_end,
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="swap",
            )
        if b_start and b_end:
            target_ids = _unique_list([str(item).strip() for item in (entry.get("target_task_ids") or []) if str(item).strip()])
            _dispatch_enabletask_phase(
                commands,
                "disable_target",
                target_ids,
                1,
                b_start - timedelta(seconds=5),
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="swap",
            )
            _dispatch_enabletask_phase(
                commands,
                "restore_target",
                target_ids,
                0,
                b_end,
                dry_run=not reschedule_remote,
                diagnostics=diagnostics,
                action_name="swap",
            )
        entry["enable_once_commands"] = [
            *_collect_enabletask_phase_payloads(commands, "enable_once_source_to_target"),
            *_collect_enabletask_phase_payloads(commands, "enable_once_target_to_source"),
        ]
        entry["commands"] = commands
        return
    entry["enable_once_commands"] = []
    entry["commands"] = commands


def _build_once_override_task_payload(
    *,
    entry: dict,
    spec: dict,
    remote_snapshot: dict,
    patch: dict,
    media_map: dict,
    terminal_lookup: dict,
) -> tuple[dict, dict]:
    schedule_name = str(entry.get("schedule_name") or spec.get("schedule_name") or "").strip()
    once_schedule_name = _once_remote_schedule_name_from_spec(entry, spec)
    if not schedule_name:
        raise HTTPException(status_code=400, detail="Once override is missing schedule_name.")
    if not once_schedule_name:
        raise HTTPException(status_code=400, detail="Once override is missing once_schedule_name.")
    task = _clone_payload(remote_snapshot) if isinstance(remote_snapshot, dict) else {}
    task["taskid"] = str(spec.get("taskid") or patch.get("taskid") or "").strip()
    explicit_once_schedule_name = _has_explicit_once_remote_schedule_name(entry, spec)
    task_name = str(patch.get("taskname") or patch.get("customName") or spec.get("taskname") or "").strip()
    if not task_name:
        raise HTTPException(status_code=400, detail="taskname is required.")
    startdate = _normalize_date_for_compare(patch.get("startdate") or spec.get("startdate") or spec.get("once_date"))
    if not startdate:
        raise HTTPException(status_code=400, detail="startdate is required.")
    starttime = _format_hhmmss(str(patch.get("starttime") or spec.get("starttime") or ""))
    if not starttime:
        raise HTTPException(status_code=400, detail="starttime is required.")
    timelength = str(patch.get("timelength") if patch.get("timelength") not in (None, "") else spec.get("timelength") or "").strip()
    timelengthtype = str(
        patch.get("timelengthtype") if patch.get("timelengthtype") not in (None, "") else spec.get("timelengthtype") or ""
    ).strip() or "1"
    if not timelength:
        raise HTTPException(status_code=400, detail="timelength is required.")
    if timelengthtype not in {"1", "2"}:
        raise HTTPException(status_code=400, detail="timelengthtype must be 1 or 2.")
    volume_raw = patch.get("volume") if patch.get("volume") not in (None, "") else spec.get("volume")
    volume_value = _coerce_int(volume_raw, 0)
    media_name = str(patch.get("medianame") or patch.get("media_name") or spec.get("medianame") or "").strip()
    media_id = patch.get("mediaid")
    if media_id in (None, ""):
        media_id = spec.get("mediaid")
    if media_id in (None, "") and media_name:
        media_id = _resolve_media_id_with_fallback({"audio": media_name, "medianame": media_name}, media_map, remote_snapshot)
    if media_id in (None, ""):
        raise HTTPException(status_code=400, detail="mediaid or resolvable medianame is required.")
    media_id_text = str(media_id).strip()
    if not _is_numeric_id(media_id_text):
        raise HTTPException(status_code=400, detail="Invalid mediaid for once task update.")
    location = _clone_payload(patch.get("location")) if isinstance(patch.get("location"), list) else []
    terminal_ids = _normalize_terminal_ids(patch.get("terminalids"))
    terminal_names = _normalize_str_list(patch.get("terminalnames"))
    liveterminalid = str(patch.get("liveterminalid") or "").strip()
    liveterminalname = str(patch.get("liveterminalname") or "").strip()
    if not terminal_ids and not liveterminalid:
        terminal_snapshot = _schedule_task_terminal_binding_snapshot(spec) or _schedule_task_terminal_binding_snapshot(remote_snapshot) or {}
        terminal_ids = _normalize_terminal_ids(terminal_snapshot.get("terminalids"))
        terminal_names = _normalize_str_list(terminal_snapshot.get("terminalnames"))
        liveterminalid = str(terminal_snapshot.get("liveterminalid") or "").strip()
        liveterminalname = str(terminal_snapshot.get("liveterminalname") or "").strip()
        if not location and isinstance(terminal_snapshot.get("location"), list):
            location = _clone_payload(terminal_snapshot.get("location"))
    if not liveterminalid and terminal_ids:
        liveterminalid = terminal_ids[0]
    if liveterminalid and not terminal_ids:
        terminal_ids = [liveterminalid]
    if not liveterminalname and terminal_names:
        liveterminalname = terminal_names[0]
    if not terminal_names and terminal_ids and isinstance(terminal_lookup, dict):
        resolved_names: List[str] = []
        for terminal_id in terminal_ids:
            lookup = terminal_lookup.get(str(terminal_id))
            if isinstance(lookup, dict) and lookup.get("name"):
                resolved_names.append(str(lookup.get("name")))
        terminal_names = _unique_list([name for name in resolved_names if name])
        if terminal_names and not liveterminalname:
            liveterminalname = terminal_names[0]
    if not terminal_ids and isinstance(location, list):
        resolved_ids: List[str] = []
        terminal_map = {
            str(item.get("name") or "").strip(): str(item.get("id") or item.get("terminalid") or item.get("terminal_id") or "").strip()
            for item in terminal_lookup.values()
            if isinstance(item, dict)
        } if isinstance(terminal_lookup, dict) else {}
        resolved_ids = _get_task_terminal_ids({"location": location}, terminal_map=terminal_map)
        terminal_ids = _normalize_terminal_ids(resolved_ids)
        if terminal_ids and not liveterminalid:
            liveterminalid = terminal_ids[0]
    if not terminal_ids and not liveterminalid:
        raise HTTPException(status_code=400, detail="Once task update requires terminal binding.")
    remote_task_name = task_name
    if not explicit_once_schedule_name:
        remote_task_name = _legacy_once_remote_task_name(task_name, task.get("taskid"))
    task.update(
        {
            "taskname": remote_task_name,
            "name": remote_task_name,
            "customName": remote_task_name,
            "audio": media_name or _lookup_name_by_id(_remote_media_lookup(), media_id_text),
            "medianame": media_name or _lookup_name_by_id(_remote_media_lookup(), media_id_text),
            "mediaid": media_id_text,
            "startdate": startdate,
            "enddate": startdate,
            "starttime": starttime,
            "timelength": timelength,
            "timelengthtype": timelengthtype,
            "volume": volume_value,
            "terminalids": terminal_ids,
            "terminalnames": terminal_names,
            "liveterminalid": liveterminalid,
            "liveterminalname": liveterminalname,
            "location": location,
            "execmode": 127,
            "tasktype": 1,
        }
    )
    _attach_shadow_schedule_name(task, once_schedule_name)
    updated_spec = _clone_payload(spec)
    updated_spec.update(
        {
            "taskid": str(task.get("taskid") or "").strip(),
            "taskname": task_name,
            "remote_taskname": remote_task_name,
            "schedule_name": schedule_name,
            "startdate": startdate,
            "starttime": starttime,
            "once_date": startdate,
            "duration_seconds": _task_duration_seconds(task),
            "mediaid": media_id_text,
            "medianame": str(task.get("medianame") or "").strip(),
            "volume": volume_value,
            "timelength": timelength,
            "timelengthtype": timelengthtype,
            "terminalids": terminal_ids,
            "terminalnames": terminal_names,
            "liveterminalid": liveterminalid,
            "liveterminalname": liveterminalname,
            "location": _clone_payload(location) if isinstance(location, list) else [],
        }
    )
    if explicit_once_schedule_name:
        updated_spec["once_schedule_name"] = once_schedule_name
    else:
        updated_spec.pop("once_schedule_name", None)
    return task, updated_spec


def _is_once_ephemeral_task_name(task_name: object) -> bool:
    text = str(task_name or "").strip().lower()
    return "_once_" in text if text else False


def _filter_once_ephemeral_schedule_tasks(tasks: object) -> List[dict]:
    filtered: List[dict] = []
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        if _is_once_ephemeral_task_name(task.get("taskname") or task.get("name") or task.get("customName")):
            continue
        filtered.append(task)
    return filtered


def _filter_once_ephemeral_in_schedules_payload(payload: object) -> dict:
    cloned = _clone_payload(payload) if isinstance(payload, dict) else {}
    schedules = cloned.get("schedules")
    if not isinstance(schedules, list):
        return cloned
    for schedule in schedules:
        if not isinstance(schedule, dict):
            continue
        schedule["tasks"] = _filter_once_ephemeral_schedule_tasks(schedule.get("tasks"))
    return cloned


def _filter_hidden_ai_once_schedules_payload(
    payload: object,
    known_ai_names: Optional[Collection[object]] = None,
) -> dict:
    cloned = _clone_payload(payload) if isinstance(payload, dict) else {}
    schedules = cloned.get("schedules")
    if not isinstance(schedules, list):
        return cloned
    hidden_names = _hidden_ai_once_schedule_names(known_ai_names)
    cloned["schedules"] = [
        schedule
        for schedule in schedules
        if isinstance(schedule, dict)
        and str(schedule.get("schedule_name") or schedule.get("name") or "").strip() not in hidden_names
    ]
    return cloned


def _once_override_target_dates(entry: dict) -> List[str]:
    dates: List[str] = []
    if not isinstance(entry, dict):
        return dates
    specs = entry.get("once_task_specs")
    if isinstance(specs, list):
        for item in specs:
            if not isinstance(item, dict):
                continue
            date_text = _normalize_date_for_compare(item.get("startdate"))
            if date_text:
                dates.append(date_text)
    if not dates:
        for key in ("new_time_start", "target_time_start", "time_start"):
            value = entry.get(key)
            if value in (None, ""):
                continue
            parsed = _parse_action_datetime(value)
            if parsed:
                dates.append(parsed.strftime("%Y-%m-%d"))
                break
    return _unique_list(dates)


def _cleanup_expired_once_overrides() -> dict:
    if not ONCE_CLEANUP_LOCK.acquire(blocking=False):
        return {"cleaned": 0, "partial_failed": 0}
    try:
        payload = _load_overrides_payload()
        overrides = payload.get("overrides") or []
        today_str = date.today().strftime("%Y-%m-%d")
        cleaned_count = 0
        partial_failed = 0
        mutated = False
        for entry in overrides:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("mode") or "") != "once":
                continue
            if str(entry.get("execution_state") or "") != "scheduled":
                continue
            if not bool(entry.get("active")):
                continue
            if entry.get("remote_synced") is False:
                continue
            target_dates = _once_override_target_dates(entry)
            if not target_dates:
                continue
            if not all(date_text < today_str for date_text in target_dates):
                continue
            once_task_ids = _unique_list([str(item).strip() for item in (entry.get("once_task_ids") or []) if _is_numeric_id(str(item).strip())])
            if not once_task_ids:
                entry["execution_state"] = "cleaned"
                entry["active"] = False
                entry["cleanup_state"] = "cleaned"
                entry["cleaned_at"] = _now_str()
                _cleanup_empty_once_remote_schedules_for_override(entry)
                mutated = True
                cleaned_count += 1
                continue
            deleted_ids: List[str] = []
            failed_attempts: List[dict] = []
            for task_id in once_task_ids:
                try:
                    _remote_delete_task(task_id)
                    deleted_ids.append(task_id)
                except Exception as exc:
                    failed_attempts.append(
                        {
                            "taskid": task_id,
                            "attempted_at": _now_str(),
                            "error": _short_error_text(getattr(exc, "detail", exc)),
                        }
                    )
            if deleted_ids:
                entry["cleaned_task_ids"] = _unique_list([*(entry.get("cleaned_task_ids") or []), *deleted_ids])
                remaining_ids = [task_id for task_id in once_task_ids if task_id not in deleted_ids]
                entry["once_task_ids"] = remaining_ids
                entry["shadow_task_ids"] = list(remaining_ids)
                mutated = True
            if failed_attempts:
                entry["cleanup_state"] = "partial_failed"
                entry["cleanup_attempts"] = [*(entry.get("cleanup_attempts") or []), *failed_attempts]
                partial_failed += 1
                mutated = True
            else:
                entry["execution_state"] = "cleaned"
                entry["active"] = False
                entry["cleanup_state"] = "cleaned"
                entry["cleaned_at"] = _now_str()
                _cleanup_empty_once_remote_schedules_for_override(entry)
                cleaned_count += 1
                mutated = True
        if mutated:
            _save_overrides_payload(_touch_generated_at(payload))
        return {"cleaned": cleaned_count, "partial_failed": partial_failed}
    finally:
        ONCE_CLEANUP_LOCK.release()


def _ensure_once_overrides_cleaned() -> None:
    try:
        _cleanup_expired_once_overrides()
    except Exception as exc:
        LOGGER.warning("once override cleanup failed: %s", exc)


def _load_assistant_command_logs_payload() -> dict:
    payload = _store_get("assistant_command_logs")
    if payload is None:
        payload = {"items": []}
        _store_set("assistant_command_logs", payload)
    return _normalize_assistant_command_logs_payload(payload)


def _save_assistant_command_logs_payload(payload: dict) -> None:
    payload = _normalize_assistant_command_logs_payload(payload)
    _write_json(ASSISTANT_COMMAND_LOGS_PATH, payload)
    _store_set("assistant_command_logs", payload)


def _load_assistant_settings_payload() -> dict:
    payload = _store_get("assistant_settings")
    if payload is None:
        _store_load_from_file(
            "assistant_settings",
            normalize=_normalize_assistant_settings_payload,
            default=_default_assistant_settings_payload,
            persist_default=True,
        )
        payload = _store_get("assistant_settings")
    if payload is None:
        payload = _default_assistant_settings_payload()
        _store_set("assistant_settings", payload)
    return _normalize_assistant_settings_payload(payload)


def _save_assistant_settings_payload(payload: dict) -> dict:
    payload = _normalize_assistant_settings_payload(payload)
    _write_json(ASSISTANT_SETTINGS_PATH, payload)
    _store_set("assistant_settings", payload)
    return payload


def _assistant_settings_response_payload(payload: Optional[dict] = None) -> dict:
    normalized = _normalize_assistant_settings_payload(payload or _load_assistant_settings_payload())
    return {
        "default_schedule_kind": normalized.get("default_schedule_kind") or "",
        "default_schedule_season": normalized.get("default_schedule_season") or "",
        "allowed_schedule_kinds": list(ALLOWED_SCHEDULE_KINDS),
        "allowed_schedule_seasons": list(ALLOWED_SCHEDULE_SEASONS),
    }


def _load_default_schedule_kind() -> str:
    payload = _load_assistant_settings_payload()
    return str(payload.get("default_schedule_kind") or "").strip()


def _load_default_schedule_season() -> str:
    payload = _load_assistant_settings_payload()
    return str(payload.get("default_schedule_season") or "").strip()


def _load_remote_settings_payload() -> dict:
    payload = _store_get("remote_settings")
    if payload is None:
        payload = {"remote_base_url": "", "last_verified_at": "", "last_verified_ip": ""}
        _store_set("remote_settings", payload)
    return _normalize_remote_settings_payload(payload)


def _clear_remote_runtime_state() -> None:
    global REMOTE_TOKEN
    REMOTE_TOKEN = None
    REMOTE_CACHE.clear()
    TTL_CACHE.clear()
    _reset_remote_sync_status()


def _save_remote_settings_payload(payload: dict) -> dict:
    current = _load_remote_settings_payload()
    payload = _normalize_remote_settings_payload(payload)
    _write_json(REMOTE_SETTINGS_PATH, payload)
    _store_set("remote_settings", payload)
    if payload.get("remote_base_url") != current.get("remote_base_url"):
        _clear_remote_runtime_state()
    return payload


def _resolved_saved_remote_base_url() -> str:
    payload = _load_remote_settings_payload()
    return _normalize_remote_base_url(payload.get("remote_base_url"))


def _current_request_remote_base_url() -> Optional[str]:
    value = CURRENT_REMOTE_BASE_URL.get()
    if not value:
        return None
    return _normalize_remote_base_url(value)


def _resolve_remote_base_url(explicit: object = None) -> str:
    resolved, _ = _resolve_remote_base_url_details(explicit)
    return resolved


def _resolve_remote_base_url_details(explicit: object = None) -> Tuple[str, str]:
    explicit_text = str(explicit or "").strip()
    if explicit_text:
        return _normalize_remote_base_url(explicit_text), "explicit"
    current = _current_request_remote_base_url()
    if current:
        return current, "session"
    saved = _resolved_saved_remote_base_url()
    if saved:
        return saved, "saved"
    environment = _normalize_remote_base_url(REMOTE_BASE_URL)
    if environment:
        return environment, "environment"
    return "", "none"


def _remote_settings_response_payload(payload: Optional[dict] = None) -> dict:
    normalized = _normalize_remote_settings_payload(payload or _load_remote_settings_payload())
    return {
        "remote_base_url": normalized.get("remote_base_url") or "",
        "last_verified_at": normalized.get("last_verified_at") or "",
        "last_verified_ip": normalized.get("last_verified_ip") or "",
        "excluded_candidate_ips": _clone_payload(normalized.get("excluded_candidate_ips") or []),
        "effective_remote_base_url": _resolve_remote_base_url(),
        "environment_remote_base_url": _normalize_remote_base_url(REMOTE_BASE_URL),
    }


def _remote_bootstrap_candidates() -> List[dict]:
    if psutil is None:
        return []
    candidates: List[dict] = []
    seen: set[str] = set()
    excluded_ips = set(_load_remote_settings_payload().get("excluded_candidate_ips") or [])
    try:
        interfaces = psutil.net_if_addrs()
    except Exception:
        return []
    for interface, addresses in interfaces.items():
        for item in addresses:
            family = getattr(item, "family", None)
            address = str(getattr(item, "address", "") or "").strip()
            if family != socket.AF_INET or not address or address.startswith("127."):
                continue
            if address in excluded_ips:
                continue
            if address in seen:
                continue
            seen.add(address)
            candidates.append({"interface": str(interface or ""), "ip": address})
    return candidates


def _default_remote_base_url_for_ip(ip: str) -> str:
    ip_text = str(ip or "").strip()
    if not ip_text:
        return ""
    return f"http://{ip_text}:{DEFAULT_REMOTE_API_PORT}{DEFAULT_REMOTE_API_PATH}".rstrip("/")


def _remote_bootstrap_response_payload() -> dict:
    saved_remote_base_url = _resolved_saved_remote_base_url()
    candidates = _remote_bootstrap_candidates()
    suggested_remote_base_urls = _unique_list(
        [
            _default_remote_base_url_for_ip(item.get("ip"))
            for item in candidates
            if isinstance(item, dict) and item.get("ip")
        ]
    )
    return {
        "saved_remote_base_url": saved_remote_base_url,
        "effective_remote_base_url": _resolve_remote_base_url(),
        "candidates": candidates,
        "suggested_remote_base_urls": suggested_remote_base_urls,
        "excluded_candidate_ips": _clone_payload(_load_remote_settings_payload().get("excluded_candidate_ips") or []),
    }


def _load_remote_settings_payload() -> dict:
    return _remote_runtime.load_remote_settings_payload()


def _save_remote_settings_payload(payload: dict) -> dict:
    current = _load_remote_settings_payload()
    normalized = _remote_runtime.save_remote_settings_payload(payload)
    if normalized.get("remote_base_url") != current.get("remote_base_url"):
        _clear_remote_runtime_state()
    return normalized


def _resolved_saved_remote_base_url() -> str:
    return _remote_runtime.resolved_saved_remote_base_url()


def _current_request_remote_base_url() -> Optional[str]:
    return _remote_runtime.current_request_remote_base_url()


def _resolve_remote_base_url(explicit: object = None) -> str:
    return _remote_runtime.resolve_remote_base_url(explicit)


def _resolve_remote_base_url_details(explicit: object = None) -> Tuple[str, str]:
    return _remote_runtime.resolve_remote_base_url_details(explicit)


def _remote_settings_response_payload(payload: Optional[dict] = None) -> dict:
    return _remote_runtime.remote_settings_response_payload(payload)


def _load_calendar_holidays_payload() -> dict:
    payload = _store_get("calendar_holidays_cn")
    if payload is None:
        payload = _read_json_optional(CALENDAR_HOLIDAYS_CN_PATH) or {"years": {}}
        _store_set("calendar_holidays_cn", payload)
    return _normalize_calendar_holidays_payload(payload)


def _load_calendar_holidays_year_payload(year: object) -> dict:
    year_text = str(year or "").strip()
    if not re.fullmatch(r"\d{4}", year_text):
        raise HTTPException(status_code=400, detail="Invalid year")

    payload = _load_calendar_holidays_payload()
    years = payload.get("years") if isinstance(payload, dict) else {}
    year_entry = years.get(year_text) if isinstance(years, dict) else None
    days = year_entry.get("days") if isinstance(year_entry, dict) else {}
    if not isinstance(days, dict):
        days = {}

    return {
        "year": int(year_text),
        "days": _clone_payload(days),
    }


def _append_assistant_command_log(
    *,
    text: str,
    reply: str,
    action_log: List[dict],
) -> Optional[dict]:
    if not isinstance(action_log, list) or not action_log:
        return None
    payload = _load_assistant_command_logs_payload()
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    entry = {
        "text": str(text or ""),
        "reply": str(reply or ""),
    }
    items.append(entry)
    payload["items"] = items[-ASSISTANT_COMMAND_LOG_LIMIT:]
    _save_assistant_command_logs_payload(payload)
    return entry


def _find_schedule(payload: dict, name: str) -> Optional[dict]:
    schedules = payload.get("schedules") or []
    for item in schedules:
        if not isinstance(item, dict):
            continue
        sched_name = item.get("schedule_name") or item.get("name")
        if sched_name and str(sched_name) == str(name):
            return item
    return None

def _schedule_display_name(schedule: dict) -> str:
    if not isinstance(schedule, dict):
        return ""
    return str(schedule.get("schedule_name") or schedule.get("name") or "").strip()

def _available_schedule_names(payload: dict) -> List[str]:
    schedules = payload.get("schedules") if isinstance(payload, dict) else []
    if not isinstance(schedules, list):
        return []
    names: List[str] = []
    for item in schedules:
        if not isinstance(item, dict):
            continue
        name = _schedule_display_name(item)
        if name:
            names.append(name)
    return _unique_list(names)


def _enabled_schedules(payload: dict) -> List[dict]:
    schedules = payload.get("schedules") if isinstance(payload, dict) else []
    if not isinstance(schedules, list):
        return []
    enabled: List[dict] = []
    for item in schedules:
        if not isinstance(item, dict):
            continue
        if _status_enabled(item.get("status") or "启用"):
            enabled.append(item)
    return enabled


def _resolve_unique_enabled_schedule(
    payload: dict,
) -> Tuple[Optional[dict], str, Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    enabled = _enabled_schedules(payload)
    if len(enabled) == 1:
        schedule = enabled[0]
        return schedule, _schedule_display_name(schedule), None

    if not enabled:
        return (
            None,
            "",
            (
                "未指定作息方案，且当前没有启用中的作息方案，请补充方案名称。",
                {"missing_slots": ["schedule_name"]},
                [],
            ),
        )

    names = [_schedule_display_name(item) for item in enabled]
    names = [name for name in _unique_list(names) if name]
    preview = "、".join(names[:8])
    suffix = "等" if len(names) > 8 else ""
    return (
        None,
        "",
        (
            f"当前有多个启用中的作息方案，请补充方案名称：{preview}{suffix}。",
            {"missing_slots": ["schedule_name"]},
            [],
        ),
    )


def _resolve_schedule_for_phase1(payload: dict, schedule_name: str) -> Tuple[Optional[dict], str, Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    raw_name = str(schedule_name or "").strip()
    if raw_name:
        schedule = _find_schedule_loose(payload, raw_name)
        if not schedule:
            return None, "", (f"未找到作息方案：{raw_name}。", {"missing_slots": []}, [])
        resolved_name = _schedule_display_name(schedule) or raw_name
        return schedule, resolved_name, None
    return _resolve_unique_enabled_schedule(payload)

def _next_schedule_task_id(payload: dict) -> str:
    max_id = 0
    for schedule in payload.get("schedules", []):
        if not isinstance(schedule, dict):
            continue
        for task in schedule.get("tasks", []) or []:
            if not isinstance(task, dict):
                continue
            task_id = task.get("taskid")
            try:
                max_id = max(max_id, int(task_id))
            except Exception:
                continue
    return str(max_id + 1)


def _parse_datetime(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("T", " "))
    except Exception:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def _parse_time_minutes(value: str) -> Optional[int]:
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


def _parse_time_seconds(value: str) -> Optional[int]:
    if not value:
        return None
    text = str(value)
    parts = text.split(":")
    if not parts:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
    except Exception:
        return None
    return hour * 3600 + minute * 60 + second


def _weekday_label(dt: datetime) -> str:
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return labels[dt.weekday()] if dt else ""


def _weekday_from_token(token: str) -> Optional[str]:
    if not token:
        return None
    day = "日" if token == "天" else token
    return f"周{day}"


def _extract_weekday_occurrences(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    pattern = r"(周|星期|礼拜)([一二三四五六日天])"
    occurrences: List[Dict[str, Any]] = []
    for match in re.finditer(pattern, text):
        label = _weekday_from_token(match.group(2))
        if label:
            occurrences.append({"label": label, "index": match.start()})
    return occurrences

def _date_for_weekday(text: str, weekday_label: str) -> Optional[datetime]:
    """
    根据文本中的星期描述,计算对应的日期
    
    核心原则:
    - "周X" = 本周的该天(不管过去还是未来)
    - "下周X" = 下一个完整周的该天
    - "下下周X" = 下下个完整周的该天
    """
    if not weekday_label:
        return None
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    if weekday_label not in labels:
        return None
    
    now = datetime.now()
    today_weekday = now.weekday()  # 0=周一, 6=周日
    target_weekday = labels.index(weekday_label)  # 目标是周几
    
    # 检查是否明确指定了"下下周"或"下周"
    has_next_next_week = any(k in text for k in ["下下周", "下下星期", "下下礼拜"])
    has_next_week = any(k in text for k in ["下周", "下星期", "下礼拜", "下个周", "下个星期", "下个礼拜"])
    
    # 计算本周一的日期(作为基准)
    days_to_this_monday = today_weekday  # 今天距离本周一的天数
    this_monday = now - timedelta(days=days_to_this_monday)
    
    if has_next_next_week:
        # 下下周X = 本周一 + 14天 + 星期偏移
        target_monday = this_monday + timedelta(days=14)
        target_date = target_monday + timedelta(days=target_weekday)
    
    elif has_next_week:
        # 下周X = 本周一 + 7天 + 星期偏移
        target_monday = this_monday + timedelta(days=7)
        target_date = target_monday + timedelta(days=target_weekday)
        
    else:
        # 周X = 本周的该天(不管过去还是未来)
        target_date = this_monday + timedelta(days=target_weekday)
    
    return datetime.combine(target_date.date(), datetime.min.time())

def _full_day_range_for_weekday(text: str, weekday_label: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    target_date = _date_for_weekday(text, weekday_label)
    if not target_date:
        return None, None
    start_dt = datetime.combine(target_date.date(), datetime.min.time())
    end_dt = datetime.combine(target_date.date(), datetime.max.time().replace(microsecond=0))
    return start_dt, end_dt


def _is_all_day(text: str) -> bool:
    if not text:
        return False
    return any(k in text for k in ["全部", "所有", "全天", "整天"])


def _extract_weekdays(text: str) -> List[str]:
    if not text:
        return []
    if any(k in text for k in ["每天", "每日", "天天"]):
        return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    days: set[str] = set()
    if "工作日" in text:
        days.update(["周一", "周二", "周三", "周四", "周五"])
    if "周末" in text or "双休" in text:
        days.update(["周六", "周日"])
    range_pattern = r"(周|星期|礼拜)([一二三四五六日天])\s*(到|至|~|～|-)\s*(周|星期|礼拜)?([一二三四五六日天])"
    order = ["一", "二", "三", "四", "五", "六", "日"]
    for match in re.finditer(range_pattern, text):
        start = "日" if match.group(2) == "天" else match.group(2)
        end = "日" if match.group(5) == "天" else match.group(5)
        if start in order and end in order:
            start_idx = order.index(start)
            end_idx = order.index(end)
            if start_idx <= end_idx:
                span = order[start_idx : end_idx + 1]
            else:
                span = order[start_idx:] + order[: end_idx + 1]
            days.update([f"周{day}" for day in span])
    single_pattern = r"(周|星期|礼拜)([一二三四五六日天])"
    for match in re.finditer(single_pattern, text):
        day = "日" if match.group(2) == "天" else match.group(2)
        days.add(f"周{day}")
    if not days:
        return []
    return [f"周{day}" for day in order if f"周{day}" in days]


def _contains_explicit_date(text: str) -> bool:
    if not text:
        return False
    pattern = (
        r"(今天|明天|后天|大后天|昨天|前天|"
        r"下下周|下下星期|下下礼拜|下周|下星期|下礼拜|下个周|下个星期|下个礼拜|"
        r"本周|这周|本星期|这星期|本礼拜|这礼拜|"
        r"\d{4}-\d{1,2}-\d{1,2}|"
        r"\d{1,2}月\d{1,2}日|\d{1,2}号|\d{1,2}日)"
    )
    return bool(re.search(pattern, text))


_TIME_TOKEN_PATTERN = (
    r"(?:"
    r"(?:下下周|下周|下星期|下礼拜|本周|这周|本星期|这星期|本礼拜|这礼拜|下个周|下个星期|下个礼拜)?"
    r"(?:周|星期|礼拜)?"
    r"[一二三四五六日天]?"
    r")?"
    r"(?:凌晨|早上|上午|中午|下午|晚上|夜里|夜间)?"
    r"(?:\d{1,2}[:：]\d{1,2}|(?:\d{1,2}|[零〇一二两三四五六七八九十]{1,3})点(?:半|一刻|三刻|\d{1,2}分)?)"
)
_TIME_RANGE_RE = re.compile(rf"({_TIME_TOKEN_PATTERN})\s*(?:到|至|~|～|-)\s*({_TIME_TOKEN_PATTERN})")


def _has_week_scope(text: str) -> bool:
    if not text:
        return False
    return any(
        key in text
        for key in [
            "下下周",
            "下下星期",
            "下下礼拜",
            "下周",
            "下星期",
            "下礼拜",
            "下个周",
            "下个星期",
            "下个礼拜",
            "本周",
            "这周",
            "本星期",
            "这星期",
            "本礼拜",
            "这礼拜",
        ]
    )


def _is_recurring_week_text(text: str, weekdays: Optional[List[str]] = None) -> bool:
    if not text:
        return False
    if any(key in text for key in ["每天", "每日", "天天", "工作日", "周末", "双休"]):
        return True
    if re.search(r"(每周|每星期|每礼拜)", text):
        return True
    if weekdays is None:
        weekdays = _extract_weekdays(text)
    if weekdays and len(weekdays) > 1 and not _has_week_scope(text):
        return True
    return False


def _split_migrate_text(text: str) -> Tuple[str, str]:
    if not text:
        return "", ""
    match = re.search(r"(挪到|移到|迁到|迁至|移至|改到|调整到|改为|改成|变更为)", text)
    if match:
        return text[: match.start()], text[match.end() :]
    return text, ""


def _iter_time_ranges(text: str) -> List[Tuple[datetime, datetime, bool]]:
    ranges: List[Tuple[datetime, datetime, bool]] = []
    if not text:
        return ranges
    for match in _TIME_RANGE_RE.finditer(text):
        start_text = match.group(1)
        end_text = match.group(2)
        start_dt = ENGINE._parse_time_point(start_text, None)
        if not start_dt:
            continue
        end_base = start_dt if not ENGINE._contains_date_word(end_text) else None
        end_dt = ENGINE._parse_time_point(end_text, end_base)
        if not end_dt:
            continue
        if end_dt < start_dt and not ENGINE._contains_date_word(end_text):
            end_dt = end_dt + timedelta(days=1)
        date_specific = ENGINE._contains_date_word(match.group(0)) or _contains_explicit_date(match.group(0))
        ranges.append((start_dt, end_dt, date_specific))
    return ranges


def _single_time_from_text(text: str) -> Tuple[Optional[datetime], bool]:
    """
    从文本中提取单个时间点
    
    【修复】优先使用 _date_for_weekday 处理纯"周X"情况,确保不会自动跳过已过日期
    """
    # 1. 先处理时间区间(如"8点到9点")
    ranges = _iter_time_ranges(text)
    if ranges:
        start_dt, _, date_specific = ranges[0]
        return start_dt, date_specific
    
    # 2. 【新增】检测纯"周X"的情况(没有具体时间点)
    weekday_occ = _extract_weekday_occurrences(text)
    if weekday_occ:
        target_weekday = weekday_occ[0]["label"]
        # 检查是否只有"周X"而没有具体时间（如"8点"）
        has_time = re.search(r'(\d{1,2}[:：]\d{1,2}|\d{1,2}点)', text)
        
        if not has_time:
            # 纯"周五"的情况,使用我们修正后的逻辑
            target_date = _date_for_weekday(text, target_weekday)
            if target_date:
                date_specific = ENGINE._contains_date_word(text) or _contains_explicit_date(text)
                return target_date, date_specific
        else:
            # 有具体时间的情况(如"周五8点"),先确定日期基准
            base_date = _date_for_weekday(text, target_weekday)
            if base_date:
                # 用这个基准日期去解析完整时间
                dt = ENGINE._parse_time_point(text, base_date)
                if dt:
                    date_specific = ENGINE._contains_date_word(text) or _contains_explicit_date(text)
                    return dt, date_specific
    
    # 3. 其他情况(如"明天"、"1月25日"等)还是用 ENGINE 的逻辑
    dt = ENGINE._parse_time_point(text, None)
    if dt:
        date_specific = ENGINE._contains_date_word(text) or _contains_explicit_date(text)
        return dt, date_specific
    
    return None, False


def _time_range_from_slots(slots: dict, prefix: str) -> Tuple[Optional[datetime], Optional[datetime], bool]:
    raw = slots.get(prefix)
    date_specific = bool(raw) and ENGINE._contains_date_word(str(raw))
    start_str = slots.get(f"{prefix}_START")
    end_str = slots.get(f"{prefix}_END")
    if start_str and end_str:
        start_dt = _parse_datetime(str(start_str))
        end_dt = _parse_datetime(str(end_str))
        return start_dt, end_dt, date_specific
    if isinstance(raw, str):
        pair = ENGINE._split_time_range(raw)
        if pair:
            start_dt = ENGINE._parse_time_point(pair[0], None)
            end_base = start_dt if start_dt and not ENGINE._contains_date_word(pair[1]) else None
            end_dt = ENGINE._parse_time_point(pair[1], end_base)
            if start_dt and end_dt and end_dt < start_dt and not ENGINE._contains_date_word(pair[1]):
                end_dt = end_dt + timedelta(days=1)
            return start_dt, end_dt, date_specific
    return None, None, date_specific


def _single_time_from_slots(slots: dict) -> Tuple[Optional[datetime], bool]:
    raw = slots.get("TIME")
    if isinstance(raw, str) and raw:
        date_specific = ENGINE._contains_date_word(raw)
        dt = ENGINE._parse_time_point(raw, None)
        return dt, date_specific
    return None, False


def _cancel_schedule_has_explicit_date_scope(*values: object) -> bool:
    relative_date_keywords = ("今天", "今日", "明天", "明日", "后天", "大后天", "昨天", "昨日", "前天")
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if any(keyword in text for keyword in relative_date_keywords) or _contains_explicit_date(text):
            return True
    return False


def _cancel_schedule_explicit_date_base(text: str, start_text: str, end_text: str) -> Optional[datetime]:
    engine_supports_time_point = hasattr(ENGINE, "_parse_time_point") and hasattr(ENGINE, "_contains_date_word")
    for candidate in (text, start_text, end_text):
        candidate_text = str(candidate or "").strip()
        if not _cancel_schedule_has_explicit_date_scope(candidate_text):
            continue
        parsed = _parse_phase1_date(candidate_text)
        if parsed:
            return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        if engine_supports_time_point:
            ranges = _iter_time_ranges(candidate_text)
            if len(ranges) == 1:
                return ranges[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
            point_dt, date_specific = _single_time_from_text(candidate_text)
            if point_dt and date_specific:
                return point_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def _resolve_cancel_schedule_time_context(
    text: str,
    slots: dict,
) -> Tuple[str, str, Optional[datetime], Optional[datetime], bool, bool, Optional[Dict[str, Any]]]:
    start_text = _slot_text(slots, "time_range_start", "start_time", "time_from", "source_time")
    end_text = _slot_text(slots, "time_range_end", "end_time", "time_to", "target_time")
    explicit_date_locked = _cancel_schedule_has_explicit_date_scope(text, start_text, end_text)
    explicit_date_base = _cancel_schedule_explicit_date_base(text, start_text, end_text)

    def _parse_value(value: str, fallback_base: Optional[datetime] = None) -> Optional[datetime]:
        candidate_text = str(value or "").strip()
        if not candidate_text:
            return None
        has_explicit_date = _cancel_schedule_has_explicit_date_scope(candidate_text)
        if explicit_date_base is not None and not has_explicit_date:
            try:
                parsed = ENGINE._parse_time_point(candidate_text, explicit_date_base)
            except Exception:
                parsed = None
            if parsed:
                return parsed
        if fallback_base is not None and not has_explicit_date:
            try:
                parsed = ENGINE._parse_time_point(candidate_text, fallback_base)
            except Exception:
                parsed = None
            if parsed:
                return parsed
        return _parse_phase1_date(candidate_text)

    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    date_specific = False
    source_anchor: Optional[Dict[str, Any]] = None

    if start_text:
        start_dt = _parse_value(start_text)
    if end_text:
        end_dt = _parse_value(end_text, fallback_base=start_dt)
    if start_dt and not end_dt:
        end_dt = datetime.combine(start_dt.date(), datetime.max.time().replace(microsecond=0))
    if end_dt and not start_dt:
        start_dt = datetime.combine(end_dt.date(), datetime.min.time())
    if start_dt and end_dt:
        date_specific = True
    elif start_text and not end_text:
        source_anchor = _parse_phase1_time_anchor(start_text)

    return start_text, end_text, start_dt, end_dt, date_specific, explicit_date_locked, source_anchor


def _task_template(schedule: dict) -> dict:
    tasks = schedule.get("tasks") or []
    if tasks:
        base = tasks[0]
        if isinstance(base, dict):
            return {**base}
    return {
        "all": 1,
        "count": 1,
        "start": 1,
        "state": 0,
        "prepower": 15,
        "datasendmode": 0,
        "enablestate": 1,
        "taskstate": 0,
        "timelength": 1,
        "timelengthtype": 2,
        "execmode": 0,
        "playmode": 0,
        "volume": 50,
        "priority": 10,
        "isinstancy": 2,
    }


def _build_schedule_task(
    schedule: dict,
    payload: dict,
    task_name: str,
    start_dt: datetime,
    date_specific: bool,
    audio_name: str,
    custom_name: str,
    weekdays: Optional[List[str]] = None,
) -> dict:
    template = _task_template(schedule)
    task_id = _next_schedule_task_id(payload)
    task = {**template}
    task["taskid"] = task_id
    task["taskname"] = task_name
    task["customName"] = custom_name
    task["audio"] = audio_name
    if weekdays:
        task["weekdays"] = weekdays
    task["starttime"] = start_dt.strftime("%H:%M:%S")
    if date_specific:
        date_str = start_dt.strftime("%Y-%m-%d")
        task["startdate"] = date_str
        task["enddate"] = date_str
    else:
        task["startdate"] = "0-00-00"
        task["enddate"] = "0-00-00"
    task["enablestate"] = 1
    return task


def _task_matches_range(task: dict, start_dt: datetime, end_dt: datetime, date_specific: bool) -> bool:
    start_minutes = start_dt.hour * 60 + start_dt.minute
    end_minutes = end_dt.hour * 60 + end_dt.minute
    task_minutes = _parse_time_minutes(task.get("starttime"))
    if task_minutes is None:
        return False
    if not date_specific:
        if start_dt.date() == end_dt.date():
            return start_minutes <= task_minutes <= end_minutes
        return task_minutes >= start_minutes or task_minutes <= end_minutes

    weekdays = task.get("weekdays") if isinstance(task.get("weekdays"), list) else []
    normalized_weekdays = [str(day).strip() for day in weekdays if str(day).strip()]
    if not normalized_weekdays:
        normalized_weekdays = _weekdays_from_execmode(task.get("execmode"))

    task_start_span, task_end_span = _task_date_span(task)
    overlap_start = start_dt.date()
    overlap_end = end_dt.date()
    if task_start_span and task_end_span:
        overlap_start = max(overlap_start, task_start_span.date())
        overlap_end = min(overlap_end, task_end_span.date())
    if overlap_start > overlap_end:
        return False

    whole_day_range = (
        start_dt.hour == 0
        and start_dt.minute == 0
        and start_dt.second == 0
        and end_dt.hour == 0
        and end_dt.minute == 0
        and end_dt.second == 0
    )

    current_date = overlap_start
    while current_date <= overlap_end:
        if normalized_weekdays:
            current_label = _weekday_label(datetime.combine(current_date, datetime.min.time()))
            if current_label not in normalized_weekdays:
                current_date += timedelta(days=1)
                continue

        if start_dt.date() == end_dt.date():
            if whole_day_range:
                day_start_minutes, day_end_minutes = 0, 23 * 60 + 59
            else:
                day_start_minutes, day_end_minutes = start_minutes, end_minutes
        elif current_date == start_dt.date():
            day_start_minutes, day_end_minutes = start_minutes, 23 * 60 + 59
        elif current_date == end_dt.date():
            day_start_minutes = 0
            day_end_minutes = 23 * 60 + 59 if whole_day_range else end_minutes
        else:
            day_start_minutes, day_end_minutes = 0, 23 * 60 + 59

        if day_start_minutes <= day_end_minutes:
            if day_start_minutes <= task_minutes <= day_end_minutes:
                return True
        elif task_minutes >= day_start_minutes or task_minutes <= day_end_minutes:
            return True

        current_date += timedelta(days=1)

    return False


def _detect_apply_mode(text: str) -> Optional[str]:
    raw = str(text or "")
    compact = _compact_text(raw)
    once_words = [
        "一次",
        "一次性",
        "仅一次",
        "只这一次",
        "临时",
        "本次",
        "这次",
        "once",
        "one-time",
        "onetime",
    ]
    permanent_words = [
        "永久",
        "长期",
        "一直",
        "以后都",
        "持续",
        "固定生效",
        "permanent",
        "always",
        "forever",
    ]
    if any(k in raw for k in once_words if len(k) > 1):
        return "once"
    if any(k in raw for k in permanent_words if len(k) > 1):
        return "permanent"
    if any(_compact_text(k) in compact for k in once_words if _compact_text(k)):
        return "once"
    if any(_compact_text(k) in compact for k in permanent_words if _compact_text(k)):
        return "permanent"
    lowered = raw.lower()
    if "once" in lowered or "one-time" in lowered or "onetime" in lowered:
        return "once"
    if "permanent" in lowered or "always" in lowered or "forever" in lowered:
        return "permanent"
    return None

def _set_pending_action(action: dict) -> None:
    _set_pending_action_for_scope(action)


def _clear_pending_action() -> None:
    _clear_pending_action_for_scope()


def _pending_action_overrides(
    action: Optional[dict],
    *,
    slots: Optional[dict] = None,
    missing_slots: Optional[List[str]] = None,
    diagnostics: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {"missing_slots": list(missing_slots or [])}
    if isinstance(action, dict):
        intent = _normalize_intent_label(str(action.get("intent") or ""))
        if intent:
            overrides["intent"] = intent
        effective_slots = slots
        if effective_slots is None and isinstance(action.get("slots"), dict):
            effective_slots = _clone_payload(action.get("slots"))
        if isinstance(effective_slots, dict):
            overrides["slots"] = effective_slots
        # Pending follow-ups should not leak a fresh NLU guess.
        overrides["confidence"] = 1.0
        overrides["raw_entities"] = {}
        overrides["tokens"] = []
        overrides["tags"] = []
    if isinstance(diagnostics, list):
        overrides["diagnostics"] = diagnostics
    return overrides


def _pending_slots_snapshot(base_slots: Optional[dict], **updates: object) -> Dict[str, Any]:
    snapshot = _clone_payload(base_slots or {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        snapshot[key] = _clone_payload(value)
    return snapshot


def _handle_pending_action_for_scope(text: str, scope: object = None) -> Optional[Tuple[str, Dict[str, Any], List[dict]]]:
    scope_key = str(scope or "").strip()
    if not scope_key:
        return _handle_pending_action(text)
    reset_scope = _set_current_pending_scope(scope_key)
    try:
        return _handle_pending_action(text)
    finally:
        _reset_current_pending_scope(reset_scope)


def _pending_expired(pending: dict) -> bool:
    created = pending.get("created_at")
    dt = _parse_datetime(str(created)) if created else None
    if not dt:
        return True
    return (datetime.now() - dt).total_seconds() > PENDING_EXPIRE_SECONDS


def _summarize_tasks(tasks: List[dict]) -> str:
    names: List[str] = []
    for task in tasks[:5]:
        name = task.get("taskname") or task.get("customName") or task.get("audio") or ""
        time_text = task.get("starttime") or ""
        if name or time_text:
            names.append(f"{time_text} {name}".strip())
    if not names:
        return "未找到任务"
    more = f" 等{len(tasks)}个任务" if len(tasks) > 5 else ""
    return "、".join(names) + more


def _task_date_span(task: dict) -> Tuple[Optional[datetime], Optional[datetime]]:
    if not isinstance(task, dict):
        return None, None
    start_dt = _parse_iso_date(task.get("startdate"))
    end_dt = _parse_iso_date(task.get("enddate")) or start_dt
    if not start_dt or not end_dt:
        return None, None
    return start_dt, end_dt


def _task_is_recurring(task: dict) -> bool:
    start_dt, end_dt = _task_date_span(task)
    if not start_dt or not end_dt:
        return False
    return start_dt.date() != end_dt.date()


def _summarize_date_window_shift(tasks: List[dict], day_delta: int, limit: int = 3) -> str:
    if not tasks or day_delta == 0:
        return ""
    preview: List[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        start_dt, end_dt = _task_date_span(task)
        if not start_dt or not end_dt:
            continue
        name = str(task.get("taskname") or task.get("name") or _task_id(task) or "任务").strip()
        new_start = (start_dt + timedelta(days=day_delta)).strftime("%Y-%m-%d")
        new_end = (end_dt + timedelta(days=day_delta)).strftime("%Y-%m-%d")
        old_start = start_dt.strftime("%Y-%m-%d")
        old_end = end_dt.strftime("%Y-%m-%d")
        preview.append(f"{name}: {old_start}~{old_end} -> {new_start}~{new_end}")
        if len(preview) >= limit:
            break
    if not preview:
        return ""
    return "；".join(preview)


def _build_recurring_risk_prompt(base_prompt: str, recurring_count: int, window_preview: str = "") -> str:
    if recurring_count <= 0:
        return base_prompt
    message = (
        f"{base_prompt}\n注意:匹配结果中有 {recurring_count} 条长期循环任务。"
        '若选择"永久",会整体平移其日期窗口(startdate/enddate)。'
    )
    message += '\n如只影响当前这次,请回复"一次性"。'
    return message

def _format_action_time(value: object) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if value is None:
        return ""
    return str(value)


def _build_action_range(start: object, end: object, date_specific: Optional[bool]) -> Optional[dict]:
    start_text = _format_action_time(start)
    end_text = _format_action_time(end)
    if not start_text and not end_text:
        return None
    return {
        "start": start_text,
        "end": end_text,
        "date_specific": bool(date_specific) if date_specific is not None else None,
    }


def _build_action_log(
    action: str,
    schedule_name: Optional[str],
    task_ids: List[str],
    time_start: object = None,
    time_end: object = None,
    date_specific: Optional[bool] = None,
    new_time_start: object = None,
    new_time_end: object = None,
    mode: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    return {
        "action": action,
        "schedule_name": str(schedule_name or ""),
        "task_ids": [str(task_id) for task_id in task_ids if task_id not in (None, "")],
        "time_range": _build_action_range(time_start, time_end, date_specific),
        "new_time_range": _build_action_range(new_time_start, new_time_end, date_specific)
        if new_time_start or new_time_end
        else None,
        "mode": mode or "",
        "details": details or {},
    }


def _action_log_with_failure_details(
    action: str,
    schedule_name: Optional[str],
    task_ids: List[str],
    *,
    mode: Optional[str] = None,
    details: Optional[dict] = None,
    raw_reason: object = None,
    user_reason: str = "",
    retryable: Optional[bool] = None,
    failure_code: str = "",
    **extra: Any,
) -> dict:
    merged_details = dict(details or {})
    merged_details.update(
        _failure_runtime_detail_payload(
            raw_reason,
            user_reason=user_reason,
            retryable=retryable,
            failure_code=failure_code,
            **extra,
        )
    )
    return _build_action_log(action, schedule_name, task_ids, mode=mode, details=merged_details)


def _parse_action_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    parsed = _parse_datetime(str(value))
    if parsed:
        return parsed
    parsed_date = _parse_iso_date(value)
    if parsed_date:
        return datetime.combine(parsed_date.date(), datetime.min.time())
    return None


def _task_kind_for_once(task: dict) -> str:
    task_type = _coerce_int(task.get("tasktype"), _coerce_int(REMOTE_BROADCAST_TASK_TYPE, 2))
    livecast_type = _coerce_int(REMOTE_LIVECAST_TASK_TYPE, 3)
    return "livecast" if task_type == livecast_type else "broadcast"


def _task_duration_seconds(task: dict) -> int:
    timelength_raw = task.get("timelength")
    timelength = _coerce_duration_int(timelength_raw, 1)
    timelengthtype = _coerce_int(task.get("timelengthtype"), 1)
    if timelengthtype == 2:
        return max(1, timelength) * 60
    parsed_seconds = _parse_hms_duration_seconds(timelength_raw)
    if parsed_seconds is not None:
        return max(1, parsed_seconds)
    return max(1, timelength)


def _task_start_datetime(task: dict, fallback: datetime) -> datetime:
    start_text = _format_hhmmss(str(task.get("starttime") or task.get("time") or "")) or "00:00:00"
    start_date = _parse_iso_date(task.get("startdate")) if task.get("startdate") not in (None, "", "0-00-00") else None
    end_date = _parse_iso_date(task.get("enddate")) if task.get("enddate") not in (None, "", "0-00-00") else None
    # Recurring tasks should align to the requested operation date for once move/swap.
    if start_date and end_date and start_date.date() != end_date.date():
        base_date = fallback.date()
    else:
        base_date = start_date.date() if start_date else fallback.date()
    try:
        hh, mm, ss = [int(part) for part in start_text.split(":")]
    except Exception:
        hh, mm, ss = 0, 0, 0
    return datetime.combine(base_date, datetime.min.time()).replace(hour=hh, minute=mm, second=ss)


def _task_end_datetime(task: dict, fallback: datetime) -> datetime:
    return _task_start_datetime(task, fallback) + timedelta(seconds=_task_duration_seconds(task))


def _tasks_window(tasks: List[dict], fallback: datetime) -> Tuple[Optional[datetime], Optional[datetime]]:
    starts: List[datetime] = []
    ends: List[datetime] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        starts.append(_task_start_datetime(task, fallback))
        ends.append(_task_end_datetime(task, fallback))
    if not starts or not ends:
        return None, None
    return min(starts), max(ends)


def _schedule_tasks_by_ids(schedule: object, task_ids: List[str]) -> List[dict]:
    if not isinstance(schedule, dict):
        return []
    tasks = schedule.get("tasks")
    if not isinstance(tasks, list):
        return []
    tracked_ids = {str(item).strip() for item in task_ids if str(item).strip()}
    if not tracked_ids:
        return []
    return [
        task
        for task in tasks
        if isinstance(task, dict) and _task_id(task) in tracked_ids
    ]


def _resolve_cancel_once_time_range(
    action: dict,
    schedule: object,
    task_ids: List[str],
) -> Tuple[str, str]:
    time_start_str = str(action.get("time_start") or "").strip()
    time_end_str = str(action.get("time_end") or "").strip()
    if time_start_str and time_end_str:
        return time_start_str, time_end_str
    source_anchor = action.get("source_anchor") or {}
    if str(source_anchor.get("kind") or "") != "date":
        return "", ""
    source_date = source_anchor.get("date")
    if not source_date:
        return "", ""
    matched_tasks = _schedule_tasks_by_ids(schedule, task_ids)
    if not matched_tasks:
        return "", ""
    fallback = datetime.combine(source_date, datetime.min.time())
    old_start, old_end = _tasks_window(matched_tasks, fallback)
    if not old_start or not old_end:
        return "", ""
    return (
        old_start.strftime("%Y-%m-%d %H:%M:%S"),
        old_end.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _build_once_shadow_task(source_task: dict, shadow_start: datetime) -> dict:
    shadow = _clone_payload(source_task) if isinstance(source_task, dict) else {}
    shadow.pop("id", None)
    shadow.pop("taskid", None)
    date_text = shadow_start.strftime("%Y-%m-%d")
    source_task_id = _task_id(source_task)
    base_name = str(shadow.get("taskname") or shadow.get("name") or shadow.get("customName") or "shadow-task").strip() or "shadow-task"
    shadow_suffix = shadow_start.strftime("%Y%m%d%H%M%S")
    if source_task_id:
        shadow["taskname"] = f"{base_name}_once_{source_task_id}_{shadow_suffix}"
    else:
        shadow["taskname"] = f"{base_name}_once_{shadow_suffix}"
    shadow["name"] = shadow["taskname"]
    shadow["starttime"] = shadow_start.strftime("%H:%M:%S")
    shadow["startdate"] = date_text
    shadow["enddate"] = date_text
    shadow["execmode"] = 0
    shadow["weekdays"] = []
    shadow["priority"] = 100
    shadow["isinstancy"] = 2
    shadow["tasktype"] = _coerce_int(REMOTE_BROADCAST_TASK_TYPE, 2)

    media_id = shadow.get("mediaid")
    if media_id in (None, "", 0, "0"):
        source_id = _task_id(source_task)
        media_ids = _remote_task_media_ids(source_id) if source_id else []
        if media_ids:
            shadow["mediaid"] = str(media_ids[0])

    terminal_ids = _get_task_terminal_ids(shadow)
    if not terminal_ids:
        source_id = _task_id(source_task)
        remote_ids = _remote_task_terminal_ids(source_id) if source_id else []
        terminal_ids = _unique_list([str(item) for item in remote_ids if str(item).strip() and str(item).strip() != "0"])
    if terminal_ids:
        shadow["terminalids"] = terminal_ids
        shadow["liveterminalid"] = str(terminal_ids[0])
    return shadow


def _build_once_schedule_task(source_task: dict, once_start: datetime) -> dict:
    once_task = _build_once_shadow_task(source_task, once_start)
    unique_name = str(once_task.get("taskname") or once_task.get("name") or "").strip()
    if unique_name:
        once_task["taskname"] = unique_name
        once_task["name"] = unique_name
        once_task["customName"] = unique_name
    if "priority" in source_task:
        once_task["priority"] = _clone_payload(source_task.get("priority"))
    else:
        once_task.pop("priority", None)
    if "weekdays" in source_task:
        once_task["weekdays"] = _clone_payload(source_task.get("weekdays"))
    else:
        once_task.pop("weekdays", None)
    once_task["execmode"] = 127
    once_task["tasktype"] = 1
    for field in ("projectstate", "taskstate", "state", "enablestate", "isinstancy"):
        once_task.pop(field, None)
    return once_task


def _attach_shadow_schedule_name(task: dict, schedule_name: object) -> dict:
    if not isinstance(task, dict):
        return task
    normalized_name = str(schedule_name or "").strip()
    if not normalized_name:
        return task
    task["sechename"] = normalized_name
    task["schedule_name"] = normalized_name
    task["scheduleName"] = normalized_name
    return task


def _remote_schedule_enabletask(
    task_ids: List[str],
    enstate: int,
    start_dt: datetime,
    dry_run: bool = False,
    source_task_ids: Optional[List[str]] = None,
    diagnostics: Optional[List[dict]] = None,
    diagnostic_id: str = "",
    action_name: str = "",
    phase: str = "",
) -> List[dict]:
    clean_ids = _unique_list([str(item).strip() for item in task_ids if str(item).strip()])
    if not clean_ids:
        return []
    del source_task_ids  # Remote /task/enabletask no longer accepts yuantaskid.
    if not isinstance(start_dt, datetime):
        parsed = _parse_action_datetime(start_dt)
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid schedule enabletask datetime.")
        start_dt = parsed
    state_value = 1 if _coerce_int(enstate, 0) != 0 else 0
    payloads: List[dict] = []

    def submit_chunk(chunk: List[str]) -> None:
        payload = {
            "id": 0,
            "taskid": ",".join(chunk),
            "enstate": ",".join([str(state_value)] * len(chunk)),
            "startdate": start_dt.strftime("%Y-%m-%d"),
            "starttime": start_dt.strftime("%H:%M:%S"),
        }
        diagnostic = _new_remote_phase_diagnostic(
            diagnostics,
            diagnostic_id=diagnostic_id,
            action=str(action_name or ""),
            phase=str(phase or ""),
            path="/task/enabletask",
            request_payload=payload,
        )
        if not dry_run:
            try:
                response = _remote_request(
                    "POST",
                    "/task/enabletask",
                    json_body=payload,
                    form_body=None,
                    allow_retry=False,
                    allow_form_retry=False,
                    diagnostic=diagnostic,
                )
            except HTTPException as exc:
                LOGGER.warning(
                    "enabletask failed | enstate=%s taskid=%s startdate=%s starttime=%s error=%s",
                    state_value,
                    payload.get("taskid"),
                    payload.get("startdate"),
                    payload.get("starttime"),
                    str(exc.detail),
                )
                raise _RemoteBatchDispatchError(
                    status_code=exc.status_code,
                    detail=str(exc.detail),
                    dispatched_payloads=payloads,
                    failed_payload=payload,
                    enstate=state_value,
                    start_dt=start_dt,
                ) from exc
            ok, detail = _remote_enabletask_response_ok(response)
            if not ok:
                if isinstance(diagnostic, dict):
                    diagnostic["ok"] = False
                    diagnostic["error_detail"] = detail
                    if diagnostic.get("response_body") in (None, ""):
                        diagnostic["response_body"] = _clone_payload(response)
                    diagnostic["timeout"] = False
                    _log_remote_phase_result(diagnostic)
                if len(chunk) > 1:
                    midpoint = max(1, len(chunk) // 2)
                    submit_chunk(chunk[:midpoint])
                    submit_chunk(chunk[midpoint:])
                    return
                raise _RemoteBatchDispatchError(
                    status_code=502,
                    detail=detail,
                    dispatched_payloads=payloads,
                    failed_payload=payload,
                    enstate=state_value,
                    start_dt=start_dt,
                )
        payloads.append(_clone_payload(payload))

    for start in range(0, len(clean_ids), REMOTE_ENABLETASK_BATCH_SIZE):
        chunk = clean_ids[start : start + REMOTE_ENABLETASK_BATCH_SIZE]
        submit_chunk(chunk)
    return payloads


def _append_enabletask_commands(commands: List[dict], phase: str, payloads: List[dict]) -> None:
    for payload in payloads or []:
        commands.append({"type": "enabletask", "phase": phase, "payload": _clone_payload(payload)})


def _remote_enabletask_response_ok(response: object) -> Tuple[bool, str]:
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, list) and data:
            failures: List[str] = []
            for item in data:
                if not isinstance(item, dict):
                    failures.append(f"invalid_item={item!r}")
                    continue
                state = _coerce_int(item.get("state"), None)
                if state == 0:
                    continue
                taskid = item.get("taskid")
                failures.append(f"state={state} taskid={taskid}")
            if not failures:
                return True, ""
            preview = json.dumps(response, ensure_ascii=False)
            return False, f"Remote enabletask rejected payload: {'; '.join(failures)} | response={preview}"
    return True, ""


def _dispatch_enabletask_phase(
    commands: List[dict],
    phase: str,
    task_ids: List[str],
    enstate: int,
    start_dt: datetime,
    *,
    dry_run: bool = False,
    source_task_ids: Optional[List[str]] = None,
    diagnostics: Optional[List[dict]] = None,
    diagnostic_id: str = "",
    action_name: str = "",
) -> None:
    try:
        payloads = _remote_schedule_enabletask(
            task_ids,
            enstate,
            start_dt,
            dry_run=dry_run,
            source_task_ids=source_task_ids,
            diagnostics=diagnostics,
            diagnostic_id=diagnostic_id,
            action_name=action_name,
            phase=phase,
        )
    except _RemoteBatchDispatchError as exc:
        exc.phase = phase
        _append_enabletask_commands(commands, phase, exc.dispatched_payloads)
        raise
    _append_enabletask_commands(commands, phase, payloads)


def _append_taskinfo_command(commands: List[dict], phase: str, task_id: str, payload: Optional[dict] = None) -> None:
    command = {"type": "taskinfo", "phase": phase, "taskid": str(task_id)}
    if isinstance(payload, dict):
        command["payload"] = _clone_payload(payload)
    commands.append(command)


def _append_sechetask_command(commands: List[dict], phase: str, task_id: str, payload: Optional[dict] = None) -> None:
    command = {"type": "sechetask", "phase": phase, "taskid": str(task_id)}
    if isinstance(payload, dict):
        command["payload"] = _clone_payload(payload)
    commands.append(command)


def _once_dispatch_failure_message(action_label: str, detail: str, partial_applied: bool) -> str:
    if partial_applied:
        return "一次性操作未完整生效: 部分远端指令可能已下发,请立即检查远端任务启停状态。"
    if _looks_like_timeout_error(detail):
        return f"一次性{action_label}未生效: 远端服务器响应超时,请稍后重试。"
    return f"一次性{action_label}未生效: 远端指令下发失败,请稍后重试。"


def _once_shadow_failure_message(action_label: str, detail: str, partial_applied: bool) -> str:
    if partial_applied:
        return "一次性操作未完整生效: 部分远端指令可能已下发,请立即检查远端任务启停状态。"
    if _looks_like_timeout_error(detail):
        return f"一次性{action_label}未生效: 远端服务器响应超时,请稍后重试。"
    lowered = str(detail or "").lower()
    if "missing mediaid" in lowered:
        return f"一次性{action_label}未生效: 临时任务缺少音频绑定(mediaid),请检查原任务的音频资源配置。"
    if "missing terminalid" in lowered or "missing terminal binding" in lowered:
        return f"一次性{action_label}未生效: 临时任务缺少终端绑定,请检查原任务的终端配置。"
    if "could not confirm the new task id" in lowered:
        return f"一次性{action_label}未生效: 远端已响应，但系统未能确认新临时任务ID。"
    if "returned no taskid" in lowered or "no taskid" in lowered:
        return f"一次性{action_label}未生效: 远端已响应成功，但未返回临时任务ID。"
    if "multiple candidate task ids" in lowered or "未能确认" in str(detail or ""):
        return f"一次性{action_label}未生效: 远端已响应,但系统未能确认临时任务是否创建成功。"
    if "state=" in lowered or "remote_rejected" in lowered or "rejected" in lowered:
        return f"一次性{action_label}未生效: 远端拒绝创建临时任务,请检查远端任务配置。"
    return f"一次性{action_label}未生效: 远端临时任务创建失败,请稍后重试。"


def _save_failed_once_entry(action_name: str, fields: dict) -> dict:
    entry = {
        "id": f"{action_name}-{int(datetime.now().timestamp())}",
        "action": action_name,
        "mode": "once",
        "created_at": _now_str(),
        "execution_state": "failed",
        "active": False,
    }
    if isinstance(fields, dict):
        payload = _clone_payload(fields) or {}
        failure_items = payload.get("once_task_failures")
        if not isinstance(failure_items, list):
            failure_items = payload.get("shadow_failures")
        if isinstance(failure_items, list) and "failure_count" not in payload:
            payload["failure_count"] = len(failure_items)
        entry.update(payload)
    _save_once_override_entry(entry)
    return entry


def _append_rollback_shadow_commands(commands: List[dict], rollback_attempts: List[dict]) -> None:
    for attempt in rollback_attempts:
        command = {
            "type": str(attempt.get("type") or "taskinfo"),
            "phase": str(attempt.get("phase") or "rollback_delete_shadow"),
            "taskid": str(attempt.get("taskid") or ""),
        }
        if attempt.get("status") not in (None, ""):
            command["status"] = attempt.get("status")
        if attempt.get("error") not in (None, ""):
            command["error"] = attempt.get("error")
        commands.append(command)


def _rollback_shadow_tasks(task_ids: List[str], commands: Optional[List[dict]] = None) -> List[dict]:
    attempts: List[dict] = []
    for task_id in _unique_list([str(item).strip() for item in task_ids if _is_numeric_id(str(item).strip())]):
        attempt = {"taskid": str(task_id)}
        try:
            _remote_delete_taskinfo(str(task_id))
            attempt["status"] = "ok"
        except HTTPException as exc:
            attempt["status"] = "failed"
            attempt["error"] = str(exc.detail)
        except Exception as exc:
            attempt["status"] = "failed"
            attempt["error"] = str(exc)
        attempts.append(attempt)
    if commands is not None and attempts:
        _append_rollback_shadow_commands(commands, attempts)
    return attempts


def _rollback_once_schedule_tasks(task_ids: List[str], commands: Optional[List[dict]] = None) -> List[dict]:
    attempts: List[dict] = []
    for task_id in _unique_list([str(item).strip() for item in task_ids if _is_numeric_id(str(item).strip())]):
        attempt = {"taskid": str(task_id), "type": "sechetask", "phase": "rollback_delete_once_task"}
        try:
            _remote_delete_task(str(task_id))
            attempt["status"] = "ok"
        except HTTPException as exc:
            attempt["status"] = "failed"
            attempt["error"] = str(exc.detail)
        except Exception as exc:
            attempt["status"] = "failed"
            attempt["error"] = str(exc)
        attempts.append(attempt)
    if commands is not None and attempts:
        _append_rollback_shadow_commands(commands, attempts)
    return attempts


def _build_once_shadow_failure_record(
    *,
    phase: str,
    failure_reason: str,
    failure_code: str,
    failed_payload: object,
    diagnostic_id: str,
    remote_diagnostics: List[dict],
    rollback_attempts: List[dict],
    shadow_diagnostic: Optional[dict] = None,
) -> dict:
    record = {
        "phase": phase,
        "failure_code": str(failure_code or "shadow_create_failed"),
        "reason": str(failure_reason or ""),
        "failed_payload": _clone_payload(failed_payload),
        "diagnostic_id": str(diagnostic_id or ""),
        "remote_diagnostics": _clone_payload(remote_diagnostics),
        "rollback_attempts": _clone_payload(rollback_attempts),
    }
    if isinstance(shadow_diagnostic, dict):
        for key in (
            "request_payload_preview",
            "remote_response_preview",
            "lookup_attempts",
            "match_ids",
            "match_basis",
            "request_payload",
            "response_body",
            "status_code",
            "error_detail",
            "timeout",
            "ok",
            "failure_code",
            "reason",
        ):
            if key in shadow_diagnostic and shadow_diagnostic.get(key) is not None:
                record[key] = _clone_payload(shadow_diagnostic.get(key))
    return record


def _save_and_return_once_shadow_failure(
    action_name: str,
    action_label: str,
    fields: dict,
    *,
    phase: str,
    failure_reason: str,
    failure_code: str,
    commands: List[dict],
    failed_payload: object,
    diagnostic_id: str,
    remote_diagnostics: List[dict],
    rollback_attempts: List[dict],
    shadow_diagnostic: Optional[dict] = None,
) -> Tuple[dict, str]:
    shadow_failure = _build_once_shadow_failure_record(
        phase=phase,
        failure_reason=failure_reason,
        failure_code=failure_code,
        failed_payload=failed_payload,
        diagnostic_id=diagnostic_id,
        remote_diagnostics=remote_diagnostics,
        rollback_attempts=rollback_attempts,
        shadow_diagnostic=shadow_diagnostic,
    )
    failure_fields = dict(fields)
    failure_fields.update(
        {
            "commands": _clone_payload(commands) or [],
            "failure_reason": str(failure_reason or ""),
            "failed_phase": phase,
            "failed_payload": _clone_payload(failed_payload),
            "once_task_failures": [shadow_failure],
            "shadow_failures": [shadow_failure],
            "rollback_attempts": _clone_payload(rollback_attempts) or [],
            "remote_diagnostics": _clone_payload(remote_diagnostics),
            "execution_state": "failed",
            "active": False,
            "remote_synced": False,
        }
    )
    failure_fields.setdefault("failure_count", len(failure_fields["once_task_failures"]))
    entry = _save_failed_once_entry(action_name, failure_fields)
    return entry, _once_shadow_failure_message(action_label, failure_reason, False)


def _save_once_override_entry(entry: dict) -> None:
    overrides = _load_overrides_payload()
    overrides.setdefault("overrides", []).append(entry)
    _save_overrides_payload(_touch_generated_at(overrides))


def _execute_once_cancel_action(
    action: dict,
    schedule: dict,
    dry_run: bool = False,
    diagnostics: Optional[List[dict]] = None,
    diagnostic_id: str = "",
) -> Tuple[dict, str]:
    del schedule
    start_dt = _parse_action_datetime(action.get("time_start"))
    end_dt = _parse_action_datetime(action.get("time_end"))
    if not start_dt or not end_dt:
        raise HTTPException(status_code=400, detail="Missing cancel time range for once mode.")
    task_ids = _unique_list([str(item).strip() for item in action.get("task_ids", []) if str(item).strip()])
    if not task_ids:
        raise HTTPException(status_code=400, detail="No task ids for once cancel.")

    commands: List[dict] = []
    remote_diagnostics = diagnostics if diagnostics is not None else []
    current_diagnostic_id = str(diagnostic_id or _new_diagnostic_id())
    try:
        _dispatch_enabletask_phase(
            commands,
            "disable",
            task_ids,
            1,
            start_dt - timedelta(seconds=5),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="cancel",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore",
            task_ids,
            0,
            end_dt,
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="cancel",
        )
    except _RemoteBatchDispatchError as exc:
        partial_applied = bool(commands)
        if partial_applied:
            _save_failed_once_entry(
                "cancel",
                {
                    "schedule_name": action.get("schedule_name"),
                    "task_ids": task_ids,
                    "time_start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "time_end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "commands": commands,
                    "failure_reason": str(exc.detail),
                    "failed_phase": exc.phase or "enabletask",
                    "failed_payload": _clone_payload(exc.failed_payload),
                    "diagnostic_id": current_diagnostic_id,
                    "remote_diagnostics": _clone_payload(remote_diagnostics),
                    "remote_synced": False,
                },
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_dispatch_failure_message("取消", str(exc.detail), partial_applied),
        ) from exc

    entry = {
        "id": f"cancel-{int(datetime.now().timestamp())}",
        "action": "cancel",
        "mode": "once",
        "schedule_name": action.get("schedule_name"),
        "task_ids": task_ids,
        "time_start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "time_end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "commands": commands,
        "created_at": _now_str(),
        "execution_state": "scheduled",
        "active": True,
        "remote_synced": not dry_run,
    }
    _save_once_override_entry(entry)
    return entry, "已设置一次性取消,任务执行后将自动恢复。"


def _execute_once_migrate_action(
    action: dict,
    schedule: dict,
    dry_run: bool = False,
    diagnostics: Optional[List[dict]] = None,
    diagnostic_id: str = "",
) -> Tuple[dict, str]:
    old_start = _parse_action_datetime(action.get("time_start"))
    old_end = _parse_action_datetime(action.get("time_end"))
    new_start = _parse_action_datetime(action.get("new_time_start"))
    new_end = _parse_action_datetime(action.get("new_time_end"))
    if not old_start or not old_end or not new_start or not new_end:
        raise HTTPException(status_code=400, detail="Missing migrate time range for once mode.")

    task_ids = _unique_list([str(item).strip() for item in action.get("task_ids", []) if str(item).strip()])
    task_map = {}
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        if task_id:
            task_map[task_id] = task
    source_tasks = [task_map[task_id] for task_id in task_ids if task_id in task_map]
    if not source_tasks:
        raise HTTPException(status_code=404, detail="No source tasks found for once migrate.")

    conflict_ids: List[str] = []
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        if not task_id or task_id in task_ids:
            continue
        if _task_matches_range(task, new_start, new_end, True):
            conflict_ids.append(task_id)
    conflict_ids = _unique_list(conflict_ids)

    media_map = _remote_media_map() if (_remote_enabled() and not dry_run) else {}
    terminal_map = _remote_terminal_map() if (_remote_enabled() and not dry_run) else {}

    commands: List[dict] = []
    shadow_task_ids: List[str] = []
    last_shadow_preview: dict = {}
    remote_diagnostics = diagnostics if diagnostics is not None else []
    current_diagnostic_id = str(diagnostic_id or _new_diagnostic_id())
    try:
        for idx, source_task in enumerate(source_tasks, start=1):
            source_dt = _task_start_datetime(source_task, old_start)
            shadow_start = new_start + (source_dt - old_start)
            shadow_task = _build_once_shadow_task(source_task, shadow_start)
            _attach_shadow_schedule_name(shadow_task, action.get("schedule_name") or schedule.get("schedule_name"))
            kind = _task_kind_for_once(source_task)
            last_shadow_preview = {
                "startdate": shadow_task.get("startdate"),
                "starttime": shadow_task.get("starttime"),
                "taskname": shadow_task.get("taskname"),
            }
            if _remote_enabled() and not dry_run and not _get_task_terminal_ids(shadow_task):
                rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                return _save_and_return_once_shadow_failure(
                    "migrate",
                    "挪动",
                    {
                        "schedule_name": action.get("schedule_name"),
                        "task_ids": task_ids,
                        "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    phase="create_shadow",
                    failure_reason=f"Shadow task missing terminal binding before remote sync via /task/taskterminal: {shadow_task.get('taskname') or 'shadow-task'}",
                    failure_code="terminal_missing",
                    commands=commands,
                    failed_payload=last_shadow_preview,
                    diagnostic_id=current_diagnostic_id,
                    remote_diagnostics=remote_diagnostics,
                    rollback_attempts=rollback_attempts,
                    shadow_diagnostic=None,
                )
            shadow_id = f"dryrun-shadow-{idx}"
            if _remote_enabled() and not dry_run:
                shadow_diagnostic = _new_remote_phase_diagnostic(
                    remote_diagnostics,
                    diagnostic_id=current_diagnostic_id,
                    action="migrate",
                    phase="create_shadow",
                    path="/task/taskinfo",
                    request_payload=None,
                )
                try:
                    created_id = _remote_add_taskinfo_with_diagnostic(
                        kind,
                        shadow_task,
                        media_map,
                        terminal_map,
                        diagnostic=shadow_diagnostic,
                    )
                except HTTPException as exc:
                    rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                    return _save_and_return_once_shadow_failure(
                        "migrate",
                        "挪动",
                        {
                            "schedule_name": action.get("schedule_name"),
                            "task_ids": task_ids,
                            "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        phase="create_shadow",
                        failure_reason=str(exc.detail),
                        failure_code=str((shadow_diagnostic or {}).get("failure_code") or "shadow_create_failed"),
                        commands=commands,
                        failed_payload=last_shadow_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=shadow_diagnostic,
                    )
                if not created_id:
                    rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                    failure_reason = str((shadow_diagnostic or {}).get("reason") or (shadow_diagnostic or {}).get("error_detail") or "Remote shadow task creation returned no taskid.")
                    return _save_and_return_once_shadow_failure(
                        "migrate",
                        "挪动",
                        {
                            "schedule_name": action.get("schedule_name"),
                            "task_ids": task_ids,
                            "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        phase="create_shadow",
                        failure_reason=failure_reason,
                        failure_code=str((shadow_diagnostic or {}).get("failure_code") or "taskinfo_lookup_not_found"),
                        commands=commands,
                        failed_payload=last_shadow_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=shadow_diagnostic,
                    )
                shadow_id = str(created_id)
            shadow_task_ids.append(str(shadow_id))
            _append_taskinfo_command(commands, "create_shadow", shadow_id, last_shadow_preview)

        _dispatch_enabletask_phase(
            commands,
            "disable_source",
            task_ids,
            1,
            old_start - timedelta(seconds=5),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="migrate",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore_source",
            task_ids,
            0,
            old_end,
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="migrate",
        )
        if conflict_ids:
            _dispatch_enabletask_phase(
                commands,
                "disable_conflict",
                conflict_ids,
                1,
                new_start - timedelta(seconds=5),
                dry_run=dry_run,
                diagnostics=remote_diagnostics,
                diagnostic_id=current_diagnostic_id,
                action_name="migrate",
            )
            _dispatch_enabletask_phase(
                commands,
                "restore_conflict",
                conflict_ids,
                0,
                new_end,
                dry_run=dry_run,
                diagnostics=remote_diagnostics,
                diagnostic_id=current_diagnostic_id,
                action_name="migrate",
            )
    except _RemoteBatchDispatchError as exc:
        rollback_attempts = _rollback_shadow_tasks(shadow_task_ids) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        if partial_applied:
            _save_failed_once_entry(
                "migrate",
                {
                    "schedule_name": action.get("schedule_name"),
                    "task_ids": task_ids,
                    "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "shadow_task_ids": shadow_task_ids,
                    "conflict_task_ids": conflict_ids,
                    "commands": commands,
                    "failure_reason": str(exc.detail),
                    "failed_phase": exc.phase or "enabletask",
                    "failed_payload": _clone_payload(exc.failed_payload),
                    "diagnostic_id": current_diagnostic_id,
                    "remote_diagnostics": _clone_payload(remote_diagnostics),
                    "rollback_attempts": rollback_attempts,
                    "remote_synced": False,
                },
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_dispatch_failure_message("挪动", str(exc.detail), partial_applied),
        ) from exc
    except HTTPException as exc:
        rollback_attempts = _rollback_shadow_tasks(shadow_task_ids) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        if partial_applied:
            _save_failed_once_entry(
                "migrate",
                {
                    "schedule_name": action.get("schedule_name"),
                    "task_ids": task_ids,
                    "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "shadow_task_ids": shadow_task_ids,
                    "conflict_task_ids": conflict_ids,
                    "commands": commands,
                    "failure_reason": str(exc.detail),
                    "failed_phase": "create_shadow",
                    "failed_payload": _clone_payload(last_shadow_preview),
                    "diagnostic_id": current_diagnostic_id,
                    "remote_diagnostics": _clone_payload(remote_diagnostics),
                    "rollback_attempts": rollback_attempts,
                    "remote_synced": False,
                },
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_shadow_failure_message("挪动", str(exc.detail), partial_applied),
        ) from exc

    entry = {
        "id": f"migrate-{int(datetime.now().timestamp())}",
        "action": "migrate",
        "mode": "once",
        "schedule_name": action.get("schedule_name"),
        "task_ids": task_ids,
        "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
        "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
        "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
        "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
        "shadow_task_ids": shadow_task_ids,
        "conflict_task_ids": conflict_ids,
        "commands": commands,
        "created_at": _now_str(),
        "execution_state": "scheduled",
        "active": True,
        "remote_synced": not dry_run,
    }
    _save_once_override_entry(entry)
    return entry, "已设置一次性挪动,原任务会在原时段静音并在目标时段播放临时任务。"


def _attach_time_window(anchor: Dict[str, Any]) -> Dict[str, Any]:
    """
    为 anchor 附加时间窗字段,便于后续按时段筛选任务。
    若仅识别出单个时间点,则将开始/结束都设为该时间点。
    """
    if not isinstance(anchor, dict):
        return anchor
    raw = str(anchor.get("raw") or "")
    if not raw:
        return anchor
    start_minutes, end_minutes = _extract_time_range_minutes(raw)
    if start_minutes is None:
        return anchor
    enriched = dict(anchor)
    enriched["time_start_minutes"] = int(start_minutes)
    enriched["time_end_minutes"] = int(end_minutes if end_minutes is not None else start_minutes)
    return enriched


def _anchor_start_minutes(anchor: Dict[str, Any]) -> Optional[int]:
    """
    获取 anchor 的起始分钟数,用于计算任务时间偏移量。
    优先使用已解析字段,其次回退到 raw 文本中提取。
    """
    if not isinstance(anchor, dict):
        return None

    start_value = anchor.get("time_start_minutes")
    if isinstance(start_value, (int, float)):
        return int(start_value)
    if isinstance(start_value, str):
        parsed = _parse_time_minutes(start_value)
        if parsed is not None:
            return parsed

    raw = str(anchor.get("raw") or "")
    if not raw:
        return None

    start_minutes, _ = _extract_time_range_minutes(raw)
    if start_minutes is not None:
        return int(start_minutes)

    # 回退：匹配单点时间（如 8点 / 08:30 / 下午3点）。
    match = re.search(r"([01]?\d|2[0-3])\s*(?:[:：点时])\s*([0-5]?\d)?", raw)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if any(marker in raw for marker in ("下午", "晚上", "傍晚", "晚间", "午后")) and hour < 12:
        hour += 12
    if "凌晨" in raw and hour == 12:
        hour = 0
    return hour * 60 + minute


def _shift_weekdays_by_delta(weekdays: List[str], day_delta: int) -> List[str]:
    """按天数偏移星期列表,保持去重和周一到周日顺序。"""
    return _rotate_weekdays([str(day) for day in weekdays if day], day_delta)

def _execute_once_swap_action(
    action: dict,
    schedule: dict,
    dry_run: bool = False,
    diagnostics: Optional[List[dict]] = None,
    diagnostic_id: str = "",
) -> Tuple[dict, str]:
    a_start = _parse_action_datetime(action.get("source_time_start"))
    a_end = _parse_action_datetime(action.get("source_time_end"))
    b_start = _parse_action_datetime(action.get("target_time_start"))
    b_end = _parse_action_datetime(action.get("target_time_end"))
    if not a_start or not a_end or not b_start or not b_end:
        raise HTTPException(status_code=400, detail="Missing swap time range for once mode.")

    source_ids = _unique_list([str(item).strip() for item in action.get("source_task_ids", []) if str(item).strip()])
    target_ids = _unique_list([str(item).strip() for item in action.get("target_task_ids", []) if str(item).strip()])
    task_map = {}
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        if task_id:
            task_map[task_id] = task
    source_tasks = [task_map[task_id] for task_id in source_ids if task_id in task_map]
    target_tasks = [task_map[task_id] for task_id in target_ids if task_id in task_map]
    if not source_tasks or not target_tasks:
        raise HTTPException(status_code=404, detail="No source/target tasks found for once swap.")

    media_map = _remote_media_map() if (_remote_enabled() and not dry_run) else {}
    terminal_map = _remote_terminal_map() if (_remote_enabled() and not dry_run) else {}

    commands: List[dict] = []
    shadow_task_ids: List[str] = []
    last_shadow_preview: dict = {}
    remote_diagnostics = diagnostics if diagnostics is not None else []
    current_diagnostic_id = str(diagnostic_id or _new_diagnostic_id())
    try:
        index = 1
        for source_task in source_tasks:
            source_dt = _task_start_datetime(source_task, a_start)
            shadow_start = b_start + (source_dt - a_start)
            shadow_task = _build_once_shadow_task(source_task, shadow_start)
            _attach_shadow_schedule_name(shadow_task, action.get("schedule_name") or schedule.get("schedule_name"))
            kind = _task_kind_for_once(source_task)
            last_shadow_preview = {
                "startdate": shadow_task.get("startdate"),
                "starttime": shadow_task.get("starttime"),
                "taskname": shadow_task.get("taskname"),
            }
            if _remote_enabled() and not dry_run and not _get_task_terminal_ids(shadow_task):
                rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                return _save_and_return_once_shadow_failure(
                    "swap",
                    "对调",
                    {
                        "schedule_name": action.get("schedule_name"),
                        "source_task_ids": source_ids,
                        "target_task_ids": target_ids,
                        "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    phase="create_shadow_from_source",
                    failure_reason=f"Shadow task missing terminal binding before remote sync via /task/taskterminal: {shadow_task.get('taskname') or 'shadow-task'}",
                    failure_code="terminal_missing",
                    commands=commands,
                    failed_payload=last_shadow_preview,
                    diagnostic_id=current_diagnostic_id,
                    remote_diagnostics=remote_diagnostics,
                    rollback_attempts=rollback_attempts,
                )
            shadow_id = f"dryrun-shadow-{index}"
            if _remote_enabled() and not dry_run:
                shadow_diagnostic = _new_remote_phase_diagnostic(
                    remote_diagnostics,
                    diagnostic_id=current_diagnostic_id,
                    action="swap",
                    phase="create_shadow_from_source",
                    path="/task/taskinfo",
                    request_payload=None,
                )
                try:
                    created_id = _remote_add_taskinfo_with_diagnostic(
                        kind,
                        shadow_task,
                        media_map,
                        terminal_map,
                        diagnostic=shadow_diagnostic,
                    )
                except HTTPException as exc:
                    rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                    return _save_and_return_once_shadow_failure(
                        "swap",
                        "对调",
                        {
                            "schedule_name": action.get("schedule_name"),
                            "source_task_ids": source_ids,
                            "target_task_ids": target_ids,
                            "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        phase="create_shadow_from_source",
                        failure_reason=str(exc.detail),
                        failure_code=str((shadow_diagnostic or {}).get("failure_code") or "shadow_create_failed"),
                        commands=commands,
                        failed_payload=last_shadow_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=shadow_diagnostic,
                    )
                if not created_id:
                    rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                    failure_reason = str((shadow_diagnostic or {}).get("reason") or (shadow_diagnostic or {}).get("error_detail") or "Remote shadow task creation returned no taskid.")
                    return _save_and_return_once_shadow_failure(
                        "swap",
                        "对调",
                        {
                            "schedule_name": action.get("schedule_name"),
                            "source_task_ids": source_ids,
                            "target_task_ids": target_ids,
                            "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        phase="create_shadow_from_source",
                        failure_reason=failure_reason,
                        failure_code=str((shadow_diagnostic or {}).get("failure_code") or "taskinfo_lookup_not_found"),
                        commands=commands,
                        failed_payload=last_shadow_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=shadow_diagnostic,
                    )
                shadow_id = str(created_id)
            shadow_task_ids.append(str(shadow_id))
            _append_taskinfo_command(commands, "create_shadow_from_source", shadow_id, last_shadow_preview)
            index += 1

        for target_task in target_tasks:
            target_dt = _task_start_datetime(target_task, b_start)
            shadow_start = a_start + (target_dt - b_start)
            shadow_task = _build_once_shadow_task(target_task, shadow_start)
            _attach_shadow_schedule_name(shadow_task, action.get("schedule_name") or schedule.get("schedule_name"))
            kind = _task_kind_for_once(target_task)
            last_shadow_preview = {
                "startdate": shadow_task.get("startdate"),
                "starttime": shadow_task.get("starttime"),
                "taskname": shadow_task.get("taskname"),
            }
            if _remote_enabled() and not dry_run and not _get_task_terminal_ids(shadow_task):
                rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                return _save_and_return_once_shadow_failure(
                    "swap",
                    "对调",
                    {
                        "schedule_name": action.get("schedule_name"),
                        "source_task_ids": source_ids,
                        "target_task_ids": target_ids,
                        "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    phase="create_shadow_from_target",
                    failure_reason=f"Shadow task missing terminal binding before remote sync via /task/taskterminal: {shadow_task.get('taskname') or 'shadow-task'}",
                    failure_code="terminal_missing",
                    commands=commands,
                    failed_payload=last_shadow_preview,
                    diagnostic_id=current_diagnostic_id,
                    remote_diagnostics=remote_diagnostics,
                    rollback_attempts=rollback_attempts,
                )
            shadow_id = f"dryrun-shadow-{index}"
            if _remote_enabled() and not dry_run:
                shadow_diagnostic = _new_remote_phase_diagnostic(
                    remote_diagnostics,
                    diagnostic_id=current_diagnostic_id,
                    action="swap",
                    phase="create_shadow_from_target",
                    path="/task/taskinfo",
                    request_payload=None,
                )
                try:
                    created_id = _remote_add_taskinfo_with_diagnostic(
                        kind,
                        shadow_task,
                        media_map,
                        terminal_map,
                        diagnostic=shadow_diagnostic,
                    )
                except HTTPException as exc:
                    rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                    return _save_and_return_once_shadow_failure(
                        "swap",
                        "对调",
                        {
                            "schedule_name": action.get("schedule_name"),
                            "source_task_ids": source_ids,
                            "target_task_ids": target_ids,
                            "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        phase="create_shadow_from_target",
                        failure_reason=str(exc.detail),
                        failure_code=str((shadow_diagnostic or {}).get("failure_code") or "shadow_create_failed"),
                        commands=commands,
                        failed_payload=last_shadow_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=shadow_diagnostic,
                    )
                if not created_id:
                    rollback_attempts = _rollback_shadow_tasks(shadow_task_ids, commands) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
                    failure_reason = str((shadow_diagnostic or {}).get("reason") or (shadow_diagnostic or {}).get("error_detail") or "Remote shadow task creation returned no taskid.")
                    return _save_and_return_once_shadow_failure(
                        "swap",
                        "对调",
                        {
                            "schedule_name": action.get("schedule_name"),
                            "source_task_ids": source_ids,
                            "target_task_ids": target_ids,
                            "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        phase="create_shadow_from_target",
                        failure_reason=failure_reason,
                        failure_code=str((shadow_diagnostic or {}).get("failure_code") or "taskinfo_lookup_not_found"),
                        commands=commands,
                        failed_payload=last_shadow_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=shadow_diagnostic,
                    )
                shadow_id = str(created_id)
            shadow_task_ids.append(str(shadow_id))
            _append_taskinfo_command(commands, "create_shadow_from_target", shadow_id, last_shadow_preview)
            index += 1

        _dispatch_enabletask_phase(
            commands,
            "disable_source",
            source_ids,
            1,
            a_start - timedelta(seconds=5),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore_source",
            source_ids,
            0,
            a_end,
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        _dispatch_enabletask_phase(
            commands,
            "disable_target",
            target_ids,
            1,
            b_start - timedelta(seconds=5),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore_target",
            target_ids,
            0,
            b_end,
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
    except _RemoteBatchDispatchError as exc:
        rollback_attempts = _rollback_shadow_tasks(shadow_task_ids) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        if partial_applied:
            _save_failed_once_entry(
                "swap",
                {
                    "schedule_name": action.get("schedule_name"),
                    "source_task_ids": source_ids,
                    "target_task_ids": target_ids,
                    "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "shadow_task_ids": shadow_task_ids,
                    "commands": commands,
                    "failure_reason": str(exc.detail),
                    "failed_phase": exc.phase or "enabletask",
                    "failed_payload": _clone_payload(exc.failed_payload),
                    "diagnostic_id": current_diagnostic_id,
                    "remote_diagnostics": _clone_payload(remote_diagnostics),
                    "rollback_attempts": rollback_attempts,
                    "remote_synced": False,
                },
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_dispatch_failure_message("对调", str(exc.detail), partial_applied),
        ) from exc
    except HTTPException as exc:
        rollback_attempts = _rollback_shadow_tasks(shadow_task_ids) if (_remote_enabled() and not dry_run and shadow_task_ids) else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        if partial_applied:
            _save_failed_once_entry(
                "swap",
                {
                    "schedule_name": action.get("schedule_name"),
                    "source_task_ids": source_ids,
                    "target_task_ids": target_ids,
                    "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "shadow_task_ids": shadow_task_ids,
                    "commands": commands,
                    "failure_reason": str(exc.detail),
                    "failed_phase": "create_shadow",
                    "failed_payload": _clone_payload(last_shadow_preview),
                    "diagnostic_id": current_diagnostic_id,
                    "remote_diagnostics": _clone_payload(remote_diagnostics),
                    "rollback_attempts": rollback_attempts,
                    "remote_synced": False,
                },
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_shadow_failure_message("对调", str(exc.detail), partial_applied),
        ) from exc

    entry = {
        "id": f"swap-{int(datetime.now().timestamp())}",
        "action": "swap",
        "mode": "once",
        "schedule_name": action.get("schedule_name"),
        "source_task_ids": source_ids,
        "target_task_ids": target_ids,
        "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
        "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
        "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
        "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
        "shadow_task_ids": shadow_task_ids,
        "commands": commands,
        "created_at": _now_str(),
        "execution_state": "scheduled",
        "active": True,
        "remote_synced": not dry_run,
    }
    _save_once_override_entry(entry)
    return entry, "已设置一次性对调,两边任务会在对应时段互换播放。"


def _collect_enabletask_phase_payloads(commands: List[dict], phase: str) -> List[dict]:
    payloads: List[dict] = []
    for command in commands or []:
        if not isinstance(command, dict):
            continue
        if str(command.get("type") or "") != "enabletask":
            continue
        if str(command.get("phase") or "") != str(phase or ""):
            continue
        payload = _clone_payload(command.get("payload"))
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _build_once_task_spec(
    *,
    schedule_name: str,
    once_schedule_name: str,
    source_task: dict,
    once_task: dict,
    once_task_id: str,
    role: str,
    once_action: str,
) -> dict:
    display_name = str(
        source_task.get("customName")
        or source_task.get("taskname")
        or source_task.get("name")
        or once_task.get("taskname")
        or "once-task"
    ).strip() or "once-task"
    once_date = str(once_task.get("startdate") or "").strip()
    media_name = str(
        source_task.get("audio")
        or source_task.get("medianame")
        or once_task.get("medianame")
        or ""
    ).strip()
    terminal_snapshot = _schedule_task_terminal_binding_snapshot(once_task)
    if not terminal_snapshot:
        terminal_snapshot = _schedule_task_terminal_binding_snapshot(source_task) or {}
    timing_task = _clone_payload(source_task) if isinstance(source_task, dict) else {}
    if isinstance(once_task, dict):
        for key in ("timelength", "timelengthtype", "volume", "mediaid"):
            value = once_task.get(key)
            if value not in (None, ""):
                timing_task[key] = value
    return {
        "taskid": str(once_task_id or ""),
        "taskname": display_name,
        "remote_taskname": str(once_task.get("taskname") or "").strip(),
        "schedule_name": str(schedule_name or "").strip(),
        "once_schedule_name": str(once_schedule_name or "").strip(),
        "startdate": once_date,
        "starttime": str(once_task.get("starttime") or "").strip(),
        "source_task_id": _task_id(source_task),
        "source_task_name": str(source_task.get("taskname") or source_task.get("name") or "").strip(),
        "role": str(role or ""),
        "once_action": str(once_action or ""),
        "once_date": once_date,
        "duration_seconds": _task_duration_seconds(timing_task),
        "mediaid": str(once_task.get("mediaid") or source_task.get("mediaid") or "").strip(),
        "medianame": media_name,
        "volume": _coerce_int(
            once_task.get("volume") if once_task.get("volume") not in (None, "") else source_task.get("volume"),
            0,
        ),
        "timelength": str(once_task.get("timelength") or source_task.get("timelength") or "").strip(),
        "timelengthtype": str(once_task.get("timelengthtype") or source_task.get("timelengthtype") or "").strip(),
        "terminalids": _normalize_terminal_ids(terminal_snapshot.get("terminalids")),
        "terminalnames": _normalize_str_list(terminal_snapshot.get("terminalnames")),
        "liveterminalid": str(terminal_snapshot.get("liveterminalid") or "").strip(),
        "liveterminalname": str(terminal_snapshot.get("liveterminalname") or "").strip(),
        "location": _clone_payload(terminal_snapshot.get("location")) if isinstance(terminal_snapshot.get("location"), list) else [],
    }


def _execute_once_migrate_action(
    action: dict,
    schedule: dict,
    dry_run: bool = False,
    diagnostics: Optional[List[dict]] = None,
    diagnostic_id: str = "",
) -> Tuple[dict, str]:
    old_start = _parse_action_datetime(action.get("time_start"))
    old_end = _parse_action_datetime(action.get("time_end"))
    new_start = _parse_action_datetime(action.get("new_time_start"))
    new_end = _parse_action_datetime(action.get("new_time_end"))
    if not old_start or not old_end or not new_start or not new_end:
        raise HTTPException(status_code=400, detail="Missing migrate time range for once mode.")

    schedule_name = str(action.get("schedule_name") or schedule.get("schedule_name") or "").strip()
    once_schedule_name = _once_remote_schedule_name(schedule_name, "migrate")
    task_ids = _unique_list([str(item).strip() for item in action.get("task_ids", []) if str(item).strip()])
    task_map = {}
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        if task_id:
            task_map[task_id] = task
    source_tasks = [task_map[task_id] for task_id in task_ids if task_id in task_map]
    if not source_tasks:
        raise HTTPException(status_code=404, detail="No source tasks found for once migrate.")

    conflict_ids: List[str] = []
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        if not task_id or task_id in task_ids:
            continue
        if _task_matches_range(task, new_start, new_end, True):
            conflict_ids.append(task_id)
    conflict_ids = _unique_list(conflict_ids)

    remote_sync_enabled = bool(_remote_enabled() and not dry_run)
    media_map = _remote_media_map() if remote_sync_enabled else {}
    terminal_map = _remote_terminal_map() if remote_sync_enabled else {}

    commands: List[dict] = []
    once_task_ids: List[str] = []
    once_task_specs: List[dict] = []
    remote_diagnostics = diagnostics if diagnostics is not None else []
    current_diagnostic_id = str(diagnostic_id or _new_diagnostic_id())
    enable_once_commands: List[dict] = []
    last_once_preview: dict = {}

    base_fields = {
        "schedule_name": schedule_name,
        "once_schedule_name": once_schedule_name,
        "task_ids": task_ids,
        "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
        "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
        "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
        "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
        "conflict_task_ids": conflict_ids,
        "once_task_ids": once_task_ids,
        "shadow_task_ids": once_task_ids,
        "once_task_specs": once_task_specs,
        "enable_once_commands": enable_once_commands,
        "cleanup_state": "pending",
        "cleanup_attempts": [],
        "cleaned_at": "",
        "cleaned_task_ids": [],
    }

    try:
        if remote_sync_enabled and once_schedule_name:
            _remote_ensure_schedule(once_schedule_name)
        for idx, source_task in enumerate(source_tasks, start=1):
            source_dt = _task_start_datetime(source_task, old_start)
            once_start = new_start + (source_dt - old_start)
            once_task = _build_once_schedule_task(source_task, once_start)
            once_remote_task_name = _format_once_remote_task_name(
                source_task,
                once_start,
                once_action="migrate",
            )
            once_task["taskname"] = once_remote_task_name
            once_task["name"] = once_remote_task_name
            once_task["customName"] = once_remote_task_name
            _attach_shadow_schedule_name(once_task, once_schedule_name or schedule_name)
            last_once_preview = {
                "taskname": once_task.get("taskname"),
                "startdate": once_task.get("startdate"),
                "starttime": once_task.get("starttime"),
                "tasktype": once_task.get("tasktype"),
                "execmode": once_task.get("execmode"),
                "projectstate": once_task.get("projectstate"),
            }
            if remote_sync_enabled and not _get_task_terminal_ids(once_task):
                rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if once_task_ids else []
                _cleanup_empty_once_remote_schedule(once_schedule_name)
                return _save_and_return_once_shadow_failure(
                    "migrate",
                    "挪动",
                    dict(base_fields),
                    phase="create_once_task",
                    failure_reason=f"Once schedule task missing terminal binding before remote sync: {once_task.get('taskname') or 'once-task'}",
                    failure_code="terminal_missing",
                    commands=commands,
                    failed_payload=last_once_preview,
                    diagnostic_id=current_diagnostic_id,
                    remote_diagnostics=remote_diagnostics,
                    rollback_attempts=rollback_attempts,
                    shadow_diagnostic=None,
                )
            once_task_id = f"dryrun-once-{idx}"
            if remote_sync_enabled:
                try:
                    once_task_id = str(_remote_add_task(once_schedule_name or schedule_name, once_task, media_map, terminal_map))
                except HTTPException as exc:
                    rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if once_task_ids else []
                    _cleanup_empty_once_remote_schedule(once_schedule_name)
                    return _save_and_return_once_shadow_failure(
                        "migrate",
                        "挪动",
                        dict(base_fields),
                        phase="create_once_task",
                        failure_reason=str(exc.detail),
                        failure_code="once_task_create_failed",
                        commands=commands,
                        failed_payload=last_once_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=None,
                    )
            once_task_ids.append(str(once_task_id))
            once_task_specs.append(
                _build_once_task_spec(
                    schedule_name=schedule_name,
                    once_schedule_name=once_schedule_name,
                    source_task=source_task,
                    once_task=once_task,
                    once_task_id=str(once_task_id),
                    role="migrate_target",
                    once_action="migrate",
                )
            )
            _append_sechetask_command(commands, "create_once_task", str(once_task_id), last_once_preview)

        _dispatch_enabletask_phase(
            commands,
            "enable_once",
            once_task_ids,
            0,
            new_start - timedelta(seconds=10),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="migrate",
        )
        enable_once_commands[:] = _collect_enabletask_phase_payloads(commands, "enable_once")

        _dispatch_enabletask_phase(
            commands,
            "disable_source",
            task_ids,
            1,
            old_start - timedelta(seconds=5),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="migrate",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore_source",
            task_ids,
            0,
            old_end,
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="migrate",
        )
        if conflict_ids:
            _dispatch_enabletask_phase(
                commands,
                "disable_conflict",
                conflict_ids,
                1,
                new_start - timedelta(seconds=5),
                dry_run=dry_run,
                diagnostics=remote_diagnostics,
                diagnostic_id=current_diagnostic_id,
                action_name="migrate",
            )
            _dispatch_enabletask_phase(
                commands,
                "restore_conflict",
                conflict_ids,
                0,
                new_end,
                dry_run=dry_run,
                diagnostics=remote_diagnostics,
                diagnostic_id=current_diagnostic_id,
                action_name="migrate",
            )
    except _RemoteBatchDispatchError as exc:
        rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if remote_sync_enabled and once_task_ids else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        _cleanup_empty_once_remote_schedule(once_schedule_name)
        _save_failed_once_entry(
            "migrate",
            {
                **dict(base_fields),
                "commands": commands,
                "failure_reason": str(exc.detail),
                "failed_phase": exc.phase or "enabletask",
                "failed_payload": _clone_payload(exc.failed_payload),
                "diagnostic_id": current_diagnostic_id,
                "remote_diagnostics": _clone_payload(remote_diagnostics),
                "rollback_attempts": rollback_attempts,
                "remote_synced": False,
            },
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_dispatch_failure_message("挪动", str(exc.detail), partial_applied),
        ) from exc
    except HTTPException as exc:
        rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if remote_sync_enabled and once_task_ids else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        _cleanup_empty_once_remote_schedule(once_schedule_name)
        _save_failed_once_entry(
            "migrate",
            {
                **dict(base_fields),
                "commands": commands,
                "failure_reason": str(exc.detail),
                "failed_phase": "create_once_task",
                "failed_payload": _clone_payload(last_once_preview),
                "diagnostic_id": current_diagnostic_id,
                "remote_diagnostics": _clone_payload(remote_diagnostics),
                "rollback_attempts": rollback_attempts,
                "remote_synced": False,
            },
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_shadow_failure_message("挪动", str(exc.detail), partial_applied),
        ) from exc

    entry = {
        "id": f"migrate-{int(datetime.now().timestamp())}",
        "action": "migrate",
        "mode": "once",
        "schedule_name": schedule_name,
        "once_schedule_name": once_schedule_name,
        "task_ids": task_ids,
        "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
        "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
        "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
        "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
        "conflict_task_ids": conflict_ids,
        "once_task_ids": once_task_ids,
        "shadow_task_ids": list(once_task_ids),
        "once_task_specs": once_task_specs,
        "enable_once_commands": enable_once_commands,
        "commands": commands,
        "created_at": _now_str(),
        "execution_state": "scheduled",
        "active": True,
        "remote_synced": remote_sync_enabled,
        "cleanup_state": "pending",
        "cleanup_attempts": [],
        "cleaned_at": "",
        "cleaned_task_ids": [],
    }
    _save_once_override_entry(entry)
    return entry, "已设置一次性挪动。目标时段会启用临时作息任务，夜间统一清理。"


def _execute_once_swap_action(
    action: dict,
    schedule: dict,
    dry_run: bool = False,
    diagnostics: Optional[List[dict]] = None,
    diagnostic_id: str = "",
) -> Tuple[dict, str]:
    a_start = _parse_action_datetime(action.get("source_time_start"))
    a_end = _parse_action_datetime(action.get("source_time_end"))
    b_start = _parse_action_datetime(action.get("target_time_start"))
    b_end = _parse_action_datetime(action.get("target_time_end"))
    if not a_start or not a_end or not b_start or not b_end:
        raise HTTPException(status_code=400, detail="Missing swap time range for once mode.")

    schedule_name = str(action.get("schedule_name") or schedule.get("schedule_name") or "").strip()
    once_schedule_name = _once_remote_schedule_name(schedule_name, "swap")
    source_ids = _unique_list([str(item).strip() for item in action.get("source_task_ids", []) if str(item).strip()])
    target_ids = _unique_list([str(item).strip() for item in action.get("target_task_ids", []) if str(item).strip()])
    task_map = {}
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        if task_id:
            task_map[task_id] = task
    source_tasks = [task_map[task_id] for task_id in source_ids if task_id in task_map]
    target_tasks = [task_map[task_id] for task_id in target_ids if task_id in task_map]
    if not source_tasks or not target_tasks:
        raise HTTPException(status_code=404, detail="No source/target tasks found for once swap.")

    remote_sync_enabled = bool(_remote_enabled() and not dry_run)
    media_map = _remote_media_map() if remote_sync_enabled else {}
    terminal_map = _remote_terminal_map() if remote_sync_enabled else {}

    commands: List[dict] = []
    once_task_ids: List[str] = []
    source_once_ids: List[str] = []
    target_once_ids: List[str] = []
    once_task_specs: List[dict] = []
    remote_diagnostics = diagnostics if diagnostics is not None else []
    current_diagnostic_id = str(diagnostic_id or _new_diagnostic_id())
    enable_once_commands: List[dict] = []
    last_once_preview: dict = {}

    base_fields = {
        "schedule_name": schedule_name,
        "once_schedule_name": once_schedule_name,
        "source_task_ids": source_ids,
        "target_task_ids": target_ids,
        "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
        "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
        "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
        "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
        "once_task_ids": once_task_ids,
        "shadow_task_ids": once_task_ids,
        "source_once_task_ids": source_once_ids,
        "target_once_task_ids": target_once_ids,
        "once_task_specs": once_task_specs,
        "enable_once_commands": enable_once_commands,
        "cleanup_state": "pending",
        "cleanup_attempts": [],
        "cleaned_at": "",
        "cleaned_task_ids": [],
    }

    try:
        if remote_sync_enabled and once_schedule_name:
            _remote_ensure_schedule(once_schedule_name)
        index = 1
        for source_task in source_tasks:
            source_dt = _task_start_datetime(source_task, a_start)
            once_start = b_start + (source_dt - a_start)
            once_task = _build_once_schedule_task(source_task, once_start)
            once_remote_task_name = _format_once_remote_task_name(
                source_task,
                once_start,
                once_action="swap",
            )
            once_task["taskname"] = once_remote_task_name
            once_task["name"] = once_remote_task_name
            once_task["customName"] = once_remote_task_name
            _attach_shadow_schedule_name(once_task, once_schedule_name or schedule_name)
            last_once_preview = {
                "taskname": once_task.get("taskname"),
                "startdate": once_task.get("startdate"),
                "starttime": once_task.get("starttime"),
                "tasktype": once_task.get("tasktype"),
                "execmode": once_task.get("execmode"),
                "projectstate": once_task.get("projectstate"),
            }
            if remote_sync_enabled and not _get_task_terminal_ids(once_task):
                rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if once_task_ids else []
                _cleanup_empty_once_remote_schedule(once_schedule_name)
                return _save_and_return_once_shadow_failure(
                    "swap",
                    "对调",
                    dict(base_fields),
                    phase="create_once_task_from_source",
                    failure_reason=f"Once schedule task missing terminal binding before remote sync: {once_task.get('taskname') or 'once-task'}",
                    failure_code="terminal_missing",
                    commands=commands,
                    failed_payload=last_once_preview,
                    diagnostic_id=current_diagnostic_id,
                    remote_diagnostics=remote_diagnostics,
                    rollback_attempts=rollback_attempts,
                    shadow_diagnostic=None,
                )
            once_task_id = f"dryrun-once-{index}"
            if remote_sync_enabled:
                try:
                    once_task_id = str(_remote_add_task(once_schedule_name or schedule_name, once_task, media_map, terminal_map))
                except HTTPException as exc:
                    rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if once_task_ids else []
                    _cleanup_empty_once_remote_schedule(once_schedule_name)
                    return _save_and_return_once_shadow_failure(
                        "swap",
                        "对调",
                        dict(base_fields),
                        phase="create_once_task_from_source",
                        failure_reason=str(exc.detail),
                        failure_code="once_task_create_failed",
                        commands=commands,
                        failed_payload=last_once_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=None,
                    )
            once_task_ids.append(str(once_task_id))
            source_once_ids.append(str(once_task_id))
            once_task_specs.append(
                _build_once_task_spec(
                    schedule_name=schedule_name,
                    once_schedule_name=once_schedule_name,
                    source_task=source_task,
                    once_task=once_task,
                    once_task_id=str(once_task_id),
                    role="source_to_target",
                    once_action="swap",
                )
            )
            _append_sechetask_command(commands, "create_once_task_from_source", str(once_task_id), last_once_preview)
            index += 1

        for target_task in target_tasks:
            target_dt = _task_start_datetime(target_task, b_start)
            once_start = a_start + (target_dt - b_start)
            once_task = _build_once_schedule_task(target_task, once_start)
            once_remote_task_name = _format_once_remote_task_name(
                target_task,
                once_start,
                once_action="swap",
            )
            once_task["taskname"] = once_remote_task_name
            once_task["name"] = once_remote_task_name
            once_task["customName"] = once_remote_task_name
            _attach_shadow_schedule_name(once_task, once_schedule_name or schedule_name)
            last_once_preview = {
                "taskname": once_task.get("taskname"),
                "startdate": once_task.get("startdate"),
                "starttime": once_task.get("starttime"),
                "tasktype": once_task.get("tasktype"),
                "execmode": once_task.get("execmode"),
                "projectstate": once_task.get("projectstate"),
            }
            if remote_sync_enabled and not _get_task_terminal_ids(once_task):
                rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if once_task_ids else []
                _cleanup_empty_once_remote_schedule(once_schedule_name)
                return _save_and_return_once_shadow_failure(
                    "swap",
                    "对调",
                    dict(base_fields),
                    phase="create_once_task_from_target",
                    failure_reason=f"Once schedule task missing terminal binding before remote sync: {once_task.get('taskname') or 'once-task'}",
                    failure_code="terminal_missing",
                    commands=commands,
                    failed_payload=last_once_preview,
                    diagnostic_id=current_diagnostic_id,
                    remote_diagnostics=remote_diagnostics,
                    rollback_attempts=rollback_attempts,
                    shadow_diagnostic=None,
                )
            once_task_id = f"dryrun-once-{index}"
            if remote_sync_enabled:
                try:
                    once_task_id = str(_remote_add_task(once_schedule_name or schedule_name, once_task, media_map, terminal_map))
                except HTTPException as exc:
                    rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if once_task_ids else []
                    _cleanup_empty_once_remote_schedule(once_schedule_name)
                    return _save_and_return_once_shadow_failure(
                        "swap",
                        "对调",
                        dict(base_fields),
                        phase="create_once_task_from_target",
                        failure_reason=str(exc.detail),
                        failure_code="once_task_create_failed",
                        commands=commands,
                        failed_payload=last_once_preview,
                        diagnostic_id=current_diagnostic_id,
                        remote_diagnostics=remote_diagnostics,
                        rollback_attempts=rollback_attempts,
                        shadow_diagnostic=None,
                    )
            once_task_ids.append(str(once_task_id))
            target_once_ids.append(str(once_task_id))
            once_task_specs.append(
                _build_once_task_spec(
                    schedule_name=schedule_name,
                    once_schedule_name=once_schedule_name,
                    source_task=target_task,
                    once_task=once_task,
                    once_task_id=str(once_task_id),
                    role="target_to_source",
                    once_action="swap",
                )
            )
            _append_sechetask_command(commands, "create_once_task_from_target", str(once_task_id), last_once_preview)
            index += 1

        _dispatch_enabletask_phase(
            commands,
            "enable_once_source_to_target",
            source_once_ids,
            0,
            b_start - timedelta(seconds=10),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        _dispatch_enabletask_phase(
            commands,
            "enable_once_target_to_source",
            target_once_ids,
            0,
            a_start - timedelta(seconds=10),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        enable_once_commands[:] = [
            *_collect_enabletask_phase_payloads(commands, "enable_once_source_to_target"),
            *_collect_enabletask_phase_payloads(commands, "enable_once_target_to_source"),
        ]

        _dispatch_enabletask_phase(
            commands,
            "disable_source",
            source_ids,
            1,
            a_start - timedelta(seconds=5),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore_source",
            source_ids,
            0,
            a_end,
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        _dispatch_enabletask_phase(
            commands,
            "disable_target",
            target_ids,
            1,
            b_start - timedelta(seconds=5),
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
        _dispatch_enabletask_phase(
            commands,
            "restore_target",
            target_ids,
            0,
            b_end,
            dry_run=dry_run,
            diagnostics=remote_diagnostics,
            diagnostic_id=current_diagnostic_id,
            action_name="swap",
        )
    except _RemoteBatchDispatchError as exc:
        rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if remote_sync_enabled and once_task_ids else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        _cleanup_empty_once_remote_schedule(once_schedule_name)
        _save_failed_once_entry(
            "swap",
            {
                **dict(base_fields),
                "commands": commands,
                "failure_reason": str(exc.detail),
                "failed_phase": exc.phase or "enabletask",
                "failed_payload": _clone_payload(exc.failed_payload),
                "diagnostic_id": current_diagnostic_id,
                "remote_diagnostics": _clone_payload(remote_diagnostics),
                "rollback_attempts": rollback_attempts,
                "remote_synced": False,
            },
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_dispatch_failure_message("对调", str(exc.detail), partial_applied),
        ) from exc
    except HTTPException as exc:
        rollback_attempts = _rollback_once_schedule_tasks(once_task_ids, commands) if remote_sync_enabled and once_task_ids else []
        partial_applied = bool(commands) or bool(rollback_attempts)
        _cleanup_empty_once_remote_schedule(once_schedule_name)
        _save_failed_once_entry(
            "swap",
            {
                **dict(base_fields),
                "commands": commands,
                "failure_reason": str(exc.detail),
                "failed_phase": "create_once_task",
                "failed_payload": _clone_payload(last_once_preview),
                "diagnostic_id": current_diagnostic_id,
                "remote_diagnostics": _clone_payload(remote_diagnostics),
                "rollback_attempts": rollback_attempts,
                "remote_synced": False,
            },
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail=_once_shadow_failure_message("对调", str(exc.detail), partial_applied),
        ) from exc

    entry = {
        "id": f"swap-{int(datetime.now().timestamp())}",
        "action": "swap",
        "mode": "once",
        "schedule_name": schedule_name,
        "once_schedule_name": once_schedule_name,
        "source_task_ids": source_ids,
        "target_task_ids": target_ids,
        "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
        "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
        "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
        "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
        "once_task_ids": once_task_ids,
        "shadow_task_ids": list(once_task_ids),
        "source_once_task_ids": source_once_ids,
        "target_once_task_ids": target_once_ids,
        "once_task_specs": once_task_specs,
        "enable_once_commands": enable_once_commands,
        "commands": commands,
        "created_at": _now_str(),
        "execution_state": "scheduled",
        "active": True,
        "remote_synced": remote_sync_enabled,
        "cleanup_state": "pending",
        "cleanup_attempts": [],
        "cleaned_at": "",
        "cleaned_task_ids": [],
    }
    _save_once_override_entry(entry)
    return entry, "已设置一次性对调。两侧会在目标时段启用临时作息任务，夜间统一清理。"


def _slot_text(slots: dict, *keys: str) -> str:
    for key in keys:
        value = slots.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, list):
            values = _split_slot_values(value)
            text = "、".join(values).strip()
            if text:
                return text
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _slot_values(slots: dict, *keys: str) -> List[str]:
    if not isinstance(slots, dict):
        return []
    for key in keys:
        if key not in slots:
            continue
        values = _split_slot_values(slots.get(key))
        if values:
            return values
    return []


def _task_slot_id(slots: dict) -> str:
    return _slot_text(slots, "task_id", "TASK_ID")


def _pending_choice_key(choice: dict) -> str:
    if not isinstance(choice, dict):
        return ""
    return "|".join(
        [
            str(choice.get("value") or "").strip(),
            str(choice.get("label") or "").strip(),
            json.dumps(choice.get("slot_updates") or {}, ensure_ascii=False, sort_keys=True),
        ]
    )


def _pending_choice_aliases(choice: dict) -> List[str]:
    if not isinstance(choice, dict):
        return []
    aliases = _split_slot_values(choice.get("aliases"))
    for key in ("value", "label"):
        value = str(choice.get(key) or "").strip()
        if value:
            aliases.append(value)
    return _unique_list([alias for alias in aliases if alias])


def _candidate_choice(
    *,
    value: str,
    label: str,
    slot_updates: Optional[dict] = None,
    aliases: Optional[List[str]] = None,
    description: str = "",
    meta: Optional[dict] = None,
) -> dict:
    return {
        "value": str(value or "").strip(),
        "label": str(label or value or "").strip(),
        "slot_updates": _clone_payload(slot_updates or {}),
        "aliases": _unique_list([str(item).strip() for item in (aliases or []) if str(item).strip()]),
        "description": str(description or "").strip(),
        "meta": _clone_payload(meta or {}),
    }


def _dedupe_candidate_choices(choices: List[dict]) -> List[dict]:
    seen: set[str] = set()
    deduped: List[dict] = []
    for choice in choices or []:
        if not isinstance(choice, dict):
            continue
        key = _pending_choice_key(choice)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(choice)
    return deduped


def _strict_choice_resolution(query: str, choices: List[dict], *, fuzzy_threshold: float = 0.58) -> dict:
    query_text = str(query or "").strip()
    if not query_text:
        return {"status": "missing", "choices": []}
    deduped = _dedupe_candidate_choices(choices)
    if not deduped:
        return {"status": "missing", "choices": []}

    compact_query = _compact_text(query_text)
    exact: List[dict] = []
    normalized: List[dict] = []
    loose: List[Tuple[float, dict]] = []
    fuzzy: List[Tuple[float, dict]] = []

    for choice in deduped:
        aliases = _pending_choice_aliases(choice)
        alias_texts = [alias for alias in aliases if alias]
        if not alias_texts:
            continue
        if any(alias == query_text for alias in alias_texts):
            exact.append(choice)
            continue
        if compact_query and any(_compact_text(alias) == compact_query for alias in alias_texts):
            normalized.append(choice)
            continue
        best_loose = 0.0
        best_fuzzy = 0.0
        for alias in alias_texts:
            compact_alias = _compact_text(alias)
            if compact_query and compact_alias and (compact_query in compact_alias or compact_alias in compact_query):
                best_loose = max(best_loose, min(len(compact_query), len(compact_alias)) / max(len(compact_query), len(compact_alias), 1))
            score = difflib.SequenceMatcher(None, query_text, alias).ratio()
            if score >= fuzzy_threshold:
                best_fuzzy = max(best_fuzzy, score)
        if best_loose > 0:
            loose.append((best_loose, choice))
        elif best_fuzzy > 0:
            fuzzy.append((best_fuzzy, choice))

    exact = _dedupe_candidate_choices(exact)
    normalized = _dedupe_candidate_choices(normalized)
    if len(exact) == 1:
        return {"status": "resolved", "choice": exact[0], "choices": exact}
    if len(normalized) == 1:
        return {"status": "resolved", "choice": normalized[0], "choices": normalized}

    if len(exact) > 1:
        return {"status": "ambiguous", "choices": exact}
    if len(normalized) > 1:
        return {"status": "ambiguous", "choices": normalized}

    ranked = loose or fuzzy
    if ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        ranked_choices = _dedupe_candidate_choices([choice for _, choice in ranked[:6]])
        if len(ranked_choices) == 1:
            return {"status": "resolved", "choice": ranked_choices[0], "choices": ranked_choices}
        if ranked_choices:
            return {"status": "ambiguous", "choices": ranked_choices}
    return {"status": "missing", "choices": []}


def _select_pending_choice(raw_text: str, choices: List[dict]) -> Optional[dict]:
    text = str(raw_text or "").strip()
    if not text:
        return None
    deduped = _dedupe_candidate_choices(choices)
    if not deduped:
        return None
    order_index = _first_int_from_text(text)
    if order_index is not None and 1 <= order_index <= len(deduped):
        return deduped[order_index - 1]
    compact_text = _compact_text(text)
    for choice in deduped:
        for alias in _pending_choice_aliases(choice):
            if alias == text:
                return choice
            compact_alias = _compact_text(alias)
            if compact_text and compact_alias and compact_alias == compact_text:
                return choice
    return None


def _build_disambiguation_prompt(target_type: str, query: str, choices: List[dict]) -> str:
    labels = {
        "schedule": "作息方案",
        "task": "任务",
        "zone": "分区",
        "media": "媒体",
    }
    target_label = labels.get(str(target_type or ""), "目标")
    lines = [f'找到了多个可能的{target_label}，请确认“{query}”指的是哪一个：']
    for idx, choice in enumerate(_dedupe_candidate_choices(choices), start=1):
        line = f"{idx}. {choice.get('label') or choice.get('value') or '未命名候选'}"
        description = str(choice.get("description") or "").strip()
        if description:
            line += f" ({description})"
        lines.append(line)
    lines.append("请直接点击候选项，或回复序号。")
    return "\n".join(lines)


def _begin_target_disambiguation(
    *,
    intent: str,
    text: str,
    slots: dict,
    target_type: str,
    query: str,
    choices: List[dict],
) -> Tuple[str, Dict[str, Any], List[dict]]:
    deduped = _dedupe_candidate_choices(choices)
    prompt = _build_disambiguation_prompt(target_type, query, deduped)
    _set_pending_action(
        {
            "kind": "target_disambiguation",
            "intent": _normalize_intent_label(intent),
            "original_text": str(text or ""),
            "slots": _clone_payload(slots or {}),
            "target_type": str(target_type or ""),
            "query": str(query or ""),
            "choices": deduped,
            "confirm_prompt": prompt,
        }
    )
    return (prompt, _pending_action_overrides(_get_pending_action(), missing_slots=[]), [])


def _strict_numeric_task_id_text(value: object) -> str:
    text = str(value or "").strip()
    if text.isdigit() and text != "0":
        return text
    return ""


def _task_matches_requested_target(task: dict, task_name: str = "", task_id: str = "") -> bool:
    strict_task_id = _strict_numeric_task_id_text(task_id)
    if strict_task_id:
        return _strict_numeric_task_id_text(_task_id(task)) == strict_task_id
    return _task_name_matches(task, task_name)


def _text_mentions_numeric_token(text: str, value: str) -> bool:
    strict_value = _strict_numeric_task_id_text(value)
    if not strict_value:
        return False
    return re.search(rf"(?<!\d){re.escape(strict_value)}(?!\d)", str(text or "")) is not None


def _phase1_effective_strict_task_id(intent: str, text: str, slots: dict) -> str:
    strict_task_id = _strict_numeric_task_id_text(_task_slot_id(slots))
    if not strict_task_id:
        return ""
    source = str((slots or {}).get("task_id_source") or "").strip().lower()
    if source in {"explicit", "confirmed_choice", "pending_confirmed"}:
        return strict_task_id
    if bool((slots or {}).get("task_id_confirmed")):
        return strict_task_id
    if _text_mentions_numeric_token(text, strict_task_id):
        return strict_task_id
    return ""


def _schedule_choice(item: dict) -> dict:
    schedule_name = str(item.get("schedule_name") or item.get("name") or "").strip()
    return _candidate_choice(
        value=schedule_name,
        label=schedule_name,
        slot_updates={"schedule_name": schedule_name},
        aliases=[schedule_name],
        description="作息方案",
    )


def _all_enabled_schedule_choice(schedules: List[dict]) -> Optional[dict]:
    names = [
        _schedule_display_name(item)
        for item in schedules or []
        if isinstance(item, dict) and _schedule_display_name(item)
    ]
    names = _unique_list([name for name in names if name])
    if len(names) <= 1:
        return None
    preview = "、".join(names[:4])
    suffix = "等" if len(names) > 4 else ""
    return _candidate_choice(
        value="全部",
        label="全部",
        slot_updates={"schedule_scope": "enabled_all", "schedule_names": names},
        aliases=["全部", "所有", "都", "全部启用方案", "所有启用方案"],
        description=f"对全部启用方案执行（{preview}{suffix}）",
        meta={"schedule_scope": "enabled_all", "schedule_names": names},
    )


def _resolve_phase1_schedule_targets(
    intent: str,
    text: str,
    slots: dict,
    payload: dict,
    schedule_name: str,
) -> Tuple[List[Tuple[dict, str]], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    scope = str((slots or {}).get("schedule_scope") or "").strip()
    requested_names = [
        str(item).strip()
        for item in ((slots or {}).get("schedule_names") or [])
        if str(item).strip()
    ] if isinstance((slots or {}).get("schedule_names"), list) else []

    if scope == "enabled_all":
        enabled = _enabled_schedules(payload)
        if not enabled:
            _, _, schedule_error = _resolve_unique_enabled_schedule(payload)
            return [], schedule_error
        requested_set = set(requested_names)
        targets: List[Tuple[dict, str]] = []
        for item in enabled:
            resolved_name = _schedule_display_name(item)
            if not resolved_name:
                continue
            if requested_set and resolved_name not in requested_set:
                continue
            targets.append((item, resolved_name))
        if not targets:
            targets = [
                (item, _schedule_display_name(item))
                for item in enabled
                if _schedule_display_name(item)
            ]
        return targets, None

    if schedule_name:
        schedule, resolved_name, schedule_error = _resolve_schedule_for_phase1(payload, schedule_name)
        if schedule_error:
            return [], schedule_error
        return ([(schedule, resolved_name)] if schedule and resolved_name else []), None

    enabled = _enabled_schedules(payload)
    if len(enabled) == 1:
        resolved_name = _schedule_display_name(enabled[0])
        return ([(enabled[0], resolved_name)] if resolved_name else []), None
    if not enabled:
        _, _, schedule_error = _resolve_unique_enabled_schedule(payload)
        return [], schedule_error

    choices = [_schedule_choice(item) for item in enabled if isinstance(item, dict)]
    all_choice = _all_enabled_schedule_choice(enabled)
    if all_choice:
        choices.append(all_choice)
    return [], _begin_target_disambiguation(
        intent=intent,
        text=text,
        slots=slots,
        target_type="schedule",
        query="当前启用方案",
        choices=choices,
    )


def _summarize_phase1_schedule_groups(groups: List[dict]) -> str:
    parts: List[str] = []
    for item in groups or []:
        if not isinstance(item, dict):
            continue
        schedule_name = str(item.get("schedule_name") or "").strip()
        count = _coerce_int(item.get("count"), 0)
        if schedule_name and count > 0:
            parts.append(f"{schedule_name}({count}条)")
    return "、".join(parts[:6])


def _zone_choice(item: dict) -> dict:
    zone_name = _zone_item_name(item)
    zone_id = str(item.get("id") or item.get("zoneid") or "").strip()
    aliases = [zone_name]
    if zone_id:
        aliases.append(zone_id)
    return _candidate_choice(
        value=zone_name or zone_id,
        label=zone_name or f"分区{zone_id}",
        slot_updates={"zone_name": zone_name or zone_id},
        aliases=aliases,
        description=f"id={zone_id}" if zone_id else "分区",
        meta={"zone_id": zone_id},
    )


def _media_choice(media_id: str, media_name: str, slot_key: str) -> dict:
    return _candidate_choice(
        value=media_name,
        label=media_name,
        slot_updates={slot_key: media_name},
        aliases=[media_name, media_id],
        description=f"id={media_id}" if media_id else "媒体",
        meta={"media_id": media_id},
    )


def _task_choice(task: dict, *, schedule_name: str = "", scope_kind: str = "") -> dict:
    task_id = str(_task_id(task) or "").strip()
    task_name = _phase1_task_name(task) or task_id or "未命名任务"
    time_text = _format_hhmm(str(task.get("starttime") or task.get("time") or ""))
    scope_text = schedule_name or scope_kind or ""
    label = task_name
    description_parts: List[str] = []
    if time_text:
        description_parts.append(time_text)
    if scope_text:
        description_parts.append(scope_text)
    if task_id:
        description_parts.append(f"id={task_id}")
    return _candidate_choice(
        value=task_id or task_name,
        label=label,
        slot_updates={
            "task_name": task_name,
            "task_id": task_id,
            "task_id_confirmed": bool(task_id),
            "task_id_source": "confirmed_choice" if task_id else "",
            **({"schedule_name": schedule_name} if schedule_name else {}),
        },
        aliases=[task_name, task_id, label],
        description=" / ".join([part for part in description_parts if part]),
        meta={"task_id": task_id, "schedule_name": schedule_name, "scope_kind": scope_kind},
    )


def _move_schedule_scope_choice(schedule_name: str, tasks: List[dict]) -> dict:
    preview = _summarize_tasks([task for task in tasks if isinstance(task, dict)])
    return _candidate_choice(
        value=schedule_name,
        label=schedule_name,
        slot_updates={"schedule_name": schedule_name, "schedule_scope": "", "schedule_names": []},
        aliases=[schedule_name],
        description=preview if preview and preview != "未找到任务" else "作息方案",
        meta={"schedule_name": schedule_name},
    )


def _strict_resolve_schedule(
    intent: str,
    text: str,
    slots: dict,
    payload: dict,
    schedule_name: str,
) -> Tuple[Optional[dict], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    schedules = payload.get("schedules") if isinstance(payload.get("schedules"), list) else []
    choices = [_schedule_choice(item) for item in schedules if isinstance(item, dict)]
    result = _strict_choice_resolution(schedule_name, choices)
    if result.get("status") == "resolved":
        choice = result.get("choice") or {}
        resolved_name = str((choice.get("slot_updates") or {}).get("schedule_name") or "")
        return _find_schedule(payload, resolved_name), None
    if result.get("status") == "ambiguous":
        return None, _begin_target_disambiguation(
            intent=intent,
            text=text,
            slots=slots,
            target_type="schedule",
            query=schedule_name,
            choices=result.get("choices") or [],
        )
    return None, None


def _strict_resolve_zone_ids(
    intent: str,
    text: str,
    slots: dict,
    zone_names: List[str],
) -> Tuple[List[str], List[str], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    if not zone_names:
        return [], [], None
    items = _remote_zone_items()
    resolved: List[str] = []
    missing: List[str] = []
    choices = [_zone_choice(item) for item in items if isinstance(item, dict)]
    for zone_name in zone_names:
        if str(zone_name or "").strip().isdigit():
            resolved.append(str(zone_name).strip())
            continue
        result = _strict_choice_resolution(zone_name, choices)
        if result.get("status") == "resolved":
            zone_id = str(((result.get("choice") or {}).get("meta") or {}).get("zone_id") or "").strip()
            if zone_id:
                resolved.append(zone_id)
            else:
                missing.append(str(zone_name))
            continue
        if result.get("status") == "ambiguous":
            return [], [], _begin_target_disambiguation(
                intent=intent,
                text=text,
                slots=slots,
                target_type="zone",
                query=str(zone_name),
                choices=result.get("choices") or [],
            )
        missing.append(str(zone_name))
    return _unique_list(resolved), _unique_list(missing), None


def _strict_resolve_media_match(
    intent: str,
    text: str,
    slots: dict,
    query: str,
    media_map: dict,
    *,
    slot_key: str,
) -> Tuple[Optional[Tuple[str, str]], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    choices: List[dict] = []
    for media_name, media_id in (media_map or {}).items():
        if not media_name or media_id in (None, ""):
            continue
        choices.append(_media_choice(str(media_id), str(media_name), slot_key))
    result = _strict_choice_resolution(query, choices)
    if result.get("status") == "resolved":
        choice = result.get("choice") or {}
        media_id = str(((choice.get("meta") or {}).get("media_id") or "")).strip()
        media_name = str(choice.get("label") or choice.get("value") or "").strip()
        if media_id and media_name:
            return (media_id, media_name), None
        return None, None
    if result.get("status") == "ambiguous":
        return None, _begin_target_disambiguation(
            intent=intent,
            text=text,
            slots=slots,
            target_type="media",
            query=query,
            choices=result.get("choices") or [],
        )
    return None, None


def _media_name_from_map_id(media_map: dict, media_id: object) -> str:
    target_id = str(media_id or "").strip()
    if not target_id:
        return ""
    for media_name, candidate_id in (media_map or {}).items():
        if str(candidate_id or "").strip() == target_id:
            return str(media_name or "").strip()
    return ""


def _resolve_media_match_with_slot_hints(
    intent: str,
    text: str,
    slots: dict,
    query: str,
    media_map: dict,
    *,
    slot_key: str,
) -> Tuple[Optional[Tuple[str, str]], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    matched_name = _slot_text(slots, f"{slot_key}_matched")
    matched_id = _slot_text(slots, f"{slot_key}_id")

    if matched_id:
        resolved_name = _media_name_from_map_id(media_map, matched_id)
        if resolved_name:
            return (str(matched_id), resolved_name), None

    if matched_name:
        media_match, pending_reply = _strict_resolve_media_match(
            intent,
            text,
            slots,
            matched_name,
            media_map,
            slot_key=slot_key,
        )
        if media_match or pending_reply:
            return media_match, pending_reply

    return _strict_resolve_media_match(intent, text, slots, query, media_map, slot_key=slot_key)


def _normalize_intent_label(intent: object) -> str:
    label = str(intent or "").strip().lower()
    alias_map = {
        "swap_task": "swap_schedule",
        "task_pause": "pause_task",
        "task_resume": "resume_task",
        "create_scheme": "create_schedule",
    }
    return alias_map.get(label, label)


def _weekday_label_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(?:周|星期|礼拜)\s*([一二三四五六日天])", text)
    if not match:
        return None
    token = match.group(1)
    if token == "天":
        token = "日"
    return f"周{token}"


def _parse_iso_date(value: object) -> Optional[datetime]:
    if value in (None, "", "0-00-00"):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    parsed = _parse_datetime(f"{text} 00:00:00")
    if parsed:
        return parsed
    return None


def _parse_phase1_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    parsed = _parse_datetime(text)
    if parsed:
        return parsed
    parsed = _parse_iso_date(text)
    if parsed:
        return parsed
    try:
        parsed = ENGINE._parse_time_point(text, None)
    except Exception:
        parsed = None
    if parsed:
        return parsed
    return None


def _cn_digit_to_arabic(text: str) -> str:
    """将文本中的中文数字(零~十二)转为阿拉伯数字,用于时间解析。"""
    result = text
    # 必须先替换多字词(十一、十二),再替换单字,避免 "十一" 被拆成 "十1"
    for cn, ar in [("十一", "11"), ("十二", "12"), ("十", "10")]:
        result = result.replace(cn, ar)
    for cn, ar in [
        ("零", "0"), ("〇", "0"),
        ("一", "1"), ("二", "2"), ("两", "2"), ("三", "3"), ("四", "4"),
        ("五", "5"), ("六", "6"), ("七", "7"), ("八", "8"), ("九", "9"),
    ]:
        result = result.replace(cn, ar)
    return result


def _extract_time_range_minutes(text: str) -> Tuple[Optional[int], Optional[int]]:
    """从文本中提取时间范围(分钟数)。如 '3-7点' -> (180,420), '下午3点到5点' -> (900,1020)"""
    if not text:
        return None, None
    # 先移除 weekday 片段,避免"周一8点30"在中文数字替换后变成"周18点30"。
    text = re.sub(r"(?:这|本|下下|下个|下|上个|上)?(?:周|星期|礼拜)[一二三四五六日天1-7]", " ", text)
    # 先将中文数字转为阿拉伯数字,以便正则匹配
    text = _cn_digit_to_arabic(text)
    _pm = ("下午", "午后", "晚上", "傍晚")

    # X点到Y点 / X点至Y点 / X:MM到Y:MM
    m = re.search(
        r"(上午|下午|早上|晚上|凌晨|午后|傍晚|早晨)?\s*(\d{1,2})\s*[点时:：]\s*(\d{1,2})?\s*分?\s*(?:到|至|-|–|—)\s*"
        r"(上午|下午|早上|晚上|凌晨|午后|傍晚|早晨)?\s*(\d{1,2})\s*[点时:：]?\s*(\d{1,2})?\s*分?",
        text,
    )
    if m:
        p1, h1, min1 = m.group(1) or "", int(m.group(2)), int(m.group(3) or 0)
        p2, h2, min2 = m.group(4) or p1, int(m.group(5)), int(m.group(6) or 0)
        if any(p in p1 for p in _pm) and h1 < 12:
            h1 += 12
        if any(p in p2 for p in _pm) and h2 < 12:
            h2 += 12
        return h1 * 60 + min1, h2 * 60 + min2

    # 紧凑格式: X-Y点
    m = re.search(r"(上午|下午|早上|晚上|凌晨)?\s*(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*[点时]", text)
    if m:
        p, h1, h2 = m.group(1) or "", int(m.group(2)), int(m.group(3))
        if any(pp in p for pp in _pm):
            if h1 < 12:
                h1 += 12
            if h2 < 12:
                h2 += 12
        return h1 * 60, h2 * 60

    # 单点时间: X点30 / X:30 / 下午3点
    m = re.search(
        r"(上午|下午|早上|晚上|凌晨|午后|傍晚|早晨)?\s*(\d{1,2})\s*(?:[:：点时])\s*(\d{1,2})?\s*分?",
        text,
    )
    if m:
        period, hour, minute = m.group(1) or "", int(m.group(2)), int(m.group(3) or 0)
        if any(p in period for p in _pm) and hour < 12:
            hour += 12
        if "凌晨" in period and hour == 12:
            hour = 0
        minutes = hour * 60 + minute
        return minutes, minutes

    return None, None


def _parse_phase1_time_anchor(value: str) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    weekday = _weekday_label_from_text(text)
    has_date_literal = bool(
        re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}|(\d{1,2}月\d{1,2}(?:日|号)?)|(\d{1,2}(?:日|号))", text)
    ) or any(word in text for word in ["今天", "明天", "后天", "大后天", "昨天", "前天"])

    time_start, time_end = _extract_time_range_minutes(text)

    if weekday and not has_date_literal:
        result: Dict[str, Any] = {"kind": "weekday", "weekday": weekday, "raw": text}
        if time_start is not None and time_end is not None:
            result["time_start_minutes"] = time_start
            result["time_end_minutes"] = time_end
        return result
    parsed_date = _parse_phase1_date(text)
    if parsed_date:
        result = {"kind": "date", "date": parsed_date.date(), "raw": text}
        if time_start is not None and time_end is not None:
            result["time_start_minutes"] = time_start
            result["time_end_minutes"] = time_end
        return result
    if weekday:
        result = {"kind": "weekday", "weekday": weekday, "raw": text}
        if time_start is not None and time_end is not None:
            result["time_start_minutes"] = time_start
            result["time_end_minutes"] = time_end
        return result
    return None

    if weekday:
        anchor = {"kind": "weekday", "weekday": weekday, "raw": text}
        return _attach_time_window(anchor)
    return None

def _task_has_missing_recurrence_metadata(task: dict) -> bool:
    if not isinstance(task, dict):
        return False
    weekdays = task.get("weekdays")
    if isinstance(weekdays, list) and any(str(day).strip() for day in weekdays):
        return False
    if _weekdays_from_execmode(task.get("execmode")):
        return False
    start_raw = str(task.get("startdate") or "").strip()
    end_raw = str(task.get("enddate") or "").strip()
    if start_raw in {"0-00-00", "0000-00-00"} or end_raw in {"0-00-00", "0000-00-00"}:
        return True
    start_dt, end_dt = _task_date_span(task)
    if not start_dt or not end_dt:
        return False
    return start_dt.date() != end_dt.date()


def _task_weekdays_for_anchor(task: dict) -> List[str]:
    weekdays = task.get("weekdays")
    if isinstance(weekdays, list) and weekdays:
        return [str(day).strip() for day in weekdays if str(day).strip()]
    mapped = _weekdays_from_execmode(task.get("execmode"))
    if mapped:
        return [str(day).strip() for day in mapped if str(day).strip()]
    return []


def _phase1_anchor_diagnostic(anchor: Optional[Dict[str, Any]], matched: dict) -> dict:
    anchor_kind = str((anchor or {}).get("kind") or "")
    anchor_date = (anchor or {}).get("date")
    return {
        "anchor_kind": anchor_kind,
        "anchor_weekday": str((anchor or {}).get("weekday") or "") if anchor_kind == "weekday" else "",
        "anchor_date": anchor_date.isoformat() if anchor_kind == "date" and hasattr(anchor_date, "isoformat") else "",
        "candidate_count_after_time_match": int(matched.get("candidate_count_after_time_match") or 0),
        "candidate_count_after_task_name_match": int(matched.get("candidate_count_after_task_name_match") or 0),
        "missing_recurrence_metadata_count": int(matched.get("missing_recurrence_metadata_count") or 0),
        "strict_task_id_applied": bool(matched.get("strict_task_id_applied")),
        "strict_task_id_value": str(matched.get("strict_task_id_value") or ""),
        "task_name_filter_applied": bool(matched.get("task_name_filter_applied")),
    }


def _match_tasks_for_phase1_anchor(
    tasks: object,
    anchor: Optional[Dict[str, Any]],
    *,
    task_name: str = "",
    strict_task_id: str = "",
    allow_recurring_date: bool = False,
) -> dict:
    time_matched: List[dict] = []
    final_matched: List[dict] = []
    missing_recurrence_metadata_count = 0
    strict_task_id = _strict_numeric_task_id_text(strict_task_id)
    task_name_filter_applied = bool(task_name and not strict_task_id)
    for task in tasks if isinstance(tasks, list) else []:
        if not isinstance(task, dict):
            continue
        count_missing_metadata = True
        if task_name_filter_applied:
            count_missing_metadata = _task_name_matches(task, task_name)
        if (
            count_missing_metadata
            and anchor
            and str(anchor.get("kind") or "") == "weekday"
            and _task_has_missing_recurrence_metadata(task)
        ):
            missing_recurrence_metadata_count += 1
        if not _task_matches_anchor(task, anchor or {}, allow_recurring_date=allow_recurring_date):
            continue
        time_matched.append(task)
        if strict_task_id and _strict_numeric_task_id_text(_task_id(task)) != strict_task_id:
            continue
        if not strict_task_id and task_name and not _task_name_matches(task, task_name):
            continue
        final_matched.append(task)
    return {
        "time_matched_tasks": time_matched,
        "matched_tasks": final_matched,
        "candidate_count_after_time_match": len(time_matched),
        "candidate_count_after_task_name_match": len(final_matched),
        "missing_recurrence_metadata_count": missing_recurrence_metadata_count,
        "strict_task_id_applied": bool(strict_task_id),
        "strict_task_id_value": strict_task_id,
        "task_name_filter_applied": task_name_filter_applied,
    }


def _phase1_anchor_failure_reply(
    schedule_targets: List[Tuple[dict, str]],
    anchor_text: str,
    *,
    task_name: str = "",
    strict_task_id: str = "",
    diagnostics: Optional[List[dict]] = None,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    diag_list = diagnostics if isinstance(diagnostics, list) else []
    total_time_matches = sum(int(item.get("candidate_count_after_time_match") or 0) for item in diag_list if isinstance(item, dict))
    total_name_matches = sum(int(item.get("candidate_count_after_task_name_match") or 0) for item in diag_list if isinstance(item, dict))
    total_missing_recurrence = sum(int(item.get("missing_recurrence_metadata_count") or 0) for item in diag_list if isinstance(item, dict))
    anchor_kind = str(diag_list[0].get("anchor_kind") or "") if diag_list else ""
    if len(schedule_targets) == 1:
        schedule_label = f"“{schedule_targets[0][1]}”"
        scope_label = f"在{schedule_label}"
    else:
        schedule_label = "当前启用中的作息方案"
        scope_label = f"在{schedule_label}里"

    if total_time_matches > 0 and task_name and not strict_task_id and total_name_matches <= 0:
        reply = f"{scope_label}的“{anchor_text}”任务中未找到名称匹配“{task_name}”的任务。"
    elif anchor_kind == "weekday" and total_missing_recurrence > 0 and total_time_matches <= 0:
        if len(schedule_targets) == 1:
            reply = f"{schedule_label}中的任务缺少星期信息，无法按“{anchor_text}”定位。"
        else:
            reply = f"{schedule_label}里有任务缺少星期信息，无法按“{anchor_text}”定位。"
    else:
        task_hint = f"且任务名为“{task_name}”" if task_name and not strict_task_id else ""
        reply = f"{scope_label}未找到匹配“{anchor_text}”{task_hint}的任务。"

    overrides: Dict[str, Any] = {"missing_slots": []}
    if diag_list:
        overrides["diagnostics"] = _clone_payload(diag_list)
    return reply, overrides, []


def _task_matches_anchor(task: dict, anchor: Dict[str, Any], allow_recurring_date: bool = False) -> bool:
    if not isinstance(task, dict) or not anchor:
        return False

    def _check_time_range() -> bool:
        """如果 anchor 带有 time_start_minutes / time_end_minutes,额外过滤任务时间。"""
        ts = anchor.get("time_start_minutes")
        te = anchor.get("time_end_minutes")
        if ts is None or te is None:
            return True  # 没有时间范围限制,视为匹配
        task_minutes = _parse_time_minutes(task.get("starttime"))
        if task_minutes is None:
            return False
        return ts <= task_minutes <= te

    if anchor.get("kind") == "weekday":
        weekday = str(anchor.get("weekday") or "")
        if not weekday:
            return False
        if weekday not in _task_weekdays_for_anchor(task):
            return False
        return _check_time_range()
    if anchor.get("kind") == "date":
        date_value = anchor.get("date")
        if not date_value:
            return False
        start_dt, end_dt = _task_date_span(task)
        if not start_dt or not end_dt:
            return False
        if start_dt.date() != end_dt.date() and not allow_recurring_date:
            # 日期维度操作仅匹配"单日任务",避免误伤长期循环任务。
            return False
        if allow_recurring_date:
            if date_value < start_dt.date() or date_value > end_dt.date():
                return False
            if start_dt.date() != end_dt.date():
                weekdays = _task_weekdays_for_anchor(task)
                if weekdays:
                    current_label = _weekday_label(datetime.combine(date_value, datetime.min.time()))
                    if current_label not in weekdays:
                        return False
        elif start_dt.date() != date_value:
            return False
        return _check_time_range()
    return False

def _replace_weekday(weekdays: List[str], source: str, target: str) -> List[str]:
    ordered = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    replaced: List[str] = []
    for day in weekdays:
        if day == source:
            replaced.append(target)
        else:
            replaced.append(day)
    dedup = _unique_list([day for day in replaced if day])
    return [day for day in ordered if day in dedup]


def _shift_task_dates(task: dict, day_delta: int, fallback_date: datetime) -> dict:
    moved = _clone_payload(task)
    start_dt = _parse_iso_date(moved.get("startdate"))
    end_dt = _parse_iso_date(moved.get("enddate")) or start_dt
    if not start_dt:
        start_dt = fallback_date
        end_dt = fallback_date
    moved["startdate"] = (start_dt + timedelta(days=day_delta)).strftime("%Y-%m-%d")
    moved["enddate"] = (end_dt + timedelta(days=day_delta)).strftime("%Y-%m-%d")
    return moved


def _apply_time_offset_to_task(moved: dict, source_anchor: Dict[str, Any], target_anchor: Dict[str, Any]) -> None:
    """场景C辅助:若源和目标 anchor 均带时间范围,对任务 starttime 做偏移。"""
    src_start = source_anchor.get("time_start_minutes")
    tgt_start = target_anchor.get("time_start_minutes")
    if src_start is None or tgt_start is None:
        return
    task_minutes = _parse_time_minutes(moved.get("starttime"))
    if task_minutes is None:
        return
    new_minutes = task_minutes + (tgt_start - src_start)
    new_h = max(0, min(23, new_minutes // 60))
    new_m = max(0, min(59, new_minutes % 60))
    moved["starttime"] = f"{new_h:02d}:{new_m:02d}:00"


def _apply_move_anchor_to_task(task: dict, source_anchor: Dict[str, Any], target_anchor: Dict[str, Any]) -> Optional[dict]:
    source_minutes = _anchor_start_minutes(source_anchor)
    target_minutes = _anchor_start_minutes(target_anchor)
    time_delta_minutes = None
    if source_minutes is not None and target_minutes is not None:
        time_delta_minutes = target_minutes - source_minutes

    if source_anchor.get("kind") == "weekday":
        source_day = str(source_anchor.get("weekday") or "")
        target_day = str(target_anchor.get("weekday") or "")
        weekdays = _task_weekdays_for_anchor(task)
        if source_day not in weekdays:
            return None
        moved = _clone_payload(task)
        moved_weekdays = _replace_weekday(weekdays, source_day, target_day)
        overflow_day = 0
        if time_delta_minutes is not None:
            shifted_time, overflow_day = _shift_hhmmss_with_day_delta(moved.get("starttime") or moved.get("time") or "00:00:00", time_delta_minutes)
            moved["starttime"] = shifted_time
        if overflow_day:
            moved_weekdays = _shift_weekdays_by_delta(moved_weekdays, overflow_day)
            start_dt = _parse_iso_date(moved.get("startdate"))
            if start_dt:
                moved = _shift_task_dates(moved, overflow_day, start_dt)
        moved["weekdays"] = moved_weekdays
        moved["execmode"] = _execmode_from_weekdays(moved_weekdays)
        return moved

    source_date = source_anchor.get("date")
    target_date = target_anchor.get("date")
    if not source_date or not target_date:
        return None
    day_delta = (target_date - source_date).days
    fallback = datetime.combine(source_date, datetime.min.time())
    moved = _shift_task_dates(task, day_delta, fallback)
    _apply_time_offset_to_task(moved, source_anchor, target_anchor)
    return moved


def _apply_swap_anchor_to_task(task: dict, anchor_a: Dict[str, Any], anchor_b: Dict[str, Any]) -> Optional[dict]:
    match_a = _task_matches_anchor(task, anchor_a)
    match_b = _task_matches_anchor(task, anchor_b)
    if (not match_a and not match_b) or (match_a and match_b):
        return None
    
    a_minutes = _anchor_start_minutes(anchor_a)
    b_minutes = _anchor_start_minutes(anchor_b)

    if anchor_a.get("kind") == "weekday":
        day_a = str(anchor_a.get("weekday") or "")
        day_b = str(anchor_b.get("weekday") or "")
        weekdays = _task_weekdays_for_anchor(task)
        if not weekdays:
            return None
        swapped = _clone_payload(task)
        swapped_weekdays = _replace_weekday(weekdays, day_a, day_b) if match_a else _replace_weekday(weekdays, day_b, day_a)
        time_delta = None
        if a_minutes is not None and b_minutes is not None:
            time_delta = (b_minutes - a_minutes) if match_a else (a_minutes - b_minutes)
        overflow_day = 0
        if time_delta is not None:
            shifted_time, overflow_day = _shift_hhmmss_with_day_delta(swapped.get("starttime") or swapped.get("time") or "00:00:00", time_delta)
            swapped["starttime"] = shifted_time
        if overflow_day:
            swapped_weekdays = _shift_weekdays_by_delta(swapped_weekdays, overflow_day)
            start_dt = _parse_iso_date(swapped.get("startdate"))
            if start_dt:
                swapped = _shift_task_dates(swapped, overflow_day, start_dt)
        swapped["weekdays"] = swapped_weekdays
        swapped["execmode"] = _execmode_from_weekdays(swapped_weekdays)
        return swapped

    date_a = anchor_a.get("date")
    date_b = anchor_b.get("date")
    if not date_a or not date_b:
        return None
    day_delta = (date_b - date_a).days if match_a else (date_a - date_b).days
    fallback = datetime.combine(date_a if match_a else date_b, datetime.min.time())
    swapped = _shift_task_dates(task, day_delta, fallback)
    if a_minutes is not None and b_minutes is not None:
        time_delta = (b_minutes - a_minutes) if match_a else (a_minutes - b_minutes)
        shifted_time, overflow_day = _shift_hhmmss_with_day_delta(swapped.get("starttime") or swapped.get("time") or "00:00:00", time_delta)
        swapped["starttime"] = shifted_time
        if overflow_day:
            shifted_start = _parse_iso_date(swapped.get("startdate")) or datetime.combine(date_b if match_a else date_a, datetime.min.time())
            swapped = _shift_task_dates(swapped, overflow_day, shifted_start)
    return swapped


def _phase1_task_name(task: dict) -> str:
    if not isinstance(task, dict):
        return ""
    return str(task.get("taskname") or task.get("name") or task.get("customName") or task.get("audio") or "").strip()


def _phase1_template_candidate_names(raw: str, data: object) -> List[str]:
    candidate_names: List[str] = []
    if isinstance(data, dict):
        schedules = data.get("schedules")
        if isinstance(schedules, list):
            for item in schedules:
                if isinstance(item, dict):
                    name = item.get("schedule_name") or item.get("name")
                    if name:
                        candidate_names.append(str(name))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                name = item.get("schedule_name") or item.get("name")
                if name:
                    candidate_names.append(str(name))
            elif item:
                candidate_names.append(str(item))
    if not candidate_names:
        for line in raw.splitlines():
            text = line.strip().strip("\"'")
            if text:
                candidate_names.append(text)
    return candidate_names


def _warn_legacy_phase1_template_inputs_once() -> None:
    global _PHASE1_LEGACY_TEMPLATE_WARNING_EMITTED
    if _PHASE1_LEGACY_TEMPLATE_WARNING_EMITTED:
        return
    legacy_paths: List[str] = []
    for candidate in (LEGACY_PHASE1_TEMPLATE_CATALOG_PATH, LEGACY_PHASE1_TEMPLATE_MANIFEST_PATH):
        if candidate.exists():
            legacy_paths.append(str(candidate))
    if not legacy_paths:
        return
    _PHASE1_LEGACY_TEMPLATE_WARNING_EMITTED = True
    LOGGER.warning(
        "legacy schedule template inputs detected; ignoring legacy_paths=%s authoritative_template_dir=%s authoritative_runtime_dir=%s",
        legacy_paths,
        str(DEFAULT_DATA_DIR),
        str(DATA_DIR),
    )


def _load_phase1_template_manifest() -> dict:
    _warn_legacy_phase1_template_inputs_once()
    if not PHASE1_TEMPLATE_MANIFEST_PATH.exists():
        return {}
    raw = PHASE1_TEMPLATE_MANIFEST_PATH.read_text(encoding="utf-8", errors="ignore").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_phase1_template_catalog() -> dict:
    _warn_legacy_phase1_template_inputs_once()
    payload = _read_json_optional(PHASE1_TEMPLATE_CATALOG_PATH)
    if not isinstance(payload, dict):
        return {}
    try:
        return _normalize_schedules_payload(payload)
    except HTTPException:
        return {}


def _load_phase1_template_name() -> str:
    manifest = _load_phase1_template_manifest()
    default_entry = manifest.get("default") if isinstance(manifest, dict) else None
    if isinstance(default_entry, dict):
        remote_template = str(default_entry.get("remote_template") or "").strip()
        if remote_template:
            return remote_template
    return PHASE1_TEMPLATE_DEFAULT_NAME


def _phase1_kind_template_map(manifest: dict) -> Dict[str, dict]:
    items = manifest.get("kind_templates") if isinstance(manifest, dict) else None
    if not isinstance(items, dict):
        return {}
    result: Dict[str, dict] = {}
    for key, value in items.items():
        key_text = str(key or "").strip()
        if key_text and isinstance(value, dict):
            result[key_text] = value
    return result


def _phase1_kind_alias_map(manifest: dict) -> Dict[str, str]:
    items = manifest.get("kind_aliases") if isinstance(manifest, dict) else None
    if not isinstance(items, dict):
        return {}
    result: Dict[str, str] = {}
    for key, value in items.items():
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if key_text and value_text:
            result[key_text] = value_text
    return result


def _phase1_season_alias_map(manifest: dict) -> Dict[str, str]:
    items = manifest.get("season_aliases") if isinstance(manifest, dict) else None
    if not isinstance(items, dict):
        return {}
    result: Dict[str, str] = {}
    for key, value in items.items():
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if key_text and value_text:
            result[key_text] = value_text
    return result


def _resolve_phase1_named_option(value: str, options: Collection[str], aliases: Dict[str, str]) -> str:
    target = _compact_text(str(value or ""))
    if not target:
        return ""
    option_list = [str(item or "").strip() for item in options if str(item or "").strip()]
    option_set = set(option_list)
    for option_name in option_list:
        if _compact_text(option_name) == target:
            return option_name
    for alias, option_name in aliases.items():
        if _compact_text(alias) == target and option_name in option_set:
            return option_name
    return ""


def _resolve_phase1_kind_name(value: str, kind_templates: Dict[str, dict], kind_aliases: Dict[str, str]) -> str:
    return _resolve_phase1_named_option(value, kind_templates.keys(), kind_aliases)


def _phase1_season_template_map(entry: dict) -> Dict[str, dict]:
    items = None
    if isinstance(entry, dict):
        items = entry.get("season_templates")
        if not isinstance(items, dict):
            items = entry.get("seasons")
    if not isinstance(items, dict):
        return {}
    result: Dict[str, dict] = {}
    for key, value in items.items():
        key_text = str(key or "").strip()
        if key_text and isinstance(value, dict):
            result[key_text] = value
    return result


def _resolve_phase1_season_name(
    value: str,
    season_templates: Dict[str, dict],
    season_aliases: Dict[str, str],
) -> str:
    options = season_templates.keys() if season_templates else ALLOWED_SCHEDULE_SEASONS
    return _resolve_phase1_named_option(value, options, season_aliases)


def _select_phase1_template_entry(
    text: str,
    schedule_kind: str,
    schedule_season: str,
) -> Tuple[str, str, Dict[str, Any]]:
    del text
    manifest = _load_phase1_template_manifest()
    kind_templates = _phase1_kind_template_map(manifest)
    kind_aliases = _phase1_kind_alias_map(manifest)
    season_aliases = _phase1_season_alias_map(manifest)
    default_entry = manifest.get("default") if isinstance(manifest.get("default"), dict) else {}

    schedule_kind_text = str(schedule_kind or "").strip()
    resolved_kind = _resolve_phase1_kind_name(schedule_kind_text, kind_templates, kind_aliases)
    if not resolved_kind and schedule_kind_text:
        available = "、".join(sorted(kind_templates.keys()))
        raise HTTPException(
            status_code=400,
            detail=f'未识别的方案场景类型:"{schedule_kind_text}"。可用类型:{available}。',
        )

    kind_entry = kind_templates.get(resolved_kind)
    if not isinstance(kind_entry, dict):
        kind_entry = _clone_payload(default_entry) if isinstance(default_entry, dict) else {}
    if not isinstance(kind_entry, dict):
        kind_entry = {}
    if not resolved_kind:
        resolved_kind = str(kind_entry.get("kind") or "").strip()

    season_templates = _phase1_season_template_map(kind_entry)
    schedule_season_text = str(schedule_season or "").strip()
    resolved_season = _resolve_phase1_season_name(schedule_season_text, season_templates, season_aliases)
    if not resolved_season and schedule_season_text:
        available_options = season_templates.keys() if season_templates else ALLOWED_SCHEDULE_SEASONS
        available = "、".join(sorted(available_options))
        raise HTTPException(
            status_code=400,
            detail=f'未识别的作息季节:"{schedule_season_text}"。可用季节:{available}。',
        )

    entry = _clone_payload(kind_entry) if isinstance(kind_entry, dict) else {}
    if not isinstance(entry, dict):
        entry = {}
    entry.pop("season_templates", None)
    entry.pop("seasons", None)
    season_entry = season_templates.get(resolved_season)
    if isinstance(season_entry, dict):
        entry.update(_clone_payload(season_entry))
    if not resolved_season:
        resolved_season = str(
            entry.get("season") or kind_entry.get("default_season") or default_entry.get("season") or ""
        ).strip()
    if resolved_kind:
        entry["kind"] = resolved_kind
    if resolved_season:
        entry["season"] = resolved_season
    return resolved_kind, resolved_season, entry


def _load_phase1_local_schedule_template(source_schedule_name: str) -> dict:
    name = str(source_schedule_name or "").strip()
    if not name:
        raise HTTPException(status_code=500, detail="未配置本地作息模板方案名。")
    payload = _load_phase1_template_catalog()
    if not payload:
        raise HTTPException(status_code=500, detail="未配置可用的作息模板资源。")
    schedule = _find_schedule(payload, name)
    if not isinstance(schedule, dict):
        raise HTTPException(status_code=500, detail=f"本地作息模板方案不存在:{name}")
    if not isinstance(schedule.get("tasks"), list):
        raise HTTPException(status_code=500, detail=f"本地作息模板方案格式无效:{name}")
    return _clone_payload(schedule)


def _load_phase1_local_template(template_file: str) -> dict:
    name = str(template_file or "").strip()
    if not name:
        raise HTTPException(status_code=500, detail="未配置本地作息模板。")
    _warn_legacy_phase1_template_inputs_once()
    path = PHASE1_TEMPLATE_RESOURCE_DIR / name
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"本地作息模板不存在:{name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取本地作息模板失败:{exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        return data
    if isinstance(data, dict) and isinstance(data.get("schedule"), dict):
        schedule = data.get("schedule")
        if isinstance(schedule, dict) and isinstance(schedule.get("tasks"), list):
            return schedule
    if isinstance(data, dict) and isinstance(data.get("schedules"), list):
        for item in data.get("schedules") or []:
            if isinstance(item, dict) and isinstance(item.get("tasks"), list):
                return item
    raise HTTPException(status_code=500, detail=f"本地作息模板格式无效:{name}")


def _phase1_template_media_library_items() -> Dict[str, Any]:
    remote_expected = _remote_enabled()
    if remote_expected:
        try:
            items = [dict(item) for item in _remote_mediainfo_items() if isinstance(item, dict)]
            return {
                "items": items,
                "source": "remote",
                "remote_expected": True,
                "remote_fetch_ok": True,
                "fallback_used": False,
            }
        except Exception:
            return {
                "items": [],
                "source": "remote",
                "remote_expected": True,
                "remote_fetch_ok": False,
                "fallback_used": False,
            }
    payload = _store_get("all_audio")
    return {
        "items": [dict(item) for item in _remote_data_list(payload) if isinstance(item, dict)],
        "source": "local",
        "remote_expected": False,
        "remote_fetch_ok": False,
        "fallback_used": False,
    }


def _normalize_phase1_template_media_library_result(media_library: object) -> Dict[str, Any]:
    if isinstance(media_library, dict):
        raw_items = media_library.get("items")
        items = [dict(item) for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
        source = str(media_library.get("source") or "").strip() or ("remote" if _remote_enabled() else "local")
        remote_expected = bool(media_library.get("remote_expected")) if "remote_expected" in media_library else _remote_enabled()
        remote_fetch_ok_raw = media_library.get("remote_fetch_ok")
        remote_fetch_ok = bool(remote_fetch_ok_raw) if remote_fetch_ok_raw is not None else (source != "remote")
        fallback_used = bool(media_library.get("fallback_used")) if "fallback_used" in media_library else False
        return {
            "items": items,
            "source": source,
            "remote_expected": remote_expected,
            "remote_fetch_ok": remote_fetch_ok,
            "fallback_used": fallback_used,
        }
    items = [dict(item) for item in media_library if isinstance(item, dict)] if isinstance(media_library, list) else []
    return {
        "items": items,
        "source": "remote" if _remote_enabled() else "local",
        "remote_expected": _remote_enabled(),
        "remote_fetch_ok": not _remote_enabled(),
        "fallback_used": False,
    }


_PHASE1_TEMPLATE_MEDIA_EXTENSIONS = (".mp3", ".wav", ".wma", ".aac", ".flac")


def _phase1_strip_media_extension(value: object) -> str:
    media_name = _clean_media_name(value)
    lowered = media_name.lower()
    for suffix in _PHASE1_TEMPLATE_MEDIA_EXTENSIONS:
        if lowered.endswith(suffix):
            return media_name[: -len(suffix)].strip()
    return media_name


def _phase1_template_media_lookup_keys(value: object) -> List[str]:
    keys: List[str] = []
    for candidate in (_clean_media_name(value), _phase1_strip_media_extension(value)):
        normalized = _compact_text(candidate)
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def _phase1_template_media_sort_value(value: object) -> int:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else 10**9


def _phase1_select_template_media_match(matches: List[dict], current_media_id: str) -> Optional[dict]:
    by_id = {
        str(item.get("mediaid") or "").strip(): item
        for item in matches
        if isinstance(item, dict) and str(item.get("mediaid") or "").strip()
    }
    if current_media_id and current_media_id in by_id:
        return by_id[current_media_id]
    ordered = sorted(
        by_id.values(),
        key=lambda item: (
            _phase1_template_media_sort_value(item.get("folderid")),
            _phase1_template_media_sort_value(item.get("mediaid")),
            str(item.get("mediaid") or "").strip(),
        ),
    )
    return ordered[0] if ordered else None


def _phase1_template_media_index(media_items: List[dict]) -> Tuple[Dict[str, List[dict]], Dict[str, dict]]:
    name_map: Dict[str, Dict[str, dict]] = {}
    id_map: Dict[str, dict] = {}
    for item in media_items if isinstance(media_items, list) else []:
        if not isinstance(item, dict):
            continue
        media_id = item.get("mediaid") or item.get("id") or item.get("media_id")
        media_name = _clean_media_name(item.get("name") or item.get("medianame") or item.get("media_name"))
        media_id_text = str(media_id or "").strip()
        normalized_keys = _phase1_template_media_lookup_keys(media_name)
        if not media_id_text or not normalized_keys:
            continue
        folder_id = item.get("folderid")
        folder_id_text = "" if folder_id is None else str(folder_id).strip()
        normalized_item = {"mediaid": media_id_text, "name": media_name, "folderid": folder_id_text}
        id_map[media_id_text] = normalized_item
        for normalized_name in normalized_keys:
            bucket = name_map.setdefault(normalized_name, {})
            bucket[media_id_text] = normalized_item
    return {name: list(items.values()) for name, items in name_map.items()}, id_map


def _phase1_template_task_display_name(task: dict, index: int) -> str:
    if not isinstance(task, dict):
        return f"任务{index + 1}"
    for key in ("taskname", "name", "customName"):
        value = str(task.get(key) or "").strip()
        if value:
            return value
    return f"任务{index + 1}"


def _phase1_template_media_name(task: dict) -> str:
    if not isinstance(task, dict):
        return ""
    return _clean_media_name(task.get("medianame") or task.get("audio") or "")


def _apply_phase1_template_media_binding_to_task(task: dict, resolved_media_id: str, resolved_media_name: str) -> bool:
    if not isinstance(task, dict):
        return False
    changed = False
    media_id_text = str(resolved_media_id or "").strip()
    media_name_text = _clean_media_name(resolved_media_name)
    if str(task.get("mediaid") or "").strip() != media_id_text:
        task["mediaid"] = media_id_text
        changed = True
    if media_name_text and _clean_media_name(task.get("medianame")) != media_name_text:
        task["medianame"] = media_name_text
        changed = True
    if media_name_text and _clean_media_name(task.get("audio")) != media_name_text:
        task["audio"] = media_name_text
        changed = True
    if task.get("mediaids") != [media_id_text]:
        task["mediaids"] = [media_id_text]
        changed = True
    if media_name_text and task.get("medianames") != [media_name_text]:
        task["medianames"] = [media_name_text]
        changed = True
    return changed


def _sync_phase1_template_task_media_fields(target_tasks: object, source_tasks: object) -> bool:
    if not isinstance(target_tasks, list) or not isinstance(source_tasks, list):
        return False
    changed = False
    for target_task, source_task in zip(target_tasks, source_tasks):
        if not isinstance(target_task, dict) or not isinstance(source_task, dict):
            continue
        source_media_id = str(source_task.get("mediaid") or "").strip()
        source_media_name = _clean_media_name(source_task.get("medianame") or source_task.get("audio") or "")
        changed = _apply_phase1_template_media_binding_to_task(
            target_task,
            source_media_id,
            source_media_name,
        ) or changed
    return changed


def _persist_phase1_template_catalog_media_bindings(source_schedule_name: str, template_schedule: dict) -> None:
    payload = _read_json_optional(PHASE1_TEMPLATE_CATALOG_PATH)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"无法读取本地作息模板目录:{source_schedule_name}")
    payload = _normalize_schedules_payload(payload)
    schedule = _find_schedule(payload, source_schedule_name)
    if not isinstance(schedule, dict):
        raise HTTPException(status_code=500, detail=f"未找到需要回写媒体绑定的模板方案:{source_schedule_name}")
    if not _sync_phase1_template_task_media_fields(schedule.get("tasks"), template_schedule.get("tasks")):
        return
    _write_json(PHASE1_TEMPLATE_CATALOG_PATH, payload)


def _persist_phase1_template_file_media_bindings(template_file: str, template_schedule: dict) -> None:
    path = PHASE1_TEMPLATE_RESOURCE_DIR / template_file
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"未找到需要回写媒体绑定的模板文件:{template_file}")
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取本地作息模板失败:{exc}") from exc

    container: Optional[dict] = None
    if isinstance(raw_payload, dict) and isinstance(raw_payload.get("tasks"), list):
        container = raw_payload
    elif isinstance(raw_payload, dict) and isinstance(raw_payload.get("schedule"), dict):
        schedule = raw_payload.get("schedule")
        if isinstance(schedule, dict) and isinstance(schedule.get("tasks"), list):
            container = schedule
    elif isinstance(raw_payload, dict) and isinstance(raw_payload.get("schedules"), list):
        for item in raw_payload.get("schedules") or []:
            if isinstance(item, dict) and isinstance(item.get("tasks"), list):
                container = item
                break
    if not isinstance(container, dict):
        raise HTTPException(status_code=500, detail=f"本地作息模板格式无效:{template_file}")
    if not _sync_phase1_template_task_media_fields(container.get("tasks"), template_schedule.get("tasks")):
        return
    _write_json(path, raw_payload)


def _persist_phase1_template_media_bindings(
    *,
    source_schedule_name: str,
    local_template_file: str,
    template_schedule: dict,
) -> None:
    if source_schedule_name:
        _persist_phase1_template_catalog_media_bindings(source_schedule_name, template_schedule)
        return
    if local_template_file:
        _persist_phase1_template_file_media_bindings(local_template_file, template_schedule)


def _normalize_phase1_template_media_bindings(
    template_schedule: dict,
    *,
    source_schedule_name: str = "",
    local_template_file: str = "",
) -> dict:
    if not isinstance(template_schedule, dict):
        raise HTTPException(status_code=500, detail="本地作息模板内容无效。")
    tasks = template_schedule.get("tasks")
    if not isinstance(tasks, list):
        raise HTTPException(status_code=500, detail="本地作息模板格式无效。")
    if not tasks:
        return {
            "template_media_rebound": [],
            "template_media_rebound_count": 0,
            "template_media_source": "remote" if _remote_enabled() else "local",
            "template_media_remote_expected": _remote_enabled(),
            "template_media_remote_fetch_ok": False,
            "template_media_fallback_used": False,
        }

    media_library = _normalize_phase1_template_media_library_result(_phase1_template_media_library_items())
    media_items = media_library.get("items") or []
    template_media_details = {
        "template_media_source": str(media_library.get("source") or ""),
        "template_media_remote_expected": bool(media_library.get("remote_expected")),
        "template_media_remote_fetch_ok": bool(media_library.get("remote_fetch_ok")),
        "template_media_fallback_used": bool(media_library.get("fallback_used")),
    }
    if bool(media_library.get("remote_expected")) and (
        not bool(media_library.get("remote_fetch_ok")) or not media_items
    ):
        detail = "远端媒体库暂时无法读取或为空，无法安全生成作息。"
        if bool(media_library.get("remote_fetch_ok")):
            detail = "远端媒体库为空，无法安全生成作息。"
        raise _CreateScheduleTemplateMediaError(
            detail,
            user_reason="远端媒体库暂时无法读取或为空，无法安全生成作息。",
            suggestion="请先确认远端媒体库可用后再试一次。",
            failure_code="template_media_remote_unavailable",
            retryable=True,
            **template_media_details,
        )
    media_name_map, media_id_map = _phase1_template_media_index(media_items)
    if not media_name_map and not media_id_map:
        raise _CreateScheduleTemplateMediaError(
            "当前音频库为空或不可用，无法为作息模板绑定媒体。",
            user_reason="目前音频库缺少能够生成作息的媒体，请上传后再试。",
            suggestion="请先同步或上传作息需要的音频资源后再试一次。",
            failure_code="template_media_library_unavailable",
            retryable=True,
            **template_media_details,
        )

    missing_media_names: List[str] = []
    invalid_media_tasks: List[str] = []
    rebound_rows: List[dict] = []
    mutated = False

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        task_name = _phase1_template_task_display_name(task, index)
        desired_media_name = _phase1_template_media_name(task)
        if not desired_media_name:
            invalid_media_tasks.append(task_name)
            continue
        desired_media_keys = _phase1_template_media_lookup_keys(desired_media_name)
        if not desired_media_keys:
            invalid_media_tasks.append(task_name)
            continue
        current_media_id = str(task.get("mediaid") or task.get("media_id") or "").strip()
        current_match = media_id_map.get(current_media_id)
        resolved_match: Optional[dict] = None
        if current_match and set(_phase1_template_media_lookup_keys(current_match.get("name") or "")).intersection(desired_media_keys):
            resolved_match = current_match
        else:
            matches_by_id: Dict[str, dict] = {}
            for normalized_media_name in desired_media_keys:
                for item in media_name_map.get(normalized_media_name) or []:
                    media_id_text = str(item.get("mediaid") or "").strip()
                    if media_id_text:
                        matches_by_id[media_id_text] = item
            matches = list(matches_by_id.values())
            if not matches:
                missing_media_names.append(desired_media_name)
                continue
            resolved_match = _phase1_select_template_media_match(matches, current_media_id)
            if not resolved_match:
                missing_media_names.append(desired_media_name)
                continue
        resolved_media_id = str(resolved_match.get("mediaid") or "").strip()
        resolved_media_name = _clean_media_name(resolved_match.get("name"))
        resolved_folder_id = str(resolved_match.get("folderid") or "").strip()
        previous_media_id = current_media_id
        previous_media_name = desired_media_name
        task_changed = _apply_phase1_template_media_binding_to_task(task, resolved_media_id, resolved_media_name)
        if task_changed:
            mutated = True
            rebound_rows.append(
                {
                    "task_name": task_name,
                    "medianame": resolved_media_name,
                    "old_mediaid": previous_media_id,
                    "mediaid": resolved_media_id,
                    "folderid": resolved_folder_id,
                    "old_medianame": previous_media_name,
                }
            )

    missing_media_names = _unique_list([name for name in missing_media_names if str(name or "").strip()])
    invalid_media_tasks = _unique_list([name for name in invalid_media_tasks if str(name or "").strip()])

    if invalid_media_tasks:
        raise _CreateScheduleTemplateMediaError(
            "模板缺少媒体名称，无法完成作息创建。",
            user_reason="模板缺少媒体名称，无法生成作息。",
            suggestion="请先补全模板中的媒体名称后再试。",
            failure_code="template_media_name_missing",
            retryable=False,
            invalid_media_tasks=invalid_media_tasks,
            template_media_rebound=rebound_rows,
            **template_media_details,
        )
    if missing_media_names:
        raise _CreateScheduleTemplateMediaError(
            f"当前音频库缺少模板所需媒体:{'、'.join(missing_media_names)}",
            user_reason="目前音频库缺少能够生成作息的媒体，请上传后再试。",
            suggestion=f"缺少媒体: {'、'.join(missing_media_names)}。请上传后再试。",
            failure_code="template_media_missing",
            retryable=True,
            missing_media_names=missing_media_names,
            template_media_rebound=rebound_rows,
            **template_media_details,
        )
    if mutated:
        _persist_phase1_template_media_bindings(
            source_schedule_name=source_schedule_name,
            local_template_file=local_template_file,
            template_schedule=template_schedule,
        )

    return {
        "template_media_rebound": rebound_rows,
        "template_media_rebound_count": len(rebound_rows),
        **template_media_details,
    }


def _apply_phase1_template_date_window(task: dict, start_date: Optional[date], end_date: Optional[date]) -> bool:
    if not start_date:
        return False
    original_start = str(task.get("startdate") or "")
    original_end = str(task.get("enddate") or "")
    task["startdate"] = start_date.strftime("%Y-%m-%d")
    if end_date:
        task["enddate"] = end_date.strftime("%Y-%m-%d")
    else:
        old_start = _parse_iso_date(original_start)
        old_end = _parse_iso_date(original_end) or old_start
        span_days = max((old_end - old_start).days, 0) if old_start and old_end else 0
        task["enddate"] = (start_date + timedelta(days=span_days)).strftime("%Y-%m-%d")
    return original_start != str(task.get("startdate") or "") or original_end != str(task.get("enddate") or "")


def _build_phase1_local_schedule_from_template(
    template_schedule: dict,
    final_name: str,
    start_date: Optional[date],
    end_date: Optional[date],
) -> Tuple[dict, int]:
    schedule = _clone_payload(template_schedule)
    if not isinstance(schedule, dict):
        raise HTTPException(status_code=500, detail="本地作息模板内容无效。")
    schedule["schedule_name"] = final_name
    if "name" in schedule:
        schedule["name"] = final_name
    schedule["status"] = "启用"
    tasks = schedule.get("tasks")
    if not isinstance(tasks, list):
        tasks = []

    normalized_tasks: List[dict] = []
    updated_count = 0
    for raw_task in tasks:
        if not isinstance(raw_task, dict):
            continue
        task = _clone_payload(raw_task)
        if not isinstance(task, dict):
            continue
        for field in ("taskid", "id", "all", "count", "start", "state", "enablestate", "taskstate"):
            task.pop(field, None)
        task["sechename"] = final_name
        task["info"] = final_name
        weekdays = task.get("weekdays")
        if isinstance(weekdays, list) and weekdays:
            normalized_weekdays = [str(day) for day in weekdays if day]
            task["weekdays"] = normalized_weekdays
            if not task.get("execmode") or str(task.get("execmode")) in {"0", ""}:
                task["execmode"] = _execmode_from_weekdays(normalized_weekdays)
        if _apply_phase1_template_date_window(task, start_date, end_date):
            updated_count += 1
        normalized_tasks.append(task)
    schedule["tasks"] = normalized_tasks
    return schedule, updated_count


def _commit_phase1_created_schedule(new_schedule: dict, *, sync_remote: bool) -> dict:
    schedule_name = str(new_schedule.get("schedule_name") or new_schedule.get("name") or "").strip()
    _normalize_schedule_task_terminals([new_schedule], force_terminal_lookup=True)
    try:
        snapshot_payload = _clone_payload(_load_schedules_payload())
    except HTTPException:
        snapshot_payload = {"schedules": []}
    new_payload = _clone_payload(snapshot_payload)
    if not isinstance(new_payload, dict):
        new_payload = {"schedules": []}
    schedules = new_payload.get("schedules")
    if not isinstance(schedules, list):
        schedules = []
    schedules.append(new_schedule)
    new_payload["schedules"] = schedules
    _commit_payload_with_rollback(
        new_payload,
        snapshot_payload if isinstance(snapshot_payload, dict) else {"schedules": []},
        sync_schedules=sync_remote,
        sync_broadcasts=False,
        sync_livecasts=False,
        target_schedule_names=[schedule_name] if sync_remote and schedule_name else None,
    )
    saved_schedule = _find_schedule(new_payload, schedule_name)
    return saved_schedule or new_schedule


_ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS = "all_playback_terminals"
_ASSISTANT_CREATE_SCHEDULE_PLAYBACK_TERMINAL_TYPES = {"11", "24"}
_ASSISTANT_CREATE_SCHEDULE_DEFAULT_STATUS = "停用"


def _assistant_create_schedule_playback_terminal_items() -> List[dict]:
    if _remote_enabled():
        try:
            source_items = _remote_terminalinfo_items()
        except Exception:
            source_items = []
    else:
        try:
            source_items = _store_terminalinfo_items()
        except Exception:
            source_items = []
    playback_items: List[dict] = []
    seen_terminal_ids: set[str] = set()
    for item in source_items if isinstance(source_items, list) else []:
        if not isinstance(item, dict):
            continue
        terminal_type = str(item.get("type") or "").strip()
        if terminal_type not in _ASSISTANT_CREATE_SCHEDULE_PLAYBACK_TERMINAL_TYPES:
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if terminal_id in (None, "", 0, "0"):
            continue
        terminal_id_str = str(terminal_id).strip()
        if not terminal_id_str or terminal_id_str in seen_terminal_ids:
            continue
        seen_terminal_ids.add(terminal_id_str)
        playback_items.append(dict(item))
    return playback_items


def _assistant_apply_created_schedule_defaults(schedule: Optional[dict]) -> None:
    if not isinstance(schedule, dict):
        return
    schedule["status"] = _ASSISTANT_CREATE_SCHEDULE_DEFAULT_STATUS


def _assistant_explicit_taskterminal_bindings(
    terminal_ids: List[str],
    terminal_lookup: Optional[dict] = None,
) -> List[dict]:
    lookup = terminal_lookup if isinstance(terminal_lookup, dict) else {}
    bindings: List[dict] = []
    normalized_terminal_ids = _unique_list([
        str(terminal_id).strip()
        for terminal_id in (terminal_ids or [])
        if str(terminal_id).strip() and str(terminal_id).strip() != "0"
    ])
    for terminal_id in normalized_terminal_ids:
        lookup_item = lookup.get(str(terminal_id), {}) if isinstance(lookup, dict) else {}
        terminal_name = (
            str((lookup_item.get("name") if isinstance(lookup_item, dict) else "") or terminal_id).strip()
        )
        zone_candidates = sorted(
            _lookup_zone_candidates(lookup_item),
            key=_zone_candidate_sort_key,
        ) if isinstance(lookup_item, dict) else []
        if not zone_candidates:
            zone_candidates = [
                {
                    "zone": str((lookup_item.get("zone") if isinstance(lookup_item, dict) else "") or "").strip(),
                    "zone_name": str((lookup_item.get("zone_name") if isinstance(lookup_item, dict) else "") or "").strip(),
                }
            ]
        for candidate in zone_candidates:
            binding = {
                "terminalid": str(terminal_id),
                "groupid": _coerce_int(candidate.get("zone"), 0),
                "groupid_present": True,
            }
            if terminal_name:
                binding["terminalname"] = terminal_name
            bindings.append(binding)
    return _normalize_taskterminal_bindings(bindings)


def _rebind_created_schedule_to_terminal_items(new_schedule: dict, terminal_items: List[dict]) -> dict:
    if not isinstance(new_schedule, dict):
        return new_schedule
    normalized_items: List[dict] = []
    terminal_ids: List[str] = []
    seen_terminal_ids: set[str] = set()
    for item in terminal_items if isinstance(terminal_items, list) else []:
        if not isinstance(item, dict):
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if terminal_id in (None, "", 0, "0"):
            continue
        terminal_id_str = str(terminal_id).strip()
        if not terminal_id_str or terminal_id_str in seen_terminal_ids:
            continue
        seen_terminal_ids.add(terminal_id_str)
        normalized_items.append(dict(item))
        terminal_ids.append(terminal_id_str)
    tasks = new_schedule.get("tasks")
    if not isinstance(tasks, list) or not terminal_ids:
        return new_schedule
    terminal_lookup = _terminal_lookup_from_items(normalized_items)
    zone_items: List[dict] = []
    if _remote_enabled():
        try:
            zone_items = _fetch_enriched_zone_items()
            _enrich_lookup_zones_from_terzone(terminal_lookup, zone_items)
        except Exception:
            zone_items = []
    assistant_bindings = _assistant_explicit_taskterminal_bindings(terminal_ids, terminal_lookup)
    first_terminal_id = terminal_ids[0]
    resolved_terminal_names: List[str] = []
    for terminal_id in terminal_ids:
        lookup_item = terminal_lookup.get(str(terminal_id)) if isinstance(terminal_lookup, dict) else None
        if not isinstance(lookup_item, dict):
            continue
        resolved_name = str(lookup_item.get("name") or "").strip()
        if resolved_name:
            resolved_terminal_names.append(resolved_name)
    resolved_terminal_names = _unique_list(resolved_terminal_names)
    first_terminal_name = resolved_terminal_names[0] if resolved_terminal_names else ""
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task["taskterminal"] = _clone_payload(assistant_bindings)
        task.pop("taskTerminal", None)
        task["terminalids"] = list(terminal_ids)
        task["liveterminalid"] = _coerce_int(first_terminal_id, 0)
        task["location"] = []
        task.pop("terminalnames", None)
        task.pop("liveterminalname", None)
        _apply_task_terminal_fields(task, terminal_ids, terminal_lookup, zone_items=zone_items)
        if resolved_terminal_names:
            task["terminalnames"] = list(resolved_terminal_names)
            task["liveterminalname"] = first_terminal_name
    return new_schedule


def _parse_time_offset_days(value: str) -> Optional[int]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "半年" in text:
        return 183
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(年|个月|月|周|星期|天|日)", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "年":
        return int(round(number * 365))
    if unit in {"月", "个月"}:
        return int(round(number * 30))
    if unit in {"周", "星期"}:
        return int(round(number * 7))
    return int(round(number))


def _split_slot_values(value: object) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        values: List[str] = []
        for item in value:
            values.extend(_split_slot_values(item))
        return _unique_list([item for item in values if item])
    text = str(value).strip()
    if not text:
        return []
    normalized = re.sub(r"\s*(和|与|跟|及)\s*", ",", text)
    parts = re.split(r"[,\uff0c\u3001;/|]", normalized)
    cleaned = [part.strip() for part in parts if part and part.strip()]
    if cleaned:
        return _unique_list(cleaned)
    return [text]


def _first_int_from_text(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    text = str(value)
    match = re.search(r"-?\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except Exception:
        return None


_PLAY_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_PLAY_CN_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}
_PLAY_DURATION_PAIR_RE = re.compile(
    r"(?P<num>\d+|[零〇一二两三四五六七八九十百千万]+)\s*"
    r"(?P<unit>小时|钟头|时|hr|hrs|hour|hours|h|分钟|分|min|mins|minute|minutes|秒钟|秒|sec|secs|second|seconds|s)",
    flags=re.IGNORECASE,
)
_PLAY_DURATION_PHRASE_RE = re.compile(
    r"(?P<phrase>(?:(?:\d+|[零〇一二两三四五六七八九十百千万]+)\s*"
    r"(?:小时|钟头|时|hr|hrs|hour|hours|h|分钟|分|min|mins|minute|minutes|秒钟|秒|sec|secs|second|seconds|s)\s*)+)",
    flags=re.IGNORECASE,
)
_PLAY_COUNT_PHRASE_RE = re.compile(
    r"(?P<phrase>(?P<num>\d+|[零〇一二两三四五六七八九十百千万]+)\s*(?:次|遍|轮))"
)


def _parse_play_chinese_number(token: str) -> Optional[int]:
    text = str(token or "").strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except Exception:
            return None
    if not re.fullmatch(r"[零〇一二两三四五六七八九十百千万]+", text):
        return None
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _PLAY_CN_DIGITS:
            number = _PLAY_CN_DIGITS[char]
            continue
        unit = _PLAY_CN_UNITS.get(char)
        if unit is None:
            return None
        if unit == 10000:
            section = (section + (number or 0)) * unit
            total += section
            section = 0
            number = 0
            continue
        if number == 0:
            number = 1
        section += number * unit
        number = 0
    return total + section + number


def _parse_play_number(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.search(r"-?\d+", text)
    if match:
        try:
            return int(match.group(0))
        except Exception:
            return None
    match = re.search(r"[零〇一二两三四五六七八九十百千万]+", text)
    if not match:
        return None
    parsed = _parse_play_chinese_number(match.group(0))
    if parsed is None:
        return None
    return int(parsed)


def _has_play_duration_unit(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if _parse_hms_duration_seconds(text) is not None:
        return True
    return bool(_PLAY_DURATION_PAIR_RE.search(text))


def _has_play_count_unit(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(_PLAY_COUNT_PHRASE_RE.search(text))


def _find_duration_phrase_in_text(text: str, preferred_value: Optional[int] = None) -> str:
    source = str(text or "").strip()
    if not source:
        return ""
    for match in _PLAY_DURATION_PHRASE_RE.finditer(source):
        phrase = str(match.group("phrase") or "").strip()
        if not phrase:
            continue
        if preferred_value is None:
            return phrase
        first_value = _parse_play_number(phrase)
        total_seconds = _duration_seconds_from_text(phrase)
        if first_value == preferred_value or total_seconds == preferred_value:
            return phrase
    clock_match = re.search(r"\b\d{1,2}:\d{1,2}(?::\d{1,2})?\b", source)
    if clock_match:
        return clock_match.group(0)
    return ""


def _find_count_phrase_in_text(text: str, preferred_value: Optional[int] = None) -> str:
    source = str(text or "").strip()
    if not source:
        return ""
    for match in _PLAY_COUNT_PHRASE_RE.finditer(source):
        phrase = str(match.group("phrase") or "").strip()
        if not phrase:
            continue
        if preferred_value is None:
            return phrase
        value = _parse_play_number(match.group("num"))
        if value == preferred_value:
            return phrase
    return ""


def _resolve_play_duration_text(text: str, raw_value: object) -> str:
    raw_text = str(raw_value or "").strip()
    if raw_text and _has_play_duration_unit(raw_text):
        return raw_text
    preferred_value = _parse_play_number(raw_text) if raw_text else None
    inferred = _find_duration_phrase_in_text(text, preferred_value)
    if inferred:
        return inferred
    return raw_text


def _resolve_play_count_text(text: str, raw_value: object) -> str:
    raw_text = str(raw_value or "").strip()
    if raw_text and _has_play_count_unit(raw_text):
        return raw_text
    preferred_value = _parse_play_number(raw_text) if raw_text else None
    inferred = _find_count_phrase_in_text(text, preferred_value)
    if inferred:
        return inferred
    return raw_text


def _parse_play_mode_slots(slots: dict) -> Tuple[int, int]:
    duration_raw = _slot_text(slots, "play_duration", "duration", "play_length")
    count_raw = _slot_text(slots, "play_count", "count")
    duration_value = _parse_play_number(duration_raw)
    count_value = _parse_play_number(count_raw)
    if duration_value is not None and duration_value > 0:
        return max(1, duration_value), 1
    if count_value is not None and count_value > 0:
        return max(1, count_value), 2
    return 1, 2


def _duration_seconds_from_text(raw: object) -> Optional[int]:
    text = str(raw or "").strip()
    if not text:
        return None
    clock_seconds = _parse_hms_duration_seconds(text)
    if clock_seconds is not None:
        return max(1, clock_seconds)
    total_seconds = 0
    matched = False
    for match in _PLAY_DURATION_PAIR_RE.finditer(text):
        value = _parse_play_number(match.group("num"))
        if value is None or value <= 0:
            continue
        matched = True
        unit = str(match.group("unit") or "").strip().lower()
        if unit in {"小时", "钟头", "时", "h", "hr", "hrs", "hour", "hours"}:
            total_seconds += value * 3600
        elif unit in {"分钟", "分", "min", "mins", "minute", "minutes"}:
            total_seconds += value * 60
        else:
            total_seconds += value
    if matched:
        return max(1, total_seconds)
    value = _parse_play_number(text)
    if value is None or value <= 0:
        return None
    return max(1, value * 60)


def _describe_play_mode(duration_raw: object, count_raw: object, playtype: int, timelength: int, playlength: int) -> str:
    if playtype == 2:
        raw_text = str(count_raw or "").strip()
        return raw_text or f"{timelength}次"
    raw_text = str(duration_raw or "").strip()
    if raw_text:
        return raw_text
    if playlength % 3600 == 0 and playlength >= 3600:
        return f"{playlength // 3600}小时"
    if playlength % 60 == 0 and playlength >= 60:
        return f"{playlength // 60}分钟"
    return f"{playlength}秒"


def _parse_volume_slot(slots: dict) -> int:
    raw = _slot_text(slots, "volume", "VOLUME")
    value = _first_int_from_text(raw)
    if value is None:
        return 50
    return max(0, min(100, value))


def _text_has_explicit_terminal_reference(text: str, terminal_id: object) -> bool:
    terminal_id_text = str(terminal_id or "").strip()
    if not terminal_id_text or not terminal_id_text.isdigit():
        return False
    escaped = re.escape(terminal_id_text)
    patterns = [
        rf"终端\s*{escaped}(?!\d)",
        rf"{escaped}\s*号?\s*终端",
        rf"(?:id|ID)\s*[:=：]?\s*{escaped}(?!\d)",
        rf"terminal\s*[:=：]?\s*{escaped}(?!\d)",
        rf"设备\s*{escaped}(?!\d)",
        rf"{escaped}\s*号?\s*设备",
    ]
    raw_text = str(text or "")
    return any(re.search(pattern, raw_text, flags=re.IGNORECASE) for pattern in patterns)


def _sanitize_play_media_slots(text: str, slots: dict) -> dict:
    sanitized = dict(slots or {})
    volume_raw = _slot_text(sanitized, "volume", "VOLUME")
    volume_value = _first_int_from_text(volume_raw)
    if volume_value is None:
        return sanitized

    for key in ("terminal_id", "scope_id"):
        values = _slot_values(sanitized, key)
        if not values:
            continue
        numeric_values = [_first_int_from_text(value) for value in values]
        if not numeric_values or any(value != volume_value for value in numeric_values):
            continue
        if any(_text_has_explicit_terminal_reference(text, value) for value in values):
            continue
        sanitized.pop(key, None)
    return sanitized


def _remote_zone_items() -> list:
    resp = _remote_request("GET", "/terminal/terzone")
    items = _remote_data_list(resp)
    if items:
        return items
    if isinstance(resp, dict):
        for key in ("zone", "zones", "items"):
            value = resp.get(key)
            if isinstance(value, list):
                return value
    return []


def _zone_item_name(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("zonename") or item.get("name") or "").strip()


def _zone_exists(zone_name: str, items: list) -> bool:
    target = _compact_text(str(zone_name or ""))
    if not target:
        return False
    for item in items:
        name = _zone_item_name(item if isinstance(item, dict) else {})
        if not name:
            continue
        if _compact_text(name) == target:
            return True
    return False


def _short_error_text(detail: object, limit: int = 260) -> str:
    text = str(detail or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _build_zone_create_payloads(zone_name: str) -> List[dict]:
    zone_text = str(zone_name or "").strip()
    # SDK requires: Id (0 for new), Zonename, Demo
    return [{"id": 0, "zonename": zone_text, "description": ""}]


def _try_create_zone_remote(zone_name: str) -> Tuple[bool, List[dict]]:
    attempts: List[dict] = []
    payload_variants = _build_zone_create_payloads(zone_name)
    for payload in payload_variants:
        attempt: Dict[str, object] = {
            "encoding": "json",
            "payload_keys": list(payload.keys()),
        }
        try:
            _remote_request(
                "POST",
                "/terminal/terzone",
                json_body=payload,
                form_body=None,
                allow_form_retry=False,
            )
        except HTTPException as exc:
            attempt["ok"] = False
            attempt["error"] = _short_error_text(exc.detail)
            attempts.append(attempt)
            continue
        try:
            if _zone_exists(zone_name, _remote_zone_items()):
                attempt["ok"] = True
                attempts.append(attempt)
                return True, attempts
            attempt["ok"] = False
            attempt["error"] = "request succeeded but zone not visible after creation"
        except HTTPException as exc:
            attempt["ok"] = False
            attempt["error"] = f"verify failed: {_short_error_text(exc.detail)}"
        attempts.append(attempt)
    try:
        if _zone_exists(zone_name, _remote_zone_items()):
            return True, attempts
    except HTTPException as exc:
        attempts.append({"ok": False, "error": f"final verify failed: {_short_error_text(exc.detail)}"})
    return False, attempts


def _resolve_zone_ids(zone_names: List[str]) -> Tuple[List[str], List[str]]:
    if not zone_names:
        return [], []
    items = _remote_zone_items()
    resolved: List[str] = []
    missing: List[str] = []
    for raw_name in zone_names:
        name = str(raw_name).strip()
        if not name:
            continue
        if name.isdigit():
            resolved.append(name)
            continue
        compact_target = _compact_text(name)
        matched_id: Optional[str] = None
        for item in items:
            if not isinstance(item, dict):
                continue
            zone_name = str(item.get("zonename") or item.get("name") or "").strip()
            zone_id = item.get("id") or item.get("zoneid")
            if zone_id is None:
                continue
            if zone_name == name:
                matched_id = str(zone_id)
                break
            compact_name = _compact_text(zone_name)
            if compact_target and compact_name and (compact_target == compact_name or compact_target in compact_name):
                matched_id = str(zone_id)
                break
        if matched_id:
            resolved.append(matched_id)
        else:
            missing.append(name)
    return _unique_list(resolved), _unique_list(missing)


def _zone_terminal_ids(zone_id: str) -> List[str]:
    if not zone_id:
        return []
    encoded = urllib.parse.quote(str(zone_id), safe="")
    resp = _remote_request("GET", f"/terminal/zoneterminal/{encoded}")
    items = _remote_data_list(resp)
    ids: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if terminal_id in (None, "", 0, "0"):
            continue
        ids.append(str(terminal_id))
    return _unique_list(ids)


def _zone_ids_present(zone_ids: List[str]) -> set[str]:
    items = _remote_zone_items()
    present: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        zone_id = item.get("id") or item.get("zoneid")
        if zone_id in (None, "", 0, "0"):
            continue
        present.add(str(zone_id))
    return present


def _build_remove_zone_terminal_payload(zone_ids: List[str], terminal_ids: List[str]) -> dict:
    data = []
    for zone_id in zone_ids:
        zone_id_value = _coerce_int(zone_id, 0)
        for terminal_id in terminal_ids:
            terminal_id_value = _coerce_int(terminal_id, 0)
            # Swagger uses eventitem(id=terminal id, taskid=zone id), but the
            # deployed remote service also expects terminalid in DELETE bodies.
            data.append(
                {
                    "id": terminal_id_value,
                    "terminalid": terminal_id_value,
                    "taskid": zone_id_value,
                }
            )
    return {"data": data}


def _zone_verify_timeout_detail(action: str) -> str:
    window_seconds = max(0.0, (REMOTE_ZONE_VERIFY_ATTEMPTS - 1) * REMOTE_ZONE_VERIFY_DELAY_SECONDS)
    return (
        f"request acknowledged but remote {action} state did not converge "
        f"within {window_seconds:.1f}s"
    )


def _wait_for_zone_ids_removed(zone_ids: List[str]) -> None:
    last_error: Optional[HTTPException] = None
    for attempt in range(1, REMOTE_ZONE_VERIFY_ATTEMPTS + 1):
        try:
            remaining_zone_ids = _zone_ids_present(zone_ids)
        except HTTPException as exc:
            last_error = exc
            remaining_zone_ids = set(zone_ids)
        else:
            if not any(zone_id in remaining_zone_ids for zone_id in zone_ids):
                return
        if attempt < REMOTE_ZONE_VERIFY_ATTEMPTS and REMOTE_ZONE_VERIFY_DELAY_SECONDS > 0:
            time.sleep(float(REMOTE_ZONE_VERIFY_DELAY_SECONDS))
    if last_error is not None:
        raise HTTPException(status_code=502, detail=f"{_zone_verify_timeout_detail('zone deletion')}: {last_error.detail}")
    raise HTTPException(status_code=502, detail=_zone_verify_timeout_detail("zone deletion"))


def _wait_for_zone_membership_state(zone_ids: List[str], terminal_ids: List[str], *, should_contain: bool) -> None:
    last_error: Optional[HTTPException] = None
    for attempt in range(1, REMOTE_ZONE_VERIFY_ATTEMPTS + 1):
        try:
            verified = _verify_zone_membership(zone_ids, terminal_ids, should_contain=should_contain)
        except HTTPException as exc:
            last_error = exc
            verified = False
        else:
            if verified:
                return
        if attempt < REMOTE_ZONE_VERIFY_ATTEMPTS and REMOTE_ZONE_VERIFY_DELAY_SECONDS > 0:
            time.sleep(float(REMOTE_ZONE_VERIFY_DELAY_SECONDS))
    action = "zone membership update"
    if last_error is not None:
        raise HTTPException(status_code=502, detail=f"{_zone_verify_timeout_detail(action)}: {last_error.detail}")
    raise HTTPException(status_code=502, detail=_zone_verify_timeout_detail(action))


def _delete_zone_remote_checked(zone_ids: List[str]) -> None:
    payload = {"id": ",".join(zone_ids)}
    resp = _remote_request(
        "DELETE",
        "/terminal/terzone",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )
    _ensure_remote_write_ack(resp, "delete zone")
    _wait_for_zone_ids_removed(zone_ids)


def _update_zone_terminal_membership_remote_checked(
    zone_ids: List[str],
    terminal_ids: List[str],
    *,
    add: bool,
    action_name: str,
) -> None:
    if add:
        data = []
        for zone_id in zone_ids:
            for terminal_id in terminal_ids:
                data.append(
                    {
                        "id": _coerce_int(zone_id, 0),
                        "zone": 255,
                        "terminalid": _coerce_int(terminal_id, 0),
                        "terminalzone": 0,
                    }
                )
        payload = {"data": data}
        method = "POST"
    else:
        payload = _build_remove_zone_terminal_payload(zone_ids, terminal_ids)
        method = "DELETE"
    resp = _remote_request(
        method,
        "/terminal/zoneterminal",
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )
    _ensure_remote_write_ack(resp, f"{action_name} zoneterminal")
    _wait_for_zone_membership_state(zone_ids, terminal_ids, should_contain=add)


def _verify_zone_membership(zone_ids: List[str], terminal_ids: List[str], *, should_contain: bool) -> bool:
    normalized_terminal_ids = {str(item) for item in terminal_ids if str(item)}
    if not normalized_terminal_ids:
        return True
    for zone_id in zone_ids:
        current_ids = set(_zone_terminal_ids(zone_id))
        if should_contain and not normalized_terminal_ids.issubset(current_ids):
            return False
        if not should_contain and normalized_terminal_ids & current_ids:
            return False
    return True


def _resolve_terminal_ids_for_play_media(slots: dict, *, expand_zones: bool = True) -> Tuple[List[str], Dict[str, List[str]]]:
    unresolved: Dict[str, List[str]] = {"zone_name": [], "terminal_name": [], "terminal_id": []}
    resolved_ids: List[str] = []
    has_pre_resolved_terminal = False

    for term_id_text in _slot_values(slots, "terminal_matched_id"):
        if term_id_text.isdigit():
            resolved_ids.append(term_id_text)
            has_pre_resolved_terminal = True
        else:
            unresolved["terminal_id"].append(term_id_text)

    for term_id_text in _slot_values(slots, "terminal_id", "scope_id"):
        if term_id_text.isdigit():
            resolved_ids.append(term_id_text)
        else:
            unresolved["terminal_id"].append(term_id_text)

    terminal_map = _remote_terminal_map()
    if not has_pre_resolved_terminal:
        for terminal_name in _slot_values(slots, "terminal_name", "SCOPE", "LOC"):
            if terminal_name.isdigit():
                resolved_ids.append(terminal_name)
                continue
            candidate = terminal_map.get(terminal_name)
            if candidate is None:
                compact = _compact_text(terminal_name)
                if compact:
                    candidate = terminal_map.get(compact)
            if candidate is None:
                unresolved["terminal_name"].append(terminal_name)
                continue
            resolved_ids.append(str(candidate))

    if expand_zones:
        zone_names = _slot_values(slots, "zone_name")
        zone_items: List[dict] = []
        if zone_names:
            try:
                zone_items = _remote_zone_items()
            except HTTPException:
                unresolved["zone_name"].extend(zone_names)
                zone_items = []
                zone_names = []
        for raw_name in zone_names:
            zone_name = str(raw_name).strip()
            if not zone_name:
                continue
            matched_id = ""
            if zone_name.isdigit():
                matched_id = zone_name
            else:
                compact_target = _compact_text(zone_name)
                for item in zone_items:
                    if not isinstance(item, dict):
                        continue
                    candidate_name = str(item.get("zonename") or item.get("name") or "").strip()
                    candidate_id = item.get("id") or item.get("zoneid")
                    if candidate_id is None:
                        continue
                    if candidate_name == zone_name:
                        matched_id = str(candidate_id)
                        break
                    compact_name = _compact_text(candidate_name)
                    if compact_target and compact_name and (
                        compact_target == compact_name or compact_target in compact_name
                    ):
                        matched_id = str(candidate_id)
                        break
            if not matched_id:
                unresolved["zone_name"].append(zone_name)
                continue
            try:
                zone_terminal_ids = _zone_terminal_ids(matched_id)
            except HTTPException:
                unresolved["zone_name"].append(zone_name)
                continue
            if not zone_terminal_ids:
                unresolved["zone_name"].append(zone_name)
                continue
            resolved_ids.extend(zone_terminal_ids)

    resolved_ids = [item for item in _unique_list(resolved_ids) if item and str(item) != "0"]
    return resolved_ids, {
        key: _unique_list(values) for key, values in unresolved.items() if values
    }


def _commit_payload_with_rollback(
    new_payload: dict,
    snapshot_payload: dict,
    sync_schedules: bool = True,
    sync_broadcasts: bool = True,
    sync_livecasts: bool = True,
    target_schedule_names: Optional[List[str]] = None,
    schedule_sync_delta: Optional[dict] = None,
    rollback_schedule_sync_delta: Optional[dict] = None,
) -> None:
    forward_schedule_sync_delta = schedule_sync_delta
    reverse_schedule_sync_delta = rollback_schedule_sync_delta
    if sync_schedules:
        if forward_schedule_sync_delta is None:
            forward_schedule_sync_delta = _schedule_sync_delta(snapshot_payload, new_payload)
        if reverse_schedule_sync_delta is None:
            reverse_schedule_sync_delta = _schedule_sync_delta(new_payload, snapshot_payload)
    try:
        _touch_generated_at(new_payload)
        _save_schedules_payload(
            new_payload,
            sync_schedules=sync_schedules,
            sync_broadcasts=sync_broadcasts,
            sync_livecasts=sync_livecasts,
            target_schedule_names=target_schedule_names,
            schedule_sync_delta=forward_schedule_sync_delta,
        )
    except Exception as exc:
        try:
            rollback_payload = _clone_payload(snapshot_payload)
            _touch_generated_at(rollback_payload)
            _save_schedules_payload(
                rollback_payload,
                sync_schedules=sync_schedules,
                sync_broadcasts=sync_broadcasts,
                sync_livecasts=sync_livecasts,
                target_schedule_names=target_schedule_names,
                schedule_sync_delta=reverse_schedule_sync_delta,
            )
        except Exception as rollback_exc:
            raise HTTPException(
                status_code=500,
                detail=f"Operation failed and rollback failed: {exc}; rollback_error: {rollback_exc}",
            ) from rollback_exc
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=500, detail=f"Operation failed: {exc}") from exc


def _resolve_weekday_anchor(raw: str, weekday: str) -> Optional[date]:
    """将单个 weekday 文本解析为 date 对象。"""
    resolved = _date_for_weekday(raw, weekday)
    if not resolved:
        return None
    return resolved.date() if hasattr(resolved, "date") else resolved


def _weekday_is_ambiguous(weekday_raw: str, resolved_date: date) -> bool:
    """判断周几是否有歧义:原文无"这周/下周"前缀且解析出的日期已过。"""
    explicit_prefixes = ["这周", "这个周", "这星期", "这个星期", "这礼拜",
                         "下周", "下星期", "下礼拜", "下个周", "下个星期", "下个礼拜",
                         "下下周", "下下星期", "下下礼拜", "上周", "上星期", "上礼拜"]
    has_explicit = any(p in weekday_raw for p in explicit_prefixes)
    if has_explicit:
        return False
    return resolved_date < date.today()


def _build_weekday_disambig_prompt(ambiguous_items: List[dict]) -> str:
    """为有歧义的周几生成追问文案。"""
    parts: List[str] = []
    for item in ambiguous_items:
        wd = item["weekday"]
        this_date = item["this_week_date"]
        next_date = item["next_week_date"]
        label = str(item.get("label") or item.get("anchor_key") or "该时间")
        parts.append(
            f'{label}选这{wd}({this_date.strftime("%m月%d日")})还是下{wd}({next_date.strftime("%m月%d日")})'
        )
    if len(parts) == 1:
        return "您是指" + parts[0] + "?"
    return "检测到多个周几都有歧义,请分别确认:" + "；".join(parts) + "。也可以直接回复“都这周”或“都下周”。"


def _weekday_disambig_label(intent: str, anchor_key: str) -> str:
    label_map = {
        ("move_schedule", "source_anchor"): "源时间",
        ("move_schedule", "target_anchor"): "目标时间",
        ("swap_schedule", "anchor_a"): "A时间",
        ("swap_schedule", "anchor_b"): "B时间",
        ("cancel_schedule", "source_anchor"): "时间",
    }
    return label_map.get((intent, anchor_key), anchor_key)


def _parse_weekday_disambig_choice(raw_text: str) -> Optional[str]:
    this_tokens = ["都这周", "这周", "这个周", "这星期", "这个星期", "这礼拜", "本周", "本星期", "本礼拜"]
    next_tokens = ["都下周", "下周", "下个周", "下星期", "下个星期", "下礼拜", "下个礼拜"]
    if any(token in raw_text for token in next_tokens):
        return "next"
    if any(token in raw_text for token in this_tokens):
        return "this"
    return None


def _parse_weekday_disambig_choices(raw_text: str, ambiguous_items: List[dict]) -> Dict[str, str]:
    choices: Dict[str, str] = {}
    global_choice: Optional[str] = None
    if "都下周" in raw_text:
        global_choice = "next"
    elif "都这周" in raw_text or "都本周" in raw_text:
        global_choice = "this"
    if global_choice:
        for item in ambiguous_items:
            choices[str(item.get("anchor_key") or "")] = global_choice
        return choices

    if len(ambiguous_items) == 1:
        single_choice = _parse_weekday_disambig_choice(raw_text)
        if single_choice:
            anchor_key = str(ambiguous_items[0].get("anchor_key") or "")
            if anchor_key:
                choices[anchor_key] = single_choice
        return choices

    for item in ambiguous_items:
        anchor_key = str(item.get("anchor_key") or "")
        label = str(item.get("label") or "")
        aliases = [label, anchor_key]
        if anchor_key == "source_anchor":
            aliases.extend(["源时间", "源", "source"])
        elif anchor_key == "target_anchor":
            aliases.extend(["目标时间", "目标", "target"])
        elif anchor_key == "anchor_a":
            aliases.extend(["A", "A时间", "甲"])
        elif anchor_key == "anchor_b":
            aliases.extend(["B", "B时间", "乙"])
        matched_choice: Optional[str] = None
        for alias in [item for item in aliases if item]:
            escaped = re.escape(alias)
            patterns = [
                rf"{escaped}[^\n，,。；;:：]{{0,12}}(这周|这个周|这星期|这个星期|这礼拜|本周|本星期|本礼拜)",
                rf"{escaped}[^\n，,。；;:：]{{0,12}}(下周|下个周|下星期|下个星期|下礼拜|下个礼拜)",
                rf"(这周|这个周|这星期|这个星期|这礼拜|本周|本星期|本礼拜)[^\n，,。；;:：]{{0,12}}{escaped}",
                rf"(下周|下个周|下星期|下个星期|下礼拜|下个礼拜)[^\n，,。；;:：]{{0,12}}{escaped}",
            ]
            for pattern in patterns:
                match = re.search(pattern, raw_text, flags=re.IGNORECASE)
                if not match:
                    continue
                matched_choice = _parse_weekday_disambig_choice(match.group(0))
                if matched_choice:
                    break
            if matched_choice:
                break
        if matched_choice and anchor_key:
            choices[anchor_key] = matched_choice
    return choices


def _resolve_weekday_anchors_to_dates(action: dict) -> Optional[dict]:
    """当用户选择一次性且 anchor 为 weekday 时,自动将周几解析为最近的具体日期。

    对 move_schedule: 解析 source_anchor / target_anchor
    对 swap_schedule: 解析 anchor_a / anchor_b
    返回更新后的 action 副本,若无法解析返回 None。
    若存在歧义(周几已过且无明确前缀),返回的 dict 中会带 weekday_ambiguous 标记。
    """
    import copy

    intent = action.get("intent", "")
    updated = copy.deepcopy(action)
    ambiguous_items: List[dict] = []

    def _resolve_and_check(anchor: dict, anchor_key: str) -> bool:
        """解析 anchor 中的 weekday,返回 False 表示解析失败。"""
        if anchor.get("kind") != "weekday":
            return True
        weekday = anchor.get("weekday", "")
        raw = anchor.get("raw", weekday)
        resolved = _resolve_weekday_anchor(raw, weekday)
        if not resolved:
            return False
        anchor["kind"] = "date"
        anchor["date"] = resolved
        if _weekday_is_ambiguous(raw, resolved):
            next_week_date = resolved + timedelta(days=7)
            ambiguous_items.append({
                "anchor_key": anchor_key,
                "label": _weekday_disambig_label(intent, anchor_key),
                "weekday": weekday,
                "this_week_date": resolved,
                "next_week_date": next_week_date,
            })
        return True

    if intent == "move_schedule":
        src = updated.get("source_anchor") or {}
        tgt = updated.get("target_anchor") or {}
        if not _resolve_and_check(src, "source_anchor"):
            return None
        if not _resolve_and_check(tgt, "target_anchor"):
            return None
        updated["source_anchor"] = src
        updated["target_anchor"] = tgt
        updated["date_specific"] = True

    elif intent == "swap_schedule":
        anc_a = updated.get("anchor_a") or {}
        anc_b = updated.get("anchor_b") or {}
        if not _resolve_and_check(anc_a, "anchor_a"):
            return None
        if not _resolve_and_check(anc_b, "anchor_b"):
            return None
        updated["anchor_a"] = anc_a
        updated["anchor_b"] = anc_b
        updated["date_specific"] = True

    elif intent == "cancel_schedule":
        anchor = updated.get("source_anchor") or {}
        if not _resolve_and_check(anchor, "source_anchor"):
            return None
        updated["source_anchor"] = anchor
        updated["date_specific"] = True
    else:
        return None

    if ambiguous_items:
        updated["weekday_ambiguous"] = True
        updated["ambiguous_items"] = ambiguous_items

    return updated


def _handle_pending_action(text: str) -> Optional[Tuple[str, Dict[str, Any], List[dict]]]:
    pending_action = _get_pending_action()
    if not pending_action:
        return None

    if _pending_expired(pending_action):
        _clear_pending_action()
        return ("刚才的操作已超时,请重新说明。", _pending_action_overrides(pending_action), [])

    raw_text = str(text or "")
    if any(k in raw_text for k in ["算了", "不用了", "停止", "取消", "没事了"]):
        _clear_pending_action()
        return ("好的,如果还有什么指令都可以跟我说。", _pending_action_overrides(pending_action), [])

    if pending_action.get("kind") == "target_disambiguation":
        action = pending_action
        prompt = str(action.get("confirm_prompt") or "请从候选项中确认一个目标。")
        choice = _select_pending_choice(raw_text, action.get("choices") or [])
        if not choice:
            return (prompt, _pending_action_overrides(action, slots=dict(action.get("slots") or {})), [])
        original_pending = _clone_payload(action)
        _clear_pending_action()
        next_slots = dict(action.get("slots") or {})
        for key, value in (choice.get("slot_updates") or {}).items():
            next_slots[key] = _clone_payload(value)
        try:
            action_reply = _apply_phase1_intent(
                str(action.get("intent") or ""),
                str(action.get("original_text") or raw_text),
                next_slots,
            )
        except Exception:
            _set_pending_action(original_pending)
            raise
        if not action_reply:
            _set_pending_action(original_pending)
            return (prompt, _pending_action_overrides(action, slots=next_slots), [])
        reply, overrides, action_log = action_reply
        merged = dict(overrides or {})
        diagnostics = merged.get("diagnostics") if isinstance(merged.get("diagnostics"), list) else None
        missing_slots = list(merged.get("missing_slots") or [])
        merged.update(_pending_action_overrides(action, slots=next_slots, missing_slots=missing_slots, diagnostics=diagnostics))
        return (reply, merged, action_log)

    # ── 周几歧义消解:用户回答"这周X"或"下周X"后,更新 anchor 并继续执行 ──
    if pending_action.get("weekday_disambiguation"):
        action = pending_action
        _clear_pending_action()
        ambiguous_items = action.get("ambiguous_items") or []
        choices = _parse_weekday_disambig_choices(raw_text, ambiguous_items)
        unresolved_items: List[dict] = []
        for item in ambiguous_items:
            anchor_key = str(item.get("anchor_key") or "")
            choice = choices.get(anchor_key)
            if not choice:
                unresolved_items.append(item)
                continue
            chosen_date = item["next_week_date"] if choice == "next" else item["this_week_date"]
            anchor = action.get(anchor_key) or {}
            anchor["date"] = chosen_date
            action[anchor_key] = anchor
        if unresolved_items:
            action["weekday_disambiguation"] = True
            action["ambiguous_items"] = unresolved_items
            action["weekday_ambiguous"] = True
            _set_pending_action(action)
            return (_build_weekday_disambig_prompt(unresolved_items), _pending_action_overrides(action), [])
        action.pop("weekday_disambiguation", None)
        action.pop("ambiguous_items", None)
        action.pop("weekday_ambiguous", None)
        # 伪装成正常的 pending action 并重新调用自身以执行 once 流程
        action["date_specific"] = True
        _set_pending_action(action)
        return _handle_pending_action("一次性")

    mode = _detect_apply_mode(raw_text)
    if not mode:
        prompt = str(pending_action.get("confirm_prompt") or "请确认要一次性执行还是永久生效?")
        return (prompt, _pending_action_overrides(pending_action), [])

    action = _clone_payload(pending_action) if isinstance(pending_action, dict) else pending_action
    _clear_pending_action()

    payload = _clone_payload(_load_schedules_payload())
    schedule_name = str(action.get("schedule_name") or "")
    schedule = _find_schedule(payload, schedule_name) if schedule_name else None

    handled_intents = {"move_schedule", "swap_schedule", "cancel_schedule"}
    if action.get("intent") in handled_intents and schedule_name and not schedule:
        return ("\u672a\u627e\u5230\u5bf9\u5e94\u7684\u4f5c\u606f\u65b9\u6848\uff0c\u8bf7\u91cd\u65b0\u786e\u8ba4\u3002", {"missing_slots": []}, [])

    if mode == "once" and action.get("intent") in handled_intents and not action.get("date_specific"):
        # 尝试自动将 weekday anchor 解析为最近的具体日期
        resolved = _resolve_weekday_anchors_to_dates(action)
        if not resolved:
            _set_pending_action(action)  # 保留上下文,让用户可以补充日期后继续
            return ("一次性操作需要具体日期,请补充日期后再执行。", {"missing_slots": []}, [])
        if resolved.get("weekday_ambiguous"):
            # 有歧义(周几已过),追问用户确认
            prompt = _build_weekday_disambig_prompt(resolved.get("ambiguous_items", []))
            resolved["weekday_disambiguation"] = True
            _set_pending_action(resolved)
            return (prompt, {"missing_slots": []}, [])
        action = resolved
    if (
        mode == "permanent"
        and action.get("intent") in {"move_schedule", "swap_schedule"}
        and bool(action.get("date_specific"))
        and bool(action.get("contains_recurring"))
    ):
        _set_pending_action(action)
        return (
            '检测到匹配结果包含长期循环任务。为避免整段日期窗口被整体平移,日期表达下这类任务仅支持"一次性"。请回复"一次性"继续,或回复"取消"。',
            {"missing_slots": []},
            [],
        )

    response_diagnostics: List[dict] = []
    response_diagnostic_id = ""
    try:
        if action.get("intent") == "move_schedule":
            source_anchor = action.get("source_anchor") or {}
            target_anchor = action.get("target_anchor") or {}
            task_groups = [
                item for item in (action.get("task_groups") or [])
                if isinstance(item, dict) and str(item.get("schedule_name") or "").strip()
            ]
            if len(task_groups) > 1 or str(action.get("schedule_scope") or "").strip() == "enabled_all":
                time_start_str = str(action.get("time_start") or "")
                time_end_str = str(action.get("time_end") or "")
                if mode == "once":
                    source_date = source_anchor.get("date")
                    target_date = target_anchor.get("date")
                    if not source_date or not target_date:
                        return ("一次性挪动需要具体日期,请补充日期。", {"missing_slots": []}, [])
                    day_delta = (target_date - source_date).days
                    action_logs: List[dict] = []
                    total_tasks = 0
                    response_diagnostics = []
                    for group in task_groups:
                        group_schedule_name = str(group.get("schedule_name") or "").strip()
                        group_schedule = _find_schedule(payload, group_schedule_name)
                        if not group_schedule:
                            return (f"未找到作息方案：{group_schedule_name}。", {"missing_slots": []}, [])
                        group_task_ids = _unique_list([str(item).strip() for item in (group.get("task_ids") or []) if str(item).strip()])
                        group_tasks = [
                            task
                            for task in (group_schedule.get("tasks", []) or [])
                            if isinstance(task, dict) and _task_id(task) in group_task_ids
                        ]
                        if not group_tasks:
                            continue
                        fallback = datetime.combine(source_date, datetime.min.time())
                        old_start, old_end = _tasks_window(group_tasks, fallback)
                        if not old_start or not old_end:
                            return ("无法计算源时段,请重新描述要挪动的任务。", {"missing_slots": []}, [])
                        once_action = {
                            "schedule_name": group_schedule_name,
                            "task_ids": group_task_ids,
                            "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "new_time_start": (old_start + timedelta(days=day_delta)).strftime("%Y-%m-%d %H:%M:%S"),
                            "new_time_end": (old_end + timedelta(days=day_delta)).strftime("%Y-%m-%d %H:%M:%S"),
                            "date_specific": True,
                        }
                        diagnostic_id = _new_diagnostic_id()
                        entry, _ = _execute_once_migrate_action(
                            once_action,
                            group_schedule,
                            dry_run=not _remote_enabled(),
                            diagnostics=response_diagnostics,
                            diagnostic_id=diagnostic_id,
                        )
                        total_tasks += len(group_task_ids)
                        action_logs.append(
                            _build_action_log(
                                "move_schedule",
                                group_schedule_name,
                                group_task_ids,
                                once_action["time_start"],
                                once_action["time_end"],
                                True,
                                new_time_start=once_action["new_time_start"],
                                new_time_end=once_action["new_time_end"],
                                mode="once",
                                details={
                                    "source_time": action.get("source_text", ""),
                                    "target_time": action.get("target_text", ""),
                                    "override_id": entry.get("id"),
                                    "shadow_task_ids": entry.get("shadow_task_ids", []),
                                },
                            )
                        )
                    if not action_logs:
                        return ("没有找到可操作的任务,请重新确认时间条件。", {"missing_slots": []}, [])
                    return (
                        f"已对 {len(action_logs)} 个启用中的作息方案执行一次性挪动,共 {total_tasks} 条任务。",
                        _pending_action_overrides(
                            action,
                            missing_slots=[],
                            diagnostics=_public_remote_diagnostics(response_diagnostics),
                        ),
                        action_logs,
                    )

                touched_schedule_names: List[str] = []
                action_logs = []
                total_tasks = 0
                next_task_id = _coerce_int(_next_schedule_task_id(payload), 1)
                for group in task_groups:
                    group_schedule_name = str(group.get("schedule_name") or "").strip()
                    group_schedule = _find_schedule(payload, group_schedule_name)
                    if not group_schedule:
                        return (f"未找到作息方案：{group_schedule_name}。", {"missing_slots": []}, [])
                    group_task_ids = _unique_list([str(item).strip() for item in (group.get("task_ids") or []) if str(item).strip()])
                    moved_tasks: List[dict] = []
                    kept_tasks: List[dict] = []
                    moved_old_ids: List[str] = []
                    for task in group_schedule.get("tasks", []) or []:
                        if not isinstance(task, dict):
                            continue
                        task_id = _task_id(task)
                        if task_id in group_task_ids:
                            moved = _apply_move_anchor_to_task(task, source_anchor, target_anchor)
                            if moved:
                                moved["taskid"] = str(next_task_id)
                                moved["id"] = str(next_task_id)
                                moved["sechename"] = group_schedule_name
                                next_task_id += 1
                                moved_tasks.append(moved)
                                moved_old_ids.append(task_id)
                                continue
                        kept_tasks.append(task)
                    if not moved_tasks:
                        continue
                    group_schedule["tasks"] = kept_tasks + moved_tasks
                    touched_schedule_names.append(group_schedule_name)
                    total_tasks += len(moved_tasks)
                    action_logs.append(
                        _build_action_log(
                            "move_schedule",
                            group_schedule_name,
                            moved_old_ids,
                            mode="permanent",
                            details={
                                "source_time": action.get("source_text", ""),
                                "target_time": action.get("target_text", ""),
                                "count": len(moved_tasks),
                            },
                        )
                    )
                if not action_logs:
                    return ("未找到可挪动的任务。", {"missing_slots": []}, [])
                _touch_generated_at(payload)
                _save_schedules_payload(
                    payload,
                    target_schedule_names=_unique_list(touched_schedule_names),
                    sync_broadcasts=False,
                    sync_livecasts=False,
                )
                return (
                    f"已将 {len(action_logs)} 个启用中的作息方案里的任务从 {action.get('source_text', '')} 挪到 {action.get('target_text', '')},共 {total_tasks} 条。",
                    _pending_action_overrides(action, missing_slots=[]),
                    action_logs,
                )
            task_ids = _unique_list([str(item).strip() for item in action.get("task_ids", []) if str(item).strip()])
            tasks = [
                task
                for task in (schedule.get("tasks", []) or [])
                if isinstance(task, dict) and _task_id(task) in task_ids
            ]
            if not tasks:
                return ("没有找到可操作的任务,请重新确认时间条件。", {"missing_slots": []}, [])

            if mode == "once":
                source_date = source_anchor.get("date")
                target_date = target_anchor.get("date")
                if not source_date or not target_date:
                    return ("一次性挪动需要具体日期,请补充日期。", {"missing_slots": []}, [])
                fallback = datetime.combine(source_date, datetime.min.time())
                old_start, old_end = _tasks_window(tasks, fallback)
                if not old_start or not old_end:
                    return ("无法计算源时段,请重新描述要挪动的任务。", {"missing_slots": []}, [])
                day_delta = (target_date - source_date).days
                new_start = old_start + timedelta(days=day_delta)
                new_end = old_end + timedelta(days=day_delta)
                once_action = {
                    "schedule_name": schedule_name,
                    "task_ids": task_ids,
                    "time_start": old_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "time_end": old_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "new_time_start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "new_time_end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "date_specific": True,
                }
                response_diagnostics = []
                response_diagnostic_id = _new_diagnostic_id()
                entry, reply = _execute_once_migrate_action(
                    once_action,
                    schedule,
                    dry_run=not _remote_enabled(),
                    diagnostics=response_diagnostics,
                    diagnostic_id=response_diagnostic_id,
                )
                action_log = _build_action_log(
                    "move_schedule",
                    schedule_name,
                    task_ids,
                    once_action["time_start"],
                    once_action["time_end"],
                    True,
                    new_time_start=once_action["new_time_start"],
                    new_time_end=once_action["new_time_end"],
                    mode="once",
                    details={
                        "source_time": action.get("source_text", ""),
                        "target_time": action.get("target_text", ""),
                        "override_id": entry.get("id"),
                        "shadow_task_ids": entry.get("shadow_task_ids", []),
                    },
                )
                return (
                    reply,
                    _pending_action_overrides(
                        action,
                        missing_slots=[],
                        diagnostics=_public_remote_diagnostics(response_diagnostics),
                    ),
                    [action_log],
                )

            moved_tasks: List[dict] = []
            kept_tasks: List[dict] = []
            moved_old_ids: List[str] = []
            next_task_id = _coerce_int(_next_schedule_task_id(payload), 1)
            for task in schedule.get("tasks", []) or []:
                if not isinstance(task, dict):
                    continue
                task_id = _task_id(task)
                if task_id in task_ids:
                    moved = _apply_move_anchor_to_task(task, source_anchor, target_anchor)
                    if moved:
                        moved["taskid"] = str(next_task_id)
                        moved["id"] = str(next_task_id)
                        moved["sechename"] = schedule_name
                        next_task_id += 1
                        moved_tasks.append(moved)
                        moved_old_ids.append(task_id)
                        continue
                kept_tasks.append(task)

            if not moved_tasks:
                return ("未找到可挪动的任务。", {"missing_slots": []}, [])

            schedule["tasks"] = kept_tasks + moved_tasks
            _touch_generated_at(payload)
            _save_schedules_payload(payload, target_schedule_names=[schedule_name], sync_broadcasts=False, sync_livecasts=False)
            action_log = _build_action_log(
                "move_schedule",
                schedule_name,
                moved_old_ids,
                mode="permanent",
                details={
                    "source_time": action.get("source_text", ""),
                    "target_time": action.get("target_text", ""),
                    "count": len(moved_tasks),
                },
            )
            return (
                f"已将 {schedule_name} 中 {action.get('source_text', '')} 的任务挪到 {action.get('target_text', '')},共 {len(moved_tasks)} 条。",
                _pending_action_overrides(action, missing_slots=[]),
                [action_log],
            )

        if action.get("intent") == "swap_schedule":
            anchor_a = action.get("anchor_a") or {}
            anchor_b = action.get("anchor_b") or {}
            task_groups = [
                item for item in (action.get("task_groups") or [])
                if isinstance(item, dict) and str(item.get("schedule_name") or "").strip()
            ]
            if len(task_groups) > 1 or str(action.get("schedule_scope") or "").strip() == "enabled_all":
                time_start_str = str(action.get("time_start") or "")
                time_end_str = str(action.get("time_end") or "")
                if mode == "once":
                    date_a = anchor_a.get("date")
                    date_b = anchor_b.get("date")
                    if not date_a or not date_b:
                        return ("一次性对调需要具体日期,请补充日期。", {"missing_slots": []}, [])
                    action_logs: List[dict] = []
                    total_tasks = 0
                    response_diagnostics = []
                    for group in task_groups:
                        group_schedule_name = str(group.get("schedule_name") or "").strip()
                        group_schedule = _find_schedule(payload, group_schedule_name)
                        if not group_schedule:
                            return (f"未找到作息方案：{group_schedule_name}。", {"missing_slots": []}, [])
                        group_task_ids_a = _unique_list([str(item).strip() for item in (group.get("task_ids_a") or []) if str(item).strip()])
                        group_task_ids_b = _unique_list([str(item).strip() for item in (group.get("task_ids_b") or []) if str(item).strip()])
                        task_map = {
                            _task_id(task): task
                            for task in (group_schedule.get("tasks", []) or [])
                            if isinstance(task, dict) and _task_id(task)
                        }
                        group_tasks_a = [task_map[task_id] for task_id in group_task_ids_a if task_id in task_map]
                        group_tasks_b = [task_map[task_id] for task_id in group_task_ids_b if task_id in task_map]
                        if not group_tasks_a or not group_tasks_b:
                            continue
                        a_start, a_end = _tasks_window(group_tasks_a, datetime.combine(date_a, datetime.min.time()))
                        b_start, b_end = _tasks_window(group_tasks_b, datetime.combine(date_b, datetime.min.time()))
                        if not a_start or not a_end or not b_start or not b_end:
                            return ("无法计算对调时段,请重新描述。", {"missing_slots": []}, [])
                        a_start_minutes = anchor_a.get("time_start_minutes")
                        b_start_minutes = anchor_b.get("time_start_minutes")
                        a_end_minutes = anchor_a.get("time_end_minutes")
                        b_end_minutes = anchor_b.get("time_end_minutes")
                        if isinstance(a_start_minutes, (int, float)):
                            a_start = datetime.combine(date_a, datetime.min.time()) + timedelta(minutes=int(a_start_minutes))
                        if isinstance(b_start_minutes, (int, float)):
                            b_start = datetime.combine(date_b, datetime.min.time()) + timedelta(minutes=int(b_start_minutes))
                        if isinstance(a_end_minutes, (int, float)):
                            a_end = datetime.combine(date_a, datetime.min.time()) + timedelta(minutes=int(a_end_minutes))
                        if isinstance(b_end_minutes, (int, float)):
                            b_end = datetime.combine(date_b, datetime.min.time()) + timedelta(minutes=int(b_end_minutes))
                        once_action = {
                            "schedule_name": group_schedule_name,
                            "source_task_ids": group_task_ids_a,
                            "target_task_ids": group_task_ids_b,
                            "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "date_specific": True,
                        }
                        diagnostic_id = _new_diagnostic_id()
                        entry, _ = _execute_once_swap_action(
                            once_action,
                            group_schedule,
                            dry_run=not _remote_enabled(),
                            diagnostics=response_diagnostics,
                            diagnostic_id=diagnostic_id,
                        )
                        total_tasks += len(group_task_ids_a) + len(group_task_ids_b)
                        action_logs.append(
                            _build_action_log(
                                "swap_schedule",
                                group_schedule_name,
                                group_task_ids_a + group_task_ids_b,
                                once_action["source_time_start"],
                                once_action["source_time_end"],
                                True,
                                new_time_start=once_action["target_time_start"],
                                new_time_end=once_action["target_time_end"],
                                mode="once",
                                details={
                                    "source_time": action.get("source_text", ""),
                                    "target_time": action.get("target_text", ""),
                                    "override_id": entry.get("id"),
                                    "shadow_task_ids": entry.get("shadow_task_ids", []),
                                },
                            )
                        )
                    if not action_logs:
                        return ("未找到可对调的任务。", {"missing_slots": []}, [])
                    return (
                        f"已对 {len(action_logs)} 个启用中的作息方案执行一次性对调,共 {total_tasks} 条任务。",
                        _pending_action_overrides(
                            action,
                            missing_slots=[],
                            diagnostics=_public_remote_diagnostics(response_diagnostics),
                        ),
                        action_logs,
                    )

                touched_schedule_names: List[str] = []
                action_logs = []
                total_tasks = 0
                for group in task_groups:
                    group_schedule_name = str(group.get("schedule_name") or "").strip()
                    group_schedule = _find_schedule(payload, group_schedule_name)
                    if not group_schedule:
                        return (f"未找到作息方案：{group_schedule_name}。", {"missing_slots": []}, [])
                    group_task_ids_a = _unique_list([str(item).strip() for item in (group.get("task_ids_a") or []) if str(item).strip()])
                    group_task_ids_b = _unique_list([str(item).strip() for item in (group.get("task_ids_b") or []) if str(item).strip()])
                    tracked_ids = set(group_task_ids_a + group_task_ids_b)
                    changed = 0
                    changed_ids: List[str] = []
                    tasks = group_schedule.get("tasks")
                    if not isinstance(tasks, list):
                        tasks = []
                        group_schedule["tasks"] = tasks
                    for idx, task in enumerate(tasks):
                        if not isinstance(task, dict):
                            continue
                        if _task_id(task) not in tracked_ids:
                            continue
                        swapped = _apply_swap_anchor_to_task(task, anchor_a, anchor_b)
                        if not swapped:
                            continue
                        tasks[idx] = swapped
                        changed += 1
                        task_id = _task_id(task)
                        if task_id:
                            changed_ids.append(task_id)
                    if changed <= 0:
                        continue
                    touched_schedule_names.append(group_schedule_name)
                    total_tasks += changed
                    action_logs.append(
                        _build_action_log(
                            "swap_schedule",
                            group_schedule_name,
                            changed_ids,
                            mode="permanent",
                            details={
                                "source_time": action.get("source_text", ""),
                                "target_time": action.get("target_text", ""),
                                "count": changed,
                            },
                        )
                    )
                if not action_logs:
                    return ("未找到可对调的任务。", {"missing_slots": []}, [])
                _touch_generated_at(payload)
                _save_schedules_payload(
                    payload,
                    target_schedule_names=_unique_list(touched_schedule_names),
                    sync_broadcasts=False,
                    sync_livecasts=False,
                )
                return (
                    f"已将 {len(action_logs)} 个启用中的作息方案里的任务完成对调,共 {total_tasks} 条。",
                    _pending_action_overrides(action, missing_slots=[]),
                    action_logs,
                )
            task_ids_a = _unique_list([str(item).strip() for item in action.get("task_ids_a", []) if str(item).strip()])
            task_ids_b = _unique_list([str(item).strip() for item in action.get("task_ids_b", []) if str(item).strip()])
            if not task_ids_a or not task_ids_b:
                return ("对调任务缺少源/目标任务,请重新确认。", {"missing_slots": []}, [])

            task_map = {
                _task_id(task): task
                for task in (schedule.get("tasks", []) or [])
                if isinstance(task, dict) and _task_id(task)
            }
            tasks_a = [task_map[task_id] for task_id in task_ids_a if task_id in task_map]
            tasks_b = [task_map[task_id] for task_id in task_ids_b if task_id in task_map]
            if not tasks_a or not tasks_b:
                return ("未找到可对调的任务。", {"missing_slots": []}, [])

            if mode == "once":
                date_a = anchor_a.get("date")
                date_b = anchor_b.get("date")
                if not date_a or not date_b:
                    return ("一次性对调需要具体日期,请补充日期。", {"missing_slots": []}, [])
                a_start, a_end = _tasks_window(tasks_a, datetime.combine(date_a, datetime.min.time()))
                b_start, b_end = _tasks_window(tasks_b, datetime.combine(date_b, datetime.min.time()))
                if not a_start or not a_end or not b_start or not b_end:
                    return ("无法计算对调时段,请重新描述。", {"missing_slots": []}, [])

                # 按用户输入的时间窗起点/终点执行 once swap(而不是按匹配任务最早时间)。
                a_start_minutes = anchor_a.get("time_start_minutes")
                b_start_minutes = anchor_b.get("time_start_minutes")
                a_end_minutes = anchor_a.get("time_end_minutes")
                b_end_minutes = anchor_b.get("time_end_minutes")
                if isinstance(a_start_minutes, (int, float)):
                    a_start = datetime.combine(date_a, datetime.min.time()) + timedelta(minutes=int(a_start_minutes))
                if isinstance(b_start_minutes, (int, float)):
                    b_start = datetime.combine(date_b, datetime.min.time()) + timedelta(minutes=int(b_start_minutes))
                if isinstance(a_end_minutes, (int, float)):
                    a_end = datetime.combine(date_a, datetime.min.time()) + timedelta(minutes=int(a_end_minutes))
                if isinstance(b_end_minutes, (int, float)):
                    b_end = datetime.combine(date_b, datetime.min.time()) + timedelta(minutes=int(b_end_minutes))
                once_action = {
                    "schedule_name": schedule_name,
                    "source_task_ids": task_ids_a,
                    "target_task_ids": task_ids_b,
                    "source_time_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_time_end": a_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_time_start": b_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_time_end": b_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "date_specific": True,
                }
                response_diagnostics = []
                response_diagnostic_id = _new_diagnostic_id()
                entry, reply = _execute_once_swap_action(
                    once_action,
                    schedule,
                    dry_run=not _remote_enabled(),
                    diagnostics=response_diagnostics,
                    diagnostic_id=response_diagnostic_id,
                )
                action_log = _build_action_log(
                    "swap_schedule",
                    schedule_name,
                    task_ids_a + task_ids_b,
                    once_action["source_time_start"],
                    once_action["source_time_end"],
                    True,
                    new_time_start=once_action["target_time_start"],
                    new_time_end=once_action["target_time_end"],
                    mode="once",
                    details={
                        "source_time": action.get("source_text", ""),
                        "target_time": action.get("target_text", ""),
                        "override_id": entry.get("id"),
                        "shadow_task_ids": entry.get("shadow_task_ids", []),
                    },
                )
                return (
                    reply,
                    _pending_action_overrides(
                        action,
                        missing_slots=[],
                        diagnostics=_public_remote_diagnostics(response_diagnostics),
                    ),
                    [action_log],
                )

            changed = 0
            changed_ids: List[str] = []
            tracked_ids = set(task_ids_a + task_ids_b)
            tasks = schedule.get("tasks")
            if not isinstance(tasks, list):
                tasks = []
                schedule["tasks"] = tasks
            for idx, task in enumerate(tasks):
                if not isinstance(task, dict):
                    continue
                if _task_id(task) not in tracked_ids:
                    continue
                swapped = _apply_swap_anchor_to_task(task, anchor_a, anchor_b)
                if not swapped:
                    continue
                tasks[idx] = swapped
                changed += 1
                task_id = _task_id(task)
                if task_id:
                    changed_ids.append(task_id)

            if changed <= 0:
                return ("未找到可对调的任务。", {"missing_slots": []}, [])

            _touch_generated_at(payload)
            _save_schedules_payload(payload, target_schedule_names=[schedule_name], sync_broadcasts=False, sync_livecasts=False)
            action_log = _build_action_log(
                "swap_schedule",
                schedule_name,
                changed_ids,
                mode="permanent",
                details={
                    "source_time": action.get("source_text", ""),
                    "target_time": action.get("target_text", ""),
                    "count": changed,
                },
            )
            return (
                f"已将 {schedule_name} 中 {action.get('source_text', '')} 与 {action.get('target_text', '')} 的任务完成对调,共 {changed} 条。",
                _pending_action_overrides(action, missing_slots=[]),
                [action_log],
            )

        if action.get("intent") == "cancel_schedule":
            task_groups = [
                item for item in (action.get("task_groups") or [])
                if isinstance(item, dict) and str(item.get("schedule_name") or "").strip()
            ]
            if len(task_groups) > 1 or str(action.get("schedule_scope") or "").strip() == "enabled_all":
                time_start_str = str(action.get("time_start") or "")
                time_end_str = str(action.get("time_end") or "")
                if mode == "once":
                    action_logs: List[dict] = []
                    total_tasks = 0
                    response_diagnostics = []
                    for group in task_groups:
                        group_schedule_name = str(group.get("schedule_name") or "").strip()
                        group_schedule = _find_schedule(payload, group_schedule_name)
                        if not group_schedule:
                            return (f"未找到作息方案：{group_schedule_name}。", {"missing_slots": []}, [])
                        group_task_ids = _unique_list([str(item).strip() for item in (group.get("task_ids") or []) if str(item).strip()])
                        if not group_task_ids:
                            continue
                        group_time_start_str, group_time_end_str = _resolve_cancel_once_time_range(
                            action,
                            group_schedule,
                            group_task_ids,
                        )
                        if not group_time_start_str or not group_time_end_str:
                            return ("一次性取消需要具体时间段,请补充开始和结束时间。", {"missing_slots": []}, [])
                        once_action = {
                            "schedule_name": group_schedule_name,
                            "task_ids": group_task_ids,
                            "time_start": group_time_start_str,
                            "time_end": group_time_end_str,
                        }
                        diagnostic_id = _new_diagnostic_id()
                        entry, _ = _execute_once_cancel_action(
                            once_action,
                            group_schedule,
                            dry_run=not _remote_enabled(),
                            diagnostics=response_diagnostics,
                            diagnostic_id=diagnostic_id,
                        )
                        total_tasks += len(group_task_ids)
                        action_logs.append(
                            _build_action_log(
                                "cancel_schedule",
                                group_schedule_name,
                                group_task_ids,
                                group_time_start_str,
                                group_time_end_str,
                                True,
                                mode="once",
                                details={
                                    "task_name": action.get("task_name", ""),
                                    "override_id": entry.get("id"),
                                },
                            )
                        )
                    if not action_logs:
                        return ("没有找到可取消的任务,请重新确认。", {"missing_slots": []}, [])
                    return (
                        f"已对 {len(action_logs)} 个启用中的作息方案执行一次性取消,共 {total_tasks} 条任务。",
                        _pending_action_overrides(
                            action,
                            missing_slots=[],
                            diagnostics=_public_remote_diagnostics(response_diagnostics),
                        ),
                        action_logs,
                    )

                removal_plans: List[dict] = []
                total_removed = 0
                for group in task_groups:
                    group_schedule_name = str(group.get("schedule_name") or "").strip()
                    group_schedule = _find_schedule(payload, group_schedule_name)
                    if not group_schedule:
                        return (f"未找到作息方案：{group_schedule_name}。", {"missing_slots": []}, [])
                    group_task_ids = _unique_list([str(item).strip() for item in (group.get("task_ids") or []) if str(item).strip()])
                    tasks = group_schedule.get("tasks")
                    if not isinstance(tasks, list):
                        continue
                    removed_tasks = [t for t in tasks if isinstance(t, dict) and _task_id(t) in group_task_ids]
                    kept_tasks = [t for t in tasks if not isinstance(t, dict) or _task_id(t) not in group_task_ids]
                    if not removed_tasks:
                        continue
                    removal_plans.append(
                        {
                            "schedule": group_schedule,
                            "schedule_name": group_schedule_name,
                            "task_ids": group_task_ids,
                            "removed_tasks": removed_tasks,
                            "kept_tasks": kept_tasks,
                        }
                    )
                    total_removed += len(removed_tasks)
                if not removal_plans:
                    return ("未找到可删除的任务。", {"missing_slots": []}, [])

                if _remote_enabled():
                    remote_delete_batches: List[Tuple[str, List[str]]] = []
                    for plan in removal_plans:
                        remote_delete_ids, unresolved_remote_tasks = _resolve_remote_delete_task_ids(
                            str(plan.get("schedule_name") or ""),
                            list(plan.get("removed_tasks") or []),
                        )
                        if unresolved_remote_tasks:
                            unresolved_preview = "、".join(unresolved_remote_tasks[:5])
                            if len(unresolved_remote_tasks) > 5:
                                unresolved_preview += f" 等{len(unresolved_remote_tasks)}条任务"
                            return (
                                f"永久删除失败:以下任务无法确定远端任务ID,已取消本地保存:{unresolved_preview}。",
                                {"missing_slots": []},
                                [],
                            )
                        if not remote_delete_ids:
                            return ("永久删除失败:未能定位任何可删除的远端任务ID,已取消本地保存。", {"missing_slots": []}, [])
                        remote_delete_batches.append((str(plan.get("schedule_name") or ""), remote_delete_ids))
                    for group_schedule_name, remote_delete_ids in remote_delete_batches:
                        _batch_delete_parallel(remote_delete_ids, _remote_delete_task, label=f"cancel_permanent_{group_schedule_name}")

                action_logs = []
                touched_schedule_names: List[str] = []
                for plan in removal_plans:
                    group_schedule = plan.get("schedule") or {}
                    group_schedule_name = str(plan.get("schedule_name") or "")
                    group_schedule["tasks"] = list(plan.get("kept_tasks") or [])
                    touched_schedule_names.append(group_schedule_name)
                    action_logs.append(
                        _build_action_log(
                            "cancel_schedule",
                            group_schedule_name,
                            list(plan.get("task_ids") or []),
                            time_start_str,
                            time_end_str,
                            bool(action.get("date_specific")),
                            mode="permanent",
                            details={
                                "task_name": action.get("task_name", ""),
                                "removed_count": len(plan.get("removed_tasks") or []),
                            },
                        )
                    )
                _touch_generated_at(payload)
                _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
                return (
                    f"已在 {len(action_logs)} 个启用中的作息方案中永久删除 {total_removed} 条任务。",
                    {"missing_slots": []},
                    action_logs,
                )
            task_ids = _unique_list(
                [str(item).strip() for item in action.get("task_ids", []) if str(item).strip()]
            )
            if not task_ids:
                return ("\u6ca1\u6709\u627e\u5230\u53ef\u53d6\u6d88\u7684\u4efb\u52a1\uff0c\u8bf7\u91cd\u65b0\u786e\u8ba4\u3002", {"missing_slots": []}, [])

            time_start_str = str(action.get("time_start") or "")
            time_end_str = str(action.get("time_end") or "")

            if mode == "once":
                # \u4e00\u6b21\u6027\u53d6\u6d88\uff1a\u901a\u8fc7 enabletask \u5b9a\u65f6\u7981\u7528/\u6062\u590d
                time_start_str, time_end_str = _resolve_cancel_once_time_range(action, schedule or {}, task_ids)
                if not time_start_str or not time_end_str:
                    return ("\u4e00\u6b21\u6027\u53d6\u6d88\u9700\u8981\u5177\u4f53\u65f6\u95f4\u6bb5\uff0c\u8bf7\u8865\u5145\u5f00\u59cb\u548c\u7ed3\u675f\u65f6\u95f4\u3002", {"missing_slots": []}, [])
                action["time_start"] = time_start_str
                action["time_end"] = time_end_str
                once_action = {
                    "schedule_name": schedule_name,
                    "task_ids": task_ids,
                    "time_start": time_start_str,
                    "time_end": time_end_str,
                }
                response_diagnostics = []
                response_diagnostic_id = _new_diagnostic_id()
                entry, reply = _execute_once_cancel_action(
                    once_action,
                    schedule or {},
                    dry_run=not _remote_enabled(),
                    diagnostics=response_diagnostics,
                    diagnostic_id=response_diagnostic_id,
                )
                action_log = _build_action_log(
                    "cancel_schedule",
                    schedule_name,
                    task_ids,
                    time_start_str,
                    time_end_str,
                    True,
                    mode="once",
                    details={
                        "task_name": action.get("task_name", ""),
                        "override_id": entry.get("id"),
                    },
                )
                return (
                    reply,
                    _pending_action_overrides(
                        action,
                        missing_slots=[],
                        diagnostics=_public_remote_diagnostics(response_diagnostics),
                    ),
                    [action_log],
                )

            # \u6c38\u4e45\u53d6\u6d88\uff1a\u4ece\u6307\u5b9a\u65b9\u6848\u4e2d\u5220\u9664\u5339\u914d\u7684\u4efb\u52a1
            removed_count = 0
            if not schedule:
                return ("\u672a\u627e\u5230\u5bf9\u5e94\u7684\u4f5c\u606f\u65b9\u6848\uff0c\u8bf7\u91cd\u65b0\u786e\u8ba4\u3002", {"missing_slots": []}, [])
            tasks = schedule.get("tasks")
            removed_tasks: List[dict] = []
            if isinstance(tasks, list):
                removed_tasks = [
                    t for t in tasks if isinstance(t, dict) and _task_id(t) in task_ids
                ]
                kept = [t for t in tasks if not isinstance(t, dict) or _task_id(t) not in task_ids]
                removed_count = len(tasks) - len(kept)
                schedule["tasks"] = kept

            if removed_count <= 0:
                return ("\u672a\u627e\u5230\u53ef\u5220\u9664\u7684\u4efb\u52a1\u3002", {"missing_slots": []}, [])

            if _remote_enabled():
                remote_delete_ids, unresolved_remote_tasks = _resolve_remote_delete_task_ids(schedule_name, removed_tasks)
                if unresolved_remote_tasks:
                    unresolved_preview = "、".join(unresolved_remote_tasks[:5])
                    if len(unresolved_remote_tasks) > 5:
                        unresolved_preview += f" 等{len(unresolved_remote_tasks)}条任务"
                    return (
                        f"永久删除失败:以下任务无法确定远端任务ID,已取消本地保存:{unresolved_preview}。",
                        {"missing_slots": []},
                        [],
                    )
                if not remote_delete_ids:
                    return ("永久删除失败:未能定位任何可删除的远端任务ID,已取消本地保存。", {"missing_slots": []}, [])
                _batch_delete_parallel(remote_delete_ids, _remote_delete_task, label=f"cancel_permanent_{schedule_name}")
            _touch_generated_at(payload)
            _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
            action_log = _build_action_log(
                "cancel_schedule",
                schedule_name,
                task_ids,
                time_start_str,
                time_end_str,
                bool(action.get("date_specific")),
                mode="permanent",
                details={
                    "task_name": action.get("task_name", ""),
                    "removed_count": removed_count,
                },
            )
            return (
                f"\u5df2\u6c38\u4e45\u5220\u9664 {removed_count} \u6761\u4efb\u52a1\u3002",
                {"missing_slots": []},
                [action_log],
            )

    except HTTPException as exc:
        _set_pending_action(action)
        overrides = _pending_action_overrides(action)
        if response_diagnostics:
            overrides["diagnostics"] = _public_remote_diagnostics(response_diagnostics)
        return (str(exc.detail), overrides, [])
    except Exception as exc:
        LOGGER.exception(
            "pending action execution failed | text=%s error=%s pending=%s",
            raw_text,
            exc,
            _clone_payload(action),
        )
        _set_pending_action(action)
        return ("当前网络不稳定，请重新发送。", _pending_action_overrides(action), [])

    return None


def _apply_cancel_schedule_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    task_name = _slot_text(slots, "task_name", "TASK", "CONTENT", "task")
    (
        start_text,
        end_text,
        start_dt,
        end_dt,
        date_specific,
        explicit_date_locked,
        source_anchor,
    ) = _resolve_cancel_schedule_time_context(text, slots)

    # \u65f6\u95f4\u6bb5\u5fc5\u586b
    if not start_text and not end_text:
        return (
            _ask_runtime_reply(
                "cancel_schedule",
                "要取消的时间范围",
                example="比如今天上午八点到九点，或者周三早读这类说法",
            ),
            {"missing_slots": ["time_range_start", "time_range_end"]},
            [],
        )

    if start_text and not start_dt and end_text:
        return ("开始时间我还没听明白，您换一种说法我就继续处理。", {"missing_slots": []}, [])
    if end_text and not end_dt:
        return ("结束时间我还没听明白，您换一种说法我就继续处理。", {"missing_slots": []}, [])
    if start_text and not end_text and not start_dt:
        source_anchor = _parse_phase1_time_anchor(start_text)
        if not source_anchor:
            return (
                "这个时间点我还没解析清楚。您可以换成“周三”“周五”或者“2月10日”这类说法。",
                {"missing_slots": []},
                [],
            )

    # \u52a0\u8f7d payload \u5e76\u5728\u6307\u5b9a\u65b9\u6848\u5185\u5339\u914d\u4efb\u52a1
    payload = _clone_payload(_load_schedules_payload())
    schedule_targets, pending_reply = _resolve_phase1_schedule_targets(
        "cancel_schedule",
        text,
        slots,
        payload,
        schedule_name,
    )
    if pending_reply:
        return pending_reply
    now = datetime.now()
    if explicit_date_locked and end_dt and end_dt.date() == now.date() and end_dt <= now:
        return ("该时间段已结束，请改说明天或未来的具体日期。", {"missing_slots": []}, [])
    matched_tasks: List[dict] = []
    task_groups: List[dict] = []
    match_diagnostics: List[dict] = []
    for schedule, resolved_schedule_name in schedule_targets:
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        matched_in_schedule: List[dict] = []
        if source_anchor:
            matched = _match_tasks_for_phase1_anchor(
                tasks,
                source_anchor,
                task_name=task_name,
                allow_recurring_date=bool(source_anchor.get("kind") == "date"),
            )
            matched_in_schedule = list(matched.get("matched_tasks") or [])
            diagnostic = _phase1_anchor_diagnostic(source_anchor, matched)
            diagnostic["schedule_name"] = resolved_schedule_name
            match_diagnostics.append(diagnostic)
        else:
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                if task_name and not _task_name_matches(task, task_name):
                    continue
                if start_dt and end_dt and not _task_matches_range(task, start_dt, end_dt, date_specific):
                    continue
                matched_in_schedule.append(task)
        task_ids = _unique_list([_task_id(task) for task in matched_in_schedule if _task_id(task)])
        if not task_ids:
            continue
        matched_tasks.extend(matched_in_schedule)
        task_groups.append(
            {
                "schedule_name": resolved_schedule_name,
                "task_ids": task_ids,
                "count": len(task_ids),
            }
        )

    if not task_groups:
        if source_anchor:
            return _phase1_anchor_failure_reply(
                schedule_targets,
                start_text or "",
                task_name=task_name,
                diagnostics=match_diagnostics,
            )
        time_hint = f"{start_text or ''}\u81f3{end_text or ''}" if (start_text or end_text) else ""
        task_hint = f"\u4efb\u52a1\u201c{task_name}\u201d" if task_name else ""
        if len(schedule_targets) == 1:
            return (
                f"\u5728\u201c{schedule_targets[0][1]}\u201d\u4e2d\u672a\u627e\u5230\u5339\u914d{time_hint}{task_hint}\u7684\u4efb\u52a1\u3002",
                {"missing_slots": []},
                [],
            )
        return (
            f"\u5728\u5f53\u524d\u542f\u7528\u4e2d\u7684\u4f5c\u606f\u65b9\u6848\u91cc\u672a\u627e\u5230\u5339\u914d{time_hint}{task_hint}\u7684\u4efb\u52a1\u3002",
            {"missing_slots": []},
            [],
        )

    mode = _detect_apply_mode(text)
    single_group = task_groups[0] if len(task_groups) == 1 else {}
    _set_pending_action(
        {
            "intent": "cancel_schedule",
            "schedule_name": str(single_group.get("schedule_name") or ""),
            "schedule_names": [str(item.get("schedule_name") or "") for item in task_groups if str(item.get("schedule_name") or "")],
            "schedule_scope": "enabled_all" if len(task_groups) > 1 else "single",
            "slots": _pending_slots_snapshot(
                slots,
                schedule_name=str(single_group.get("schedule_name") or ""),
                schedule_names=[str(item.get("schedule_name") or "") for item in task_groups if str(item.get("schedule_name") or "")],
                schedule_scope="enabled_all" if len(task_groups) > 1 else "single",
                task_name=task_name or "",
                time_range_start=start_text or "",
                time_range_end=end_text or "",
                source_time=start_text or "",
            ),
            "task_name": task_name or "",
            "time_range_start": start_text,
            "time_range_end": end_text,
            "task_ids": list(single_group.get("task_ids") or []),
            "task_groups": _clone_payload(task_groups),
            "time_start": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "",
            "time_end": end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else "",
            "date_specific": date_specific,
            "source_text": start_text or "",
            "source_anchor": _clone_payload(source_anchor) if source_anchor else None,
        }
    )

    if not mode:
        if len(task_groups) > 1:
            schedule_summary = _summarize_phase1_schedule_groups(task_groups)
            return (
                _confirm_runtime_reply(
                    "cancel_schedule",
                    f"在 {len(task_groups)} 个启用中的作息方案里，共匹配到 {len(matched_tasks)} 条任务：{schedule_summary}",
                ),
                {"missing_slots": []},
                [],
            )
        preview = _summarize_tasks(matched_tasks)
        return (
            _confirm_runtime_reply(
                "cancel_schedule",
                f'作息方案“{single_group.get("schedule_name") or ""}”里匹配到 {len(matched_tasks)} 条任务：{preview}',
            ),
            {"missing_slots": []},
            [],
        )

    return _handle_pending_action(mode)

def _apply_move_schedule_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    """
    move_schedule 单向挪动作息。
    场景A: 周维度 "将春季作息中周一的任务挪到周六"
    场景B: 日期维度 "将春季作息中1月24日的任务挪到2月1日"
    场景C: 时间段  "把周五3-7点的任务挪到周六4-5点"
    schedule_name 选填,缺失时默认当前唯一启用方案,否则追问。
    """
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    task_name = _slot_text(slots, "task_name", "TASK", "CONTENT", "task")
    strict_task_id = _phase1_effective_strict_task_id("move_schedule", text, slots)
    source_text = _slot_text(slots, "source_time", "time_from", "from_time")
    target_text = _slot_text(slots, "target_time", "end_time", "time_to", "to_time")

    # source_time / target_time 必填
    time_missing: List[str] = []
    if not source_text:
        time_missing.append("source_time")
    if not target_text:
        time_missing.append("target_time")
    if time_missing:
        return (
            _ask_runtime_reply(
                "move_schedule",
                "源时间和目标时间",
                example="比如把周三早读挪到周五，或者把 8 点的任务改到 9 点",
            ),
            {"missing_slots": time_missing},
            [],
        )

    source_anchor = _parse_phase1_time_anchor(source_text)
    target_anchor = _parse_phase1_time_anchor(target_text)
    if not source_anchor or not target_anchor:
        return ("这两个时间我还没完全听明白。您可以换成“周三”“周五”或者“2月10日”这类说法。", {"missing_slots": []}, [])
    if source_anchor.get("kind") != target_anchor.get("kind"):
        return ("\u6e90\u65f6\u95f4\u548c\u76ee\u6807\u65f6\u95f4\u9700\u8981\u540c\u4e00\u7ef4\u5ea6\uff08\u90fd\u4e3a\u661f\u671f\uff0c\u6216\u90fd\u4e3a\u65e5\u671f\uff09\u3002", {"missing_slots": []}, [])

    payload = _clone_payload(_load_schedules_payload())
    schedule_targets, pending_reply = _resolve_phase1_schedule_targets(
        "move_schedule",
        text,
        slots,
        payload,
        schedule_name,
    )
    if pending_reply:
        return pending_reply

    date_specific = bool(source_anchor.get("kind") == "date" and target_anchor.get("kind") == "date")
    mode = _detect_apply_mode(text)
    matched_tasks: List[dict] = []
    task_groups: List[dict] = []
    recurring_tasks: List[dict] = []
    multi_schedule_choices: List[dict] = []
    match_diagnostics: List[dict] = []
    has_multi_schedule_ambiguity = False
    for schedule, resolved_name in schedule_targets:
        tasks = schedule.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            continue
        matched = _match_tasks_for_phase1_anchor(
            tasks,
            source_anchor,
            task_name=task_name,
            strict_task_id=strict_task_id,
            allow_recurring_date=date_specific,
        )
        matched_in_schedule = list(matched.get("matched_tasks") or [])
        diagnostic = _phase1_anchor_diagnostic(source_anchor, matched)
        diagnostic["schedule_name"] = resolved_name
        match_diagnostics.append(diagnostic)
        if len(schedule_targets) == 1 and task_name and not strict_task_id and len(matched_in_schedule) > 1:
            return _begin_target_disambiguation(
                intent="move_schedule",
                text=text,
                slots=slots,
                target_type="task",
                query=task_name,
                choices=[_task_choice(task, schedule_name=resolved_name, scope_kind="schedule") for task in matched_in_schedule],
            )
        task_ids = _unique_list([_task_id(task) for task in matched_in_schedule if _task_id(task)])
        if not task_ids:
            continue
        if len(schedule_targets) > 1 and task_name and not strict_task_id:
            multi_schedule_choices.append(_move_schedule_scope_choice(resolved_name, matched_in_schedule))
            if len(matched_in_schedule) > 1:
                has_multi_schedule_ambiguity = True
        matched_tasks.extend(matched_in_schedule)
        if date_specific:
            recurring_tasks.extend([task for task in matched_in_schedule if _task_is_recurring(task)])
        task_groups.append(
            {
                "schedule_name": resolved_name,
                "task_ids": task_ids,
                "count": len(task_ids),
            }
        )

    if has_multi_schedule_ambiguity and multi_schedule_choices:
        return _begin_target_disambiguation(
            intent="move_schedule",
            text=text,
            slots=slots,
            target_type="schedule",
            query=f"{task_name}对应的作息方案" if task_name else "要继续的作息方案",
            choices=multi_schedule_choices,
        )

    if not task_groups:
        return _phase1_anchor_failure_reply(
            schedule_targets,
            source_text,
            task_name=task_name,
            strict_task_id=strict_task_id,
            diagnostics=match_diagnostics,
        )

    recurring_task_ids = _unique_list([_task_id(task) for task in recurring_tasks if _task_id(task)])
    if len(task_groups) > 1:
        base_prompt = (
            f"\u5728 {len(task_groups)} \u4e2a\u542f\u7528\u4e2d\u7684\u4f5c\u606f\u65b9\u6848\u4e2d\u5339\u914d\u5230 {len(matched_tasks)} \u6761\u4efb\u52a1\uff1a"
            f"{_summarize_phase1_schedule_groups(task_groups)}\u3002\u8bf7\u786e\u8ba4\u8981\u4e00\u6b21\u6027\u6267\u884c\u8fd8\u662f\u6c38\u4e45\u751f\u6548\uff1f"
        )
    else:
        base_prompt = f"\u627e\u5230\u8fd9\u4e9b\u4efb\u52a1\uff1a{_summarize_tasks(matched_tasks)}\u3002\u8bf7\u786e\u8ba4\u8981\u4e00\u6b21\u6027\u6267\u884c\u8fd8\u662f\u6c38\u4e45\u751f\u6548\uff1f"
    recurring_preview = ""
    if date_specific:
        source_date = source_anchor.get("date")
        target_date = target_anchor.get("date")
        if source_date and target_date:
            recurring_preview = _summarize_date_window_shift(recurring_tasks, (target_date - source_date).days)
    confirm_prompt = _build_recurring_risk_prompt(base_prompt, len(recurring_task_ids), recurring_preview)
    if len(task_groups) > 1:
        friendly_summary = f"在 {len(task_groups)} 个启用中的作息方案里，共匹配到 {len(matched_tasks)} 条任务：{_summarize_phase1_schedule_groups(task_groups)}"
    else:
        friendly_summary = f"已识别到这些任务：{_summarize_tasks(matched_tasks)}"
    friendly_confirm_prompt = _build_recurring_risk_prompt(
        _confirm_runtime_reply("move_schedule", friendly_summary),
        len(recurring_task_ids),
        recurring_preview,
    )
    single_group = task_groups[0] if len(task_groups) == 1 else {}
    _set_pending_action(
        {
            "intent": "move_schedule",
            "schedule_name": str(single_group.get("schedule_name") or ""),
            "schedule_names": [str(item.get("schedule_name") or "") for item in task_groups if str(item.get("schedule_name") or "")],
            "schedule_scope": "enabled_all" if len(task_groups) > 1 else "single",
            "slots": _pending_slots_snapshot(
                slots,
                schedule_name=str(single_group.get("schedule_name") or ""),
                schedule_names=[str(item.get("schedule_name") or "") for item in task_groups if str(item.get("schedule_name") or "")],
                schedule_scope="enabled_all" if len(task_groups) > 1 else "single",
                task_name=task_name or "",
                task_id=str(strict_task_id or ""),
                source_time=source_text or "",
                target_time=target_text or "",
            ),
            "source_text": source_text,
            "target_text": target_text,
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
            "task_name": task_name,
            "task_id": strict_task_id,
            "task_ids": list(single_group.get("task_ids") or []),
            "task_groups": _clone_payload(task_groups),
            "date_specific": date_specific,
            "contains_recurring": bool(recurring_task_ids),
            "recurring_task_ids": recurring_task_ids,
            "confirm_prompt": friendly_confirm_prompt,
        }
    )

    if not mode:
        return (friendly_confirm_prompt, {"missing_slots": []}, [])

    return _handle_pending_action(mode)

def _extract_swap_time_values(slots: dict) -> Tuple[str, str]:
    source_text = _slot_text(slots, "source_time", "time_a", "time_from")
    target_text = _slot_text(slots, "target_time", "end_time", "time_b", "time_to")
    if source_text and not target_text:
        raw_source = slots.get("source_time")
        if isinstance(raw_source, list):
            items = [str(item).strip() for item in raw_source if str(item).strip()]
            if len(items) >= 2:
                return items[0], items[1]
        for sep in ["\uFF0C", ",", "\u548C", "\u4E0E", "\u8DDF", "\u53CA"]:
            if sep in source_text:
                left, right = source_text.split(sep, 1)
                left = left.strip()
                right = right.strip()
                if left and right:
                    return left, right
    return source_text, target_text

def _apply_swap_schedule_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    """
    swap_schedule 双向对调作息。
    场景A: 周维度 "把春季作息中周一和周五的任务对调"
    场景B: 日期维度 "把春季作息中1月24日和2月1日的任务对调"
    schedule_name 选填,缺失时默认当前唯一启用方案,否则追问。
    """
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    task_name = _slot_text(slots, "task_name", "TASK", "CONTENT", "task")
    source_text, target_text = _extract_swap_time_values(slots)

    # source_time / target_time 必填
    time_missing: List[str] = []
    if not source_text:
        time_missing.append("source_time")
    if not target_text:
        time_missing.append("target_time")
    if time_missing:
        return (
            _ask_runtime_reply(
                "swap_schedule",
                "要对调的两个时间",
                example="比如把周一早读和周五早读对调，或者把 8 点和 9 点的任务互换",
            ),
            {"missing_slots": time_missing},
            [],
        )

    anchor_a = _parse_phase1_time_anchor(source_text)
    anchor_b = _parse_phase1_time_anchor(target_text)
    if not anchor_a or not anchor_b:
        return ("这两个时间我还没完全听明白。您可以换成“周三”“周五”或者“2月10日”这类说法。", {"missing_slots": []}, [])
    if anchor_a.get("kind") != anchor_b.get("kind"):
        return ("\u5bf9\u8c03\u65f6\u95f4\u9700\u8981\u540c\u4e00\u7ef4\u5ea6\uff08\u90fd\u4e3a\u661f\u671f\uff0c\u6216\u90fd\u4e3a\u65e5\u671f\uff09\u3002", {"missing_slots": []}, [])

    payload = _clone_payload(_load_schedules_payload())
    schedule_targets, pending_reply = _resolve_phase1_schedule_targets(
        "swap_schedule",
        text,
        slots,
        payload,
        schedule_name,
    )
    if pending_reply:
        return pending_reply

    date_specific = bool(anchor_a.get("kind") == "date" and anchor_b.get("kind") == "date")
    mode = _detect_apply_mode(text)
    matched_a: List[dict] = []
    matched_b: List[dict] = []
    recurring_a: List[dict] = []
    recurring_b: List[dict] = []
    task_groups: List[dict] = []
    diagnostics_a: List[dict] = []
    diagnostics_b: List[dict] = []
    for schedule, resolved_name in schedule_targets:
        tasks = schedule.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            continue
        matched_for_a = _match_tasks_for_phase1_anchor(
            tasks,
            anchor_a,
            task_name=task_name,
            allow_recurring_date=date_specific,
        )
        matched_for_b = _match_tasks_for_phase1_anchor(
            tasks,
            anchor_b,
            task_name=task_name,
            allow_recurring_date=date_specific,
        )
        tasks_a = list(matched_for_a.get("matched_tasks") or [])
        tasks_b = list(matched_for_b.get("matched_tasks") or [])
        diagnostic_a = _phase1_anchor_diagnostic(anchor_a, matched_for_a)
        diagnostic_a["schedule_name"] = resolved_name
        diagnostics_a.append(diagnostic_a)
        diagnostic_b = _phase1_anchor_diagnostic(anchor_b, matched_for_b)
        diagnostic_b["schedule_name"] = resolved_name
        diagnostics_b.append(diagnostic_b)
        task_ids_a = _unique_list([_task_id(task) for task in tasks_a if _task_id(task)])
        task_ids_b = _unique_list([_task_id(task) for task in tasks_b if _task_id(task)])
        if not task_ids_a or not task_ids_b:
            continue
        matched_a.extend(tasks_a)
        matched_b.extend(tasks_b)
        if date_specific:
            recurring_a.extend([task for task in tasks_a if _task_is_recurring(task)])
            recurring_b.extend([task for task in tasks_b if _task_is_recurring(task)])
        task_groups.append(
            {
                "schedule_name": resolved_name,
                "task_ids_a": task_ids_a,
                "task_ids_b": task_ids_b,
                "count": len(task_ids_a) + len(task_ids_b),
            }
        )

    if not task_groups:
        total_a = sum(int(item.get("candidate_count_after_task_name_match") or 0) for item in diagnostics_a if isinstance(item, dict))
        total_b = sum(int(item.get("candidate_count_after_task_name_match") or 0) for item in diagnostics_b if isinstance(item, dict))
        if len(schedule_targets) == 1:
            prefix = f"在“{schedule_targets[0][1]}”中未找到可对调的“{source_text}/{target_text}”任务。"
        else:
            prefix = f"在当前启用中的作息方案里未找到可对调的“{source_text}/{target_text}”任务。"
        if total_a <= 0:
            detail_reply, detail_state, detail_logs = _phase1_anchor_failure_reply(
                schedule_targets,
                source_text,
                task_name=task_name,
                diagnostics=diagnostics_a,
            )
            return f"{prefix}{detail_reply}", detail_state, detail_logs
        detail_reply, detail_state, detail_logs = _phase1_anchor_failure_reply(
            schedule_targets,
            target_text,
            task_name=task_name,
            diagnostics=diagnostics_b,
        )
        return f"{prefix}{detail_reply}", detail_state, detail_logs

    recurring_task_ids = _unique_list(
        [_task_id(task) for task in (recurring_a + recurring_b) if _task_id(task)]
    )
    if len(task_groups) > 1:
        base_prompt = (
            f"\u5728 {len(task_groups)} \u4e2a\u542f\u7528\u4e2d\u7684\u4f5c\u606f\u65b9\u6848\u4e2d\u627e\u5230\u53ef\u5bf9\u8c03\u7684\u4efb\u52a1\uff1a"
            f"{_summarize_phase1_schedule_groups(task_groups)}\u3002\u8bf7\u786e\u8ba4\u8981\u4e00\u6b21\u6027\u6267\u884c\u8fd8\u662f\u6c38\u4e45\u751f\u6548\uff1f"
        )
    else:
        base_prompt = (
            f"\u627e\u5230\u4e24\u7ec4\u4efb\u52a1\uff1aA[{_summarize_tasks(matched_a)}]\uff0c"
            f"B[{_summarize_tasks(matched_b)}]\u3002\u8bf7\u786e\u8ba4\u8981\u4e00\u6b21\u6027\u6267\u884c\u8fd8\u662f\u6c38\u4e45\u751f\u6548\uff1f"
        )
    recurring_preview = ""
    if date_specific:
        date_a = anchor_a.get("date")
        date_b = anchor_b.get("date")
        if date_a and date_b:
            day_delta = (date_b - date_a).days
            parts: List[str] = []
            text_a = _summarize_date_window_shift(recurring_a, day_delta)
            text_b = _summarize_date_window_shift(recurring_b, -day_delta)
            if text_a:
                parts.append(f"A组 {text_a}")
            if text_b:
                parts.append(f"B组 {text_b}")
            recurring_preview = "；".join(parts)
    confirm_prompt = _build_recurring_risk_prompt(base_prompt, len(recurring_task_ids), recurring_preview)
    if len(task_groups) > 1:
        friendly_summary = f"在 {len(task_groups)} 个启用中的作息方案里，找到了可对调的任务：{_summarize_phase1_schedule_groups(task_groups)}"
    else:
        friendly_summary = f"我找到两组任务：A[{_summarize_tasks(matched_a)}]，B[{_summarize_tasks(matched_b)}]"
    friendly_confirm_prompt = _build_recurring_risk_prompt(
        _confirm_runtime_reply("swap_schedule", friendly_summary),
        len(recurring_task_ids),
        recurring_preview,
    )
    single_group = task_groups[0] if len(task_groups) == 1 else {}
    _set_pending_action(
        {
            "intent": "swap_schedule",
            "schedule_name": str(single_group.get("schedule_name") or ""),
            "schedule_names": [str(item.get("schedule_name") or "") for item in task_groups if str(item.get("schedule_name") or "")],
            "schedule_scope": "enabled_all" if len(task_groups) > 1 else "single",
            "slots": _pending_slots_snapshot(
                slots,
                schedule_name=str(single_group.get("schedule_name") or ""),
                schedule_names=[str(item.get("schedule_name") or "") for item in task_groups if str(item.get("schedule_name") or "")],
                schedule_scope="enabled_all" if len(task_groups) > 1 else "single",
                source_time=source_text or "",
                target_time=target_text or "",
                task_name=task_name or "",
            ),
            "task_name": task_name or "",
            "source_text": source_text,
            "target_text": target_text,
            "anchor_a": anchor_a,
            "anchor_b": anchor_b,
            "task_ids_a": list(single_group.get("task_ids_a") or []),
            "task_ids_b": list(single_group.get("task_ids_b") or []),
            "task_groups": _clone_payload(task_groups),
            "date_specific": date_specific,
            "contains_recurring": bool(recurring_task_ids),
            "recurring_task_ids": recurring_task_ids,
            "confirm_prompt": friendly_confirm_prompt,
        }
    )

    if not mode:
        return (friendly_confirm_prompt, {"missing_slots": []}, [])

    return _handle_pending_action(mode)


def _create_phase1_schedule_via_remote_copy(
    final_name: str,
    template_name: str,
    start_date: Optional[date],
    end_date: Optional[date],
) -> Tuple[dict, int]:
    copy_payload = {"fromtaskname": template_name, "totaskname": final_name}
    try:
        _remote_request(
            "POST",
            "/task/sechinfo",
            json_body=copy_payload,
            form_body=None,
            allow_form_retry=False,
        )
    except HTTPException as exc:
        raise HTTPException(status_code=502, detail=f"远端复制方案失败:{exc.detail}") from exc

    updated_task_ids: List[str] = []
    if start_date:
        try:
            remote_tasks = [_normalize_remote_task(item) for item in _remote_fetch_schedule_tasks(final_name)]
        except HTTPException as exc:
            _raise_remote_created_schedule_failure(final_name, f"方案已创建,但读取新方案任务失败:{exc.detail}")
        try:
            media_map = _remote_media_map()
            terminal_map = _remote_terminal_map()
        except HTTPException as exc:
            _raise_remote_created_schedule_failure(final_name, f"方案已创建,但读取远端依赖失败:{exc.detail}")
        rollback_items: List[Tuple[str, dict, dict]] = []
        target_start = start_date.strftime("%Y-%m-%d")
        fixed_end = end_date.strftime("%Y-%m-%d") if end_date else ""

        tasks_to_update: List[Tuple[str, dict, dict]] = []
        for task in remote_tasks:
            if not isinstance(task, dict):
                continue
            task_id = _task_id(task)
            if not task_id or not _is_numeric_id(task_id):
                continue
            original = _clone_payload(task)
            updated = _clone_payload(task)
            if fixed_end:
                updated["startdate"] = target_start
                updated["enddate"] = fixed_end
            else:
                old_start = _parse_iso_date(updated.get("startdate"))
                old_end = _parse_iso_date(updated.get("enddate")) or old_start
                if old_start and old_end:
                    span_days = max((old_end - old_start).days, 0)
                else:
                    span_days = 0
                updated["startdate"] = target_start
                updated["enddate"] = (start_date + timedelta(days=span_days)).strftime("%Y-%m-%d")
            if (
                str(updated.get("startdate") or "") == str(original.get("startdate") or "")
                and str(updated.get("enddate") or "") == str(original.get("enddate") or "")
            ):
                continue
            tasks_to_update.append((task_id, original, updated))

        if tasks_to_update:
            update_errors: List[Tuple[int, HTTPException]] = []

            def _do_update(index_and_item):
                idx, (tid, _orig, upd) = index_and_item
                _remote_update_task(tid, final_name, upd, media_map, terminal_map, _orig)
                return idx

            try:
                worker_count = min(len(tasks_to_update), REMOTE_FETCH_WORKERS or 4)
                if worker_count <= 1:
                    for tid, orig, upd in tasks_to_update:
                        _remote_update_task(tid, final_name, upd, media_map, terminal_map, orig)
                        rollback_items.append((tid, orig, upd))
                        updated_task_ids.append(tid)
                else:
                    with ThreadPoolExecutor(max_workers=worker_count) as executor:
                        futures = {
                            _submit_with_current_remote_token(executor, _do_update, (idx, item)): idx
                            for idx, item in enumerate(tasks_to_update)
                        }
                        for future in as_completed(futures):
                            idx = futures[future]
                            tid, orig, upd = tasks_to_update[idx]
                            try:
                                future.result()
                                rollback_items.append((tid, orig, upd))
                                updated_task_ids.append(tid)
                            except HTTPException as exc:
                                update_errors.append((idx, exc))
                    if update_errors:
                        raise update_errors[0][1]
            except HTTPException as exc:
                for tid, orig, upd in reversed(rollback_items):
                    try:
                        _remote_update_task(tid, final_name, orig, media_map, terminal_map, upd)
                    except HTTPException:
                        continue
                _raise_remote_created_schedule_failure(final_name, f"方案已创建,但有效期更新失败:{exc.detail}")

    try:
        new_tasks_raw = [_normalize_remote_task(item) for item in _remote_fetch_schedule_tasks(final_name)]
    except HTTPException as exc:
        _raise_remote_created_schedule_failure(final_name, f"方案已创建,但读取更新后的任务失败:{exc.detail}")
    return ({"schedule_name": final_name, "status": "启用", "tasks": new_tasks_raw}, len(updated_task_ids))


def _apply_create_scheme_intent(
    text: str,
    slots: dict,
    *,
    assistant_terminal_scope: str = "",
) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_kind = _load_default_schedule_kind()
    schedule_season = _load_default_schedule_season()
    schedule_name = _slot_text(slots, "schedule_name", "new_schedule_name", "name")
    if not schedule_name:
        return (
            _ask_runtime_reply(
                "create_schedule",
                "新作息方案名称",
                example="比如春季作息、考试周作息或者高三冲刺作息",
            ),
            {"missing_slots": ["schedule_name"]},
            [],
        )
    if not schedule_kind:
        return ("请先在AI助手中设置学校类型（小学/中学/高中/大学）。", {"missing_slots": []}, [])
    if not schedule_season:
        return ("请先在AI助手中设置作息季节（夏季/冬季）。", {"missing_slots": []}, [])
    try:
        resolved_kind, resolved_season, template_entry = _select_phase1_template_entry(
            text,
            schedule_kind,
            schedule_season,
        )
    except HTTPException as exc:
        return (str(exc.detail), {"missing_slots": []}, [])
    display_kind = resolved_kind or schedule_kind
    display_season = resolved_season or schedule_season
    desired_name = schedule_name.strip()

    start_text = _slot_text(slots, "source_time", "time_range_start", "start_date", "start")
    offset_text = _slot_text(slots, "time_offset", "duration_offset")
    end_text = _slot_text(slots, "end_time", "time_range_end", "end_date", "end")

    if (offset_text or end_text) and not start_text:
        return ("设置有效期时,请先提供开始日期(time_range_start)。", {"missing_slots": ["time_range_start"]}, [])
    if offset_text and end_text:
        return ("time_offset 与 time_range_end 二选一即可,请保留其中一个。", {"missing_slots": []}, [])

    start_date = _parse_phase1_date(start_text) if start_text else None
    if start_text and not start_date:
        return ("开始日期我还没解析清楚，您可以换成“2026-02-10”或“2月10日”这类说法。", {"missing_slots": []}, [])
    end_date = _parse_phase1_date(end_text) if end_text else None
    if end_text and not end_date:
        return ("结束日期我还没解析清楚，您可以换成“2026-09-10”或“9月10日”这类说法。", {"missing_slots": []}, [])

    if start_date and offset_text:
        offset_days = _parse_time_offset_days(offset_text)
        if offset_days is None:
            return ('time_offset 解析失败,请使用"30天/6个月/1年"等格式。', {"missing_slots": []}, [])
        end_date = start_date + timedelta(days=offset_days)
    if start_date and end_date and end_date < start_date:
        return ("结束日期不能早于开始日期。", {"missing_slots": []}, [])

    remote_enabled = _remote_enabled()
    remote_template_name = str(template_entry.get("remote_template") or "").strip()
    source_schedule_name = str(template_entry.get("source_schedule_name") or "").strip()
    local_template_file = str(template_entry.get("local_template_file") or "").strip()
    assistant_terminal_items: Optional[List[dict]] = None
    if assistant_terminal_scope == _ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS:
        assistant_terminal_items = _assistant_create_schedule_playback_terminal_items()
        if not assistant_terminal_items:
            return ("未找到可绑定的播放终端，已取消新建作息。", {"missing_slots": []}, [])

    try:
        local_payload = _load_schedules_payload()
    except HTTPException:
        local_payload = {"schedules": []}
    local_names = {
        str(item.get("schedule_name") or item.get("name") or "").strip()
        for item in (local_payload.get("schedules") or [])
        if isinstance(item, dict)
    }
    local_names.discard("")

    remote_names: List[str] = []
    remote_names_error: Optional[HTTPException] = None
    if remote_enabled:
        try:
            remote_names = _remote_schedule_names()
        except HTTPException as exc:
            remote_names_error = exc

    existing_names = set(local_names)
    existing_names.update(str(name or "").strip() for name in remote_names if str(name or "").strip())

    final_name = desired_name
    suffix = 1
    while final_name in existing_names:
        final_name = f"{desired_name}({suffix})"
        suffix += 1

    if remote_enabled and remote_template_name and remote_names_error is None and remote_template_name in remote_names:
        remote_copy_created = False
        try:
            new_schedule_entry, updated_count = _create_phase1_schedule_via_remote_copy(
                final_name,
                remote_template_name,
                start_date,
                end_date,
            )
            remote_copy_created = True
            if assistant_terminal_items is not None:
                _rebind_created_schedule_to_terminal_items(new_schedule_entry, assistant_terminal_items)
                _assistant_apply_created_schedule_defaults(new_schedule_entry)
            _commit_phase1_created_schedule(
                new_schedule_entry,
                sync_remote=assistant_terminal_items is not None,
            )
        except HTTPException as exc:
            if remote_copy_created:
                cleanup_error = _cleanup_remote_created_schedule(final_name)
                if cleanup_error:
                    failure_details = _failure_runtime_detail_payload(
                        exc.detail,
                        user_reason="方案没创建完成，且远端还有残留记录",
                        retryable=True,
                        failure_code="remote_copy_cleanup_incomplete",
                        cleanup_error=cleanup_error,
                    )
                    action_log = _action_log_with_failure_details(
                        "create_schedule",
                        final_name,
                        [],
                        details={
                            "template": remote_template_name,
                            "kind": display_kind,
                            "season": display_season,
                            "creation_path": "remote_copy",
                            "remote_template": remote_template_name,
                        },
                        raw_reason=exc.detail,
                        user_reason="方案没创建完成，且远端还有残留记录",
                        retryable=True,
                        failure_code="remote_copy_cleanup_incomplete",
                        cleanup_error=cleanup_error,
                    )
                    return (
                        _failure_runtime_reply(
                            "create_schedule",
                            "新作息方案",
                            final_name,
                            reason="远端复制没有完成",
                            suggestion="方案没创建完成，且远端还有残留记录。建议稍后重试。",
                        ),
                        {"missing_slots": [], "diagnostics": [failure_details]},
                        [action_log],
                    )
                failure_details = _failure_runtime_detail_payload(
                    exc.detail,
                    user_reason="远端模板复制失败，已回滚已创建内容",
                    retryable=True,
                    failure_code="remote_copy_failed_rolled_back",
                )
                action_log = _action_log_with_failure_details(
                    "create_schedule",
                    final_name,
                    [],
                    details={
                        "template": remote_template_name,
                        "kind": display_kind,
                        "season": display_season,
                        "creation_path": "remote_copy",
                        "remote_template": remote_template_name,
                    },
                    raw_reason=exc.detail,
                    user_reason="远端模板复制失败，已回滚已创建内容",
                    retryable=True,
                    failure_code="remote_copy_failed_rolled_back",
                )
                return (
                    _failure_runtime_reply(
                        "create_schedule",
                        "新作息方案",
                        final_name,
                        reason="远端模板复制失败",
                        suggestion="已回滚已创建内容，稍后可以再试一次。",
                    ),
                    {"missing_slots": [], "diagnostics": [failure_details]},
                    [action_log],
                )
            failure_details = _failure_runtime_detail_payload(
                exc.detail,
                user_reason="远端模板复制失败",
                retryable=True,
                failure_code="remote_copy_failed",
            )
            action_log = _action_log_with_failure_details(
                "create_schedule",
                final_name,
                [],
                details={
                    "template": remote_template_name,
                    "kind": display_kind,
                    "season": display_season,
                    "creation_path": "remote_copy",
                    "remote_template": remote_template_name,
                },
                raw_reason=exc.detail,
                user_reason="远端模板复制失败",
                retryable=True,
                failure_code="remote_copy_failed",
            )
            return (
                _failure_runtime_reply(
                    "create_schedule",
                    "新作息方案",
                    final_name,
                    reason="远端模板复制失败",
                    suggestion="这一步没有完成，稍后可以再试一次。",
                ),
                {"missing_slots": [], "diagnostics": [failure_details]},
                [action_log],
            )

        detail = {
            "template": remote_template_name,
            "kind": display_kind,
            "season": display_season,
            "updated_tasks": updated_count,
            "creation_path": "remote_copy",
            "remote_template": remote_template_name,
            "source_schedule_name": source_schedule_name,
            "local_template_file": local_template_file,
            "fallback_used": False,
        }
        action_log = _build_action_log("create_schedule", final_name, [], details=detail)
        if start_date:
            period_text = start_date.strftime("%Y-%m-%d")
            if end_date:
                period_text = f"{period_text} 至 {end_date.strftime('%Y-%m-%d')}"
            return (
                _append_key_intent_followup(
                    "create_schedule",
                    _success_runtime_reply(
                        "create_schedule",
                        [
                            '小电已经为您创建好了“{schedule_name}”，有效期为 {period_text}。',
                            '搞定啦，小电已经把“{schedule_name}”创建好了，生效时间为 {period_text}。',
                            '小电已经帮您创建好了“{schedule_name}”，有效期为 {period_text}。',
                        ],
                        final_name,
                        period_text,
                        schedule_name=final_name,
                        period_text=period_text,
                    ),
                ),
                {"missing_slots": []},
                [action_log],
            )
        return (
            _append_key_intent_followup(
                "create_schedule",
                _success_runtime_reply(
                    "create_schedule",
                    [
                        '小电已经为您创建好了“{schedule_name}”，来源模板是“{template_name}”。',
                        '搞定啦，小电已经按“{template_name}”为您创建好了“{schedule_name}”。',
                        '小电已经帮您基于“{template_name}”创建好了“{schedule_name}”。',
                    ],
                    remote_template_name,
                    final_name,
                    template_name=remote_template_name,
                    schedule_name=final_name,
                ),
            ),
            {"missing_slots": []},
            [action_log],
        )

    if not source_schedule_name and not local_template_file:
        if remote_names_error is not None:
            failure_details = _failure_runtime_detail_payload(
                remote_names_error.detail,
                user_reason="远端方案列表暂时无法读取",
                retryable=True,
                failure_code="remote_schedule_list_unavailable",
            )
            action_log = _action_log_with_failure_details(
                "create_schedule",
                final_name,
                [],
                details={
                    "kind": display_kind,
                    "season": display_season,
                    "creation_path": "template_lookup",
                    "remote_template": remote_template_name,
                },
                raw_reason=remote_names_error.detail,
                user_reason="远端方案列表暂时无法读取",
                retryable=True,
                failure_code="remote_schedule_list_unavailable",
            )
            return (
                "远端方案列表暂时无法读取，稍后再试。",
                {"missing_slots": [], "diagnostics": [failure_details]},
                [action_log],
            )
        if remote_template_name:
            return (
                f'未找到可用模板。远端模板"{remote_template_name}"不可用，且未配置本地模板。',
                {"missing_slots": []},
                [],
            )
        return ("未配置可用的本地作息模板。", {"missing_slots": []}, [])

    try:
        if source_schedule_name:
            template_schedule = _load_phase1_local_schedule_template(source_schedule_name)
        else:
            template_schedule = _load_phase1_local_template(local_template_file)
        template_media_details = _normalize_phase1_template_media_bindings(
            template_schedule,
            source_schedule_name=source_schedule_name,
            local_template_file=local_template_file,
        )
        new_schedule_entry, updated_count = _build_phase1_local_schedule_from_template(
            template_schedule,
            final_name,
            start_date,
            end_date,
        )
        if assistant_terminal_items is not None:
            _rebind_created_schedule_to_terminal_items(new_schedule_entry, assistant_terminal_items)
            _assistant_apply_created_schedule_defaults(new_schedule_entry)
        _commit_phase1_created_schedule(new_schedule_entry, sync_remote=remote_enabled)
    except _CreateScheduleTemplateMediaError as exc:
        detail = {
            "template": source_schedule_name or local_template_file,
            "kind": display_kind,
            "season": display_season,
            "creation_path": "local_template_sync" if remote_enabled else "local_template_only",
            "remote_template": remote_template_name,
            "source_schedule_name": source_schedule_name,
            "local_template_file": local_template_file,
        }
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason=exc.user_reason,
            retryable=exc.retryable,
            failure_code=exc.failure_code,
            missing_media_names=exc.missing_media_names,
            ambiguous_media_names=exc.ambiguous_media_names,
            invalid_media_tasks=exc.invalid_media_tasks,
            template_media_rebound=exc.template_media_rebound,
            template_media_source=exc.template_media_source,
            template_media_remote_expected=exc.template_media_remote_expected,
            template_media_remote_fetch_ok=exc.template_media_remote_fetch_ok,
            template_media_fallback_used=exc.template_media_fallback_used,
        )
        action_log = _action_log_with_failure_details(
            "create_schedule",
            final_name,
            [],
            details=detail,
            raw_reason=exc.detail,
            user_reason=exc.user_reason,
            retryable=exc.retryable,
            failure_code=exc.failure_code,
            missing_media_names=exc.missing_media_names,
            ambiguous_media_names=exc.ambiguous_media_names,
            invalid_media_tasks=exc.invalid_media_tasks,
            template_media_rebound=exc.template_media_rebound,
            template_media_source=exc.template_media_source,
            template_media_remote_expected=exc.template_media_remote_expected,
            template_media_remote_fetch_ok=exc.template_media_remote_fetch_ok,
            template_media_fallback_used=exc.template_media_fallback_used,
        )
        return (
            _failure_runtime_reply(
                "create_schedule",
                "新作息方案",
                final_name,
                reason=exc.user_reason,
                suggestion=exc.suggestion,
            ),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )
    except HTTPException as exc:
        user_reason = "模板同步失败，已回滚已创建内容" if remote_enabled else "模板处理失败"
        suggestion = "已回滚已创建内容，稍后可以再试一次。" if remote_enabled else "请检查模板配置后再试一次。"
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason=user_reason,
            retryable=True,
            failure_code="local_template_sync_failed" if remote_enabled else "local_template_failed",
        )
        action_log = _action_log_with_failure_details(
            "create_schedule",
            final_name,
            [],
            details={
                "template": source_schedule_name or local_template_file,
                "kind": display_kind,
                "season": display_season,
                "creation_path": "local_template_sync" if remote_enabled else "local_template_only",
                "remote_template": remote_template_name,
                "source_schedule_name": source_schedule_name,
                "local_template_file": local_template_file,
            },
            raw_reason=exc.detail,
            user_reason=user_reason,
            retryable=True,
            failure_code="local_template_sync_failed" if remote_enabled else "local_template_failed",
        )
        return (
            _failure_runtime_reply("create_schedule", "新作息方案", final_name, reason=user_reason, suggestion=suggestion),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )
    except Exception as exc:
        raw_reason = _short_error_text(exc)
        user_reason = "模板同步失败，已回滚已创建内容" if remote_enabled else "模板处理失败"
        suggestion = "已回滚已创建内容，稍后可以再试一次。" if remote_enabled else "请检查模板配置后再试一次。"
        failure_details = _failure_runtime_detail_payload(
            raw_reason,
            user_reason=user_reason,
            retryable=True,
            failure_code="local_template_sync_failed" if remote_enabled else "local_template_failed",
        )
        action_log = _action_log_with_failure_details(
            "create_schedule",
            final_name,
            [],
            details={
                "template": source_schedule_name or local_template_file,
                "kind": display_kind,
                "season": display_season,
                "creation_path": "local_template_sync" if remote_enabled else "local_template_only",
                "remote_template": remote_template_name,
                "source_schedule_name": source_schedule_name,
                "local_template_file": local_template_file,
            },
            raw_reason=raw_reason,
            user_reason=user_reason,
            retryable=True,
            failure_code="local_template_sync_failed" if remote_enabled else "local_template_failed",
        )
        return (
            _failure_runtime_reply("create_schedule", "新作息方案", final_name, reason=user_reason, suggestion=suggestion),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )

    detail = {
        "template": source_schedule_name or local_template_file,
        "kind": display_kind,
        "season": display_season,
        "updated_tasks": updated_count,
        "creation_path": "local_template_sync" if remote_enabled else "local_template_only",
        "remote_template": remote_template_name,
        "source_schedule_name": source_schedule_name,
        "local_template_file": local_template_file,
        "fallback_used": bool(remote_enabled and remote_template_name),
    }
    detail.update(template_media_details)
    action_log = _build_action_log("create_schedule", final_name, [], details=detail)
    if start_date:
        period_text = start_date.strftime("%Y-%m-%d")
        if end_date:
            period_text = f"{period_text} 至 {end_date.strftime('%Y-%m-%d')}"
        return (
            _append_key_intent_followup(
                "create_schedule",
                _success_runtime_reply(
                    "create_schedule",
                    [
                        '小电已经为您创建好了“{schedule_name}”，有效期为 {period_text}。',
                        '搞定啦，小电已经把“{schedule_name}”创建好了，生效时间为 {period_text}。',
                        '小电已经帮您创建好了“{schedule_name}”，有效期为 {period_text}。',
                    ],
                    final_name,
                    period_text,
                    schedule_name=final_name,
                    period_text=period_text,
                ),
            ),
            {"missing_slots": []},
            [action_log],
        )
    return (
        _append_key_intent_followup(
            "create_schedule",
            _success_runtime_reply(
                "create_schedule",
                [
                    '小电已经为您创建好了“{schedule_name}”。',
                    '搞定啦，小电已经把“{schedule_name}”创建好了。',
                    '小电已经帮您创建好了“{schedule_name}”。',
                ],
                final_name,
                schedule_name=final_name,
            ),
        ),
        {"missing_slots": []},
        [action_log],
    )


def _task_name_matches(task: dict, task_name: str) -> bool:
    if not isinstance(task, dict) or not task_name:
        return False
    target = _compact_text(task_name)
    candidates = [
        task.get("taskname"),
        task.get("name"),
        task.get("customName"),
        task.get("audio"),
        task.get("medianame"),
    ]
    for value in candidates:
        if not value:
            continue
        value_text = str(value)
        if value_text == task_name:
            return True
        compact = _compact_text(value_text)
        if compact == target or (target and target in compact):
            return True
    return False


def _schedule_name_matches(item: dict, schedule_name: str) -> bool:
    if not isinstance(item, dict) or not schedule_name:
        return False
    target = _compact_text(schedule_name)
    candidates = [
        item.get("schedule_name"),
        item.get("name"),
        item.get("sechename"),
        item.get("schedule"),
    ]
    for value in candidates:
        if not value:
            continue
        value_text = str(value)
        if value_text == schedule_name:
            return True
        compact = _compact_text(value_text)
        if compact and target and (compact == target or target in compact or compact in target):
            return True
    return False


def _apply_runtime_task_state_change(
    intent: str,
    text: str,
    slots: dict,
    *,
    state_value: int,
    action_name: str,
    action_text: str,
    check_terminal_status: bool = False,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name, task_name = _resolve_schedule_and_task_slots(slots)
    task_id = _task_slot_id(slots)
    if not task_name and not _strict_numeric_task_id_text(task_id):
        return (f"请补充要{action_text}的任务名称(task_name)。", {"missing_slots": ["task_name"]}, [])

    payload = _clone_payload(_load_schedules_payload())
    resolved_schedule_name, scope_kind, rows, pending_reply = _runtime_task_rows_for_scope(
        intent,
        text,
        slots,
        payload,
        schedule_name,
        default_scope="broadcast",
    )
    if pending_reply:
        return pending_reply
    if schedule_name and not rows:
        return (f'没有找到作息方案“{schedule_name}”。', {"missing_slots": []}, [])

    matched_rows, pending_reply = _strict_resolve_task_rows(intent, text, slots, rows, task_name, task_id)
    if pending_reply:
        return pending_reply
    if not matched_rows:
        # Fallback: 本地 broadcast_schedules 缓存可能跟远端不同步（前端"作息管理"页面
        # 走 routes/light.py 的 CRUD，不会回写到 broadcast_schedules.json）。
        # 找不到 task 时，对当前启用方案的任务做一次实时模糊匹配（gettaskinfo）。
        if task_name and _remote_enabled() and not resolved_schedule_name:
            remote_hit = _remote_find_task_id_by_name(task_name)
            if remote_hit:
                fallback_task_id, fallback_task_name, fallback_score = remote_hit
                # R1: score < 0.95 视为低置信度，不自动执行，而是返回明确提示，
                # 让用户用完整名字再说一次，避免误开/误停任务。
                if fallback_score < 0.95:
                    return (
                        f'未在当前启用方案里找到任务"{task_name}"。'
                        f'可能您指的是"{fallback_task_name}"？请用完整任务名称再说一次。',
                        {"missing_slots": []},
                        [],
                    )
                try:
                    _remote_set_task_state(fallback_task_id, state_value)
                except HTTPException as exc:
                    return (
                        f'尝试{action_text}任务"{fallback_task_name}"时远端返回错误：{exc.detail}',
                        {"missing_slots": []},
                        [],
                    )
                fallback_log = _build_action_log(
                    action_name, "", [],
                    mode="runtime",
                    details={
                        "runtime_scope": "remote_fallback",
                        "task_id": fallback_task_id,
                        "task_name": fallback_task_name,
                        "match_score": round(fallback_score, 3),
                        "state": state_value,
                        "matched_query": task_name,
                        "created_at": _now_str(),
                    },
                )
                return (
                    f'已{action_text}任务"{fallback_task_name}"。',
                    {"missing_slots": []},
                    [fallback_log],
                )
        if resolved_schedule_name:
            return (f'在方案"{resolved_schedule_name}"中未找到任务"{task_name}"。', {"missing_slots": []}, [])
        return (f'未找到文件广播任务"{task_name or task_id}"。', {"missing_slots": []}, [])

    updated_ids: List[str] = []
    invalid_targets: List[dict] = []
    failed_targets: List[dict] = []
    offline_names: List[str] = []
    remote_on = _remote_enabled()
    for row in matched_rows:
        task = row.get("task") or {}
        raw_task_id = _task_id(task)
        strict_task_id = _strict_numeric_task_id_text(raw_task_id)
        task_label = _phase1_task_name(task) or raw_task_id or "未命名任务"
        if remote_on:
            if not strict_task_id:
                invalid_targets.append({"task_name": task_label, "task_id": str(raw_task_id or "")})
                continue
            try:
                _remote_set_task_state(strict_task_id, state_value)
            except HTTPException as exc:
                failed_targets.append(
                    {
                        "task_name": task_label,
                        "task_id": strict_task_id,
                        "error": str(exc.detail),
                    }
                )
                continue
        terminal_ids = _get_task_terminal_ids(task)
        if check_terminal_status and terminal_ids:
            _, offline = _check_terminal_online_status(terminal_ids)
            if offline:
                offline_names.extend(offline)
        task["taskstate"] = state_value
        task["status"] = _task_display_status(state_value, task.get("status"))
        if strict_task_id or raw_task_id:
            updated_ids.append(strict_task_id or str(raw_task_id))

    if remote_on and not updated_ids:
        failure_source = (
            failed_targets[0].get("error")
            if failed_targets
            else f"invalid_targets={len(invalid_targets)}"
            if invalid_targets
            else "没有成功改动任何任务状态"
        )
        user_reason = (
            "远端暂未处理成功"
            if failed_targets
            else "目标任务缺少有效编号"
            if invalid_targets
            else "没有找到可执行目标"
        )
        retryable = True if failed_targets else False
        failure_code = (
            "task_state_update_failed"
            if failed_targets
            else "task_state_invalid_target"
            if invalid_targets
            else "task_state_no_effective_target"
        )
        failure_details = _failure_runtime_detail_payload(
            failure_source,
            user_reason=user_reason,
            retryable=retryable,
            failure_code=failure_code,
        )
        action_log = _action_log_with_failure_details(
            action_name,
            resolved_schedule_name,
            [],
            mode="runtime",
            details={
                "task_name": task_name,
                "schedule_name": resolved_schedule_name,
                "count": len(matched_rows),
                "scope": scope_kind,
                "invalid_targets": invalid_targets,
                "failed_targets": failed_targets,
            },
            raw_reason=failure_source,
            user_reason=user_reason,
            retryable=retryable,
            failure_code=failure_code,
        )
        return (
            _failure_runtime_reply(
                action_name,
                f"任务“{task_name or task_id or '当前目标'}”的{action_text}",
                task_name or task_id or "",
                reason=user_reason,
                suggestion="您可以换个说法再试，或者补充更明确的任务名。",
            ),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )

    _touch_generated_at(payload)
    _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
    unique_offline = _unique_list(offline_names)
    action_label_map = {
        "play_task": "开始播放",
        "stop_task": "停止",
        "task_pause": "暂停",
        "task_resume": "恢复播放",
    }
    action_label = action_label_map.get(action_name, action_text)
    task_label = str(task_name or task_id or "相关任务")
    if scope_kind == "schedule" and resolved_schedule_name:
        reply = _success_runtime_reply(
            action_name,
            [
                '已将方案“{schedule_name}”里的任务“{task_name}”设为{action_label}。',
                '方案“{schedule_name}”中的“{task_name}”现在是{action_label}状态。',
                '任务“{task_name}”已在方案“{schedule_name}”中调整为{action_label}。',
            ],
            resolved_schedule_name,
            task_label,
            schedule_name=resolved_schedule_name,
            task_name=task_label,
            action_label=action_label,
        )
    else:
        reply = _success_runtime_reply(
            action_name,
            [
                '已为您将任务“{task_name}”设为{action_label}。',
                '任务“{task_name}”现在是{action_label}状态。',
                '“{task_name}”已经调整为{action_label}。',
            ],
            task_label,
            task_name=task_label,
            action_label=action_label,
        )
    detail_lines: List[str] = []
    if invalid_targets:
        detail_lines.append(f"另有 {len(invalid_targets)} 条任务缺少有效 task_id，已按失败处理。")
    if failed_targets:
        detail_lines.append(f"另有 {len(failed_targets)} 条任务远端执行失败，请查看 action_log。")
    if unique_offline:
        detail_lines.append(f"注意：{_preview_runtime_names(unique_offline, limit=5, noun='个终端')} 当前离线，请留意播放状态。")
    reply = _append_runtime_reply_details(reply, *detail_lines)
    action_log = _action_log_with_failure_details(
        action_name,
        resolved_schedule_name,
        _unique_list(updated_ids),
        mode="runtime",
        details={
            "task_name": task_name,
            "schedule_name": resolved_schedule_name,
            "count": len(matched_rows),
            "scope": scope_kind,
            "invalid_targets": invalid_targets,
            "failed_targets": failed_targets,
        },
        raw_reason=failed_targets[0]["error"] if failed_targets else None,
        user_reason="部分任务状态调整失败" if failed_targets else "",
        retryable=True if failed_targets else None,
        failure_code="task_state_partial_failure" if failed_targets else "",
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_play_task_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_runtime_task_state_change(
        "play_task",
        text,
        slots,
        state_value=1,
        action_name="play_task",
        action_text="执行",
        check_terminal_status=True,
    )


def _apply_stop_task_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_runtime_task_state_change(
        "stop_task",
        text,
        slots,
        state_value=0,
        action_name="stop_task",
        action_text="停止",
    )


def _apply_stop_media_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    if not _remote_enabled():
        return ("未配置远端服务，无法停止临时播放。", {"missing_slots": []}, [])
    from backend.routes.light import action_request as _light_action_request
    resp = _light_action_request("POST", "/action/stoptmptask", body_mode="none")
    if resp.get("success"):
        reply = "已停止临时播放。"
        status = "ok"
    else:
        reply = f"停止临时播放失败：{resp.get('message', '未知错误')}"
        status = "error"
    action_log = {"action": "stop_media", "mode": "runtime", "status": status}
    return (reply, {"missing_slots": []}, [action_log])


def _apply_task_pause_resume_intent(
    text: str,
    slots: dict,
    *,
    state_value: int,
    action_name: str,
    action_text: str,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_runtime_task_state_change(
        action_name,
        text,
        slots,
        state_value=state_value,
        action_name=action_name,
        action_text=action_text,
    )


def _apply_task_pause_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_task_pause_resume_intent(
        text,
        slots,
        state_value=2,
        action_name="task_pause",
        action_text="暂停",
    )


def _apply_task_resume_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_task_pause_resume_intent(
        text,
        slots,
        state_value=3,
        action_name="task_resume",
        action_text="恢复",
    )


def _apply_play_media_intent_legacy(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    effective_slots = _sanitize_play_media_slots(text, slots)
    media_text = _slot_text(effective_slots, "media_name", "CONTENT", "TASK", "audio", "medianame")
    if not media_text:
        return (
            _ask_runtime_reply(
                "play_media",
                "要播放的媒体名称",
                example="比如播放国歌，或者播放课间音乐",
            ),
            {"missing_slots": ["media_name"]},
            [],
        )
    if not _remote_enabled():
        return ("未配置远端服务,无法执行即时媒体播放。", {"missing_slots": []}, [])

    terminal_ids, unresolved = _resolve_terminal_ids_for_play_media(effective_slots)
    zone_names = _slot_values(effective_slots, "zone_name")
    explicit_target_values = _slot_values(effective_slots, "terminal_id", "scope_id") + _slot_values(
        effective_slots, "terminal_name", "SCOPE", "LOC"
    )
    has_explicit_targets = bool([item for item in explicit_target_values if item])
    unresolved_zones = unresolved.get("zone_name", [])
    if zone_names and unresolved_zones and not has_explicit_targets:
        return (
            f"分区解析失败,未执行即时媒体播放。未完成分区:{_unique_list(unresolved_zones)}。",
            {"missing_slots": []},
            [],
        )
    if not terminal_ids:
        missing = ["zone_name/terminal_id/terminal_name"]
        detail = "请至少提供分区、终端ID或终端名称中的一个。"
        if unresolved:
            detail = f"{detail} 未匹配信息:{unresolved}。"
        return (detail, {"missing_slots": missing}, [])

    try:
        media_match = _play_media_folder_exact_match(
            effective_slots,
            media_text,
            slot_key="media_name",
        )
    except HTTPException as exc:
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason="媒体目录暂时不可用",
            retryable=True,
            failure_code="media_directory_unavailable",
        )
        action_log = _action_log_with_failure_details(
            "play_media",
            "",
            [],
            mode="runtime",
            details={"runtime_scope": "temp_task"},
            raw_reason=exc.detail,
            user_reason="媒体目录暂时不可用",
            retryable=True,
            failure_code="media_directory_unavailable",
        )
        return (
            "媒体目录暂时不可用，稍后再试。",
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )
    if not media_match:
        return (f'媒体库中未找到"{media_text}"。', {"missing_slots": []}, [])
    media_id, media_name = str(media_match[0]), str(media_match[1])

    duration_raw = _resolve_play_duration_text(text, _slot_text(effective_slots, "play_duration", "duration", "play_length"))
    count_raw = _resolve_play_count_text(text, _slot_text(effective_slots, "play_count", "count"))
    timelength, timelengthtype = _parse_play_mode_slots({
        **effective_slots,
        "play_duration": duration_raw,
        "play_count": count_raw,
    })
    volume = _parse_volume_slot(effective_slots)
    addtemp_playtype = 1 if timelengthtype == 1 else 2
    addtemp_playlength = (
        _duration_seconds_from_text(duration_raw) or timelength * 60
        if addtemp_playtype == 1
        else timelength
    )

    created_task_id: Optional[str] = None
    try:
        created_task_id = _remote_add_temp_task(
            media_ids=[media_id],
            terminal_ids=terminal_ids,
            volume=volume,
            playtype=addtemp_playtype,
            playlength=addtemp_playlength,
            playpriority=10,
        )
    except HTTPException as exc:
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason="即时播放指令没有发出",
            retryable=True,
            failure_code="runtime_play_dispatch_failed",
        )
        action_log = _action_log_with_failure_details(
            "play_media",
            "",
            [],
            mode="runtime",
            details={
                "runtime_scope": "temp_task",
                "media_id": media_id,
                "media_name": media_name,
                "terminal_ids": [str(item) for item in terminal_ids],
                "terminal_count": len(terminal_ids),
                "timelength": timelength,
                "timelengthtype": timelengthtype,
                "playtype": addtemp_playtype,
                "playlength": addtemp_playlength,
                "volume": volume,
                "unresolved": unresolved,
            },
            raw_reason=exc.detail,
            user_reason="即时播放指令没有发出",
            retryable=True,
            failure_code="runtime_play_dispatch_failed",
        )
        return (
            _failure_runtime_reply(
                "play_media",
                f"媒体“{media_name}”的即时播放",
                media_name,
                reason="指令没有发出",
                suggestion="稍后可以再试一次。",
            ),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )

    offline_names: List[str] = []
    try:
        _, offline_names = _check_terminal_online_status(terminal_ids)
    except Exception:
        offline_names = []

    duration_desc = _describe_play_mode(duration_raw, count_raw, addtemp_playtype, timelength, addtemp_playlength)
    terminal_desc = _reply_preview_terminals_by_ids(terminal_ids, limit=3) or f"{len(terminal_ids)}个终端"
    reply = _success_runtime_reply(
        "play_media",
        [
            '已为您在 {terminal_desc} 播放“{media_name}”，预计持续 {duration_desc}。',
            '“{media_name}”正在 {terminal_desc} 播放，预计时长 {duration_desc}。',
            '即时播放已经发出，目标是 {terminal_desc}，内容是“{media_name}”。',
        ],
        media_name,
        terminal_desc,
        duration_desc,
        media_name=media_name,
        terminal_desc=terminal_desc,
        duration_desc=duration_desc,
    )
    detail_lines: List[str] = []
    if offline_names:
        unique_offline = _unique_list(offline_names)
        detail_lines.append(f"注意：{_preview_runtime_names(unique_offline, limit=5, noun='个终端')} 当前离线。")
    if unresolved_zones and has_explicit_targets:
        detail_lines.append(f"以下分区未执行：{_preview_runtime_names(_unique_list(unresolved_zones), noun='个分区')}。")
    unresolved_other = {
        key: value
        for key, value in unresolved.items()
        if value and not (key == "zone_name" and has_explicit_targets)
    }
    if unresolved_other:
        detail_lines.append(_reply_unresolved_line(unresolved_other))
    reply = _append_runtime_reply_details(reply, *detail_lines)
_AREA_NAME_TO_INDEX: Dict[str, int] = {
    "??1": 0,
    "???": 0,
    "????1": 0,
    "?????": 0,
    "??2": 1,
    "???": 1,
    "????2": 1,
    "?????": 1,
    "??3": 2,
    "???": 2,
    "????3": 2,
    "?????": 2,
    "??4": 3,
    "???": 3,
    "????4": 3,
    "?????": 3,
    "??5": 4,
    "???": 4,
    "????5": 4,
    "?????": 4,
    "??6": 5,
    "???": 5,
    "????6": 5,
    "?????": 5,
    "????": 6,
    "??": 6,
    "????": 7,
    "??": 7,
}


def _build_area_params_from_slots(slots: dict) -> dict:
    # Map zone_name slots to area0-area7 params.
    zone_names = _slot_values(slots, "zone_name", "SCOPE", "LOC")
    named = [str(name).strip() for name in zone_names if str(name).strip()]
    areas = {i: 0 for i in range(8)}
    areas[6] = 1
    if named:
        for zone_name in named:
            idx = _AREA_NAME_TO_INDEX.get(zone_name)
            if idx is not None:
                areas[idx] = 1
    else:
        for i in range(6):
            areas[i] = 1
    return {f"area{i}": str(value) for i, value in areas.items()}


def _overlay_power_keywords_on_areas(text: str, area_params: Dict[str, str]) -> Dict[str, str]:
    """Slot extractor doesn't reliably tag 功放/外控; scan raw text as a fallback."""
    raw = str(text or "")
    out = dict(area_params)
    if "功放" in raw:
        out["area6"] = "1"
    if "外控" in raw:
        out["area7"] = "1"
    return out


_CN_DIGIT_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}


def _resolve_zone_index(zone_name: str) -> Optional[int]:
    """Map a zone slot value to area0-area5 index.
    Accepts full names from _AREA_NAME_TO_INDEX, plain digits "1"-"6",
    and Chinese digits 一-六. The NLU emits a variety of forms depending on
    the user's wording, so we try multiple normalizations.
    """
    if not zone_name:
        return None
    name = str(zone_name).strip()
    idx = _AREA_NAME_TO_INDEX.get(name)
    if idx is not None:
        return idx
    if name.isdigit():
        n = int(name)
        if 1 <= n <= 6:
            return n - 1
    # Strip common surrounding tokens: "分区", "号", "区"
    stripped = name.replace("分区", "").replace("号", "").replace("区", "").strip()
    if stripped and stripped != name:
        return _resolve_zone_index(stripped)
    # Chinese digit single char
    if name in _CN_DIGIT_MAP:
        return _CN_DIGIT_MAP[name] - 1
    return None


def _expand_zone_range_in_text(text: str) -> List[int]:
    """Detect range expressions like "1到6", "1-6", "一到六", "1～6"
    and return the list of 1-based zone numbers in the range (clamped to 1-6).
    """
    if not text:
        return []
    raw = str(text)
    # Normalize Chinese digits to Arabic for range detection
    for cn, ar in _CN_DIGIT_MAP.items():
        raw = raw.replace(cn, str(ar))
    match = re.search(r"([1-6])\s*(?:到|至|-|~|～)\s*([1-6])", raw)
    if not match:
        return []
    a, b = int(match.group(1)), int(match.group(2))
    lo, hi = (a, b) if a <= b else (b, a)
    return list(range(lo, hi + 1))


def _overlay_all_zones_keywords(text: str, areas: Dict[int, int]) -> Dict[int, int]:
    """If the user says "全部" / "所有" / "全场" / "全开" near "分区", flip area0-5 all on.
    Also honors explicit ranges like "1到6" / "一到六" via _expand_zone_range_in_text,
    and enumerations like "1、3、5 号分区" / "1 号和 3 号分区".
    """
    raw = str(text or "")
    out = dict(areas)
    has_all_keyword = any(kw in raw for kw in ("全部分区", "所有分区", "全场", "全开", "全部打开"))
    # "全部" alone is too ambiguous, only trigger if 分区 is in the sentence
    if not has_all_keyword and "全部" in raw and "分区" in raw:
        has_all_keyword = True
    if not has_all_keyword and "所有" in raw and "分区" in raw:
        has_all_keyword = True
    if has_all_keyword:
        for i in range(6):
            out[i] = 1
    for n in _expand_zone_range_in_text(raw):
        if 1 <= n <= 6:
            out[n - 1] = 1
    # 枚举兜底：「1、3、5 号分区」「1 号和 3 号分区」「一、二、三号分区」
    # 仅当语境里出现 "分区" 或 "号" 时触发，避免一般陈述句里的数字被误抓。
    # 负向断言阻止抓 "13" / "100" 里的子数字。
    if "分区" in raw or "号" in raw:
        for match in re.finditer(r"(?<![0-9])([1-6]|[一二三四五六])(?![0-9])", raw):
            token = match.group(1)
            n = _CN_DIGIT_MAP.get(token) if token in _CN_DIGIT_MAP else int(token)
            if 1 <= n <= 6:
                out[n - 1] = 1
    return out


def _build_zone_only_area_params(text: str, slots: dict) -> Dict[str, str]:
    """When no media is selected, build area params for a power/zone-only temp task.
    Differs from the media path: do NOT auto-fill all six zones if user said nothing —
    only honor what the user actually mentioned (zones via slots, power via keywords).
    Amplifier power (area6) defaults to 1 per device convention.
    """
    zone_names = _slot_values(slots, "zone_name", "SCOPE", "LOC")
    named = [str(name).strip() for name in zone_names if str(name).strip()]
    areas = {i: 0 for i in range(8)}
    areas[6] = 1  # 功放电源默认开
    for zone_name in named:
        idx = _resolve_zone_index(zone_name)
        if idx is not None:
            areas[idx] = 1
    # Honor "全部分区" / "所有分区" / "1到6" / "一到六" in the raw text — slot
    # extractor often gives a partial or empty zone_name for these phrasings.
    areas = _overlay_all_zones_keywords(text, areas)
    base = {f"area{i}": str(value) for i, value in areas.items()}
    return _overlay_power_keywords_on_areas(text, base)


def _label_area_key(key: str) -> str:
    """Translate raw area0-area7 keys into user-readable Chinese names."""
    if key.startswith("area") and key[4:].isdigit():
        idx = int(key[4:])
        if 0 <= idx <= 5:
            return f"分区{idx + 1}"
        if idx == 6:
            return "功放电源"
        if idx == 7:
            return "外控电源"
    return key


def _apply_zone_only_temp_task(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    """No-media variant of /action/executetmptask: open zones / power only."""
    if not _remote_enabled():
        return ("远端设备未启用，无法下发临时任务。", {"missing_slots": []}, [])

    area_params = _build_zone_only_area_params(text, slots)
    active = [k for k, v in area_params.items() if v == "1"]
    if not active:
        return (
            "没有识别到要打开的分区或电源，请说明具体的分区编号或电源名称。",
            {"missing_slots": ["zone_name"]},
            [],
        )

    form: Dict[str, Any] = {
        # no "media" key — this is the zone/power-only branch
        # no "terminal" key — 本地分区/电源不需要终端
        "playmode": "0",
        "timehour": "0",
        "timeminute": "2",
        "timesecond": "0",
        "times": "1",
        "volume": "80",
        "random": "0",
        **area_params,
    }

    from backend.routes.light import action_request as _light_action_request
    resp = _light_action_request("POST", "/action/executetmptask", form=form, body_mode="urlencoded")
    if resp.get("success"):
        # 区分用户主动点到的项和系统默认带上的功放电源。
        # 用户原文里没说"功放"但 area6=1，是默认逻辑加的，单独括号说明。
        raw_text = str(text or "")
        amp_was_default = "area6" in active and "功放" not in raw_text
        primary_keys = [k for k in sorted(active) if not (k == "area6" and amp_was_default)]
        primary_labels = [_label_area_key(k) for k in primary_keys]
        if primary_labels:
            reply = "已开启 " + "、".join(primary_labels)
            if amp_was_default:
                reply += "（功放电源已默认同时开启）"
            reply += "。"
        else:
            # 极端情况：用户没点任何东西，只剩默认 area6（理论上 active 不会只有 area6
            # 因为前面 if not active 已经过滤，但保留兜底）
            reply = "已开启 功放电源（默认）。"
        status = "ok"
    else:
        reply = f"下发失败：{resp.get('message', '未知错误')}"
        status = "error"
    action_log = _build_action_log(
        "play_media",
        "",
        [],
        mode="runtime",
        details={
            "runtime_scope": "temp_task_zone_only",
            "media_id": None,
            "media_name": None,
            "terminal_ids": [],
            "area_params": area_params,
            "status": status,
            "created_at": _now_str(),
        },
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_play_media_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    effective_slots = _sanitize_play_media_slots(text, slots)
    media_text = _slot_text(effective_slots, "media_name", "CONTENT", "TASK", "audio", "medianame")
    if not media_text:
        # 无媒体 = "只开分区/电源" 模式：复用 /action/executetmptask 但不传 media 字段
        return _apply_zone_only_temp_task(text, effective_slots)
    if not _remote_enabled():
        return ("???????????????????", {"missing_slots": []}, [])

    try:
        media_match = _play_media_folder_exact_match(effective_slots, media_text, slot_key="media_name")
    except HTTPException:
        return ("???????????????????", {"missing_slots": []}, [])
    if not media_match:
        return (f'??????????????{media_text}??', {"missing_slots": []}, [])
    media_id, media_name = str(media_match[0]), str(media_match[1])
    terminal_ids, unresolved = _resolve_terminal_ids_for_play_media(effective_slots)
    if not terminal_ids:
        return (
            "?????????????????????????",
            {"missing_slots": ["zone_name/terminal_id/terminal_name"], "unresolved": unresolved},
            [],
        )

    volume = _parse_volume_slot(effective_slots)
    area_params = _build_area_params_from_slots(effective_slots)
    form: Dict[str, Any] = {
        "media": media_id,
        "terminal": ",".join(str(item) for item in terminal_ids),
        "playmode": "0",
        "timehour": "0",
        "timeminute": "2",
        "timesecond": "0",
        "times": "1",
        "volume": str(max(0, min(100, int(volume or 80)))),
        "random": "0",
        **area_params,
    }

    from backend.routes.light import action_request as _light_action_request
    resp = _light_action_request("POST", "/action/executetmptask", form=form, body_mode="urlencoded")
    if resp.get("success"):
        reply = f'??????{media_name}??'
        status = "ok"
    else:
        reply = f'???{media_text}????{resp.get("message", "????")}'
        status = "error"
    action_log = _build_action_log(
        "play_media",
        "",
        [],
        mode="runtime",
        details={
            "runtime_scope": "temp_task",
            "media_id": media_id,
            "media_name": media_name,
            "terminal_ids": [str(item) for item in terminal_ids],
            "area_params": area_params,
            "volume": volume,
            "status": status,
            "created_at": _now_str(),
        },
    )
    return (reply, {"missing_slots": []}, [action_log])


def _find_schedule_loose(payload: dict, schedule_name: str) -> Optional[dict]:
    schedule = _find_schedule(payload, schedule_name)
    if schedule:
        return schedule
    target = _compact_text(schedule_name)
    if not target:
        return None
    schedules = payload.get("schedules") if isinstance(payload, dict) else []
    if not isinstance(schedules, list):
        return None
    for item in schedules:
        if not isinstance(item, dict):
            continue
        name = str(item.get("schedule_name") or item.get("name") or "")
        compact = _compact_text(name)
        if compact and (compact == target or target in compact or compact in target):
            return item
    return None


def _parse_time_offset_minutes(value: str) -> Optional[int]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "半小时" in text:
        return 30
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(分钟|分|小时|时|天|日|周|星期|个月|月|年)", text)
    if not match:
        number = _first_int_from_text(text)
        return number if number is not None else None
    number = float(match.group(1))
    unit = match.group(2)
    if unit in {"分钟", "分"}:
        return int(round(number))
    if unit in {"小时", "时"}:
        return int(round(number * 60))
    if unit in {"天", "日"}:
        return int(round(number * 24 * 60))
    if unit in {"周", "星期"}:
        return int(round(number * 7 * 24 * 60))
    if unit in {"月", "个月"}:
        return int(round(number * 30 * 24 * 60))
    if unit == "年":
        return int(round(number * 365 * 24 * 60))
    return int(round(number))


def _shift_hhmmss_with_day_delta(value: object, delta_minutes: int) -> Tuple[str, int]:
    raw = _format_hhmmss(str(value or "00:00:00")) or "00:00:00"
    parts = str(raw).split(":")
    if len(parts) < 2:
        return raw, 0
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) >= 3 else 0
    except Exception:
        return raw, 0
    base = datetime(2000, 1, 1, hour=hour, minute=minute, second=second)
    shifted = base + timedelta(minutes=delta_minutes)
    day_delta = (shifted.date() - base.date()).days
    return shifted.strftime("%H:%M:%S"), day_delta


def _rotate_weekdays(weekdays: List[str], day_delta: int) -> List[str]:
    ordered = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    offset = day_delta % 7
    if not weekdays or offset == 0:
        return _unique_list([str(day) for day in weekdays if day])
    rotated: List[str] = []
    for day in weekdays:
        if day not in ordered:
            continue
        idx = ordered.index(day)
        rotated.append(ordered[(idx + offset) % 7])
    return [day for day in ordered if day in _unique_list(rotated)]


def _shift_task_by_minutes(task: dict, delta_minutes: int) -> dict:
    shifted = _clone_payload(task)
    new_time, day_delta = _shift_hhmmss_with_day_delta(shifted.get("starttime") or shifted.get("time"), delta_minutes)
    shifted["starttime"] = new_time
    shifted["time"] = _format_hhmm(new_time)
    if day_delta == 0:
        return shifted
    weekdays = shifted.get("weekdays")
    if isinstance(weekdays, list) and weekdays:
        rotated = _rotate_weekdays([str(day) for day in weekdays if day], day_delta)
        if rotated:
            shifted["weekdays"] = rotated
            shifted["execmode"] = _execmode_from_weekdays(rotated)
    else:
        mapped = _weekdays_from_execmode(shifted.get("execmode"))
        if mapped:
            rotated = _rotate_weekdays(mapped, day_delta)
            shifted["weekdays"] = rotated
            shifted["execmode"] = _execmode_from_weekdays(rotated)
    start_dt = _parse_iso_date(shifted.get("startdate"))
    end_dt = _parse_iso_date(shifted.get("enddate"))
    if start_dt:
        shifted["startdate"] = (start_dt + timedelta(days=day_delta)).strftime("%Y-%m-%d")
    if end_dt:
        shifted["enddate"] = (end_dt + timedelta(days=day_delta)).strftime("%Y-%m-%d")
    return shifted


def _media_map_for_replace() -> dict:
    return _safe_media_map()


def _resolve_schedule_and_task_slots(slots: dict) -> Tuple[str, str]:
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    task_name = _slot_text(slots, "task_name", "TASK", "CONTENT", "task")
    return schedule_name, task_name


def _task_row(task: dict, *, schedule_name: str = "", scope_kind: str = "") -> dict:
    return {
        "task": task if isinstance(task, dict) else {},
        "schedule_name": str(schedule_name or ""),
        "scope_kind": str(scope_kind or ""),
    }


def _strict_resolve_task_rows(
    intent: str,
    text: str,
    slots: dict,
    rows: List[dict],
    task_name: str,
    task_id: str = "",
) -> Tuple[List[dict], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    strict_task_id = _strict_numeric_task_id_text(task_id)
    if strict_task_id:
        matched_rows = [
            row for row in rows
            if _strict_numeric_task_id_text(_task_id((row.get("task") or {}))) == strict_task_id
        ]
        return matched_rows, None
    if not task_name:
        return [], None
    choices = [
        _task_choice(
            row.get("task") or {},
            schedule_name=str(row.get("schedule_name") or ""),
            scope_kind=str(row.get("scope_kind") or ""),
        )
        for row in rows
        if isinstance(row.get("task"), dict)
    ]
    result = _strict_choice_resolution(task_name, choices)
    if result.get("status") == "resolved":
        choice = result.get("choice") or {}
        chosen_task_id = str(((choice.get("meta") or {}).get("task_id") or "")).strip()
        matched_rows = [
            row for row in rows
            if _task_matches_requested_target(row.get("task") or {}, task_name, chosen_task_id)
        ]
        return matched_rows, None
    if result.get("status") == "ambiguous":
        return [], _begin_target_disambiguation(
            intent=intent,
            text=text,
            slots=slots,
            target_type="task",
            query=task_name,
            choices=result.get("choices") or [],
        )
    return [], None


def _strict_query_task_rows(
    intent: str,
    text: str,
    slots: dict,
    rows: List[dict],
    task_name: str,
    task_id: str = "",
) -> Tuple[List[dict], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    strict_task_id = _strict_numeric_task_id_text(task_id)
    if strict_task_id:
        matched_rows = [
            row for row in rows
            if _strict_numeric_task_id_text(_task_id((row.get("task") or {}))) == strict_task_id
        ]
        return matched_rows, None
    if not task_name:
        return rows, None
    query_text = str(task_name or "").strip()
    compact_query = _compact_text(query_text)
    exact_rows: List[dict] = []
    normalized_rows: List[dict] = []
    for row in rows:
        task = row.get("task") or {}
        aliases = [
            task.get("taskname"),
            task.get("name"),
            task.get("customName"),
            task.get("audio"),
            task.get("medianame"),
        ]
        alias_texts = [str(alias).strip() for alias in aliases if str(alias).strip()]
        if any(alias == query_text for alias in alias_texts):
            exact_rows.append(row)
            continue
        if compact_query and any(_compact_text(alias) == compact_query for alias in alias_texts):
            normalized_rows.append(row)
    if exact_rows:
        return exact_rows, None
    if normalized_rows:
        return normalized_rows, None
    choices = [
        _task_choice(
            row.get("task") or {},
            schedule_name=str(row.get("schedule_name") or ""),
            scope_kind=str(row.get("scope_kind") or ""),
        )
        for row in rows
        if isinstance(row.get("task"), dict)
    ]
    result = _strict_choice_resolution(task_name, choices)
    if result.get("status") == "ambiguous":
        return [], _begin_target_disambiguation(
            intent=intent,
            text=text,
            slots=slots,
            target_type="task",
            query=task_name,
            choices=result.get("choices") or [],
        )
    return [], None


def _runtime_task_rows_for_scope(
    intent: str,
    text: str,
    slots: dict,
    payload: dict,
    schedule_name: str,
    *,
    default_scope: str = "broadcast",
    include_all_scopes_without_schedule: bool = False,
) -> Tuple[str, str, List[dict], Optional[Tuple[str, Dict[str, Any], List[dict]]]]:
    resolved_schedule_name = ""
    scope_kind = default_scope
    rows: List[dict] = []
    if schedule_name:
        schedule, pending_reply = _strict_resolve_schedule(intent, text, slots, payload, schedule_name)
        if pending_reply:
            return "", scope_kind, [], pending_reply
        if not schedule:
            return "", scope_kind, [], None
        resolved_schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or schedule_name)
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        rows = [
            _task_row(task, schedule_name=resolved_schedule_name, scope_kind="schedule")
            for task in tasks
            if isinstance(task, dict)
        ]
        return resolved_schedule_name, "schedule", rows, None
    if include_all_scopes_without_schedule:
        rows = _collect_query_task_rows(payload)
        for row in rows:
            row["scope_kind"] = str(row.get("kind") or "")
        return "", "mixed", rows, None
    items = payload.get(f"{default_scope}s") if isinstance(payload.get(f"{default_scope}s"), list) else []
    rows = [_task_row(task, scope_kind=default_scope) for task in items if isinstance(task, dict)]
    return "", default_scope, rows, None


def _save_schedules_payload_local(payload: dict) -> None:
    local_payload = _clone_payload(payload)
    _touch_generated_at(local_payload)
    _save_schedules_payload(
        local_payload,
        sync_schedules=False,
        sync_broadcasts=False,
        sync_livecasts=False,
    )


def _resolve_runtime_task_targets(
    payload: dict,
    schedule_name: str,
    task_name: str,
) -> Tuple[str, List[dict], str]:
    resolved_schedule_name = ""
    scope_kind = "broadcast"
    if schedule_name:
        schedule = _find_schedule_loose(payload, schedule_name)
        if not schedule:
            raise HTTPException(status_code=404, detail=f"没有找到作息方案“{schedule_name}”。")
        resolved_schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or schedule_name)
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        matched_tasks = [task for task in tasks if _task_name_matches(task, task_name)]
        return resolved_schedule_name, matched_tasks, "schedule"
    items = payload.get("broadcasts") if isinstance(payload.get("broadcasts"), list) else []
    matched_tasks = [task for task in items if _task_name_matches(task, task_name)]
    return "", matched_tasks, scope_kind


def _apply_enable_disable_schedule_intent(
    text: str,
    slots: dict,
    *,
    enabled: bool,
    action_name: str,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name, task_name = _resolve_schedule_and_task_slots(slots)
    task_id = _task_slot_id(slots)
    if not schedule_name and not task_name:
        return ("请提供方案名称或任务名称。", {"missing_slots": ["schedule_name/task_name"]}, [])
    if task_name and not schedule_name:
        return ("请补充 schedule_name，以确定要操作的作息方案。", {"missing_slots": ["schedule_name"]}, [])

    payload = _clone_payload(_load_schedules_payload())
    target_schedule_name = ""
    candidate_rows: List[dict] = []

    if schedule_name:
        schedule, pending_reply = _strict_resolve_schedule(action_name, text, slots, payload, schedule_name)
        if pending_reply:
            return pending_reply
        if not schedule:
            return (f'没有找到作息方案“{schedule_name}”。', {"missing_slots": []}, [])
        target_schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or schedule_name)
        tasks = schedule.get("tasks")
        if not isinstance(tasks, list):
            tasks = []
        if task_name:
            candidate_rows = [
                _task_row(task, schedule_name=target_schedule_name, scope_kind="schedule")
                for task in tasks
                if isinstance(task, dict)
            ]
            candidate_rows, pending_reply = _strict_resolve_task_rows(
                action_name,
                text,
                slots,
                candidate_rows,
                task_name,
                task_id,
            )
            if pending_reply:
                return pending_reply
            if not candidate_rows:
                return (f'在方案"{target_schedule_name}"中未找到任务"{task_name}"。', {"missing_slots": []}, [])
        else:
            schedule["status"] = "启用" if enabled else "停用"
            if _remote_enabled():
                try:
                    _remote_set_schedule_status(target_schedule_name, enabled)
                except HTTPException as exc:
                    failure_details = _failure_runtime_detail_payload(
                        exc.detail,
                        user_reason="方案状态没有改成功",
                        retryable=True,
                        failure_code="schedule_status_update_failed",
                    )
                    action_log = _action_log_with_failure_details(
                        action_name,
                        target_schedule_name,
                        [],
                        mode="runtime",
                        details={"enabled": enabled, "scope": "schedule"},
                        raw_reason=exc.detail,
                        user_reason="方案状态没有改成功",
                        retryable=True,
                        failure_code="schedule_status_update_failed",
                    )
                    return (
                        "方案状态没有改成功，稍后再试。",
                        {"missing_slots": [], "diagnostics": [failure_details]},
                        [action_log],
                    )
            _touch_generated_at(payload)
            _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
            action_log = _build_action_log(
                action_name,
                target_schedule_name,
                [],
                mode="runtime",
                details={"enabled": enabled, "scope": "schedule"},
            )
            state_text = "启用" if enabled else "停用"
            return (f'方案“{target_schedule_name}”已{state_text}。', {"missing_slots": []}, [action_log])

    state_value = 1 if enabled else 0
    display_status = _task_display_status(state_value, "执行中" if enabled else "停止")
    updated_ids: List[str] = []
    invalid_targets: List[dict] = []
    failed_targets: List[dict] = []
    for row in candidate_rows:
        task = row.get("task") or {}
        raw_task_id = _task_id(task)
        strict_task_id = _strict_numeric_task_id_text(raw_task_id)
        if _remote_enabled():
            if not strict_task_id:
                invalid_targets.append(
                    {"task_name": _phase1_task_name(task) or "未命名任务", "task_id": str(raw_task_id or "")}
                )
                continue
            try:
                _remote_set_task_state(strict_task_id, state_value)
            except HTTPException as exc:
                failed_targets.append(
                    {
                        "task_name": _phase1_task_name(task) or "未命名任务",
                        "task_id": strict_task_id,
                        "error": str(exc.detail),
                    }
                )
                continue
        task["taskstate"] = state_value
        task["status"] = display_status
        if strict_task_id or raw_task_id:
            updated_ids.append(strict_task_id or str(raw_task_id))
    if _remote_enabled() and not updated_ids:
        failure_source = (
            failed_targets[0].get("error")
            if failed_targets
            else f"invalid_targets={len(invalid_targets)}"
            if invalid_targets
            else "没有成功改动任何任务状态"
        )
        user_reason = (
            "远端暂未处理成功"
            if failed_targets
            else "目标任务缺少有效编号"
            if invalid_targets
            else "没有找到可执行目标"
        )
        retryable = True if failed_targets else False
        failure_code = (
            "schedule_task_state_update_failed"
            if failed_targets
            else "schedule_task_state_invalid_target"
            if invalid_targets
            else "schedule_task_state_no_effective_target"
        )
        failure_details = _failure_runtime_detail_payload(
            failure_source,
            user_reason=user_reason,
            retryable=retryable,
            failure_code=failure_code,
        )
        action_log = _action_log_with_failure_details(
            action_name,
            target_schedule_name,
            [],
            mode="runtime",
            details={
                "enabled": enabled,
                "scope": '方案任务' if target_schedule_name else "任务",
                "task_name": task_name,
                "invalid_targets": invalid_targets,
                "failed_targets": failed_targets,
            },
            raw_reason=failure_source,
            user_reason=user_reason,
            retryable=retryable,
            failure_code=failure_code,
        )
        return (
            _failure_runtime_reply(
                action_name,
                f'方案“{target_schedule_name}”中的任务状态调整' if target_schedule_name else "任务状态调整",
                target_schedule_name or task_name or "",
                reason=user_reason,
                suggestion="您可以换个说法再试，或者补充更明确的任务名。",
            ),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )
    _touch_generated_at(payload)
    _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
    state_text = "启用" if enabled else "停用"
    scope_text = f'方案"{target_schedule_name}"中的任务' if target_schedule_name else "任务"
    action_log = _action_log_with_failure_details(
        action_name,
        target_schedule_name,
        updated_ids,
        mode="runtime",
        details={
            "enabled": enabled,
            "scope": scope_text,
            "task_name": task_name,
            "invalid_targets": invalid_targets,
            "failed_targets": failed_targets,
        },
        raw_reason=failed_targets[0]["error"] if failed_targets else None,
        user_reason="部分任务状态调整失败" if failed_targets else "",
        retryable=True if failed_targets else None,
        failure_code="schedule_task_state_partial_failure" if failed_targets else "",
    )
    changed_count = len(updated_ids) or len(candidate_rows)
    reply = _success_runtime_reply(
        action_name,
        [
            "{scope_text}已设为{state_text}，共 {count} 条。",
            "{scope_text}现在都是{state_text}状态，共 {count} 条。",
            "{scope_text}已经调整完成，本次共处理 {count} 条。",
        ],
        scope_text,
        state_text,
        changed_count,
        scope_text=scope_text,
        state_text=state_text,
        count=changed_count,
    )
    detail_lines: List[str] = []
    if invalid_targets:
        detail_lines.append(f"另有 {len(invalid_targets)} 条任务缺少有效 task_id，已按失败处理。")
    if failed_targets:
        detail_lines.append(f"另有 {len(failed_targets)} 条任务远端执行失败，请查看 action_log。")
    reply = _append_runtime_reply_details(reply, *detail_lines)
    return (reply, {"missing_slots": []}, [action_log])


def _apply_enable_schedule_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_enable_disable_schedule_intent(text, slots, enabled=True, action_name="enable_schedule")


def _apply_disable_schedule_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_enable_disable_schedule_intent(text, slots, enabled=False, action_name="disable_schedule")


def _apply_shift_schedule_intent(
    text: str,
    slots: dict,
    *,
    later: bool,
    action_name: str,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    new_schedule_name = _slot_text(slots, "new_schedule_name", "target_schedule_name")
    offset_text = _slot_text(slots, "time_offset", "duration_offset")
    missing: List[str] = []
    if not schedule_name:
        missing.append("schedule_name")
    if not offset_text:
        missing.append("time_offset")
    if not new_schedule_name:
        missing.append("new_schedule_name")
    if missing:
        return ("请补充完整:源方案、位移量和新方案名称。", {"missing_slots": missing}, [])

    offset_minutes = _parse_time_offset_minutes(offset_text)
    if offset_minutes is None:
        return ('time_offset 解析失败,请使用如"30分钟/1小时/1天"格式。', {"missing_slots": []}, [])
    if offset_minutes <= 0:
        return ("time_offset 需要大于0。", {"missing_slots": []}, [])
    if not later:
        offset_minutes = -offset_minutes

    snapshot = _clone_payload(_load_schedules_payload())
    payload = _clone_payload(snapshot)
    source, pending_reply = _strict_resolve_schedule(action_name, text, slots, payload, schedule_name)
    if pending_reply:
        return pending_reply
    if not source:
        return (f"未找到源方案:{schedule_name}。", {"missing_slots": []}, [])
    if _find_schedule(payload, new_schedule_name):
        return (f'目标方案"{new_schedule_name}"已存在,请换一个名称。', {"missing_slots": []}, [])

    source_name = str(source.get("schedule_name") or source.get("name") or schedule_name)
    target = _clone_payload(source)
    target["schedule_name"] = new_schedule_name
    if "name" in target:
        target["name"] = new_schedule_name
    source_tasks = target.get("tasks") if isinstance(target.get("tasks"), list) else []
    shifted_tasks: List[dict] = []
    next_id = _coerce_int(_next_schedule_task_id(payload), 1)
    for task in source_tasks:
        if not isinstance(task, dict):
            continue
        shifted_task = _shift_task_by_minutes(task, offset_minutes)
        shifted_task["taskid"] = str(next_id)
        shifted_task["id"] = str(next_id)
        shifted_task["sechename"] = new_schedule_name
        next_id += 1
        shifted_tasks.append(shifted_task)
    target["tasks"] = shifted_tasks

    schedules = payload.get("schedules")
    if not isinstance(schedules, list):
        schedules = []
    schedules.append(target)
    payload["schedules"] = schedules

    try:
        _save_schedules_payload_local(payload)
    except HTTPException as exc:
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason="方案位移没有完成",
            retryable=True,
            failure_code="shift_schedule_local_save_failed",
        )
        action_log = _action_log_with_failure_details(
            action_name,
            new_schedule_name,
            [],
            details={
                "source_schedule_name": source_name,
                "new_schedule_name": new_schedule_name,
                "time_offset": offset_text,
                "count": len(shifted_tasks),
            },
            raw_reason=exc.detail,
            user_reason="方案位移没有完成",
            retryable=True,
            failure_code="shift_schedule_local_save_failed",
        )
        return ("方案位移没有完成，稍后再试。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])
    except Exception as exc:
        short_reason = _short_error_text(exc)
        failure_details = _failure_runtime_detail_payload(
            short_reason,
            user_reason="方案位移没有完成",
            retryable=True,
            failure_code="shift_schedule_local_save_failed",
        )
        action_log = _action_log_with_failure_details(
            action_name,
            new_schedule_name,
            [],
            details={
                "source_schedule_name": source_name,
                "new_schedule_name": new_schedule_name,
                "time_offset": offset_text,
                "count": len(shifted_tasks),
            },
            raw_reason=short_reason,
            user_reason="方案位移没有完成",
            retryable=True,
            failure_code="shift_schedule_local_save_failed",
        )
        return ("方案位移没有完成，稍后再试。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])

    if _remote_enabled():
        try:
            _sync_remote_schedules_targeted(payload, [new_schedule_name])
        except HTTPException as exc:
            rollback_errors: List[str] = []
            try:
                _save_schedules_payload_local(snapshot)
            except Exception as rollback_exc:
                rollback_errors.append(f"本地回滚失败:{_short_error_text(getattr(rollback_exc, 'detail', rollback_exc))}")
            cleanup_error = _cleanup_remote_created_schedule(new_schedule_name)
            if cleanup_error:
                rollback_errors.append(f"远端残留未清理:{cleanup_error}")
            failure_details = _failure_runtime_detail_payload(
                exc.detail,
                user_reason="方案位移没有完成",
                retryable=True,
                failure_code="shift_schedule_remote_sync_failed",
                cleanup_error="；".join(rollback_errors) if rollback_errors else "已回滚本地并清理远端新方案。",
            )
            action_log = _action_log_with_failure_details(
                action_name,
                new_schedule_name,
                [],
                details={
                    "source_schedule_name": source_name,
                    "new_schedule_name": new_schedule_name,
                    "time_offset": offset_text,
                    "count": len(shifted_tasks),
                },
                raw_reason=exc.detail,
                user_reason="方案位移没有完成",
                retryable=True,
                failure_code="shift_schedule_remote_sync_failed",
                cleanup_error="；".join(rollback_errors) if rollback_errors else "已回滚本地并清理远端新方案。",
            )
            suggestion = "已回滚本地并尝试清理远端新方案。"
            if rollback_errors:
                suggestion = "已尝试回滚，但还有残留需要处理。"
            return (
                _failure_runtime_reply(
                    action_name,
                    "方案位移",
                    new_schedule_name,
                    reason="方案位移没有完成",
                    suggestion=suggestion,
                ),
                {"missing_slots": [], "diagnostics": [failure_details]},
                [action_log],
            )
        except Exception as exc:
            rollback_errors = []
            try:
                _save_schedules_payload_local(snapshot)
            except Exception as rollback_exc:
                rollback_errors.append(f"本地回滚失败:{_short_error_text(getattr(rollback_exc, 'detail', rollback_exc))}")
            cleanup_error = _cleanup_remote_created_schedule(new_schedule_name)
            if cleanup_error:
                rollback_errors.append(f"远端残留未清理:{cleanup_error}")
            short_reason = _short_error_text(exc)
            failure_details = _failure_runtime_detail_payload(
                short_reason,
                user_reason="方案位移没有完成",
                retryable=True,
                failure_code="shift_schedule_remote_sync_failed",
                cleanup_error="；".join(rollback_errors) if rollback_errors else "已回滚本地并清理远端新方案。",
            )
            action_log = _action_log_with_failure_details(
                action_name,
                new_schedule_name,
                [],
                details={
                    "source_schedule_name": source_name,
                    "new_schedule_name": new_schedule_name,
                    "time_offset": offset_text,
                    "count": len(shifted_tasks),
                },
                raw_reason=short_reason,
                user_reason="方案位移没有完成",
                retryable=True,
                failure_code="shift_schedule_remote_sync_failed",
                cleanup_error="；".join(rollback_errors) if rollback_errors else "已回滚本地并清理远端新方案。",
            )
            suggestion = "已回滚本地并尝试清理远端新方案。"
            if rollback_errors:
                suggestion = "已尝试回滚，但还有残留需要处理。"
            return (
                _failure_runtime_reply(
                    action_name,
                    "方案位移",
                    new_schedule_name,
                    reason="方案位移没有完成",
                    suggestion=suggestion,
                ),
                {"missing_slots": [], "diagnostics": [failure_details]},
                [action_log],
            )

    action_log = _build_action_log(
        action_name,
        new_schedule_name,
        [],
        details={
            "source_schedule_name": source_name,
            "new_schedule_name": new_schedule_name,
            "time_offset": offset_text,
            "count": len(shifted_tasks),
        },
    )
    direction = "向后" if later else "向前"
    return (
        f'已基于"{source_name}"生成"{new_schedule_name}",并将任务整体{direction}位移 {offset_text}。',
        {"missing_slots": []},
        [action_log],
    )


def _apply_shift_schedule_later_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_shift_schedule_intent(text, slots, later=True, action_name="shift_schedule_later")


def _apply_shift_schedule_earlier_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_shift_schedule_intent(text, slots, later=False, action_name="shift_schedule_earlier")


def _apply_delete_schedule_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    if not schedule_name:
        return ("请补充要删除的方案名称(schedule_name)。", {"missing_slots": ["schedule_name"]}, [])

    payload = _clone_payload(_load_schedules_payload())
    overrides_payload = _clone_payload(_load_overrides_payload())
    schedules = payload.get("schedules") if isinstance(payload.get("schedules"), list) else []
    removed_schedule, pending_reply = _strict_resolve_schedule("delete_schedule", text, slots, payload, schedule_name)
    if pending_reply:
        return pending_reply
    if not removed_schedule:
        return (f"未找到方案:{schedule_name}。", {"missing_slots": []}, [])
    removed_name = str(removed_schedule.get("schedule_name") or removed_schedule.get("name") or schedule_name)
    removed_tasks = [task for task in (removed_schedule.get("tasks") or []) if isinstance(task, dict)]
    task_ids = [str(_task_id(task)) for task in removed_tasks if _task_id(task)]
    payload["schedules"] = [item for item in schedules if item is not removed_schedule]
    overrides_changed = _remove_once_overrides_for_schedule(overrides_payload, removed_name)

    if _remote_enabled():
        try:
            _delete_remote_schedule_tasks_strict(removed_name, removed_tasks)
        except HTTPException as exc:
            failure_details = _failure_runtime_detail_payload(
                exc.detail,
                user_reason="远端任务没有全部删除，本地变更未提交",
                retryable=True,
                failure_code="delete_schedule_remote_failed",
            )
            action_log = _action_log_with_failure_details(
                "delete_schedule",
                removed_name,
                task_ids,
                raw_reason=exc.detail,
                user_reason="远端任务没有全部删除，本地变更未提交",
                retryable=True,
                failure_code="delete_schedule_remote_failed",
                details={"count": len(task_ids)},
            )
            return ("方案没有删除成功，远端任务还没清完。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])
    failure_stage, failure_reason = _commit_schedule_delete_with_once_cleanup(
        payload,
        overrides_payload,
        save_schedule_payload=_save_schedules_payload_local,
        overrides_changed=overrides_changed,
    )
    if failure_stage == "schedule":
        user_reason = "远端任务已删除，但本地保存失败" if _remote_enabled() else "本地保存失败"
        failure_details = _failure_runtime_detail_payload(
            failure_reason,
            user_reason=user_reason,
            retryable=True,
            failure_code="delete_schedule_save_failed",
        )
        action_log = _action_log_with_failure_details(
            "delete_schedule",
            removed_name,
            task_ids,
            raw_reason=failure_reason,
            user_reason=user_reason,
            retryable=True,
            failure_code="delete_schedule_save_failed",
            details={"count": len(task_ids)},
        )
        if _remote_enabled():
            return ("方案删除已生效，但本地保存失败。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])
        return ("方案没有删除成功，本地保存这一步失败了。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])
    if failure_stage == "override":
        user_reason = "方案和远端任务已删除，但临时变更清理未完成"
        failure_details = _failure_runtime_detail_payload(
            failure_reason,
            user_reason=user_reason,
            retryable=True,
            failure_code="delete_schedule_override_cleanup_failed",
        )
        action_log = _action_log_with_failure_details(
            "delete_schedule",
            removed_name,
            task_ids,
            raw_reason=failure_reason,
            user_reason=user_reason,
            retryable=True,
            failure_code="delete_schedule_override_cleanup_failed",
            details={"count": len(task_ids), "schedule_deleted": True},
        )
        return ("方案已经删除，但临时变更清理未完成。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])

    action_log = _build_action_log("delete_schedule", removed_name, task_ids, details={"count": len(task_ids)})
    return (f'已删除方案"{removed_name}"。', {"missing_slots": []}, [action_log])


def _apply_replace_media_in_task_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    old_media = _slot_text(slots, "media_name", "media_old", "old_media")
    new_media = _slot_text(slots, "new_media_name", "media_new", "new_media")
    task_name = _slot_text(slots, "task_name", "TASK", "task")
    task_id = _task_slot_id(slots)
    missing: List[str] = []
    if not schedule_name and not task_name:
        missing.append("schedule_name/task_name")
    if not old_media:
        missing.append("media_name")
    if not new_media:
        missing.append("new_media_name")
    if missing:
        return ("请补充完整:方案名称或任务名称、旧媒体、新媒体。", {"missing_slots": missing}, [])

    media_map = _media_map_for_replace()
    old_match, pending_reply = _resolve_media_match_with_slot_hints(
        "replace_media_in_task",
        text,
        slots,
        old_media,
        media_map,
        slot_key="media_name",
    )
    if pending_reply:
        return pending_reply
    new_match, pending_reply = _resolve_media_match_with_slot_hints(
        "replace_media_in_task",
        text,
        slots,
        new_media,
        media_map,
        slot_key="new_media_name",
    )
    if pending_reply:
        return pending_reply
    if not old_match:
        return (f"媒体库中未找到旧媒体:{old_media}。", {"missing_slots": []}, [])
    if not new_match:
        return (f"媒体库中未找到新媒体:{new_media}。", {"missing_slots": []}, [])
    old_media_id, old_media_name = str(old_match[0]), str(old_match[1])
    new_media_id, new_media_name = str(new_match[0]), str(new_match[1])
    if old_media_id == new_media_id:
        return ("旧媒体与新媒体相同,无需替换。", {"missing_slots": []}, [])

    snapshot = _clone_payload(_load_schedules_payload())
    payload = _clone_payload(snapshot)
    resolved_schedule_name = ""
    task_sets: List[Tuple[str, List[dict]]] = []
    allowed_task_ids: set[str] = set()
    if schedule_name:
        schedule, pending_reply = _strict_resolve_schedule("replace_media_in_task", text, slots, payload, schedule_name)
        if pending_reply:
            return pending_reply
        if not schedule:
            return (f"未找到方案:{schedule_name}。", {"missing_slots": []}, [])
        resolved_schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or schedule_name)
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        task_sets.append((resolved_schedule_name, tasks))
    else:
        for schedule in payload.get("schedules", []):
            tasks = schedule.get("tasks") if isinstance(schedule, dict) else None
            if not isinstance(tasks, list):
                continue
            scoped_name = str(schedule.get("schedule_name") or schedule.get("name") or "")
            task_sets.append((scoped_name, tasks))
        for key in ("broadcasts",):
            items = payload.get(key) if isinstance(payload.get(key), list) else []
            task_sets.append((key, items))

    if task_name:
        task_rows: List[dict] = []
        for scope_name, tasks in task_sets:
            scope_kind = "schedule" if scope_name not in {"broadcasts", "livecasts"} else scope_name[:-1]
            for task in tasks:
                if isinstance(task, dict):
                    task_rows.append(
                        _task_row(
                            task,
                            schedule_name=scope_name if scope_kind == "schedule" else "",
                            scope_kind=scope_kind,
                        )
                    )
        matched_rows, pending_reply = _strict_resolve_task_rows(
            "replace_media_in_task",
            text,
            slots,
            task_rows,
            task_name,
            task_id,
        )
        if pending_reply:
            return pending_reply
        if not matched_rows:
            return (f'未找到任务"{task_name}"。', {"missing_slots": []}, [])
        allowed_task_ids = {
            _strict_numeric_task_id_text(_task_id(row.get("task") or {})) or str(_task_id(row.get("task") or {}))
            for row in matched_rows
            if _task_id(row.get("task") or {})
        }
        if not resolved_schedule_name and len(matched_rows) == 1:
            resolved_schedule_name = str(matched_rows[0].get("schedule_name") or "")

    old_compact = _compact_text(old_media_name)
    updated = 0
    updated_ids: List[str] = []
    for scope_name, tasks in task_sets:
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_key = _strict_numeric_task_id_text(_task_id(task)) or str(_task_id(task) or "")
            if allowed_task_ids:
                if not task_key or task_key not in allowed_task_ids:
                    continue
            elif task_name and not _task_name_matches(task, task_name):
                continue
            media_id = task.get("mediaid") or task.get("media_id")
            media_name = task.get("medianame") or task.get("audio")
            by_id = media_id is not None and str(media_id) == old_media_id
            by_name = bool(media_name) and _compact_text(str(media_name)) == old_compact
            legacy_by_taskname = (
                not by_id
                and not by_name
                and not media_id
                and not task.get("medianame")
                and not task.get("audio")
                and bool(task.get("taskname"))
                and _compact_text(str(task.get("taskname"))) == old_compact
            )
            if not by_id and not by_name and not legacy_by_taskname:
                continue
            task["mediaid"] = _coerce_int(new_media_id, 0)
            task["medianame"] = new_media_name
            if not task.get("audio") or _compact_text(str(task.get("audio"))) == old_compact:
                task["audio"] = new_media_name
            task_id = _task_id(task)
            if task_id:
                updated_ids.append(task_id)
            updated += 1
            if not resolved_schedule_name:
                resolved_schedule_name = scope_name

    if updated <= 0:
        if schedule_name:
            return (f'在方案"{resolved_schedule_name}"中未找到引用"{old_media_name}"的任务。', {"missing_slots": []}, [])
        if task_name:
            return (f'在任务范围"{task_name}"内未找到引用"{old_media_name}"的任务。', {"missing_slots": []}, [])
        return (f'未找到引用"{old_media_name}"的任务。', {"missing_slots": []}, [])

    try:
        _commit_payload_with_rollback(
            payload,
            snapshot,
            sync_schedules=True,
            sync_broadcasts=not bool(schedule_name),
            sync_livecasts=False,
            target_schedule_names=[resolved_schedule_name] if schedule_name and resolved_schedule_name else None,
        )
    except HTTPException as exc:
        return (f"媒体替换失败并已回滚:{exc.detail}", {"missing_slots": []}, [])

    action_log = _build_action_log(
        "replace_media_in_task",
        resolved_schedule_name if schedule_name else "",
        updated_ids,
        details={"media_old": old_media_name, "media_new": new_media_name, "count": updated, "task_name": task_name},
    )
    if schedule_name:
        reply = _stable_runtime_reply(
            "replace_media_in_task",
            [
                '已在方案“{schedule_name}”中将“{old_media}”替换为“{new_media}”，共 {count} 条。',
                '方案“{schedule_name}”中的媒体替换已完成：“{old_media}”已改为“{new_media}”，共 {count} 条。',
                '方案“{schedule_name}”里共有 {count} 条任务已从“{old_media}”替换为“{new_media}”。',
            ],
            resolved_schedule_name,
            old_media_name,
            new_media_name,
            updated,
            schedule_name=resolved_schedule_name,
            old_media=old_media_name,
            new_media=new_media_name,
            count=updated,
        )
    elif task_name:
        reply = _stable_runtime_reply(
            "replace_media_in_task",
            [
                '已在任务范围“{task_name}”内将“{old_media}”替换为“{new_media}”，共 {count} 条。',
                '任务范围“{task_name}”的媒体替换已完成，共 {count} 条：从“{old_media}”改为“{new_media}”。',
                '“{task_name}”范围内共有 {count} 条任务已从“{old_media}”替换为“{new_media}”。',
            ],
            task_name,
            old_media_name,
            new_media_name,
            updated,
            task_name=task_name,
            old_media=old_media_name,
            new_media=new_media_name,
            count=updated,
        )
    else:
        reply = _stable_runtime_reply(
            "replace_media_in_task",
            [
                '已将“{old_media}”替换为“{new_media}”，共 {count} 条。',
                '媒体替换已完成：共有 {count} 条记录从“{old_media}”改为“{new_media}”。',
                '共有 {count} 条任务已将“{old_media}”替换为“{new_media}”。',
            ],
            old_media_name,
            new_media_name,
            updated,
            old_media=old_media_name,
            new_media=new_media_name,
            count=updated,
        )
    return (reply, {"missing_slots": []}, [action_log])


def _resolve_terminal_ids_from_slots(slots: dict) -> Tuple[List[str], Dict[str, List[str]]]:
    return _resolve_terminal_ids_for_play_media(slots)


def _terminal_runtime_status(netstate: object, taskstate: object, devicestate: object) -> str:
    if str(netstate).strip().lower() == "unknown":
        return "未知"
    if str(netstate) == "0":
        return "离线"
    task_state = _coerce_int(taskstate, -1)
    if task_state in {1, 3}:
        return "播放中"
    if task_state == 2:
        return "暂停"
    if task_state == 0:
        return "空闲"
    device_text = str(devicestate or "").strip().lower()
    if device_text in {"fault", "error", "abnormal", "2", "3", "4"}:
        return "故障"
    return "在线"


def _remote_event_state_value(payload: object) -> Optional[int]:
    candidates = [payload]
    if isinstance(payload, dict):
        for key in ("data", "result", "item", "obj"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif isinstance(value, dict):
                candidates.append(value)
    for item in candidates:
        if not isinstance(item, dict):
            continue
        value = item.get("state")
        if value in (None, ""):
            continue
        try:
            return int(str(value).strip())
        except Exception:
            continue
    return None


def _post_remote_eventid(path: str, ids: List[str]) -> object:
    cleaned = [str(item).strip() for item in ids if str(item).strip() and str(item).strip() != "0"]
    if not cleaned:
        raise HTTPException(status_code=400, detail="Missing terminal ids.")
    payload = {"id": ",".join(_unique_list(cleaned))}
    resp = _remote_request(
        "POST",
        path,
        json_body=payload,
        form_body=None,
        allow_form_retry=False,
    )
    _ensure_remote_write_ack(resp, path, require_explicit=True)
    return resp


def _task_state_value(task: dict) -> int:
    if not isinstance(task, dict):
        return 0
    if task.get("taskstate") is not None:
        return _coerce_int(task.get("taskstate"), _task_state_from_label(task.get("status") or ""))
    return _task_state_from_label(task.get("status") or "")


def _terminal_lookup_for_actions() -> dict:
    try:
        lookup = _remote_terminal_lookup() if _remote_enabled() else {}
    except HTTPException:
        lookup = {}
    if isinstance(lookup, dict) and lookup:
        return lookup
    built: Dict[str, dict] = {}
    for item in _store_terminalinfo_items():
        if not isinstance(item, dict):
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if terminal_id is None:
            continue
        name = item.get("name") or item.get("ip") or f"terminal-{terminal_id}"
        built[str(terminal_id)] = {"name": str(name), "zone": item.get("zone")}
    if _remote_enabled():
        try:
            zone_items = _fetch_enriched_zone_items()
            _enrich_lookup_zones_from_terzone(built, zone_items)
        except Exception:
            pass
    return built


def _reply_preview_terminals_by_ids(terminal_ids: List[str], terminal_lookup: Optional[dict] = None, limit: int = 3) -> str:
    lookup = terminal_lookup if isinstance(terminal_lookup, dict) else _terminal_lookup_for_actions()
    names: List[str] = []
    for terminal_id in terminal_ids:
        item = lookup.get(str(terminal_id)) if isinstance(lookup, dict) else None
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
                continue
        names.append(f"终端{terminal_id}")
    return _preview_runtime_names(names, limit=limit, noun="个终端")


def _reply_preview_terminal_rows(rows: List[dict], limit: int = 3) -> str:
    return _preview_runtime_names(
        [row.get("terminal_name") for row in rows if isinstance(row, dict)],
        limit=limit,
        noun="个终端",
    )


def _reply_resolved_zone_names(zone_names: List[str], missing_zone_names: List[str]) -> List[str]:
    missing = {str(name or "").strip() for name in missing_zone_names}
    resolved: List[str] = []
    for name in zone_names:
        text = str(name or "").strip()
        if text and text not in missing:
            resolved.append(text)
    return _unique_runtime_texts(resolved)


def _reply_unresolved_line(unresolved: object) -> str:
    if not unresolved:
        return ""
    return f"以下对象没有匹配上：{unresolved}。"


def _apply_query_terminal_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    if not _remote_enabled():
        return ("未配置远端服务,无法查询终端状态。", {"missing_slots": []}, [])
    terminal_ids, unresolved = _resolve_terminal_ids_from_slots(slots)
    if not terminal_ids:
        return ("请至少提供终端ID、终端名称或分区名称。", {"missing_slots": ["terminal_id/terminal_name/zone_name"]}, [])

    snapshot = _terminal_runtime_rows(terminal_ids, _remote_terminalinfo_items())
    rows = snapshot.get("rows") or []
    online = len(snapshot.get("online_ids") or [])
    offline = len(snapshot.get("offline_names") or [])
    unknown = len(snapshot.get("unknown_names") or [])

    terminal_desc = _reply_preview_terminal_rows(rows, limit=3) or f"{len(rows)}个终端"
    reply = _query_runtime_reply(
        "query_terminal",
        [
            "{terminal_desc} 的状态已经查到：在线 {online} 个，离线 {offline} 个，未知 {unknown} 个。",
            "小电已经帮您查到 {terminal_desc} 的状态：在线 {online} 个，离线 {offline} 个，未知 {unknown} 个。",
            "终端查询结果已经出来了：{terminal_desc} 在线 {online} 个，离线 {offline} 个，未知 {unknown} 个。",
        ],
        terminal_desc,
        online,
        offline,
        unknown,
        terminal_desc=terminal_desc,
        online=online,
        offline=offline,
        unknown=unknown,
    )
    unresolved_line = _reply_unresolved_line(unresolved)
    reply = _finalize_key_intent_reply("query_terminal", reply, unresolved_line)
    action_log = _build_action_log(
        "query_terminal",
        "",
        [],
        mode="query",
        details={
            "count": len(rows),
            "online": online,
            "offline": offline,
            "unknown": unknown,
            "online_ids": snapshot.get("online_ids") or [],
            "offline_names": snapshot.get("offline_names") or [],
            "unknown_names": snapshot.get("unknown_names") or [],
            "terminals": rows,
            "unresolved": unresolved,
        },
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_enable_disable_terminal_intent(
    text: str,
    slots: dict,
    *,
    enabled: bool,
    action_name: str,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    del text, slots, enabled
    unsupported_label = "启用终端" if action_name == "enable_terminal" else "停用终端"
    return (
        f"当前航天广电 action 协议暂不支持{unsupported_label}。",
        {"missing_slots": []},
        [{"action": action_name, "mode": "runtime", "status": "unsupported"}],
    )
    if not _remote_enabled():
        return ("未配置远端服务,无法执行终端控制。", {"missing_slots": []}, [])
    terminal_ids, unresolved = _resolve_terminal_ids_from_slots(slots)
    if not terminal_ids:
        return ("请至少提供终端ID、终端名称或分区名称。", {"missing_slots": ["terminal_id/terminal_name/zone_name"]}, [])
    path = ""
    state_text = "启用" if enabled else "停用"
    terminal_desc = _reply_preview_terminals_by_ids(terminal_ids, limit=3) or f"{len(terminal_ids)}个终端"
    try:
        remote_payload = _post_remote_eventid(path, terminal_ids)
    except HTTPException as exc:
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason=f"{state_text}请求没有发出",
            retryable=True,
            failure_code="terminal_remote_request_failed",
        )
        action_log = _action_log_with_failure_details(
            action_name,
            "",
            [],
            mode="runtime",
            details={
                "terminal_ids": terminal_ids,
                "count": len(terminal_ids),
                "unresolved": unresolved,
                "acknowledged": False,
                "verified": False,
                "remote_state": None,
                "success_by_remote_state": False,
            },
            raw_reason=exc.detail,
            user_reason=f"{state_text}请求没有发出",
            retryable=True,
            failure_code="terminal_remote_request_failed",
        )
        return (
            _failure_runtime_reply(
                action_name,
                f"{state_text}终端",
                *terminal_ids,
                reason="请求没有发出",
                suggestion="稍后可以再试一次。",
            ),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )
    TTL_CACHE.pop("terminalinfo_payload", None)
    REMOTE_CACHE.pop("terminal_map", None)
    REMOTE_CACHE.pop("terminal_lookup", None)
    remote_state = _remote_event_state_value(remote_payload)
    success_by_remote_state = remote_state == 0
    if success_by_remote_state:
        reply = _success_runtime_reply(
            action_name,
            [
                '已为您{state_text}{terminal_desc}。',
                '{terminal_desc} 现在是{state_text}状态。',
                '{terminal_desc} 已调整为{state_text}状态。',
            ],
            terminal_desc,
            state_text,
            terminal_desc=terminal_desc,
            state_text=state_text,
        )
    else:
        failure_details = _failure_runtime_detail_payload(
            f"remote_state={remote_state}",
            user_reason="远端暂未确认成功",
            retryable=True,
            failure_code="terminal_remote_unconfirmed",
        )
        reply = _failure_runtime_reply(
            action_name,
            f"{state_text}{terminal_desc}",
            terminal_desc,
            reason="远端暂未确认成功",
            suggestion="稍后可以再试一次。",
        )
    reply = _append_runtime_reply_details(reply, _reply_unresolved_line(unresolved))
    action_log = _action_log_with_failure_details(
        action_name,
        "",
        [],
        mode="runtime",
        details={
            "terminal_ids": terminal_ids,
            "count": len(terminal_ids),
            "unresolved": unresolved,
            "acknowledged": True,
            "verified": success_by_remote_state,
            "remote_state": remote_state,
            "success_by_remote_state": success_by_remote_state,
        },
        raw_reason=None if success_by_remote_state else f"remote_state={remote_state}",
        user_reason="" if success_by_remote_state else "远端暂未确认成功",
        retryable=None if success_by_remote_state else True,
        failure_code="" if success_by_remote_state else "terminal_remote_unconfirmed",
    )
    overrides = {"missing_slots": []}
    if not success_by_remote_state:
        overrides["diagnostics"] = [failure_details]
    return (reply, overrides, [action_log])

def _apply_enable_terminal_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    del text, slots
    return (
        "当前航天广电 action 协议暂不支持启用终端。",
        {"missing_slots": []},
        [{"action": "enable_terminal", "mode": "runtime", "status": "unsupported"}],
    )

def _apply_disable_terminal_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    del text, slots
    return (
        "当前航天广电 action 协议暂不支持停用终端。",
        {"missing_slots": []},
        [{"action": "disable_terminal", "mode": "runtime", "status": "unsupported"}],
    )


def _apply_sync_terminal_time_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    del text, slots
    return (
        "当前航天广电 action 协议暂不支持终端校时。",
        {"missing_slots": []},
        [{"action": "sync_terminal_time", "mode": "runtime", "status": "unsupported"}],
    )


def _apply_check_terminal_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    if not _remote_enabled():
        return ("未配置远端服务,无法执行终端自检。", {"missing_slots": []}, [])
    has_explicit_target = any(
        _slot_text(slots, key)
        for key in ("terminal_id", "terminal_name", "zone_name")
    )
    terminal_ids, unresolved = _resolve_terminal_ids_from_slots(slots)
    if not terminal_ids:
        if has_explicit_target:
            return ("未找到匹配的终端或分区,未执行全量自检。", {"missing_slots": []}, [])
        terminal_ids = []
        for item in _remote_terminalinfo_items():
            if not isinstance(item, dict):
                continue
            terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
            if terminal_id in (None, "", 0, "0"):
                continue
            terminal_ids.append(str(terminal_id))
        terminal_ids = _unique_list(terminal_ids)
    if not terminal_ids:
        return ("未找到可自检的终端。", {"missing_slots": []}, [])

    snapshot = _terminal_runtime_rows(terminal_ids, _remote_terminalinfo_items())
    online_ids = snapshot.get("online_ids") or []
    offline_names = snapshot.get("offline_names") or []
    unknown_names = snapshot.get("unknown_names") or []
    terminal_desc = _reply_preview_terminal_rows(snapshot.get("rows") or [], limit=3) or f"{len(terminal_ids)}个终端"
    reply = _query_runtime_reply(
        "check_terminal",
        [
            "终端自检我已经查完了，涉及 {terminal_desc}：在线 {online} 个，离线 {offline} 个，未知 {unknown} 个。",
            "{terminal_desc} 的自检结果已经回来了：在线 {online} 个，离线 {offline} 个，未知 {unknown} 个。",
            "这条我已经帮您查完了，{terminal_desc} 当前状态是：在线 {online} 个，离线 {offline} 个，未知 {unknown} 个。",
        ],
        terminal_desc,
        len(online_ids),
        len(offline_names),
        len(unknown_names),
        terminal_desc=terminal_desc,
        online=len(online_ids),
        offline=len(offline_names),
        unknown=len(unknown_names),
    )
    detail_lines: List[str] = []
    if offline_names:
        detail_lines.append(f"离线终端：{_preview_runtime_names(offline_names, limit=8, noun='个终端')}。")
    if unknown_names:
        detail_lines.append(f"状态未知：{_preview_runtime_names(unknown_names, limit=8, noun='个终端')}。")
    detail_lines.append(_reply_unresolved_line(unresolved))
    reply = _append_runtime_reply_details(reply, *detail_lines)
    action_log = _build_action_log(
        "check_terminal",
        "",
        [],
        mode="query",
        details={
            "count": len(terminal_ids),
            "online_ids": online_ids,
            "offline_names": offline_names,
            "unknown_names": unknown_names,
            "terminals": snapshot.get("rows") or [],
            "unresolved": unresolved,
        },
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_create_zone_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    if not _remote_enabled():
        return ("未配置远端服务,无法新建分区。", {"missing_slots": []}, [])
    zone_names = _slot_values(slots, "zone_name", "ZONE")
    if not zone_names:
        return ("请补充分区名称(zone_name)。", {"missing_slots": ["zone_name"]}, [])

    existing_compact = {
        _compact_text(_zone_item_name(item)): _zone_item_name(item)
        for item in _remote_zone_items()
        if isinstance(item, dict)
    }

    created: List[str] = []
    skipped: List[str] = []
    failures: Dict[str, List[dict]] = {}
    for zone_name in zone_names:
        compact = _compact_text(zone_name)
        if compact and compact in existing_compact:
            skipped.append(zone_name)
            continue
        ok, attempts = _try_create_zone_remote(zone_name)
        if ok:
            created.append(zone_name)
            existing_compact[compact] = zone_name
            continue
        skipped.append(zone_name)
        failures[zone_name] = attempts

    try:
        if created:
            _invalidate_zone_runtime_caches()
        _sync_remote_data(force=True, keys=["all_loc"])
    except Exception:
        pass

    if not created:
        detail_hint = ""
        for failed_zone_name, attempts in failures.items():
            for attempt in attempts:
                error_text = str(attempt.get("error") or "").strip()
                if error_text:
                    detail_hint = f"{failed_zone_name}: {error_text}"
                    break
            if detail_hint:
                break
        reply = "分区新建失败，远端未接受本次请求。"
        if detail_hint:
            reply = reply + chr(10) + "首个错误：" + detail_hint
        action_log = _build_action_log(
            "create_zone",
            "",
            [],
            mode="runtime",
            details={"created": created, "skipped": skipped, "failures": failures},
        )
        return (reply, {"missing_slots": []}, [action_log])

    zone_desc = _preview_runtime_names(created, noun="个分区")
    reply = _stable_runtime_reply(
        "create_zone",
        [
            "分区已经建好：{zone_desc}。",
            "已完成分区创建：{zone_desc}。",
            "新的分区已经准备好了：{zone_desc}。",
        ],
        zone_desc,
        zone_desc=zone_desc,
    )
    detail_lines: List[str] = []
    if skipped:
        detail_lines.append(f"以下分区已存在，未重复创建：{_preview_runtime_names(skipped, noun='个分区')}。")
    if failures:
        detail_lines.append(f"另有 {len(failures)} 个分区创建失败，请查看 action_log.details.failures。")
    reply = _append_runtime_reply_details(reply, *detail_lines)
    action_log = _build_action_log(
        "create_zone",
        "",
        [],
        mode="runtime",
        details={"created": created, "skipped": skipped, "failures": failures},
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_delete_zone_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    if not _remote_enabled():
        return ("未配置远端服务,无法删除分区。", {"missing_slots": []}, [])
    zone_names = _slot_values(slots, "zone_name", "ZONE")
    if not zone_names:
        return ("请补充分区名称(zone_name)。", {"missing_slots": ["zone_name"]}, [])

    zone_ids, missing, pending_reply = _strict_resolve_zone_ids("delete_zone", text, slots, zone_names)
    if pending_reply:
        return pending_reply
    if not zone_ids:
        return ("未找到可删除的分区。", {"missing_slots": []}, [])
    try:
        _delete_zone_remote_checked(zone_ids)
    except HTTPException as exc:
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason="分区删除没有完成",
            retryable=True,
            failure_code="delete_zone_failed",
        )
        action_log = _action_log_with_failure_details(
            "delete_zone",
            "",
            [],
            mode="runtime",
            details={"zone_ids": zone_ids, "zone_names": _reply_resolved_zone_names(zone_names, missing), "missing": missing},
            raw_reason=exc.detail,
            user_reason="分区删除没有完成",
            retryable=True,
            failure_code="delete_zone_failed",
        )
        return ("分区删除没有完成，稍后再试。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])

    try:
        _invalidate_zone_runtime_caches(zone_ids)
        _sync_remote_data(force=True, keys=["all_loc"])
    except Exception:
        pass

    deleted_zone_names = _reply_resolved_zone_names(zone_names, missing)
    zone_desc = _preview_runtime_names(deleted_zone_names, noun="个分区") or f"{len(zone_ids)}个分区"
    reply = _stable_runtime_reply(
        "delete_zone",
        [
            "已删除分区：{zone_desc}。",
            "{zone_desc}分区已经删除完成。",
            "分区删除已完成，涉及：{zone_desc}。",
        ],
        zone_desc,
        zone_desc=zone_desc,
    )
    reply = _append_runtime_reply_details(reply, f"删除数量：{len(zone_ids)} 个。", (f"未匹配分区：{missing}。" if missing else ""))
    action_log = _build_action_log(
        "delete_zone",
        "",
        [],
        mode="runtime",
        details={"zone_ids": zone_ids, "zone_names": deleted_zone_names, "missing": missing},
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_add_remove_terminal_to_zone_intent(
    text: str,
    slots: dict,
    *,
    add: bool,
    action_name: str,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    if not _remote_enabled():
        return ("未配置远端服务,无法执行分区终端调整。", {"missing_slots": []}, [])
    zone_names = _slot_values(slots, "zone_name", "ZONE")
    if not zone_names:
        return ("请补充分区名称(zone_name)。", {"missing_slots": ["zone_name"]}, [])
    zone_ids, missing_zone, pending_reply = _strict_resolve_zone_ids(action_name, text, slots, zone_names)
    if pending_reply:
        return pending_reply
    if not zone_ids:
        return ("未找到可操作的分区。", {"missing_slots": []}, [])

    terminal_ids, unresolved = _resolve_terminal_ids_for_play_media(slots, expand_zones=False)
    if not terminal_ids:
        return ("请至少提供终端ID或终端名称。", {"missing_slots": ["terminal_id/terminal_name"]}, [])

    try:
        _update_zone_terminal_membership_remote_checked(
            zone_ids,
            terminal_ids,
            add=add,
            action_name=action_name,
        )
    except HTTPException as exc:
        failure_details = _failure_runtime_detail_payload(
            exc.detail,
            user_reason="分区终端调整没有完成",
            retryable=True,
            failure_code="zone_terminal_update_failed",
        )
        action_log = _action_log_with_failure_details(
            action_name,
            "",
            [],
            mode="runtime",
            details={
                "zone_ids": zone_ids,
                "zone_names": _reply_resolved_zone_names(zone_names, missing_zone),
                "terminal_ids": terminal_ids,
                "missing_zone": missing_zone,
                "unresolved": unresolved,
            },
            raw_reason=exc.detail,
            user_reason="分区终端调整没有完成",
            retryable=True,
            failure_code="zone_terminal_update_failed",
        )
        return ("分区终端调整没有完成，稍后再试。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])

    try:
        _invalidate_zone_runtime_caches(zone_ids)
        _sync_remote_data(force=True, keys=["all_loc"])
    except Exception:
        pass

    terminal_lookup = _terminal_lookup_for_actions()
    action_label = "加入" if add else "移出"
    zone_desc = _preview_runtime_names(_reply_resolved_zone_names(zone_names, missing_zone), noun="个分区") or f"{len(zone_ids)}个分区"
    terminal_desc = _reply_preview_terminals_by_ids(terminal_ids, terminal_lookup, limit=3) or f"{len(terminal_ids)}个终端"
    reply = _stable_runtime_reply(
        action_name,
        [
            "已将{terminal_desc}{action_label}分区{zone_desc}。",
            "{terminal_desc}已经{action_label}到分区{zone_desc}。",
            "分区调整完成：{terminal_desc}已{action_label}到{zone_desc}。",
        ] if add else [
            "已将{terminal_desc}从分区{zone_desc}移出。",
            "{terminal_desc}已经从分区{zone_desc}移除。",
            "分区调整完成：{terminal_desc}已从{zone_desc}移出。",
        ],
        zone_desc,
        terminal_desc,
        action_label,
        zone_desc=zone_desc,
        terminal_desc=terminal_desc,
        action_label=action_label,
    )
    reply = _append_runtime_reply_details(
        reply,
        _reply_unresolved_line({"zone_name": missing_zone, "terminal": unresolved} if (unresolved or missing_zone) else ""),
    )
    action_log = _build_action_log(
        action_name,
        "",
        [],
        mode="runtime",
        details={
            "zone_ids": zone_ids,
            "zone_names": _reply_resolved_zone_names(zone_names, missing_zone),
            "terminal_ids": terminal_ids,
            "terminal_names_preview": _reply_preview_terminals_by_ids(terminal_ids, terminal_lookup, limit=5),
            "missing_zone": missing_zone,
            "unresolved": unresolved,
        },
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_add_terminal_to_zone_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_add_remove_terminal_to_zone_intent(
        text,
        slots,
        add=True,
        action_name="add_terminal_to_zone",
    )


def _apply_remove_terminal_from_zone_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_add_remove_terminal_to_zone_intent(
        text,
        slots,
        add=False,
        action_name="remove_terminal_from_zone",
    )


def _select_task_targets_for_terminal_op(payload: dict, schedule_name: str, task_name: str) -> Tuple[str, List[dict]]:
    if schedule_name:
        schedule = _find_schedule_loose(payload, schedule_name)
        if not schedule:
            return "", []
        resolved_schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or schedule_name)
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        if task_name:
            return resolved_schedule_name, [task for task in tasks if _task_name_matches(task, task_name)]
        return resolved_schedule_name, [task for task in tasks if isinstance(task, dict)]
    if not task_name:
        return "", []
    # \u641c\u7d22\u6240\u6709\u65b9\u6848\u4e2d\u7684\u4efb\u52a1 + broadcasts / livecasts
    selected: List[dict] = []
    for sched in payload.get("schedules") if isinstance(payload.get("schedules"), list) else []:
        if not isinstance(sched, dict):
            continue
        for task in sched.get("tasks") if isinstance(sched.get("tasks"), list) else []:
            if _task_name_matches(task, task_name):
                selected.append(task)
    for key in ("broadcasts", "livecasts"):
        items = payload.get(key) if isinstance(payload.get(key), list) else []
        for task in items:
            if _task_name_matches(task, task_name):
                selected.append(task)
    return "", selected


def _apply_add_remove_terminal_to_task_intent(
    text: str,
    slots: dict,
    *,
    add: bool,
    action_name: str,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name, task_name = _resolve_schedule_and_task_slots(slots)
    task_id = _task_slot_id(slots)
    if not schedule_name and not task_name:
        return ("请至少提供任务名称或方案名称。", {"missing_slots": ["schedule_name/task_name"]}, [])

    terminal_ids, unresolved = _resolve_terminal_ids_from_slots(slots)
    terminal_ids = _normalize_terminal_ids(terminal_ids)
    if not terminal_ids:
        return ("请至少提供终端ID、终端名称或分区名称。", {"missing_slots": ["terminal_id/terminal_name"]}, [])

    payload = _clone_payload(_load_schedules_payload())
    resolved_schedule_name, _, rows, pending_reply = _runtime_task_rows_for_scope(
        action_name,
        text,
        slots,
        payload,
        schedule_name,
        default_scope="broadcast",
        include_all_scopes_without_schedule=True,
    )
    if pending_reply:
        return pending_reply
    if schedule_name and not rows:
        return (f'没有找到作息方案“{schedule_name}”。', {"missing_slots": []}, [])
    if task_name:
        rows, pending_reply = _strict_resolve_task_rows(action_name, text, slots, rows, task_name, task_id)
        if pending_reply:
            return pending_reply
    targets = [row.get("task") or {} for row in rows if isinstance(row.get("task"), dict)]
    if not targets:
        if resolved_schedule_name and task_name:
            return (f'在方案"{resolved_schedule_name}"中未找到任务"{task_name}"。', {"missing_slots": []}, [])
        return ("未找到可操作的任务。", {"missing_slots": []}, [])

    terminal_lookup = _terminal_lookup_for_actions()
    update_ids: List[str] = []
    remove_set = {str(item) for item in terminal_ids}
    remote_failures: List[dict] = []
    invalid_targets: List[dict] = []
    remote_changed = 0
    local_changed = 0
    local_synced_only = 0
    total_changed = 0
    remote_on = _remote_enabled()
    for task in targets:
        if not isinstance(task, dict):
            continue
        task_id = _task_id(task)
        task_display_name = str(task.get("taskname") or task.get("name") or task_id or "")
        current_ids = _normalize_terminal_ids(_get_task_terminal_ids(task))
        remote_snapshot_ok = False
        strict_task_id = _strict_numeric_task_id_text(task_id)
        if remote_on and not strict_task_id:
            invalid_targets.append({"task_id": str(task_id or ""), "task_name": task_display_name})
            continue
        if remote_on and strict_task_id:
            remote_current_ids, remote_snapshot_ok = _remote_task_terminal_ids_checked(strict_task_id)
            if not remote_snapshot_ok:
                remote_current_ids = _remote_task_terminal_ids(strict_task_id)
                remote_snapshot_ok = bool(remote_current_ids)
            if remote_snapshot_ok:
                current_ids = _normalize_terminal_ids(remote_current_ids)
            else:
                remote_failures.append(
                    {
                        "task_id": strict_task_id,
                        "task_name": task_display_name,
                        "error": "远端当前终端绑定快照获取失败",
                    }
                )
                continue
        if add:
            new_ids = _normalize_terminal_ids(current_ids + terminal_ids)
        else:
            new_ids = _normalize_terminal_ids([item for item in current_ids if str(item) not in remove_set])

        remote_effective_change = _unique_list(current_ids) != _unique_list(new_ids)
        if not remote_effective_change:
            local_updated = _apply_task_terminal_fields(task, new_ids, terminal_lookup)
            if local_updated:
                local_changed += 1
                total_changed += 1
                if remote_on and remote_snapshot_ok:
                    local_synced_only += 1
                if task_id:
                    update_ids.append(task_id)
            continue

        if remote_on and strict_task_id:
            current_id_set = {str(item) for item in current_ids}
            try:
                if add:
                    added_ids = [tid for tid in terminal_ids if str(tid) not in current_id_set]
                    for tid in added_ids:
                        _remote_add_taskterminal(strict_task_id, tid)
                else:
                    removed_ids = [tid for tid in terminal_ids if str(tid) in current_id_set]
                    for tid in removed_ids:
                        _remote_remove_taskterminal(strict_task_id, tid)
            except HTTPException as exc:
                verified_ids, verified_ok = _remote_task_terminal_ids_checked(strict_task_id)
                verified = False
                if verified_ok:
                    verified_set = {str(item) for item in _normalize_terminal_ids(verified_ids)}
                    if add:
                        verified = all(str(tid) in verified_set for tid in terminal_ids)
                    else:
                        verified = all(str(tid) not in verified_set for tid in terminal_ids)
                    if verified:
                        new_ids = _normalize_terminal_ids(verified_ids)
                        remote_effective_change = _unique_list(current_ids) != _unique_list(new_ids)
                if not verified:
                    remote_failures.append(
                        {
                            "task_id": strict_task_id,
                            "task_name": task_display_name,
                            "error": str(exc.detail),
                        }
                    )
                    continue

        if remote_effective_change and remote_on and strict_task_id:
            remote_changed += 1

        local_updated = _apply_task_terminal_fields(task, new_ids, terminal_lookup)
        if local_updated:
            local_changed += 1
            if remote_on and not remote_effective_change:
                local_synced_only += 1
        if local_updated or remote_effective_change:
            total_changed += 1
            if strict_task_id or task_id:
                update_ids.append(strict_task_id or task_id)

    if total_changed <= 0:
        if remote_failures:
            preview = "; ".join(
                f"{entry.get('task_name') or entry.get('task_id')}: {entry.get('error')}"
                for entry in remote_failures[:3]
            )
            if len(remote_failures) > 3:
                preview += f" ... 共 {len(remote_failures)} 条失败"
            failure_details = _failure_runtime_detail_payload(
                preview,
                user_reason="终端调整暂未生效",
                retryable=True,
                failure_code="task_terminal_remote_failed",
            )
            action_log = _action_log_with_failure_details(
                action_name,
                resolved_schedule_name,
                [],
                mode="runtime",
                details={
                    "schedule_name": resolved_schedule_name,
                    "task_name": task_name,
                    "terminal_ids": terminal_ids,
                    "changed": total_changed,
                    "remote_changed": remote_changed,
                    "local_changed": local_changed,
                    "local_synced_only": local_synced_only,
                    "unresolved": unresolved,
                    "remote_failures": remote_failures,
                    "invalid_targets": invalid_targets,
                },
                raw_reason=preview,
                user_reason="终端调整暂未生效",
                retryable=True,
                failure_code="task_terminal_remote_failed",
            )
            return ("终端调整暂未生效，稍后再试。", {"missing_slots": [], "diagnostics": [failure_details]}, [action_log])
        if invalid_targets:
            failure_details = _failure_runtime_detail_payload(
                f"invalid_targets={len(invalid_targets)}",
                user_reason="目标任务缺少有效编号",
                retryable=False,
                failure_code="task_terminal_invalid_target",
            )
            action_log = _action_log_with_failure_details(
                action_name,
                resolved_schedule_name,
                [],
                mode="runtime",
                details={
                    "schedule_name": resolved_schedule_name,
                    "task_name": task_name,
                    "terminal_ids": terminal_ids,
                    "changed": total_changed,
                    "remote_changed": remote_changed,
                    "local_changed": local_changed,
                    "local_synced_only": local_synced_only,
                    "unresolved": unresolved,
                    "remote_failures": remote_failures,
                    "invalid_targets": invalid_targets,
                },
                raw_reason=f"invalid_targets={len(invalid_targets)}",
                user_reason="目标任务缺少有效编号",
                retryable=False,
                failure_code="task_terminal_invalid_target",
            )
            return (
                "终端调整暂未生效，部分目标任务缺少有效编号。",
                {"missing_slots": [], "diagnostics": [failure_details]},
                [action_log],
            )
        return ("没有任务发生变化。", {"missing_slots": []}, [])

    _touch_generated_at(payload)
    _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
    op_text = "添加终端" if add else "移除终端"
    update_ids = _unique_list(update_ids)
    changed_count = remote_changed if remote_on and remote_changed > 0 else local_changed
    reply = _stable_runtime_reply(
        action_name,
        [
            "已为 {count} 条任务完成{op_text}操作。",
            "{op_text}已完成，涉及 {count} 条任务。",
            "共有 {count} 条任务已经{op_text}。",
        ],
        op_text,
        changed_count,
        op_text=op_text,
        count=changed_count,
    )
    detail_lines: List[str] = []
    if remote_on and remote_changed > 0 and local_synced_only > 0:
        detail_lines.append(f"另有 {local_synced_only} 条任务远端已是目标状态，已同步本地。")
    if remote_failures:
        detail_lines.append(f"另有 {len(remote_failures)} 条任务远端更新失败，请查看 action_log。")
    if invalid_targets:
        detail_lines.append(f"另有 {len(invalid_targets)} 条任务缺少有效 task_id，已按失败处理。")
    detail_lines.append(_reply_unresolved_line(unresolved))
    reply = _append_runtime_reply_details(reply, *detail_lines)
    action_log = _build_action_log(
        action_name,
        resolved_schedule_name,
        update_ids,
        mode="runtime",
        details={
            "schedule_name": resolved_schedule_name,
            "task_name": task_name,
            "terminal_ids": terminal_ids,
            "changed": total_changed,
            "remote_changed": remote_changed,
            "local_changed": local_changed,
            "local_synced_only": local_synced_only,
            "unresolved": unresolved,
            "remote_failures": remote_failures,
            "invalid_targets": invalid_targets,
        },
    )
    return (reply, {"missing_slots": []}, [action_log])


def _apply_add_terminal_to_task_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_add_remove_terminal_to_task_intent(
        text,
        slots,
        add=True,
        action_name="add_terminal_to_task",
    )


def _apply_remove_terminal_from_task_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    return _apply_add_remove_terminal_to_task_intent(
        text,
        slots,
        add=False,
        action_name="remove_terminal_from_task",
    )


def _parse_query_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    parsed = _parse_phase1_date(value)
    if parsed:
        return parsed
    try:
        return ENGINE._parse_time_point(str(value), None)
    except Exception:
        return None


_QUERY_TASK_TIME_FRAGMENT_CHAR_RE = re.compile(
    r"[0-9A-Za-z一二两三四五六七八九十零〇年月日号点分秒:：\-—–~～到至周星期礼拜上下今明后前昨本这中早晚晨午凌傍间夜个天半]"
)
_QUERY_TASK_FUZZY_WINDOWS: Tuple[Tuple[str, int, int], ...] = (
    ("凌晨", 0, 6 * 60),
    ("早上", 6 * 60, 12 * 60),
    ("早晨", 6 * 60, 12 * 60),
    ("上午", 6 * 60, 12 * 60),
    ("中午", 12 * 60, 14 * 60),
    ("午后", 12 * 60, 18 * 60),
    ("下午", 12 * 60, 18 * 60),
    ("傍晚", 17 * 60, 19 * 60),
    ("晚上", 18 * 60, 24 * 60),
    ("夜间", 18 * 60, 24 * 60),
    ("夜里", 18 * 60, 24 * 60),
)


def _query_time_has_date_scope(value: str) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if not text:
        return False
    anchor = _parse_phase1_time_anchor(text)
    if anchor and anchor.get("kind") in {"date", "weekday"}:
        return True
    return ENGINE._contains_date_word(text) or _contains_explicit_date(text)


def _query_time_has_clock_component(value: str) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if not text:
        return False
    return bool(re.search(r"(\d{1,2}[:：]\d{1,2}|[零〇一二两三四五六七八九十\d]{1,3}\s*(点|时))", text))


def _format_query_filter_raw(value: datetime, *, include_date: bool) -> str:
    return value.strftime("%Y-%m-%d %H:%M" if include_date else "%H:%M")


def _repair_query_time_fragment(raw_value: str, original_text: str) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        return ""
    text = str(original_text or "").strip()
    if not text:
        return raw
    explicit_fragment_repairs = {
        "今天下": "今天下午",
        "今日下": "今日下午",
        "明天下": "明天下午",
        "后天下": "后天下午",
        "昨天下": "昨天下午",
    }
    repaired = explicit_fragment_repairs.get(raw)
    if repaired and repaired in text:
        return repaired
    if raw.endswith("下"):
        candidate = f"{raw}午"
        if candidate in text:
            return candidate
    index = text.find(raw)
    if index < 0:
        return raw
    end = index + len(raw)
    while end < len(text) and _QUERY_TASK_TIME_FRAGMENT_CHAR_RE.fullmatch(text[end]):
        end += 1
    candidate = text[index:end].strip()
    if candidate and not re.search(r"(?:到|至|~|～|-|–|—)", raw):
        candidate = re.split(r"(?:到|至|~|～|-|–|—)", candidate, maxsplit=1)[0].strip()
    return candidate or raw


def _query_task_fuzzy_window_minutes(value: str) -> Optional[Tuple[int, int]]:
    text = str(value or "").strip()
    if not text or _query_time_has_clock_component(text):
        return None
    for keyword, start_minutes, end_minutes in _QUERY_TASK_FUZZY_WINDOWS:
        if keyword in text:
            return start_minutes, end_minutes
    return None


def _resolve_query_task_time_token(raw_value: str, original_text: str) -> Dict[str, Any]:
    display_raw = _repair_query_time_fragment(raw_value, original_text)
    resolved: Dict[str, Any] = {
        "display_raw": display_raw,
        "filter_start_raw": display_raw,
        "filter_end_raw": "",
        "point_dt": None,
        "window_start_dt": None,
        "window_end_dt": None,
    }
    if not display_raw:
        return resolved
    fuzzy_window = _query_task_fuzzy_window_minutes(display_raw)
    if not fuzzy_window:
        resolved["point_dt"] = _parse_query_datetime(display_raw)
        return resolved

    include_date = _query_time_has_date_scope(display_raw)
    if include_date:
        base_dt = _parse_phase1_date(display_raw) or _parse_query_datetime(display_raw)
    else:
        base_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if base_dt is None:
        return resolved

    start_minutes, end_minutes = fuzzy_window
    base_day = base_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start_dt = base_day + timedelta(minutes=start_minutes)
    window_end_dt = base_day + timedelta(minutes=end_minutes)
    resolved["window_start_dt"] = window_start_dt
    resolved["window_end_dt"] = window_end_dt
    resolved["filter_start_raw"] = _format_query_filter_raw(window_start_dt, include_date=include_date)
    resolved["filter_end_raw"] = _format_query_filter_raw(window_end_dt, include_date=include_date)
    return resolved


def _set_query_task_time_slot(slots: dict, canonical_key: str, aliases: Tuple[str, ...], value: str) -> None:
    if not value:
        return
    slots[canonical_key] = value
    for key in aliases:
        if key in slots:
            slots[key] = value


def _normalize_query_task_time_filters(text: str, slots: dict) -> Dict[str, Any]:
    normalized_slots = dict(slots) if isinstance(slots, dict) else {}
    start_value = _slot_text(normalized_slots, "source_time", "time_range_start", "start_time", "start")
    end_value = _slot_text(normalized_slots, "end_time", "time_range_end", "end")
    start_token = _resolve_query_task_time_token(start_value, text)
    end_token = _resolve_query_task_time_token(end_value, text)

    start_raw = str(start_token.get("display_raw") or "")
    end_raw = str(end_token.get("display_raw") or "")
    if start_raw:
        _set_query_task_time_slot(
            normalized_slots,
            "source_time",
            ("source_time", "time_range_start", "start_time", "start"),
            start_raw,
        )
    if end_raw:
        _set_query_task_time_slot(
            normalized_slots,
            "end_time",
            ("end_time", "time_range_end", "end"),
            end_raw,
        )

    filter_start_raw = start_raw
    filter_end_raw = end_raw
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None

    if start_raw and end_raw:
        start_dt = start_token.get("window_start_dt") or start_token.get("point_dt")
        end_dt = end_token.get("window_end_dt") or end_token.get("point_dt")
        filter_start_raw = str(start_token.get("filter_start_raw") or start_raw)
        filter_end_raw = str(end_token.get("filter_end_raw") or end_token.get("filter_start_raw") or end_raw)
    elif start_raw:
        start_dt = start_token.get("window_start_dt") or start_token.get("point_dt")
        end_dt = start_token.get("window_end_dt")
        filter_start_raw = str(start_token.get("filter_start_raw") or start_raw)
        filter_end_raw = str(start_token.get("filter_end_raw") or "")
    elif end_raw:
        if end_token.get("window_start_dt") and end_token.get("window_end_dt"):
            start_dt = end_token.get("window_start_dt")
            end_dt = end_token.get("window_end_dt")
            filter_start_raw = str(end_token.get("filter_start_raw") or end_raw)
            filter_end_raw = str(end_token.get("filter_end_raw") or filter_start_raw)
        else:
            end_dt = end_token.get("point_dt")
            filter_end_raw = str(end_token.get("filter_start_raw") or end_raw)

    return {
        "slots": normalized_slots,
        "start_raw": start_raw,
        "end_raw": end_raw,
        "filter_start_raw": filter_start_raw,
        "filter_end_raw": filter_end_raw,
        "start_dt": start_dt,
        "end_dt": end_dt,
    }


def _task_occurs_on_date(task: dict, current_date: date) -> bool:
    if not isinstance(task, dict):
        return False
    start_span, end_span = _task_date_span(task)
    if start_span and end_span:
        if current_date < start_span.date() or current_date > end_span.date():
            return False
    weekdays = _task_weekdays_for_anchor(task)
    if weekdays:
        current_label = _weekday_label(datetime.combine(current_date, datetime.min.time()))
        return current_label in weekdays
    return True


def _task_matches_dated_query_window(task: dict, query_start: datetime, query_end: datetime) -> bool:
    task_seconds = _parse_time_seconds(str(task.get("starttime") or task.get("time") or ""))
    if task_seconds is None:
        return False
    if query_end <= query_start:
        query_end = query_start + timedelta(seconds=1)
    duration_seconds = max(1, _task_duration_seconds(task))
    lookback_days = max(1, int(duration_seconds // 86400) + 1)
    current_date = query_start.date() - timedelta(days=lookback_days)
    final_date = query_end.date()
    while current_date <= final_date:
        if _task_occurs_on_date(task, current_date):
            task_start = datetime.combine(current_date, datetime.min.time()) + timedelta(seconds=task_seconds)
            task_end = task_start + timedelta(seconds=duration_seconds)
            if task_start < query_end and query_start < task_end:
                return True
        current_date += timedelta(days=1)
    return False


def _task_matches_query_time(
    task: dict,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    start_raw: str,
    end_raw: str = "",
) -> bool:
    if not start_dt and not end_dt:
        return True

    task_seconds = _parse_time_seconds(str(task.get("starttime") or task.get("time") or ""))
    if task_seconds is None:
        return False
    duration_seconds = max(1, _task_duration_seconds(task))

    def build_ranges(start_seconds: int, span_seconds: int) -> List[Tuple[int, int]]:
        if span_seconds >= 24 * 3600:
            return [(0, 24 * 3600)]
        end_seconds = start_seconds + span_seconds
        if end_seconds <= 24 * 3600:
            return [(start_seconds, end_seconds)]
        return [(start_seconds, 24 * 3600), (0, end_seconds % (24 * 3600))]

    def ranges_overlap(left: List[Tuple[int, int]], right: List[Tuple[int, int]]) -> bool:
        for left_start, left_end in left:
            for right_start, right_end in right:
                if left_start < right_end and right_start < left_end:
                    return True
        return False

    task_ranges = build_ranges(task_seconds, duration_seconds)
    if start_dt and not end_dt:
        if _query_time_has_date_scope(start_raw):
            if _query_time_has_clock_component(start_raw):
                return _task_matches_dated_query_window(task, start_dt, start_dt + timedelta(minutes=1))
            return _task_matches_dated_query_window(task, start_dt, start_dt + timedelta(days=1))
        target_seconds = (start_dt.hour * 3600) + (start_dt.minute * 60) + start_dt.second
        return ranges_overlap(task_ranges, build_ranges(target_seconds, 60))
    if end_dt and not start_dt:
        if _query_time_has_date_scope(end_raw):
            if _query_time_has_clock_component(end_raw):
                return _task_matches_dated_query_window(task, end_dt, end_dt + timedelta(minutes=1))
            return _task_matches_dated_query_window(task, end_dt, end_dt + timedelta(days=1))
        target_seconds = (end_dt.hour * 3600) + (end_dt.minute * 60) + end_dt.second
        return ranges_overlap(task_ranges, build_ranges(target_seconds, 60))
    if start_dt and end_dt:
        if _query_time_has_date_scope(start_raw) or _query_time_has_date_scope(end_raw):
            normalized_end = end_dt
            if not _query_time_has_clock_component(end_raw):
                normalized_end = normalized_end + timedelta(days=1)
            return _task_matches_dated_query_window(task, start_dt, normalized_end)
        start_seconds = (start_dt.hour * 3600) + (start_dt.minute * 60) + start_dt.second
        end_seconds = (end_dt.hour * 3600) + (end_dt.minute * 60) + end_dt.second
        query_span = end_seconds - start_seconds
        if query_span < 0:
            query_span += 24 * 3600
        query_span = max(1, query_span or 1)
        return ranges_overlap(task_ranges, build_ranges(start_seconds, query_span))
    return True


def _collect_query_task_rows(payload: dict, *, include_runtime_scopes: bool = True) -> List[dict]:
    rows: List[dict] = []
    schedules = payload.get("schedules") if isinstance(payload.get("schedules"), list) else []
    for schedule in schedules:
        if not isinstance(schedule, dict):
            continue
        schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or "")
        tasks = schedule.get("tasks")
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if isinstance(task, dict):
                rows.append({"kind": "schedule", "schedule_name": schedule_name, "task": task})
    if include_runtime_scopes:
        for key in ("broadcasts", "livecasts"):
            items = payload.get(key) if isinstance(payload.get(key), list) else []
            for task in items:
                if isinstance(task, dict):
                    rows.append({"kind": key[:-1], "schedule_name": "", "task": task})
    return rows


def _extract_volume_number(volume_text: object) -> Optional[int]:
    if volume_text in (None, ""):
        return None
    match = re.search(r"(\d{1,3})", str(volume_text).strip())
    if not match:
        return None
    return max(0, min(100, _coerce_int(match.group(1), 0)))


def _parse_volume_adjustment(volume_text: str) -> Optional[Dict[str, Any]]:
    """
    统一解析音量控制表达:
    1. 有方向词且有数字 -> 相对调节
    2. 有方向词无数字 -> 默认相对调节 10
    3. 无方向词但有数字 -> 绝对设置
    """
    if not volume_text:
        return None
    text_norm = str(volume_text).lower().strip()
    if not text_norm:
        return None

    unmute_keywords = {"取消静音", "解除静音", "恢复声音", "恢复音量", "取消静默"}
    if any(kw in text_norm for kw in unmute_keywords):
        return None

    mute_keywords = {"静音", "静默", "无声", "mute"}
    if any(kw in text_norm for kw in mute_keywords):
        return {
            "mode": "absolute",
            "direction": None,
            "delta": None,
            "target": 0,
        }

    increase_keywords = {"增加", "提高", "上调", "加大", "增大", "高一点", "大一点", "加音", "调大"}
    decrease_keywords = {"减少", "降低", "下调", "减小", "降小", "低一点", "小一点", "减音", "调小"}
    direction: Optional[str] = None
    if any(kw in text_norm for kw in increase_keywords):
        direction = "increase"
    elif any(kw in text_norm for kw in decrease_keywords):
        direction = "decrease"

    number = _extract_volume_number(text_norm)
    if direction:
        return {
            "mode": "relative",
            "direction": direction,
            "delta": number if number is not None else 10,
            "target": None,
        }
    if number is not None:
        return {
            "mode": "absolute",
            "direction": None,
            "delta": None,
            "target": number,
        }
    return None


def _detect_volume_direction(volume_text: str) -> Optional[str]:
    parsed = _parse_volume_adjustment(volume_text)
    if not parsed:
        return None
    if parsed.get("mode") == "absolute":
        return "set"
    return str(parsed.get("direction") or "")


def _describe_volume_adjustment(adjustment: Dict[str, Any]) -> str:
    if adjustment.get("mode") == "absolute":
        target = max(0, min(100, _coerce_int(adjustment.get("target"), 50)))
        if target == 0:
            return "设置为静音"
        return f"设置为 {target}%"
    delta = max(0, min(100, _coerce_int(adjustment.get("delta"), 10)))
    if adjustment.get("direction") == "decrease":
        return f"减少 {delta}%"
    return f"增加 {delta}%"


def _calculate_adjusted_volume(current_volume: object, adjustment: Dict[str, Any]) -> int:
    current = max(0, min(100, _coerce_int(current_volume, 50)))
    if adjustment.get("mode") == "absolute":
        return max(0, min(100, _coerce_int(adjustment.get("target"), current)))
    delta = max(0, min(100, _coerce_int(adjustment.get("delta"), 10)))
    if adjustment.get("direction") == "decrease":
        return max(0, current - delta)
    return min(100, current + delta)


def _terminal_current_volume(item: Optional[dict], default: int = 50) -> int:
    if not isinstance(item, dict):
        return default
    for key in ("volume", "Volume", "VOLUME", "vol", "VOL", "terminalvolume", "soundvolume"):
        value = item.get(key)
        if value not in (None, ""):
            return max(0, min(100, _coerce_int(value, default)))
    return default


def _apply_adjust_volume_global(volume_text: str) -> Tuple[str, Dict[str, Any], List[dict]]:
    if not _remote_enabled():
        return ("未配置远端服务，无法调整系统全局音量。", {"missing_slots": []}, [])
    adjustment = _parse_volume_adjustment(volume_text)
    if not adjustment:
        return ("请说明系统音量要调到多少，或调大、调小。", {"missing_slots": ["volume"]}, [])
    current_volume = _coerce_int(REMOTE_CACHE.get("system_volume"), 50)
    target_volume = _calculate_adjusted_volume(current_volume, adjustment)
    from backend.routes.light import action_request as _light_action_request

    response = _light_action_request(
        "POST",
        "/action/setvolume",
        form={"volume": str(target_volume)},
        body_mode="multipart",
    )
    if not response.get("success"):
        return (
            "系统全局音量调整失败，请稍后重试。",
            {"missing_slots": []},
            [{"action": "adjust_volume", "mode": "system", "status": "error"}],
        )
    REMOTE_CACHE["system_volume"] = target_volume
    action_desc = _describe_volume_adjustment(adjustment)
    return (
        f"系统全局音量已{action_desc}。",
        {"missing_slots": []},
        [{
            "action": "adjust_volume",
            "mode": "system",
            "status": "ok",
            "details": {"previous_volume": current_volume, "target": target_volume},
        }],
    )


def _apply_adjust_volume_task(
    task_name: str,
    volume_text: str,
    schedule_name: str = "",
    task_id: str = "",
    *,
    text: str = "",
    slots: Optional[dict] = None,
) -> Tuple[str, Dict[str, Any], List[dict]]:
    """
    【场景B】任务指向性控制:仅改变特定任务的音轨音量
    """
    if not _remote_enabled():
        return ("未配置远端服务,无法调整任务音量。", {"missing_slots": []}, [])
    
    adjustment = _parse_volume_adjustment(volume_text)
    if not adjustment:
        return (
            _ask_runtime_reply(
                "adjust_volume",
                "音量调整方式",
                example="比如把任务音量调大一点、调小一点，或者直接调到 60",
            ),
            {"missing_slots": ["volume"]},
            [],
        )
    
    payload = _clone_payload(_load_schedules_payload())
    slot_payload = dict(slots or {})
    if task_name and "task_name" not in slot_payload:
        slot_payload["task_name"] = task_name
    if schedule_name and "schedule_name" not in slot_payload:
        slot_payload["schedule_name"] = schedule_name
    if task_id and "task_id" not in slot_payload:
        slot_payload["task_id"] = task_id
    resolved_schedule_name, scope_kind, rows, pending_reply = _runtime_task_rows_for_scope(
        "adjust_volume",
        text or task_name,
        slot_payload,
        payload,
        schedule_name,
        default_scope="broadcast",
        include_all_scopes_without_schedule=not bool(schedule_name),
    )
    if pending_reply:
        return pending_reply
    if not text and not slots and not schedule_name and not task_id:
        matching_rows = [row for row in rows if _task_name_matches(row.get("task") or {}, task_name)]
    else:
        matching_rows, pending_reply = _strict_resolve_task_rows(
            "adjust_volume",
            text or task_name,
            slot_payload,
            rows,
            task_name,
            task_id,
        )
        if pending_reply:
            return pending_reply
    if not matching_rows:
        return ("暂时没有找到对应任务。您可以再说一次任务名，或者补充所属方案。", {"missing_slots": ["task_name"]}, [])
    
    affected_tasks = []
    invalid_targets: List[dict] = []
    failed_targets: List[dict] = []
    action_desc = _describe_volume_adjustment(adjustment)
    for row in matching_rows:
        task = row.get("task") or {}
        row_task_id = _task_id(task)
        strict_task_id = _strict_numeric_task_id_text(row_task_id)
        if not strict_task_id:
            invalid_targets.append({"task_name": _phase1_task_name(task), "task_id": str(row_task_id or "")})
            continue
        
        current_volume = _coerce_int(task.get("volume"), 50)
        new_volume = _calculate_adjusted_volume(current_volume, adjustment)
        
        try:
            _remote_set_task_volume(strict_task_id, new_volume)
            task["volume"] = new_volume
            affected_tasks.append({
                "task_id": strict_task_id,
                "task_name": _phase1_task_name(task),
                "old_volume": current_volume,
                "new_volume": new_volume,
            })
        except HTTPException as exc:
            LOGGER.warning(f"调整任务 {strict_task_id} 音量失败: {exc.detail}")
            failed_targets.append(
                {"task_id": strict_task_id, "task_name": _phase1_task_name(task), "error": str(exc.detail)}
            )
    
    if not affected_tasks:
        failure_source = failed_targets[0]["error"] if failed_targets else "未找到可调整的有效任务"
        user_reason = "没有成功改动任何任务音量"
        failure_details = _failure_runtime_detail_payload(
            failure_source,
            user_reason=user_reason,
            retryable=True,
            failure_code="task_volume_update_failed",
        )
        action_log = _action_log_with_failure_details(
            "adjust_volume",
            resolved_schedule_name,
            [],
            mode="task",
            details={
                "task_name": task_name,
                "schedule_name": resolved_schedule_name,
                "scope": scope_kind,
                "mode": adjustment.get("mode"),
                "direction": adjustment.get("direction"),
                "step": adjustment.get("delta"),
                "target": adjustment.get("target"),
                "affected_count": 0,
                "details": [],
                "invalid_targets": invalid_targets,
                "failed_targets": failed_targets,
            },
            raw_reason=failure_source,
            user_reason=user_reason,
            retryable=True,
            failure_code="task_volume_update_failed",
        )
        return (
            _failure_runtime_reply(
                "adjust_volume",
                f"任务“{task_name or '当前目标'}”的音量调整",
                task_name or "",
                reason="没有成功改动任何任务音量",
                suggestion="请确认任务名后再试一次。",
            ),
            {"missing_slots": [], "diagnostics": [failure_details]},
            [action_log],
        )

    _touch_generated_at(payload)
    _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)

    task_label = str(task_name or (affected_tasks[0].get("task_name") if affected_tasks else "") or "相关任务")
    if resolved_schedule_name:
        reply = _success_runtime_reply(
            "adjust_volume_task",
            [
                '小电已经帮您把“{schedule_name}”里任务“{task_name}”的音量调成{action_desc}。',
                '搞定啦，小电已经把“{schedule_name}”中的“{task_name}”调整为{action_desc}。',
                '小电已经为您处理好了，“{schedule_name}”里的“{task_name}”现在是{action_desc}。',
            ],
            resolved_schedule_name,
            task_label,
            action_desc,
            schedule_name=resolved_schedule_name,
            task_name=task_label,
            action_desc=action_desc,
        )
    else:
        reply = _success_runtime_reply(
            "adjust_volume_task",
            [
                '小电已经帮您把任务“{task_name}”的音量调成{action_desc}。',
                '搞定啦，小电已经把“{task_name}”调整为{action_desc}。',
                '小电已经为您处理好了，任务“{task_name}”现在是{action_desc}。',
            ],
            task_label,
            action_desc,
            task_name=task_label,
            action_desc=action_desc,
        )
    detail_lines: List[str] = []
    if invalid_targets:
        detail_lines.append(f"另有 {len(invalid_targets)} 条任务缺少有效 task_id，已按失败处理。")
    if failed_targets:
        detail_lines.append(f"另有 {len(failed_targets)} 条任务远端执行失败，请查看 action_log。")
    reply = _finalize_key_intent_reply("adjust_volume", reply, *detail_lines)
    action_log = _action_log_with_failure_details(
        "adjust_volume",
        resolved_schedule_name,
        [t["task_id"] for t in affected_tasks],
        mode="task",
        details={
            "task_name": task_name,
            "schedule_name": resolved_schedule_name,
            "scope": scope_kind,
            "mode": adjustment.get("mode"),
            "direction": adjustment.get("direction"),
            "step": adjustment.get("delta"),
            "target": adjustment.get("target"),
            "affected_count": len(affected_tasks),
            "details": affected_tasks,
            "invalid_targets": invalid_targets,
            "failed_targets": failed_targets,
        },
        raw_reason=failed_targets[0]["error"] if failed_targets else None,
        user_reason="部分任务音量调整失败" if failed_targets else "",
        retryable=True if failed_targets else None,
        failure_code="task_volume_partial_failure" if failed_targets else "",
    )
    
    # 【缓存同步】清除本地缓存,下次查询时将从远端刷新最新数据
    _cache_set("taskinfo:broadcast", [])
    _cache_set("taskinfo:livecast", [])
    _ttl_cache_set("mediainfo_payload", None, 0)
    
    return (reply, {"missing_slots": []}, [action_log])


def _apply_adjust_volume_terminal(terminal_ids: List[str], volume_text: str) -> Tuple[str, Dict[str, Any], List[dict]]:
    del terminal_ids, volume_text
    return (
        "当前仅支持系统全局音量，不支持单终端或分区音量。",
        {"missing_slots": []},
        [{"action": "adjust_volume", "mode": "terminal", "status": "unsupported"}],
    )


def _adjust_volume_fallback_scope_slots(slots: dict, task_name: str) -> dict:
    fallback_slots = dict(slots or {})
    fallback_slots.pop("task_name", None)
    if not _slot_text(fallback_slots, "zone_name", "terminal_id", "terminal_name") and task_name:
        fallback_slots["zone_name"] = task_name
    return fallback_slots


def _apply_adjust_volume_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    """
    处理音量调整意图,支持三个场景:
    - 场景A:全局控制(无目标)
    - 场景B:任务指向(task_name)
    - 场景C:终端指向(terminal_id/terminal_name/zone_name)
    """
    volume_text = _slot_text(slots, "volume")
    if not volume_text:
        return (
            _ask_runtime_reply(
                "adjust_volume",
                "音量调整方式",
                example="比如调大一点、调小一点，或者直接调到 60",
            ),
            {"missing_slots": ["volume"]},
            [],
        )
    
    task_name = _slot_text(slots, "task_name")
    schedule_name = _slot_text(slots, "schedule_name", "schedule_id", "SCHEDULE", "SCHEDULE_ID")
    task_id = _task_slot_id(slots)
    
    # 优先级:有任务→有终端→全局
    if task_name or _strict_numeric_task_id_text(task_id):
        reply, state, logs = _apply_adjust_volume_task(
            task_name,
            volume_text,
            schedule_name,
            task_id,
            text=text,
            slots=slots,
        )
        if logs or "task_name" not in (state.get("missing_slots") or []):
            return reply, state, logs

        has_explicit_scope = bool(_slot_values(slots, "zone_name", "terminal_id", "terminal_name"))
        if not has_explicit_scope and task_name:
            zone_ids, missing_zone, pending_reply = _strict_resolve_zone_ids(
                "adjust_volume",
                text,
                dict(slots or {}, zone_name=task_name),
                [task_name],
            )
            if pending_reply:
                return pending_reply
            if zone_ids and not missing_zone:
                fallback_terminal_ids: List[str] = []
                for zone_id in zone_ids:
                    fallback_terminal_ids.extend(_zone_terminal_ids(zone_id))
                fallback_terminal_ids = _unique_list(fallback_terminal_ids)
                if fallback_terminal_ids:
                    reply, state, logs = _apply_adjust_volume_terminal(fallback_terminal_ids, volume_text)
                    if logs:
                        details = logs[0].setdefault("details", {})
                        details["scope"] = "zone"
                        details["fallback_scope"] = "zone"
                        details["resolved_as"] = "zone"
                        details["zone_fallback"] = True
                        details["zone_name"] = task_name
                        reply = _finalize_key_intent_reply(
                            "adjust_volume",
                            reply,
                            f'未找到任务“{task_name}”，已先按分区“{task_name}”为您处理',
                        )
                    return reply, state, logs
        return reply, state, logs
    
    terminal_ids, _ = _resolve_terminal_ids_from_slots(slots)
    if terminal_ids:
        return _apply_adjust_volume_terminal(terminal_ids, volume_text)
    
    # 默认:全局调整
    return _apply_adjust_volume_global(volume_text)


def _apply_query_task_intent(text: str, slots: dict) -> Tuple[str, Dict[str, Any], List[dict]]:
    schedule_name, task_name = _resolve_schedule_and_task_slots(slots)
    task_id = _task_slot_id(slots)
    time_filters = _normalize_query_task_time_filters(text, slots)
    normalized_slots = time_filters["slots"]
    start_raw = str(time_filters.get("start_raw") or "")
    end_raw = str(time_filters.get("end_raw") or "")
    filter_start_raw = str(time_filters.get("filter_start_raw") or start_raw)
    filter_end_raw = str(time_filters.get("filter_end_raw") or end_raw)
    start_dt = time_filters.get("start_dt")
    end_dt = time_filters.get("end_dt")
    if start_raw and not start_dt:
        return ("开始时间范围我还没解析清楚，您换个说法试试。", {"missing_slots": []}, [])
    if end_raw and not end_dt:
        return ("结束时间范围我还没解析清楚，您换个说法试试。", {"missing_slots": []}, [])
    if start_dt and end_dt and end_dt < start_dt and not (
        ENGINE._contains_date_word(filter_end_raw) if filter_end_raw else False
    ):
        end_dt = end_dt + timedelta(days=1)

    payload = _clone_payload(_load_schedules_payload())
    rows = _collect_query_task_rows(payload, include_runtime_scopes=False)
    for row in rows:
        row["scope_kind"] = str(row.get("kind") or "")

    resolved_schedule_name = ""
    if schedule_name:
        schedule, pending_reply = _strict_resolve_schedule("query_task", text, slots, payload, schedule_name)
        if pending_reply:
            return pending_reply
        if not schedule:
            return (f'没有找到作息方案“{schedule_name}”。', {"missing_slots": []}, [])
        resolved_schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or schedule_name)
        tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
        rows = [
            _task_row(task, schedule_name=resolved_schedule_name, scope_kind="schedule")
            for task in tasks
            if isinstance(task, dict)
        ]
    else:
        enabled_names = {
            _schedule_display_name(item)
            for item in _enabled_schedules(payload)
            if _schedule_display_name(item)
        }
        if not enabled_names:
            return (
                "当前没有启用中的作息方案；如需查询停用方案，请补充方案名称。",
                {"missing_slots": ["schedule_name"]},
                [],
            )
        rows = [row for row in rows if str(row.get("schedule_name") or "") in enabled_names]
    if task_name or _strict_numeric_task_id_text(task_id):
        rows, pending_reply = _strict_query_task_rows("query_task", text, slots, rows, task_name, task_id)
        if pending_reply:
            return pending_reply
    rows = [
        row
        for row in rows
        if _task_matches_query_time(
            row.get("task") or {},
            start_dt,
            end_dt,
            filter_start_raw,
            filter_end_raw,
        )
    ]

    if not rows:
        return ("暂时没有查到匹配的任务。您可以换个时间范围、任务名，或者补充作息方案后再试。", {"missing_slots": []}, [])

    rows.sort(key=lambda row: _parse_time_minutes(str((row.get("task") or {}).get("starttime") or "")) or 0)
    task_items: List[dict] = []
    for row in rows[:50]:
        task = row.get("task") or {}
        state_value = _task_state_value(task)
        task_items.append(
            {
                "task_id": _task_id(task),
                "task_name": _phase1_task_name(task),
                "time": _format_hhmm(str(task.get("starttime") or task.get("time") or "")),
                "status": task.get("status") or _task_display_status(state_value),
                "state": state_value,
                "kind": row.get("kind"),
                "schedule_name": row.get("schedule_name") or "",
            }
        )

    preview_include_schedule = len(
        {str(item.get("schedule_name") or "").strip() for item in task_items if str(item.get("schedule_name") or "").strip()}
    ) > 1
    preview = "、".join(
        [
            (
                f"{item.get('schedule_name')}/{item.get('task_name') or '未命名任务'}({item.get('time') or '--:--'})"
                if preview_include_schedule and item.get("schedule_name")
                else f"{item.get('task_name') or '未命名任务'}({item.get('time') or '--:--'})"
            )
            for item in task_items[:5]
        ]
    )
    scope_desc = ""
    if resolved_schedule_name or schedule_name:
        scope_desc = f'方案“{resolved_schedule_name or schedule_name}”'
    elif task_name:
        scope_desc = f'任务“{task_name}”'
    reply = _query_runtime_reply(
        "query_task",
        [
            "{scope_desc}已经查到，共 {count} 条任务。",
            "小电已经帮您查到 {scope_desc}，共 {count} 条任务。",
            "{scope_desc}的任务已经整理好了，共 {count} 条任务。",
        ] if scope_desc else [
            "已经查到 {count} 条任务。",
            "小电已经帮您查到 {count} 条任务。",
            "任务列表已经整理好了，共 {count} 条任务。",
        ],
        scope_desc or len(rows),
        len(rows),
        scope_desc=scope_desc,
        count=len(rows),
    )
    if preview:
        reply = _finalize_key_intent_reply("query_task", reply, f"先给您看几条：{preview}")
    else:
        reply = _append_key_intent_followup("query_task", reply)
    action_log = _build_action_log(
        "query_task",
        resolved_schedule_name or schedule_name,
        [item["task_id"] for item in task_items if item.get("task_id")],
        mode="query",
        details={
            "count": len(rows),
            "schedule_name": resolved_schedule_name or schedule_name,
            "task_name": task_name,
            "task_id": _strict_numeric_task_id_text(task_id),
            "time_range_start": start_raw,
            "time_range_end": end_raw,
            "tasks": task_items,
        },
    )
    return (reply, {"missing_slots": [], "slots": normalized_slots}, [action_log])


def _apply_phase1_intent(intent: str, text: str, slots: dict) -> Optional[Tuple[str, Dict[str, Any], List[dict]]]:
    return _assistant_apply_phase1_intent(intent, text, slots)


def _apply_action(text: str, result: dict) -> Optional[Tuple[str, Dict[str, Any], List[dict]]]:
    return _assistant_apply_action(text, result)

def compute_missing(intent: str, slots: dict) -> List[str]:
    return _assistant_compute_missing(intent, slots)


@app.post("/infer", response_model=InferResponse)
def infer_api(payload: InferRequest) -> InferResponse:
    return _assistant_infer_api(payload)


def build_reply(intent: str, missing: List[str], slots: dict) -> str:
    return _assistant_build_reply(intent, missing, slots)

@app.post("/assistant/chat", response_model=ChatResponse)
async def chat_api(request: Request) -> ChatResponse:
    return await _assistant_chat_api(request)


@app.post("/debug/test_phase1_intent", response_model=TestPhase1IntentResponse)
def debug_test_phase1_intent(payload: TestPhase1IntentRequest) -> TestPhase1IntentResponse:
    """
    【测试接口】直接测试Phase1意图处理(跳过NLU模型)
    
    用途:在NLU模型尚未完成时,快速测试各个Phase1意图的业务逻辑
    
    请求示例:
    {
        "intent": "adjust_volume",
        "text": "音量增加",
        "slots": {
            "volume": "增加"
        }
    }
    
    响应示例:
    {
        "success": true,
        "reply": "已向所有终端下发音量增加 10% 的指令。",
        "missing_slots": [],
        "action_logs": [{...}]
    }
    """
    intent = str(payload.intent or "").strip().lower()
    text = str(payload.text or "").strip()
    slots = payload.slots if isinstance(payload.slots, dict) else {}
    
    # 验证意图是否在PHASE1_INTENTS中
    if intent not in PHASE1_INTENTS:
        available_intents = sorted(list(PHASE1_INTENTS))
        return TestPhase1IntentResponse(
            success=False,
            reply="",
            error=f"意图 '{intent}' 不在 PHASE1_INTENTS 中。可用意图:{', '.join(available_intents)}",
        )
    
    # 如果text为空,使用intent作为text
    if not text:
        text = intent
    
    try:
        result = _apply_phase1_intent(intent, text, slots)
        if result:
            reply, missing_slots_dict, action_logs = result
            missing_slots = missing_slots_dict.get("missing_slots", []) if isinstance(missing_slots_dict, dict) else []
            return TestPhase1IntentResponse(
                success=True,
                reply=reply,
                missing_slots=missing_slots,
                action_logs=action_logs if isinstance(action_logs, list) else [],
            )
        else:
            return TestPhase1IntentResponse(
                success=False,
                reply="",
                error="意图处理返回None(可能未实现或无法匹配槽位)",
            )
    except HTTPException as exc:
        return TestPhase1IntentResponse(
            success=False,
            reply="",
            error=f"HTTP异常: {exc.detail}",
        )
    except Exception as exc:
        return TestPhase1IntentResponse(
            success=False,
            reply="",
            error=f"处理异常: {str(exc)}",
        )


@app.post("/debug/apply_action", response_model=DebugApplyActionResponse)
def debug_apply_action(payload: DebugApplyActionRequest) -> DebugApplyActionResponse:
    if payload.clear_pending:
        _clear_pending_action()

    text = str(payload.text or "").strip()
    intent = str(payload.intent or "").strip()
    slots = payload.slots if isinstance(payload.slots, dict) else {}
    confidence = float(payload.intent_confidence or 0.0)
    missing = list(payload.missing_slots or [])
    action_log: List[dict] = []
    diagnostics: List[dict] = []
    applied = False

    if payload.pending_only or not intent:
        if not text:
            raise HTTPException(status_code=400, detail="text is required when pending_only=true or intent is empty.")
        action_reply = _handle_pending_action(text)
        if not action_reply:
            raise HTTPException(status_code=400, detail="No pending action to continue.")
        reply, overrides, action_log = action_reply
        if overrides and "missing_slots" in overrides:
            missing = list(overrides.get("missing_slots") or [])
        if isinstance((overrides or {}).get("diagnostics"), list):
            diagnostics = list(overrides.get("diagnostics") or [])
        normalized_intent = _normalize_intent_label(intent) if intent else ""
        return DebugApplyActionResponse(
            reply=reply,
            intent=intent,
            normalized_intent=normalized_intent,
            confidence=confidence,
            slots=slots,
            missing_slots=missing,
            action_log=action_log,
            diagnostics=diagnostics,
            pending_action=_snapshot_pending_action(),
            applied=True,
        )

    if not text:
        text = intent

    result = {
        "intent": intent,
        "intent_confidence": confidence,
        "slots": slots,
        "status": payload.status or "success",
        "entities": payload.entities or {},
        "missing_slots": missing,
        "tokens": [],
        "tag_ids": [],
    }

    action_reply = _apply_action(text, result)
    if action_reply:
        reply, overrides, action_log = action_reply
        applied = True
        if overrides:
            if "intent" in overrides:
                result["intent"] = overrides["intent"]
            if "slots" in overrides:
                result["slots"] = overrides["slots"]
            if "missing_slots" in overrides:
                missing = list(overrides["missing_slots"] or [])
            if isinstance(overrides.get("diagnostics"), list):
                diagnostics = list(overrides.get("diagnostics") or [])
    else:
        missing = result.get("missing_slots") or compute_missing(result.get("intent", ""), result.get("slots", {}))
        reply = build_reply(result.get("intent", ""), missing, result.get("slots", {}))

    final_intent = str(result.get("intent", ""))
    final_slots = result.get("slots", {})
    return DebugApplyActionResponse(
        reply=reply,
        intent=final_intent,
        normalized_intent=_normalize_intent_label(final_intent),
        confidence=float(result.get("intent_confidence", confidence)),
        slots=final_slots if isinstance(final_slots, dict) else {},
        missing_slots=list(missing or []),
        action_log=action_log,
        diagnostics=diagnostics,
        pending_action=_snapshot_pending_action(),
        applied=applied,
    )


def _add_item(path: Path, id_key: str, item: dict) -> dict:
    if not isinstance(item, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    payload, items = _read_data_container(path)
    new_id = item.get(id_key) or _next_id(items, id_key)
    if any(str(i.get(id_key)) == str(new_id) for i in items if isinstance(i, dict)):
        raise HTTPException(status_code=409, detail=f"{id_key} already exists")
    item[id_key] = new_id
    items.append(item)
    payload["data"] = items
    _write_json(path, payload)
    return {"id": new_id, "count": len(items)}


def _update_item(path: Path, id_key: str, item_id: str, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    payload, items = _read_data_container(path)
    idx, existing = _find_item(items, id_key, item_id)
    merged = {**existing, **patch}
    merged[id_key] = existing.get(id_key, item_id)
    items[idx] = merged
    payload["data"] = items
    _write_json(path, payload)
    return merged


def _delete_item(path: Path, id_key: str, item_id: str) -> dict:
    payload, items = _read_data_container(path)
    idx, existing = _find_item(items, id_key, item_id)
    items.pop(idx)
    payload["data"] = items
    _write_json(path, payload)
    return {"deleted": existing, "count": len(items)}

def _normalize_setvolume_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    def pick(keys: Tuple[str, ...]) -> str:
        for key in keys:
            if key in payload and payload[key] not in (None, ""):
                return str(payload[key])
        return ""
    device_id = pick(("DEVICE_ID", "device_id", "deviceId", "id"))
    if not device_id:
        raise HTTPException(status_code=400, detail="DEVICE_ID is required")
    volume = pick(("VOLUME", "volume"))
    if volume == "":
        raise HTTPException(status_code=400, detail="VOLUME is required")
    device_ip = pick(("DEVICE_IP", "device_ip", "deviceIp", "ip"))
    return {
        "DEVICE_ID": device_id,
        "DEVICE_IP": device_ip or "",
        "VOLUME": str(volume),
    }


def _normalize_move_terminal_payload(payload: dict) -> Dict[str, str]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    def pick(keys: Tuple[str, ...]) -> str:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    device_id = pick(("deviceId", "device_id", "terminalId", "terminal_id", "id", "DEVICE_ID"))
    target_zone_id = pick(("targetZoneId", "target_zone_id", "zoneId", "zone_id"))
    source_zone_id = pick(("sourceZoneId", "source_zone_id", "fromZoneId", "from_zone_id"))

    if not device_id:
        raise HTTPException(status_code=400, detail="deviceId is required")
    if not target_zone_id:
        raise HTTPException(status_code=400, detail="targetZoneId is required")
    return {
        "device_id": device_id,
        "target_zone_id": target_zone_id,
        "source_zone_id": source_zone_id,
    }

def _terminal_map_from_items(items: list) -> dict:
    mapping: Dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        terminal_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if terminal_id is None:
            continue
        terminal_id_str = str(terminal_id)
        name = item.get("name")
        ip = item.get("ip")
        if name:
            name_str = str(name)
            mapping[name_str] = terminal_id_str
            compact = _compact_text(name_str)
            if compact:
                mapping[compact] = terminal_id_str
        if ip:
            ip_str = str(ip)
            mapping[ip_str] = terminal_id_str
            compact = _compact_text(ip_str)
            if compact:
                mapping[compact] = terminal_id_str
    return mapping

def _terminal_name_by_id(terminal_id: str) -> str:
    if not terminal_id:
        return ""
    try:
        lookup = _remote_terminal_lookup() if _remote_enabled() else {}
    except HTTPException:
        lookup = {}
    entry = lookup.get(str(terminal_id)) if isinstance(lookup, dict) else None
    if isinstance(entry, dict) and entry.get("name"):
        return str(entry.get("name"))
    items = _store_terminalinfo_items()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id") or item.get("terminalid") or item.get("terminal_id")
        if item_id is not None and str(item_id) == str(terminal_id):
            name = item.get("name") or item.get("ip")
            if name:
                return str(name)
    return ""

def _task_matches_terminal(task: dict, terminal_id: str, terminal_name: str, terminal_map: dict) -> bool:
    if not isinstance(task, dict):
        return False
    terminal_id_str = str(terminal_id) if terminal_id else ""
    if terminal_id_str:
        for key in ("liveterminalid", "terminalid", "terminal_id"):
            value = task.get(key)
            if value is not None and str(value) == terminal_id_str:
                return True
    if terminal_name:
        for key in ("liveterminalname", "terminalname", "terminal_name"):
            value = task.get(key)
            if value and str(value) == terminal_name:
                return True
    location = task.get("location")
    if isinstance(location, list):
        def matches_value(value: object) -> bool:
            if value is None:
                return False
            value_str = str(value)
            if terminal_name and value_str == terminal_name:
                return True
            if terminal_id_str and value_str == terminal_id_str:
                return True
            if terminal_map:
                mapped = terminal_map.get(value_str)
                if mapped is None:
                    compact = _compact_text(value_str)
                    if compact:
                        mapped = terminal_map.get(compact)
                if mapped is not None and terminal_id_str and str(mapped) == terminal_id_str:
                    return True
            return False
        for entry in location:
            if isinstance(entry, list):
                for value in entry:
                    if matches_value(value):
                        return True
            else:
                if matches_value(entry):
                    return True
    return False

def _persist_volume_for_terminal(terminal_id: str, volume: int) -> int:
    try:
        payload = _clone_payload(_load_schedules_payload())
    except HTTPException:
        return 0
    if not isinstance(payload, dict):
        return 0
    terminal_name = _terminal_name_by_id(terminal_id)
    try:
        terminal_map = _remote_terminal_map() if _remote_enabled() else _terminal_map_from_items(_store_terminalinfo_items())
    except HTTPException:
        terminal_map = _terminal_map_from_items(_store_terminalinfo_items())
    updated = 0
    updated_task_ids: List[str] = []

    def apply_task(task: dict) -> None:
        nonlocal updated
        if not isinstance(task, dict):
            return
        if not _task_matches_terminal(task, terminal_id, terminal_name, terminal_map):
            return
        task["volume"] = volume
        updated += 1
        task_id = _task_id(task)
        if task_id:
            updated_task_ids.append(str(task_id))

    for key in ("broadcasts", "livecasts"):
        items = payload.get(key)
        if isinstance(items, list):
            for task in items:
                apply_task(task)
    schedules = payload.get("schedules")
    if isinstance(schedules, list):
        for schedule in schedules:
            tasks = schedule.get("tasks") if isinstance(schedule, dict) else None
            if isinstance(tasks, list):
                for task in tasks:
                    apply_task(task)
    if updated <= 0:
        return 0
    payload = _touch_generated_at(payload)
    _store_set("broadcast_schedules", payload)
    _write_cache_json(SCHEDULES_PATH, payload)
    _write_engine_schedules(payload)
    all_task_payload = _build_all_task_payload(payload)
    _store_set("all_task", all_task_payload)
    _write_cache_json(ALL_TASK_PATH, all_task_payload)
    _write_engine_all_task(all_task_payload)
    if _remote_enabled():
        unique_ids = _unique_list([task_id for task_id in updated_task_ids if _is_numeric_id(task_id)])
        for task_id in unique_ids:
            try:
                _remote_set_task_volume(task_id, volume)
            except HTTPException:
                continue
    return updated


@app.get("/data/assistant_command_logs")
def get_assistant_command_logs(
    limit: int = Query(100, ge=1, le=ASSISTANT_COMMAND_LOG_LIMIT),
):
    payload = _load_assistant_command_logs_payload()
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    ordered = [item for item in reversed(items) if isinstance(item, dict)]
    return {
        "items": _clone_payload(ordered[:limit]),
        "total": len(ordered),
        "limit": limit,
    }

@app.get("/auth/remote-bootstrap")
def auth_remote_bootstrap():
    return _auth_response(_remote_bootstrap_response_payload())


def _legacy_auth_token_login_removed(payload: object):
    raise HTTPException(status_code=400, detail="当前航天广电 action 协议不支持 token 登录，请使用账号密码登录。")


@app.post("/auth/login")
def auth_login(payload: AuthLoginRequest):
    username = str(payload.username or "").strip()
    password = str(payload.password or "")
    remote_base_url = _resolve_remote_base_url(payload.remote_base_url)
    if not remote_base_url:
        raise HTTPException(status_code=400, detail="请选择或输入远端地址。")
    remote_token = _remote_login_with_credentials(username, password, remote_base_url=remote_base_url)
    _save_remote_settings_payload(
        {
            "remote_base_url": remote_base_url,
            "last_verified_at": "",
            "last_verified_ip": "",
        }
    )
    session = _create_local_session(remote_token, username, "password", remote_base_url=remote_base_url)
    return _auth_response(_build_local_session_payload(session))


@app.get("/auth/session")
def auth_session(request: Request):
    session = _get_local_session_from_request(request)
    if not session:
        raise HTTPException(status_code=401, detail="Login required.")
    return _auth_response(_build_local_session_payload(session))


@app.post("/auth/logout")
def auth_logout(request: Request):
    _delete_local_session_from_request(request)
    return _auth_response({"success": True})


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "service": "ai-speaker-api",
    }


def _build_readyz_payload() -> Tuple[dict, int]:
    missing_data_keys = _missing_ready_data_keys()
    data_dir_writable, data_dir_write_error = _runtime_data_dir_write_check()
    remote_enabled = _remote_enabled()
    remote_sync = _remote_sync_status_snapshot()
    status_code = 200
    status = "ready"
    degraded = False
    remote_status = "disabled"

    if not STARTUP_LOAD_DONE:
        status = "not_ready"
        status_code = 503
        remote_status = "starting"
    elif missing_data_keys or not data_dir_writable:
        status = "not_ready"
        status_code = 503
    elif remote_enabled:
        if remote_sync.get("last_success_at"):
            if remote_sync.get("last_error"):
                status = "degraded"
                degraded = True
                remote_status = "degraded"
            else:
                remote_status = "ok"
        else:
            status = "not_ready"
            status_code = 503
            remote_status = "not_synced"

    payload = {
        "status": status,
        "service": "ai-speaker-api",
        "degraded": degraded,
        "startup_loaded": bool(STARTUP_LOAD_DONE),
        "data_dir_writable": bool(data_dir_writable),
        "data_dir_write_error": str(data_dir_write_error or ""),
        "loaded_data_keys": _loaded_data_keys(),
        "missing_data_keys": missing_data_keys,
        "remote_enabled": bool(remote_enabled),
        "remote_status": remote_status,
        "current_remote_base_url": _resolve_remote_base_url(),
        "remote_sync": {
            "last_attempt_at": remote_sync.get("last_attempt_at") or "",
            "last_success_at": remote_sync.get("last_success_at") or "",
            "last_error": remote_sync.get("last_error") or "",
            "consecutive_failures": int(remote_sync.get("consecutive_failures") or 0),
            "last_duration_ms": remote_sync.get("last_duration_ms"),
        },
    }
    return payload, status_code


@app.get("/readyz")
def readyz():
    payload, status_code = _build_readyz_payload()
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/ops/status")
def get_ops_status():
    process_rss_bytes: Optional[int] = None
    if psutil is not None:
        try:
            process_rss_bytes = int(psutil.Process(os.getpid()).memory_info().rss)
        except Exception:
            process_rss_bytes = None
    remote_base_url, remote_base_url_source = _resolve_remote_base_url_details()
    remote_sync = _remote_sync_status_snapshot()
    return {
        "status": "ok",
        "service": "ai-speaker-api",
        "started_at": SERVICE_STARTED_AT_TEXT,
        "uptime_seconds": round(max(0.0, time.time() - SERVICE_STARTED_AT), 3),
        "process_rss_bytes": process_rss_bytes,
        "startup_loaded": bool(STARTUP_LOAD_DONE),
        "loaded_data_keys": _loaded_data_keys(),
        "pending_action_count": _pending_action_count(),
        "current_remote_base_url": remote_base_url,
        "current_remote_base_url_source": remote_base_url_source,
        "remote_enabled": bool(_remote_enabled()),
        "remote_auto_sync_seconds": float(REMOTE_AUTO_SYNC_SECONDS),
        "remote_sync": remote_sync,
    }


@app.get("/data/calendar_holidays")
def get_calendar_holidays(year: str = Query(...)):
    return _load_calendar_holidays_year_payload(year)


@app.get("/data/all_audio")
def get_all_audio(folderid: Optional[int] = None):
    status_code = 503 if _remote_enabled() else 404
    if folderid is None:
        return _store_require("all_audio", "all_audio", status_code)
    if _remote_enabled():
        try:
            return _fetch_remote_all_audio(folder_id=folderid)
        except HTTPException:
            pass
    payload = _store_require("all_audio", "all_audio", status_code)
    return _filter_media_payload_by_folderid(payload, folderid)


@app.get("/data/all_loc")
def get_all_loc():
    status_code = 503 if _remote_enabled() else 404
    return _store_require("all_loc", "all_loc", status_code)

def get_terminalinfo(force: bool = False):
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    return _filter_terminal_payload_for_ui(_remote_terminalinfo_payload(force=force))

def get_terminal_zones(force: bool = False):
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    return _normalize_zone_payload_for_ui(_remote_terzone_cached(force=force))

def get_terminals_by_zone(zone_id: str):
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    return _clean_zone_terminal_payload(_remote_zoneterminal_cached(zone_id))


# ── 缓存版 terzone / zoneterminal 查询函数 ──────────────────────
_TERZONE_CACHE_TTL = 30  # 分区列表 30 秒缓存
_ZONETERMINAL_CACHE_TTL = 15  # 分区终端 15 秒缓存


def _remote_terzone_cached(force: bool = False) -> object:
    """带 TTL 缓存的 terzone 请求。"""
    if not force:
        cached = _ttl_cache_get("terzone_payload")
        if cached is not None:
            return cached
    payload = _remote_request("GET", "/terminal/terzone")
    _ttl_cache_set("terzone_payload", payload, _TERZONE_CACHE_TTL)
    return payload


def _remote_zoneterminal_cached(zone_id: str, force: bool = False) -> object:
    """带 TTL 缓存的单分区终端请求。"""
    cache_key = f"zoneterminal_{zone_id}"
    if not force:
        cached = _ttl_cache_get(cache_key)
        if cached is not None:
            return cached
    encoded = urllib.parse.quote(str(zone_id), safe="")
    payload = _remote_request("GET", f"/terminal/zoneterminal/{encoded}")
    _ttl_cache_set(cache_key, payload, _ZONETERMINAL_CACHE_TTL)
    return payload


def _invalidate_zone_runtime_caches(zone_ids: Optional[List[str]] = None) -> None:
    TTL_CACHE.pop("terzone_payload", None)
    TTL_CACHE.pop("enriched_terzone_items", None)
    TTL_CACHE.pop("terminal_map", None)
    TTL_CACHE.pop("ambiguous_zone_warning_cache", None)
    if zone_ids:
        for zone_id in zone_ids:
            TTL_CACHE.pop(f"zoneterminal_{zone_id}", None)
    else:
        for key in list(TTL_CACHE.keys()):
            if str(key).startswith("zoneterminal_"):
                TTL_CACHE.pop(key, None)
    REMOTE_CACHE.pop("terminal_lookup", None)
    REMOTE_CACHE.pop("terminal_map", None)


def _fetch_all_terminal_data(force: bool = False) -> dict:
    """并发获取分区列表 + 各分区终端 + 全终端状态,一次性返回。"""
    # 第一步:并发获取 terzone 和 terminalinfo
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_zones = _submit_with_current_remote_token(executor, _remote_terzone_cached, force)
        future_info = _submit_with_current_remote_token(executor, _remote_terminalinfo_payload, force)
        zones_payload = _normalize_zone_payload_for_ui(future_zones.result())
        terminal_info_payload = _filter_terminal_payload_for_ui(future_info.result())

    # 第二步:从 terzone 结果中提取 zone id 列表
    zones_list = _remote_data_list(zones_payload)
    zone_ids: List[str] = []
    for item in zones_list:
        if not isinstance(item, dict):
            continue
        zid = item.get("id") or item.get("zone") or item.get("zoneid")
        if zid is not None:
            zone_ids.append(str(zid))

    # 第三步:并发获取所有分区的终端列表
    zone_terminals: Dict[str, object] = {}
    if zone_ids:
        results = _parallel_map(zone_ids, lambda zone_id: _remote_zoneterminal_cached(zone_id, force=force))
        for zid, result in zip(zone_ids, results):
            zone_terminals[zid] = _clean_zone_terminal_payload(result)

    return {
        "zones": zones_payload,
        "zone_terminals": zone_terminals,
        "terminal_info": terminal_info_payload,
    }


def get_all_terminal_data(force: bool = False):
    """聚合接口:一次请求返回 terzone + 所有 zoneterminal + terminalinfo。"""
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    return _fetch_all_terminal_data(force=force)


def move_terminal_zone(payload: dict = Body(...)):
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")

    normalized = _normalize_move_terminal_payload(payload)
    device_id_value = _coerce_int(normalized["device_id"], 0)
    if device_id_value <= 0:
        raise HTTPException(status_code=400, detail="Invalid deviceId")

    target_zone_raw = str(normalized["target_zone_id"]).strip()
    target_is_unassigned = target_zone_raw.lower() == "unassigned" or target_zone_raw == "0"
    source_zone_raw = str(normalized.get("source_zone_id") or "").strip()
    affected_zone_ids: List[str] = []

    source_zone_value = _coerce_int(source_zone_raw, 0)
    if source_zone_value > 0:
        affected_zone_ids.append(str(source_zone_value))

    if target_is_unassigned:
        if source_zone_value <= 0:
            raise HTTPException(
                status_code=400,
                detail="sourceZoneId is required when targetZoneId is 'unassigned' because this operation removes only the current zone association.",
            )
        remote_payload = _build_remove_zone_terminal_payload(
            [str(source_zone_value)],
            [str(device_id_value)],
        )
        resp = _remote_request(
            "DELETE",
            "/terminal/zoneterminal",
            json_body=remote_payload,
            form_body=None,
            allow_form_retry=False,
        )
    else:
        target_zone_value = _coerce_int(target_zone_raw, 0)
        if target_zone_value <= 0:
            raise HTTPException(status_code=400, detail="Invalid targetZoneId")
        target_zone_id = str(target_zone_value)
        if target_zone_id not in affected_zone_ids:
            affected_zone_ids.append(target_zone_id)
        remote_payload = {
            # Swagger eventterminal for POST /terminal/zoneterminal:
            # id = zone id, terminalid = terminal id.
            "data": [{
                "id": target_zone_value,
                "zone": 255,
                "terminalid": device_id_value,
                "terminalzone": 0,
            }]
        }
        resp = _remote_request(
            "POST",
            "/terminal/zoneterminal",
            json_body=remote_payload,
            form_body=None,
            allow_form_retry=False,
        )

    try:
        _invalidate_zone_runtime_caches(affected_zone_ids or None)
        _sync_remote_data(force=True, keys=["all_loc"])
    except Exception:
        pass

    return {
        "status": "ok",
        "deviceId": str(device_id_value),
        "sourceZoneId": source_zone_raw or "",
        "targetZoneId": "unassigned" if target_is_unassigned else str(_coerce_int(target_zone_raw, 0)),
        "operation": "remove_from_zone" if target_is_unassigned else "add_to_zone",
        "message": (
            "Removed terminal from the current zone association without deleting the terminal device."
            if target_is_unassigned
            else "Added terminal to the target zone."
        ),
        "remote": resp,
    }


def set_volume(payload: dict = Body(...)):
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    body = _normalize_setvolume_payload(payload)
    resp = _remote_request(
        "POST",
        "/setvolume",
        json_body=body,
        form_body=None,
        allow_form_retry=False,
    )
    volume_value = _coerce_int(body.get("VOLUME"), 0)
    volume_value = max(0, min(100, volume_value))
    _persist_volume_for_terminal(body.get("DEVICE_ID") or "", volume_value)
    return resp


@app.get("/data/all_task")
def get_all_task():
    return _store_require("all_task", "all_task", 404)
@app.put("/data/all_task")
def put_all_task(payload: dict = Body(...), scope: str = Query("all")):
    # 1. 标准化输入
    payload = _normalize_all_task_payload(payload)
    incoming = payload.get("data") or []
    scope_key = str(scope or "all").lower()
    broadcast_type = _coerce_int(REMOTE_BROADCAST_TASK_TYPE, 2)
    livecast_type = _coerce_int(REMOTE_LIVECAST_TASK_TYPE, 3)

    # 2. 智能刷新 Media 查找表 (保持不变)
    try:
        media_lookup = _remote_media_lookup() if _remote_enabled() else _store_media_lookup()
    except HTTPException:
        media_lookup = _store_media_lookup()

    # (中间的刷新逻辑省略,保持不变...)

    # 3. 数据清洗与【核心修复:双字段补全 + 脏数据清洗】
    for item in incoming:
        if not isinstance(item, dict): continue
        
        # --- 修复 1:确保名字存在 ---
        real_name = item.get("taskname") or item.get("name") or item.get("medianame") or item.get("audio")
        if real_name:
            real_name_str = str(real_name)
            if not item.get("taskname"): item["taskname"] = real_name_str
            if not item.get("name"): item["name"] = real_name_str
            if not item.get("medianame"): item["medianame"] = real_name_str

        # --- 修复 2:处理 ID 为 0 的情况(防止引擎崩溃)---
        # 如果终端ID是0,AI引擎可能会崩溃。尝试将其设为 None 或一个默认安全值(如1)
        # 或者仅仅是确保它是 int 类型
        term_id = item.get("liveterminalid")
        if term_id is not None:
             # 很多引擎不喜欢字符串类型的 "0",确保是 int
             item["liveterminalid"] = _coerce_int(term_id, 0)
        
        # ID 匹配逻辑 (保持不变)
        medianame = item.get("medianame")
        if medianame is None or str(medianame).strip().lower() == "string":
            media_id = item.get("mediaid")
            if media_id is not None:
                resolved = media_lookup.get(str(media_id))
                if resolved:
                    item["medianame"] = str(resolved)

    # 4. 根据 Scope 筛选合并 (保持不变)
    def task_type(item: dict) -> int:
        return _coerce_int(item.get("tasktype"), 0)

    def filter_type(items: list, type_value: int) -> list:
        return [item for item in items if isinstance(item, dict) and task_type(item) == type_value]
    def filter_other_types(items: list) -> list:
        return [
            item
            for item in items
            if isinstance(item, dict) and task_type(item) not in {broadcast_type, livecast_type}
        ]

    existing_payload = _store_get("all_task")
    existing_items = []
    if isinstance(existing_payload, dict) and isinstance(existing_payload.get("data"), list):
        existing_items = [item for item in existing_payload["data"] if isinstance(item, dict)]

    other_items = filter_other_types(existing_items)

    if scope_key in {"broadcasts", "broadcast", "2"}:
        for item in incoming: item["tasktype"] = broadcast_type
        broadcast_items = incoming
        livecast_items = filter_type(existing_items, livecast_type)
    elif scope_key in {"livecasts", "livecast", "live", "3"}:
        for item in incoming: item["tasktype"] = livecast_type
        livecast_items = incoming
        broadcast_items = filter_type(existing_items, broadcast_type)
    else:
        broadcast_items = filter_type(incoming, broadcast_type)
        livecast_items = filter_type(incoming, livecast_type)
        other_items = filter_other_types(incoming)

    merged = broadcast_items + livecast_items + other_items
    
    # 5. 保存文件
    stored = {"data": merged}

    livecast_only_scope = scope_key in {"livecasts", "livecast", "live", "3"}
    mixed_livecast_scope = scope_key == "all"
    if _remote_enabled():
        if scope_key in {"all", "broadcasts", "broadcast", "2"}:
            _sync_remote_taskinfo("broadcast", REMOTE_BROADCAST_TASK_TYPE, broadcast_items)
        if livecast_only_scope:
            _sync_livecasts_independent(livecast_items, raise_on_failure=True)

    _store_set("all_task", stored)
    _write_cache_json(ALL_TASK_PATH, stored)
    _write_engine_all_task(stored)

    schedules_payload = _store_get("broadcast_schedules")
    if isinstance(schedules_payload, dict):
        if scope_key in {"all", "broadcasts", "broadcast", "2"}:
            schedules_payload["broadcasts"] = broadcast_items
        if scope_key in {"all", "livecasts", "livecast", "live", "3"}:
            schedules_payload["livecasts"] = livecast_items
        schedules_payload = _touch_generated_at(schedules_payload)
        _store_set("broadcast_schedules", schedules_payload)
        _write_cache_json(SCHEDULES_PATH, schedules_payload)
        _write_engine_schedules(schedules_payload)

    if _remote_enabled() and mixed_livecast_scope:
        _sync_livecasts_independent(livecast_items, raise_on_failure=False)

    # 6. 热重载AI引擎 - 数据已保存,引擎重载失败不应丢失数据
    engine_error = None
    try:
        LOGGER.info("Executing Engine Reload...")
        _reload_engine_assets()
        LOGGER.info("Engine Reload Successful.")
    except Exception as e:
        engine_error = str(e)
        LOGGER.error(f"AI引擎重载失败(任务数据已保存)。错误详情: {e}")

    result = {"status": "ok", "count": len(merged)}
    if engine_error:
        result["status"] = "partial"
        result["warning"] = f"数据已保存,但AI引擎重载失败: {engine_error}"
    return result


def _load_runtime_play_rows(force: bool = False) -> List[dict]:
    """Load runtime-play rows using configured remote listing paths when available.

    Interface semantics:
    - If REMOTE_TEMP_TASK_PATHS is configured and the remote list endpoint works,
      rows are built from the remote listing and merged with the recent cache.
    - If no remote list endpoint is configured for this deployment, the response is
      cache-first: it only includes recent tasks recorded by this process and then
      refreshes each task via /task/gettasktatus when possible.
    - In cache-first mode, a process restart starts from an empty recent cache, so
      already-playing remote temp tasks are not guaranteed to appear until this
      process creates or records them again.
    """
    cache_key = "runtime_play_rows"
    if not force:
        cached = _cache_get(cache_key)
        if isinstance(cached, list):
            return _clone_payload(cached) or []
    remote_rows: List[dict] = []
    try:
        remote_rows = _fetch_remote_runtime_play_rows()
    except HTTPException as exc:
        LOGGER.warning("load runtime play rows failed from remote: %s", exc.detail)
        remote_rows = []
    recent_rows = _recent_runtime_play_entries()
    rows = _merge_runtime_play_rows(remote_rows, recent_rows)
    rows = _refresh_runtime_play_rows_remote_state(rows, force=force)
    rows = rows[:RUNTIME_PLAY_RECENT_LIMIT]
    _cache_set(cache_key, rows)
    return _clone_payload(rows) or []


@app.get("/data/broadcast_schedules")
def get_broadcast_schedules(light: bool = False):
    _ensure_once_overrides_cleaned()
    if light:
        return _load_schedules_summary_payload()
    payload = _filter_hidden_ai_once_schedules_payload(
        _filter_once_ephemeral_in_schedules_payload(_load_schedules_payload())
    )
    _normalize_schedule_task_terminals(payload.get("schedules"))
    return payload


@app.get("/data/runtime_play_tasks")
def get_runtime_play_tasks(force: bool = False):
    """Return runtime-play tasks visible to the current deployment.

    This endpoint does not promise a full remote source-of-truth list in every
    deployment. When REMOTE_TEMP_TASK_PATHS is unset, it returns the process-local
    recent runtime-play cache and refreshes known task states via
    /task/gettasktatus. Deployments that provide a real remote listing endpoint can
    preserve remote enumeration by configuring REMOTE_TEMP_TASK_PATHS explicitly.
    """
    rows = _load_runtime_play_rows(force=force)
    return {"runtime_play_tasks": rows, "generated_at": _now_str()}


@app.post("/data/runtime_play_tasks/stop")
def stop_runtime_play_tasks(request: RuntimePlayStopRequest):
    task_ids = [str(item).strip() for item in (request.task_ids or []) if str(item).strip()]
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required.")
    stopped_ids = _remote_stop_temp_tasks(task_ids)
    for task_id in stopped_ids:
        _update_recent_runtime_play_entry(
            task_id,
            remote_state=-1,
            status="停止",
        )
    REMOTE_CACHE.pop("runtime_play_rows", None)
    rows = _load_runtime_play_rows(force=True)
    return {
        "status": "ok",
        "stopped_ids": stopped_ids,
        "runtime_play_tasks": rows,
        "generated_at": _now_str(),
    }


@app.get("/data/broadcast_schedules/broadcasts")
def get_broadcasts():
    payload = _clone_payload(_load_schedules_payload())
    raw_list = payload.get("broadcasts", []) if isinstance(payload.get("broadcasts"), list) else []
    
    # === 关键修改:在返回前加一层翻译 ===
    broadcasts = [_normalize_view_task(t, kind="broadcast") for t in raw_list]
    
    return {"broadcasts": broadcasts, "generated_at": _now_str()}



@app.get("/data/broadcast_schedules/livecasts")
def get_livecasts():
    payload = _clone_payload(_load_schedules_payload())
    raw_list = payload.get("livecasts", []) if isinstance(payload.get("livecasts"), list) else []
    
    # === 关键修改:在返回前加一层翻译 ===
    livecasts = [_normalize_view_task(t, kind="livecast") for t in raw_list]
    
    return {"livecasts": livecasts, "generated_at": _now_str()}

@app.post("/data/task_state")
def set_task_state(request: TaskStateRequest):
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    task_ids = [str(task_id) for task_id in (request.task_ids or []) if task_id not in (None, "")]
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required.")
    state_value = request.state
    if state_value is None:
        if not request.status:
            raise HTTPException(status_code=400, detail="state or status is required.")
        state_value = _task_state_from_label(request.status)
    state_value = _coerce_int(state_value, -1)
    if state_value not in {0, 1, 2, 3}:
        raise HTTPException(status_code=400, detail="Unsupported task state.")
    display_status = _task_display_status(state_value, request.status)
    kind = str(request.kind or "broadcast").lower()
    if kind in {"broadcast", "broadcasts", "2"}:
        key = "broadcasts"
    elif kind in {"livecast", "livecasts", "live", "3"}:
        key = "livecasts"
    else:
        raise HTTPException(status_code=400, detail="Unsupported kind.")
    payload = _clone_payload(_load_schedules_payload())
    items = payload.get(key, []) if isinstance(payload, dict) else []
    updated_ids: List[str] = []
    skipped_ids: List[str] = []
    request_set = set(task_ids)
    for item in items:
        if not isinstance(item, dict):
            continue
        task_id = _task_id(item)
        if not task_id or task_id not in request_set:
            continue
        try:
            _remote_set_task_state(task_id, state_value)
        except HTTPException:
            skipped_ids.append(task_id)
            continue
        item["status"] = display_status
        item["taskstate"] = state_value
        updated_ids.append(task_id)
    if updated_ids:
        _touch_generated_at(payload)
        _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
    missing_ids = [task_id for task_id in task_ids if task_id not in updated_ids and task_id not in skipped_ids]
    return {
        "status": "ok",
        "updated": len(updated_ids),
        "updated_ids": updated_ids,
        "skipped_ids": skipped_ids,
        "missing_ids": missing_ids,
        "state": state_value,
        "display_status": display_status,
    }


@app.post("/data/schedule_state")
def set_schedule_state(request: ScheduleStateRequest):
    schedule_names = [str(name).strip() for name in (request.schedule_names or []) if str(name).strip()]
    if not schedule_names:
        raise HTTPException(status_code=400, detail="schedule_names is required.")
    state_value = request.state
    if state_value is None:
        if not request.status:
            raise HTTPException(status_code=400, detail="state or status is required.")
        state_value = 0 if _status_enabled(request.status) else 1
    state_value = _coerce_int(state_value, -1)
    if state_value not in {0, 1}:
        raise HTTPException(status_code=400, detail="Unsupported schedule state.")
    display_status = "启用" if state_value == 0 else "停用"

    payload = _clone_payload(_load_schedules_payload())
    schedules = payload.get("schedules") if isinstance(payload, dict) else []
    if not isinstance(schedules, list):
        schedules = []

    updated_names: List[str] = []
    request_set = set(schedule_names)
    for item in schedules:
        if not isinstance(item, dict):
            continue
        schedule_name = item.get("schedule_name") or item.get("name")
        if not schedule_name:
            continue
        schedule_name = str(schedule_name)
        if schedule_name not in request_set:
            continue
        if _remote_enabled():
            _remote_set_schedule_status(schedule_name, state_value == 0)
        item["status"] = display_status
        updated_names.append(schedule_name)

    if not updated_names:
        raise HTTPException(status_code=404, detail="schedule not found")

    payload["schedules"] = schedules
    payload = _touch_generated_at(payload)
    _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)

    missing_names = [name for name in schedule_names if name not in updated_names]
    return {
        "status": "ok",
        "updated": len(updated_names),
        "updated_names": updated_names,
        "missing_names": missing_names,
        "state": state_value,
        "display_status": display_status,
    }


@app.get("/data/task_overrides")
def get_task_overrides():
    _ensure_once_overrides_cleaned()
    return _load_overrides_payload()


@app.put("/data/task_overrides/once/{override_id}/tasks/{once_task_id}")
def update_once_override_task(override_id: str, once_task_id: str, patch: dict = Body(...)):
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    _ensure_once_overrides_cleaned()
    payload = _load_overrides_payload()
    override_index, entry, spec_index, spec = _find_editable_once_override(payload, override_id, once_task_id)
    if not _remote_enabled():
        raise HTTPException(status_code=503, detail="Remote sync is required for once task editing.")
    schedule_name = _once_remote_schedule_name_from_spec(entry, spec)
    if not schedule_name:
        raise HTTPException(status_code=400, detail="Once override is missing schedule_name.")
    remote_tasks = [_normalize_remote_task(item) for item in _remote_fetch_schedule_tasks(schedule_name)]
    remote_snapshot = next((item for item in remote_tasks if _task_id(item) == str(once_task_id).strip()), None)
    if not isinstance(remote_snapshot, dict):
        raise HTTPException(status_code=404, detail="Remote once task not found.")
    media_map = _remote_media_map()
    terminal_map = _remote_terminal_map()
    terminal_lookup = _remote_terminal_lookup()
    task_payload, updated_spec = _build_once_override_task_payload(
        entry=entry,
        spec=spec,
        remote_snapshot=remote_snapshot,
        patch=patch,
        media_map=media_map,
        terminal_lookup=terminal_lookup,
    )
    _remote_update_task(str(once_task_id), schedule_name, task_payload, media_map, terminal_map, remote_snapshot)
    entry["once_task_specs"][spec_index] = updated_spec
    entry["updated_at"] = _now_str()
    _refresh_once_override_schedule_commands(entry, reschedule_remote=True)
    payload["overrides"][override_index] = entry
    _save_overrides_payload(_touch_generated_at(payload))
    return {"status": "ok", "override": entry, "once_task_spec": updated_spec}


@app.delete("/data/task_overrides/once/{override_id}/tasks/{once_task_id}")
def delete_once_override_task(override_id: str, once_task_id: str):
    _ensure_once_overrides_cleaned()
    payload = _load_overrides_payload()
    override_index, entry, spec_index, spec = _find_editable_once_override(payload, override_id, once_task_id)
    once_task_id_text = str(once_task_id or "").strip()
    if not _remote_enabled():
        raise HTTPException(status_code=503, detail="Remote sync is required for once task deletion.")
    if not _is_numeric_id(once_task_id_text):
        raise HTTPException(status_code=400, detail="Remote once task id is invalid.")
    once_schedule_name = _once_remote_schedule_name_from_spec(entry, spec)
    _remote_delete_task(once_task_id_text)
    specs = [item for idx, item in enumerate(entry.get("once_task_specs") or []) if idx != spec_index]
    entry["once_task_specs"] = specs
    entry["once_task_ids"] = [item for item in (entry.get("once_task_ids") or []) if str(item or "").strip() != once_task_id_text]
    entry["shadow_task_ids"] = [item for item in (entry.get("shadow_task_ids") or []) if str(item or "").strip() != once_task_id_text]
    entry["source_once_task_ids"] = [item for item in (entry.get("source_once_task_ids") or []) if str(item or "").strip() != once_task_id_text]
    entry["target_once_task_ids"] = [item for item in (entry.get("target_once_task_ids") or []) if str(item or "").strip() != once_task_id_text]
    entry["cleaned_task_ids"] = _unique_list([*(entry.get("cleaned_task_ids") or []), once_task_id_text])
    entry["updated_at"] = _now_str()
    if not entry["once_task_specs"]:
        entry["active"] = False
        entry["execution_state"] = "cleaned"
        entry["cleanup_state"] = "cleaned"
        entry["cleaned_at"] = _now_str()
        entry["enable_once_commands"] = []
        entry["commands"] = _once_override_non_enabletask_commands(entry)
    else:
        _refresh_once_override_schedule_commands(entry, reschedule_remote=True)
    payload["overrides"][override_index] = entry
    _cleanup_empty_once_remote_schedule(once_schedule_name)
    _save_overrides_payload(_touch_generated_at(payload))
    return {"status": "ok", "override": entry, "deleted_once_task_id": once_task_id_text}


@app.get("/data/assistant_settings")
def get_assistant_settings():
    return _assistant_settings_response_payload()


def get_remote_settings():
    return _remote_settings_response_payload()


def put_remote_settings(payload: dict = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    remote_base_url = _normalize_remote_base_url(payload.get("remote_base_url"))
    stored = _save_remote_settings_payload(
        {
            "remote_base_url": remote_base_url,
            "last_verified_at": payload.get("last_verified_at") or "",
            "last_verified_ip": payload.get("last_verified_ip") or "",
        }
    )
    return _remote_settings_response_payload(stored)


@app.put("/data/assistant_settings")
def put_assistant_settings(payload: dict = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    default_schedule_kind = str(payload.get("default_schedule_kind") or "").strip()
    default_schedule_season = str(payload.get("default_schedule_season") or "").strip()
    if default_schedule_kind not in ALLOWED_SCHEDULE_KINDS and default_schedule_kind != "":
        raise HTTPException(status_code=400, detail="default_schedule_kind must be one of 小学、中学、高中、大学.")
    if default_schedule_season not in ALLOWED_SCHEDULE_SEASONS and default_schedule_season != "":
        raise HTTPException(status_code=400, detail="default_schedule_season must be one of 夏季、冬季.")
    stored = _save_assistant_settings_payload(
        {
            "default_schedule_kind": default_schedule_kind,
            "default_schedule_season": default_schedule_season,
        }
    )
    return _assistant_settings_response_payload(stored)


@app.put("/data/broadcast_schedules")
def put_broadcast_schedules(payload: dict = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    unnamed_indexes = []
    for index, schedule in enumerate(payload.get("schedules") or []):
        if not isinstance(schedule, dict):
            continue
        schedule_name = str(schedule.get("schedule_name") or schedule.get("name") or "").strip()
        if not schedule_name:
            unnamed_indexes.append(str(index + 1))
    if unnamed_indexes:
        raise HTTPException(
            status_code=400,
            detail="schedule_name is required for every schedule entry: " + ", ".join(unnamed_indexes),
        )
    existing = _load_schedules_payload()
    overrides_payload = _clone_payload(_load_overrides_payload())
    sync_schedules = "schedules" in payload
    sync_broadcasts = "broadcasts" in payload
    sync_livecasts = "livecasts" in payload
    if not sync_schedules:
        payload["schedules"] = existing.get("schedules", [])
    if not sync_broadcasts:
        payload["broadcasts"] = existing.get("broadcasts", [])
    if not sync_livecasts:
        payload["livecasts"] = existing.get("livecasts", [])
    if "directories" not in payload:
        payload["directories"] = existing.get("directories", [])
    removed_schedule_names = _removed_schedule_names(existing, payload) if sync_schedules else []
    overrides_changed = _cleanup_once_overrides_for_schedules(overrides_payload, removed_schedule_names)
    _commit_payload_with_rollback(
        payload,
        existing,
        sync_schedules=sync_schedules,
        sync_broadcasts=sync_broadcasts,
        sync_livecasts=sync_livecasts,
    )
    if overrides_changed:
        try:
            _save_overrides_payload(_touch_generated_at(overrides_payload))
        except HTTPException as exc:
            raise HTTPException(
                status_code=500,
                detail=f"put_broadcast_schedules override cleanup failed: {exc.detail}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"put_broadcast_schedules override cleanup failed: {_short_error_text(exc)}",
            ) from exc
    return {"status": "ok"}


@app.post("/data/broadcast_schedules/schedules")
def add_schedule(schedule: dict = Body(...)):
    if not isinstance(schedule, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    payload = _clone_payload(_load_schedules_payload())
    schedules = payload.get("schedules")
    if not isinstance(schedules, list):
        schedules = []
    name = schedule.get("schedule_name") or schedule.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="schedule_name is required")
    if any(isinstance(s, dict) and s.get("schedule_name") == name for s in schedules):
        raise HTTPException(status_code=409, detail="schedule already exists")
    schedule["schedule_name"] = name
    schedules.append(schedule)
    payload["schedules"] = schedules
    _commit_payload_with_rollback(
        payload,
        _load_schedules_payload(),
        target_schedule_names=[name],
        sync_broadcasts=False,
        sync_livecasts=False,
    )
    return {"schedule_name": name, "count": len(schedules)}


@app.get("/data/broadcast_schedules/schedules/{schedule_name}/tasks")
def get_schedule_tasks(schedule_name: str):
    if not schedule_name:
        raise HTTPException(status_code=400, detail="schedule_name is required")
    _ensure_once_overrides_cleaned()
    payload = _filter_once_ephemeral_in_schedules_payload(_load_schedules_payload())
    _normalize_schedule_task_terminals(payload.get("schedules"))
    schedule = _find_schedule(payload, schedule_name)
    if not schedule:
        raise HTTPException(status_code=404, detail="schedule not found")
    tasks = _filter_once_ephemeral_schedule_tasks(schedule.get("tasks"))
    return {"schedule_name": schedule_name, "tasks": tasks}


@app.put("/data/broadcast_schedules/schedules/{schedule_name}")
def update_schedule(schedule_name: str, schedule: dict = Body(...)):
    if not isinstance(schedule, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    payload = _clone_payload(_load_schedules_payload())
    schedules = payload.get("schedules")
    if not isinstance(schedules, list):
        schedules = []
    updated = None
    for idx, item in enumerate(schedules):
        if isinstance(item, dict) and item.get("schedule_name") == schedule_name:
            schedule["schedule_name"] = schedule_name
            schedules[idx] = schedule
            updated = schedule
            break
    if updated is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    payload["schedules"] = schedules
    _commit_payload_with_rollback(
        payload,
        _load_schedules_payload(),
        target_schedule_names=[schedule_name],
        sync_broadcasts=False,
        sync_livecasts=False,
    )
    return updated


@app.delete("/data/broadcast_schedules/schedules/{schedule_name}")
def delete_schedule(schedule_name: str):
    payload = _clone_payload(_load_schedules_payload())
    overrides_payload = _clone_payload(_load_overrides_payload())
    schedules = payload.get("schedules")
    if not isinstance(schedules, list):
        schedules = []
    idx = None
    for i, item in enumerate(schedules):
        if isinstance(item, dict) and item.get("schedule_name") == schedule_name:
            idx = i
            break
    if idx is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    removed = schedules.pop(idx)
    removed_tasks = [task for task in (removed.get("tasks") or []) if isinstance(task, dict)]
    if _remote_enabled():
        _delete_remote_schedule_tasks_strict(schedule_name, removed_tasks)
    payload["schedules"] = schedules
    overrides_changed = _cleanup_once_overrides_for_schedules(overrides_payload, [schedule_name])
    failure_stage, failure_reason = _commit_schedule_delete_with_once_cleanup(
        payload,
        overrides_payload,
        save_schedule_payload=lambda new_payload: _save_schedules_payload(
            new_payload,
            sync_schedules=False,
            sync_broadcasts=False,
            sync_livecasts=False,
        ),
        overrides_changed=overrides_changed,
    )
    if failure_stage == "schedule":
        raise HTTPException(status_code=500, detail=f"delete_schedule save failed: {failure_reason}")
    if failure_stage == "override":
        raise HTTPException(
            status_code=500,
            detail=f"delete_schedule override cleanup failed: {failure_reason}",
        )
    return {"deleted": removed, "count": len(schedules)}


@app.post("/admin/reload")
def reload_assets():
    if _remote_enabled():
        _sync_remote_data(force=True)
    _reload_engine_assets()
    return {"status": "ok"}


@app.post("/admin/sync_data")
def sync_data(repair_catalog: bool = Query(True)):
    if not _remote_enabled():
        raise HTTPException(status_code=400, detail="未配置远端地址。")
    resolved_remote_base_url, remote_base_url_source = _resolve_remote_base_url_details()
    _debug_remote(
        "sync data request",
        resolved_remote_base_url=resolved_remote_base_url,
        remote_base_url_source=remote_base_url_source,
        thread_name=threading.current_thread().name,
        thread_pool_task="ThreadPoolExecutor" in threading.current_thread().name,
        repair_catalog=repair_catalog,
    )
    results = _sync_remote_data(force=True)
    catalog_repair: Dict[str, Any] = {}
    if repair_catalog and results.get("broadcast_schedules"):
        payload = _store_get("broadcast_schedules")
        if isinstance(payload, dict):
            catalog_repair = _repair_remote_schedule_catalog(payload)
            if catalog_repair.get("created"):
                refreshed = _sync_remote_data(force=True, keys=["broadcast_schedules"])
                results.update(refreshed)
    if any(results.values()):
        _reload_engine_assets()
    status = "ok" if results and all(results.values()) else "partial"
    if catalog_repair.get("still_missing") or catalog_repair.get("failed"):
        status = "partial"
    resp = {"status": status, "synced": results}
    if repair_catalog:
        resp["catalog_repair"] = catalog_repair
    return resp
@app.get("/debug/diagnose")
def debug_diagnose():
    """
    终极诊断:全链路检查文件路径、内容读取、以及 AI 索引状态
    """
    import os
    
    # 1. 检查路径解析情况
    # 获取 main.py 中定义的全局变量
    target_path = ALL_TASK_PATH 
    abs_path = target_path.resolve() if isinstance(target_path, Path) else Path(str(target_path)).resolve()
    
    diagnosis = {
        "1_env_cwd": os.getcwd(),  # 当前运行目录
        "2_config_path_raw": str(target_path), # 代码里写的路径
        "3_config_path_abs": str(abs_path),    # 实际解析的绝对路径
        "4_file_exists": abs_path.exists(),    # 文件到底在不在?
    }

    # 2. 尝试读取文件内容
    file_content_preview = "N/A"
    parse_success = False
    item_count = 0
    names_found = []
    
    if abs_path.exists():
        try:
            content = abs_path.read_text(encoding="utf-8")
            file_content_preview = content[:200] + "..." # 只看前200个字符
            
            data = json.loads(content)
            items = data.get("data", []) if isinstance(data, dict) else data
            if isinstance(items, list):
                item_count = len(items)
                # 模拟 adaptation 的读取逻辑看看能不能读到名字
                for item in items[:5]: # 只检查前5个
                    # 优先找 taskname, 然后 name
                    found = item.get("taskname") or item.get("name") or item.get("medianame")
                    names_found.append(str(found))
            parse_success = True
        except Exception as e:
            parse_success = False
            file_content_preview = f"Error reading file: {str(e)}"

    diagnosis["5_read_test"] = {
        "success": parse_success,
        "item_count_on_disk": item_count,
        "names_extracted_test": names_found, # 看看这里有没有"蜡笔小新"
        "content_preview": file_content_preview
    }

    # 3. 检查 AI 引擎内存状态
    engine_index = getattr(ENGINE, "task_index", None)
    engine_names = []
    if isinstance(engine_index, dict):
        engine_names = list(engine_index.keys())
    elif hasattr(engine_index, "names"): # 兼容 adaptation 的 AssetIndex 对象
        engine_names = engine_index.names
        
    diagnosis["6_engine_memory"] = {
        "count_in_memory": len(engine_names),
        "has_labixiaoxin": "蜡笔小新" in engine_names,
        "sample_memory": engine_names[:10]
    }
    return diagnosis

@app.get("/debug/fix_brain")
def debug_fix_brain():
    """
    强制手术:把 AI 引擎的读取路径强行扭送到 backend/data 目录下,并立即重载
    """
    # 1. 获取正确的绝对路径
    correct_task_path = ALL_TASK_PATH.resolve() if isinstance(ALL_TASK_PATH, Path) else Path(str(ALL_TASK_PATH)).resolve()
    correct_media_path = ALL_AUDIO_PATH.resolve() if isinstance(ALL_AUDIO_PATH, Path) else Path(str(ALL_AUDIO_PATH)).resolve()
    correct_loc_path = ALL_LOC_PATH.resolve() if isinstance(ALL_LOC_PATH, Path) else Path(str(ALL_LOC_PATH)).resolve()

    LOGGER.info("强制 AI 读取路径: %s", correct_task_path)

    # 2. 强行调用 adaptation 加载(绕过 Engine Config)
    from src.adaptation import load_adaptation_assets
    
    # 这里的关键是:必须传入字符串路径,且必须是 backend/data 下的那个
    new_media, new_loc, new_task, new_zone = load_adaptation_assets(
        str(correct_media_path), 
        str(correct_loc_path), 
        str(correct_task_path), 
        str(correct_loc_path)
    )

    # 3. 强行替换 AI 内存
    ENGINE.media_index = new_media
    ENGINE.loc_index = new_loc
    ENGINE.task_index = new_task
    ENGINE.zone_index = new_zone
    
    # 4. 刷新调度(如果需要)
    _reload_engine_schedules()

    # 5. 验证结果
    engine_names = []
    if hasattr(ENGINE.task_index, "names"):
        engine_names = ENGINE.task_index.names
    elif isinstance(ENGINE.task_index, dict):
        engine_names = list(ENGINE.task_index.keys())

    return {
        "status": "success", 
        "message": "Brain Transplant Completed",
        "correct_path": str(correct_task_path),
        "memory_count_after_fix": len(engine_names),
        "has_labixiaoxin": "蜡笔小新" in engine_names,
        "current_memory": engine_names
    }


def _perform_import_from_template(source_template: str, target_name: str):
    # 1. 读取模板文件
    if not TEMPLATES_PATH.exists():
        return None, "错误:后台没有找到 templates.json 模板文件。"
    
    try:
        tpl_data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        tpl_list = tpl_data.get("schedules", [])
    except Exception as e:
        return None, f"模板文件损坏: {str(e)}"

    # 2. 寻找母本
    source_schedule = None
    for s in tpl_list:
        curr = s.get("schedule_name") or s.get("name")
        if curr == source_template:
            source_schedule = s
            break
    
    if not source_schedule:
        return None, f"系统里没找到【{source_template}】这个母本,无法复制。"

    # 3. 准备新名字
    payload = _clone_payload(_load_schedules_payload())
    current_schedules = payload.get("schedules", [])
    existing_names = {str(s.get("schedule_name")) for s in current_schedules}
    
    final_name = target_name
    counter = 1
    while final_name in existing_names:
        final_name = f"{target_name}({counter})"
        counter += 1

    # 4. 执行克隆
    new_schedule = _clone_payload(source_schedule)
    new_schedule["schedule_name"] = final_name 
    new_schedule["status"] = "启用"
    
    # 5. 遍历任务,进行关键修正！
    new_tasks = new_schedule.get("tasks", [])
    workweek_weekdays = ["周一", "周二", "周三", "周四", "周五"]
    workweek_execmode = _execmode_from_weekdays(workweek_weekdays)
    for task in new_tasks:
        # 改名
        task["sechename"] = final_name
        task["info"] = final_name
        
        task["weekdays"] = list(workweek_weekdays)
        task["execmode"] = workweek_execmode  # 周一至周五 -> 62

    # 6. 保存
    current_schedules.append(new_schedule)
    payload["schedules"] = current_schedules
    _touch_generated_at(payload)
    _save_schedules_payload(payload, sync_schedules=False, sync_broadcasts=False, sync_livecasts=False)
    
    return final_name, len(new_tasks)


def _resolve_web_dist_dir() -> Optional[Path]:
    override = str(os.getenv("AI_SPEAKER_WEB_DIST", "")).strip()
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates.append(BASE_DIR.parent / "web" / "dist")
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_dir():
                return candidate
        except Exception:
            continue
    return None


def _register_static_frontend() -> None:
    dist_dir = _resolve_web_dist_dir()
    if dist_dir is None:
        return

    static_dir = dist_dir / "static"
    favicon_file = dist_dir / "favicon.ico"
    index_file = dist_dir / "index.html"

    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="web-static")

    if favicon_file.is_file():
        @app.get("/favicon.ico", include_in_schema=False)
        def _web_favicon() -> FileResponse:
            return FileResponse(favicon_file)

    if index_file.is_file():
        @app.get("/", include_in_schema=False)
        def _web_index() -> FileResponse:
            return FileResponse(index_file)


_register_static_frontend()
