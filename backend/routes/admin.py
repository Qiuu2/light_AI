"""Admin and debug routes delegated to injectable handlers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter, Query


@dataclass(frozen=True)
class AdminHandlers:
    reload_assets: Callable[[], object]
    sync_data: Callable[[bool], object]
    debug_diagnose: Callable[[], object]
    debug_fix_brain: Callable[[], object]


def create_router(handlers: AdminHandlers) -> APIRouter:
    router = APIRouter()

    @router.post("/admin/reload")
    def reload_assets():
        return handlers.reload_assets()

    @router.post("/admin/sync_data")
    def sync_data(repair_catalog: bool = Query(True)):
        return handlers.sync_data(repair_catalog)

    @router.get("/debug/diagnose")
    def debug_diagnose():
        return handlers.debug_diagnose()

    @router.get("/debug/fix_brain")
    def debug_fix_brain():
        return handlers.debug_fix_brain()

    return router
