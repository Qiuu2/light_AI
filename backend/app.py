"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
import backend.api_public as api_public
from backend.routes.admin import AdminHandlers, create_router as create_admin_router
from backend.routes.assistant import create_router as create_assistant_router
from backend.routes.data import DataHandlers, create_router as create_data_router
from backend.routes.debug import create_router as create_debug_router
from backend.routes.light import create_router as create_light_router


def _build_data_handlers() -> DataHandlers:
    return DataHandlers(
        get_assistant_command_logs=api_public.get_assistant_command_logs,
        healthz=api_public.healthz,
        readyz=api_public.readyz,
        get_ops_status=api_public.get_ops_status,
        get_calendar_holidays=api_public.get_calendar_holidays,
        get_all_audio=api_public.get_all_audio,
        get_all_loc=api_public.get_all_loc,
        get_all_task=api_public.get_all_task,
        put_all_task=api_public.put_all_task,
        get_broadcast_schedules=api_public.get_broadcast_schedules,
        get_runtime_play_tasks=api_public.get_runtime_play_tasks,
        stop_runtime_play_tasks=api_public.stop_runtime_play_tasks,
        get_broadcasts=api_public.get_broadcasts,
        get_livecasts=api_public.get_livecasts,
        set_task_state=api_public.set_task_state,
        set_schedule_state=api_public.set_schedule_state,
        get_task_overrides=api_public.get_task_overrides,
        get_assistant_settings=api_public.get_assistant_settings,
        put_assistant_settings=api_public.put_assistant_settings,
        put_broadcast_schedules=api_public.put_broadcast_schedules,
        add_schedule=api_public.add_schedule,
        get_schedule_tasks=api_public.get_schedule_tasks,
        update_schedule=api_public.update_schedule,
        delete_schedule=api_public.delete_schedule,
    )


def _build_admin_handlers() -> AdminHandlers:
    return AdminHandlers(
        reload_assets=api_public.reload_assets,
        sync_data=api_public.sync_data,
        debug_diagnose=api_public.debug_diagnose,
        debug_fix_brain=api_public.debug_fix_brain,
    )


def build_app() -> FastAPI:
    app = FastAPI(title="AI Speaker NLU API", version="1.0.0")
    api_public.configure_cors(app)

    app.include_router(
        create_assistant_router(
            infer_handler=api_public.infer_api,
            chat_handler=api_public.chat_api,
        )
    )
    app.include_router(
        create_debug_router(
            test_phase1_handler=api_public.debug_test_phase1_intent,
            apply_action_handler=api_public.debug_apply_action,
        )
    )
    app.include_router(create_data_router(_build_data_handlers()))
    app.include_router(create_light_router())
    app.include_router(create_admin_router(_build_admin_handlers()))
    app.add_event_handler("startup", api_public._startup_load_data)
    app.add_event_handler("shutdown", api_public._shutdown_runtime)
    return app


app = build_app()

__all__ = ["app", "build_app"]
