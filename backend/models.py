"""Pydantic models for API request/response schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InferRequest(BaseModel):
    text: str


class InferResponse(BaseModel):
    intent: str
    confidence: float
    slots: dict
    missing_slots: List[str] = Field(default_factory=list)
    dialog_state_detail: Optional[str] = None
    raw_entities: dict
    tokens: List[str]
    tags: List[int]
    output_speech: Optional[str] = None
    message: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    output_speech: Optional[str] = None
    intent: str
    confidence: float
    slots: dict
    missing_slots: List[str]
    dialog_state_detail: Optional[str] = None
    raw_entities: dict
    tokens: List[str]
    tags: List[int]
    action_log: Optional[List[dict]] = None
    diagnostics: List[dict] = Field(default_factory=list)
    pending_action: Optional[dict] = None


class TaskStateRequest(BaseModel):
    task_ids: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    state: Optional[int] = None
    kind: Optional[str] = "broadcast"


class ScheduleStateRequest(BaseModel):
    schedule_names: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    state: Optional[int] = None


class RuntimePlayStopRequest(BaseModel):
    task_ids: List[str] = Field(default_factory=list)


class AuthLoginRequest(BaseModel):
    username: str
    password: str
    remote_base_url: Optional[str] = None


class TestPhase1IntentRequest(BaseModel):
    """用于直接测试 Phase1 意图的请求模型（跳过 NLU）。"""

    intent: str
    text: str = ""
    slots: Dict[str, Any] = Field(default_factory=dict)


class TestPhase1IntentResponse(BaseModel):
    """测试 Phase1 意图的响应模型。"""

    success: bool
    reply: str
    missing_slots: List[str] = Field(default_factory=list)
    action_logs: List[dict] = Field(default_factory=list)
    error: Optional[str] = None


class DebugApplyActionRequest(BaseModel):
    text: str = ""
    intent: str = ""
    slots: Dict[str, Any] = Field(default_factory=dict)
    status: str = "success"
    intent_confidence: float = 1.0
    entities: Dict[str, Any] = Field(default_factory=dict)
    missing_slots: List[str] = Field(default_factory=list)
    clear_pending: bool = False
    pending_only: bool = False


class DebugApplyActionResponse(BaseModel):
    reply: str
    intent: str
    normalized_intent: str
    confidence: float
    slots: dict
    missing_slots: List[str]
    action_log: List[dict] = Field(default_factory=list)
    diagnostics: List[dict] = Field(default_factory=list)
    pending_action: Optional[dict] = None
    applied: bool = False


class CreateScheduleRequest(BaseModel):
    name: str
    pass
