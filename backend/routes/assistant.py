"""Assistant-facing routes for inference and chat."""
from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import APIRouter, Request

from backend.models import ChatResponse, InferRequest, InferResponse


def create_router(
    infer_handler: Callable[[InferRequest], InferResponse],
    chat_handler: Callable[[Request], Awaitable[ChatResponse]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/infer", response_model=InferResponse)
    def infer_api(payload: InferRequest) -> InferResponse:
        return infer_handler(payload)

    @router.post("/assistant/chat", response_model=ChatResponse)
    async def chat_api(request: Request) -> ChatResponse:
        return await chat_handler(request)

    return router
