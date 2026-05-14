"""Data routes for local JSON storage and schedule payload management."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, Body, Query

from backend.models import RuntimePlayStopRequest, ScheduleStateRequest, TaskStateRequest

ASSISTANT_COMMAND_LOG_LIMIT = 1000


@dataclass(frozen=True)
class DataHandlers:
    get_assistant_command_logs: Callable[[int], object]
    healthz: Callable[[], object]
    readyz: Callable[[], object]
    get_ops_status: Callable[[], object]
    get_calendar_holidays: Callable[[str], object]
    get_all_audio: Callable[[int | None], object]
    get_all_loc: Callable[[], object]
    get_all_task: Callable[[], object]
    put_all_task: Callable[[dict, str], object]
    get_broadcast_schedules: Callable[[bool], object]
    get_runtime_play_tasks: Callable[[bool], object]
    stop_runtime_play_tasks: Callable[[RuntimePlayStopRequest], object]
    get_broadcasts: Callable[[], object]
    get_livecasts: Callable[[], object]
    set_task_state: Callable[[TaskStateRequest], object]
    set_schedule_state: Callable[[ScheduleStateRequest], object]
    get_task_overrides: Callable[[], object]
    get_assistant_settings: Callable[[], object]
    put_assistant_settings: Callable[[dict], object]
    put_broadcast_schedules: Callable[[dict], object]
    add_schedule: Callable[[dict], object]
    get_schedule_tasks: Callable[[str], object]
    update_schedule: Callable[[str, dict], object]
    delete_schedule: Callable[[str], object]


def create_router(handlers: DataHandlers) -> APIRouter:
    router = APIRouter()

    @router.get("/data/assistant_command_logs")
    def get_assistant_command_logs(limit: int = Query(100, ge=1, le=ASSISTANT_COMMAND_LOG_LIMIT)):
        return handlers.get_assistant_command_logs(limit)

    @router.get("/healthz")
    def healthz():
        return handlers.healthz()

    @router.get("/readyz")
    def readyz():
        return handlers.readyz()

    @router.get("/ops/status")
    def get_ops_status():
        return handlers.get_ops_status()

    @router.get("/data/calendar_holidays")
    def get_calendar_holidays(year: str = Query(...)):
        return handlers.get_calendar_holidays(year)

    @router.get("/data/all_audio")
    def get_all_audio(folderid: int | None = Query(None)):
        return handlers.get_all_audio(folderid)

    @router.get("/data/all_loc")
    def get_all_loc():
        return handlers.get_all_loc()

    @router.get("/data/all_task")
    def get_all_task():
        return handlers.get_all_task()

    @router.put("/data/all_task")
    def put_all_task(payload: dict = Body(...), scope: str = Query("all")):
        return handlers.put_all_task(payload, scope)

    @router.get("/data/broadcast_schedules")
    def get_broadcast_schedules(light: bool = False):
        return handlers.get_broadcast_schedules(light)

    @router.get("/data/runtime_play_tasks")
    def get_runtime_play_tasks(force: bool = Query(False)):
        return handlers.get_runtime_play_tasks(force)

    @router.post("/data/runtime_play_tasks/stop")
    def stop_runtime_play_tasks(request: RuntimePlayStopRequest):
        return handlers.stop_runtime_play_tasks(request)

    @router.get("/data/broadcast_schedules/broadcasts")
    def get_broadcasts():
        return handlers.get_broadcasts()

    @router.get("/data/broadcast_schedules/livecasts")
    def get_livecasts():
        return handlers.get_livecasts()

    @router.post("/data/task_state")
    def set_task_state(request: TaskStateRequest):
        return handlers.set_task_state(request)

    @router.post("/data/schedule_state")
    def set_schedule_state(request: ScheduleStateRequest):
        return handlers.set_schedule_state(request)

    @router.get("/data/task_overrides")
    def get_task_overrides():
        return handlers.get_task_overrides()

    @router.get("/data/assistant_settings")
    def get_assistant_settings():
        return handlers.get_assistant_settings()

    @router.put("/data/assistant_settings")
    def put_assistant_settings(payload: dict = Body(...)):
        return handlers.put_assistant_settings(payload)

    @router.put("/data/broadcast_schedules")
    def put_broadcast_schedules(payload: dict = Body(...)):
        return handlers.put_broadcast_schedules(payload)

    @router.post("/data/broadcast_schedules/schedules")
    def add_schedule(schedule: dict = Body(...)):
        return handlers.add_schedule(schedule)

    @router.get("/data/broadcast_schedules/schedules/{schedule_name}/tasks")
    def get_schedule_tasks(schedule_name: str):
        return handlers.get_schedule_tasks(schedule_name)

    @router.put("/data/broadcast_schedules/schedules/{schedule_name}")
    def update_schedule(schedule_name: str, schedule: dict = Body(...)):
        return handlers.update_schedule(schedule_name, schedule)

    @router.delete("/data/broadcast_schedules/schedules/{schedule_name}")
    def delete_schedule(schedule_name: str):
        return handlers.delete_schedule(schedule_name)

    return router
