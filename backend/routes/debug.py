"""Debug routes for intent/action validation."""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter

from backend.models import (
    DebugApplyActionRequest,
    DebugApplyActionResponse,
    TestPhase1IntentRequest,
    TestPhase1IntentResponse,
)


def create_router(
    test_phase1_handler: Callable[[TestPhase1IntentRequest], TestPhase1IntentResponse],
    apply_action_handler: Callable[[DebugApplyActionRequest], DebugApplyActionResponse],
) -> APIRouter:
    router = APIRouter()

    @router.post("/debug/test_phase1_intent", response_model=TestPhase1IntentResponse)
    def debug_test_phase1_intent(payload: TestPhase1IntentRequest) -> TestPhase1IntentResponse:
        return test_phase1_handler(payload)

    @router.post("/debug/apply_action", response_model=DebugApplyActionResponse)
    def debug_apply_action(payload: DebugApplyActionRequest) -> DebugApplyActionResponse:
        return apply_action_handler(payload)

    return router
