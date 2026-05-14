"""
Local JSON data store: read/write/backup with thread-safe in-memory cache.
"""
from __future__ import annotations

import json
import os
import time
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException

from backend.config import (
    ALL_AUDIO_PATH, ALL_LOC_PATH, ALL_TASK_PATH,
    SCHEDULES_PATH, OVERRIDES_PATH, ASSISTANT_COMMAND_LOGS_PATH, CALENDAR_HOLIDAYS_CN_PATH, HISTORY_DIR, LOGGER,
)
from backend.services.file_permissions import apply_shared_json_permissions

DATA_STORE_LOCK = threading.Lock()
DATA_STORE: Dict[str, Dict[str, object]] = {
    "all_audio": {"path": ALL_AUDIO_PATH, "payload": None, "loaded": False},
    "all_loc": {"path": ALL_LOC_PATH, "payload": None, "loaded": False},
    "all_task": {"path": ALL_TASK_PATH, "payload": None, "loaded": False},
    "broadcast_schedules": {"path": SCHEDULES_PATH, "payload": None, "loaded": False},
    "task_overrides": {"path": OVERRIDES_PATH, "payload": None, "loaded": False},
    "assistant_command_logs": {"path": ASSISTANT_COMMAND_LOGS_PATH, "payload": None, "loaded": False},
    "calendar_holidays_cn": {"path": CALENDAR_HOLIDAYS_CN_PATH, "payload": None, "loaded": False},
}


def read_json(path: Path) -> object:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing file: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read {path.name}") from exc


def read_json_optional(path: Path) -> Optional[object]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def backup_file(path: Path, keep: int = 20) -> None:
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


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path)
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


def write_cache_json(path: Path, payload: object) -> None:
    try:
        write_json(path, payload)
    except PermissionError:
        return


def store_get(key: str) -> Optional[object]:
    entry = DATA_STORE.get(key)
    if not entry:
        return None
    with DATA_STORE_LOCK:
        if not entry.get("loaded"):
            return None
        return entry.get("payload")


def store_set(key: str, payload: object) -> None:
    entry = DATA_STORE.get(key)
    if not entry:
        return
    with DATA_STORE_LOCK:
        entry["payload"] = payload
        entry["loaded"] = True
        entry["updated_at"] = time.time()


def store_require(key: str, label: str, status_code: int) -> object:
    payload = store_get(key)
    if payload is None:
        raise HTTPException(status_code=status_code, detail=f"{label} is not available yet.")
    return payload


def store_load_from_file(
    key: str,
    normalize: Optional[Callable[[object], object]] = None,
    default: Optional[object] = None,
) -> bool:
    entry = DATA_STORE.get(key)
    if not entry:
        return False
    path = entry.get("path")
    if not isinstance(path, Path):
        return False
    payload = read_json_optional(path)
    if payload is None:
        if default is None:
            return False
        payload = default
    if normalize:
        try:
            payload = normalize(payload)
        except Exception:
            return False
    store_set(key, payload)
    return True


def clone_payload(payload: object) -> object:
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return payload


def read_data_container(path: Path) -> tuple:
    payload = read_json(path)
    if isinstance(payload, dict):
        items = payload.get("data")
        if isinstance(items, list):
            return payload, items
    if isinstance(payload, list):
        return {"data": payload}, payload
    raise HTTPException(status_code=500, detail=f"Invalid data format in {path.name}")
