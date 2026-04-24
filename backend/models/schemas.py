from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------

class OriginalImageInfo(BaseModel):
    filename: str
    size_bytes: int
    width: int
    height: int
    mime_type: str


class TrajectoryEventPayload(BaseModel):
    user_text: Optional[str] = None
    intent_classified: Optional[str] = None
    engine_used: Optional[str] = None  # "opencv" | "gemini" | None
    model_used: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result_image_hash: Optional[str] = None
    image_url: Optional[str] = None  # Cloudinary URL
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    # image_upload specific
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    # agent pipeline details
    plan: Optional[Dict[str, Any]] = None
    validator_verdict: Optional[Dict[str, Any]] = None
    validator_attempts: Optional[int] = None
    quality_verdict: Optional[Dict[str, Any]] = None
    orchestrator_step_logs: Optional[List[Dict[str, Any]]] = None
    # V2: VLM analysis + feedback
    source_image_context: Optional[Dict[str, Any]] = None
    satisfaction_score: Optional[float] = None
    feedback_type: Optional[str] = None  # "explicit" | "implicit"
    is_correction: Optional[bool] = None  # True if prompt was a correction of prior edit
    timing_ms: Optional[Dict[str, int]] = None  # {vlm, memory, planner, validator, tool_exec, total}
    # prompt recommendations
    recommendations: Optional[List[Dict[str, Any]]] = None
    selected_recommendation_index: Optional[int] = None


class TrajectoryEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    type: str  # image_upload | chat_input | edit_applied | image_saved | undo | session_end
    payload: TrajectoryEventPayload


class Trajectory(BaseModel):
    session_id: str
    user_nickname: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    original_image: Optional[OriginalImageInfo] = None
    events: List[TrajectoryEvent] = []


# ---------------------------------------------------------------------------
# Session (in-memory)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SessionState(BaseModel):
    session_id: str
    user_nickname: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    current_image_b64: Optional[str] = None
    edit_history: List[str] = []      # base64 images, max 50
    chat_history: List[ChatMessage] = []
    trajectory: Optional[Trajectory] = None
    original_filename: str = ""


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------

class SessionCreateResponse(BaseModel):
    session_id: str
    created_at: datetime
    original_image_b64: str
    width: int
    height: int
    filename: str


class SessionInfoResponse(BaseModel):
    session_id: str
    created_at: datetime
    current_image_b64: Optional[str]
    edit_count: int
    chat_history: List[ChatMessage]


class EditRequest(BaseModel):
    user_text: str
    input_image_b64: Optional[str] = None  # If set, use this as source instead of session.current_image_b64
    selected_recommendation_index: Optional[int] = None


class EditResponse(BaseModel):
    session_id: str
    event_id: Optional[str] = None
    result_image_b64: Optional[str] = None
    chat_message: str
    intent: str
    engine: Optional[str] = None
    operation: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    latency_ms: int
    timing_ms: Optional[Dict[str, int]] = None


class FeedbackRequest(BaseModel):
    target_event_id: str
    feedback_type: str = "explicit"   # "explicit" | "implicit"
    action: str                        # "thumbs_up" | "thumbs_down" | "re_prompt"
    reward_score: float                # 1.0 (positive) | -0.5 (correction) | -1.0 (negative)
