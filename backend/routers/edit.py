"""Edit endpoint — routes user text to opencv or gemini."""
import hashlib
import logging
import time
import traceback
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

from models.schemas import (
    ChatMessage,
    EditRequest,
    EditResponse,
    TrajectoryEvent,
    TrajectoryEventPayload,
)
import store
from services import intent_router, opencv_editor, gemini_editor, image_store
from services.trajectory_store import append_event

router = APIRouter(prefix="/api/edit", tags=["edit"])

MAX_HISTORY = 50


def _image_hash(b64: str) -> str:
    return hashlib.sha256(b64.encode()).hexdigest()[:16]


@router.post("/{session_id}")
async def edit_image(session_id: str, req: EditRequest):
    try:
        return await _edit_image(session_id, req)
    except HTTPException:
        raise
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Unhandled error in edit_image:\n%s", tb)
        return JSONResponse(status_code=500, content={"detail": str(exc), "traceback": tb})


async def _edit_image(session_id: str, req: EditRequest):
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.current_image_b64:
        raise HTTPException(status_code=400, detail="No image in session")

    user_text = req.user_text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="user_text is empty")

    # Use provided image as source (viewer-driven edit), else use session's latest
    source_image = req.input_image_b64 or session.current_image_b64

    # Record chat input
    session.chat_history.append(ChatMessage(role="user", content=user_text))
    append_event(
        session.trajectory,
        TrajectoryEvent(
            type="chat_input",
            payload=TrajectoryEventPayload(user_text=user_text),
        ),
    )

    # --- Intent classification ---
    t0 = time.time()
    classification = intent_router.classify_intent(user_text, session.chat_history)
    intent = classification.get("intent", "clarify")
    operation = classification.get("operation")
    params = classification.get("params", {}) or {}
    response_text = classification.get("response_text", "")

    result_b64: str | None = None
    engine: str | None = None
    error_msg: str | None = None

    # --- Session actions ---
    if intent == "session_action":
        if operation == "undo":
            if len(session.edit_history) > 1:
                session.edit_history.pop()
                session.current_image_b64 = session.edit_history[-1]
                response_text = response_text or "이전 상태로 되돌렸습니다."
            else:
                response_text = "되돌릴 편집 이력이 없습니다."
        elif operation == "reset":
            session.current_image_b64 = session.edit_history[0]
            session.edit_history = [session.edit_history[0]]
            response_text = response_text or "원본 이미지로 초기화했습니다."
        result_b64 = session.current_image_b64

    # --- OpenCV edit ---
    elif intent == "opencv" and operation:
        try:
            result_b64 = opencv_editor.apply_edit(source_image, operation, params)
            engine = "opencv"
        except Exception as exc:
            error_msg = str(exc)
            response_text = f"편집 중 오류가 발생했습니다: {exc}"
            result_b64 = source_image

    # --- Gemini generative edit ---
    elif intent == "gemini_generative" and operation:
        result_b64, gemini_text = gemini_editor.edit_image(
            source_image, user_text, operation
        )
        engine = "gemini"
        if result_b64 is None:
            # Fallback: keep current image, show explanation
            result_b64 = session.current_image_b64
            response_text = gemini_text
            error_msg = "gemini returned no image"
        else:
            response_text = gemini_text or response_text

    # --- Clarify ---
    else:
        result_b64 = source_image
        response_text = response_text or "어떤 편집을 원하시나요?"

    latency_ms = int((time.time() - t0) * 1000)

    # Update session history
    image_changed = result_b64 and result_b64 != session.current_image_b64
    if image_changed:
        session.current_image_b64 = result_b64
        session.edit_history.append(result_b64)
        if len(session.edit_history) > MAX_HISTORY:
            session.edit_history = session.edit_history[-MAX_HISTORY:]

    # Upload result image to Cloudinary (only when image actually changed)
    result_url: str | None = None
    if image_changed and result_b64:
        event_id = str(uuid.uuid4())
        step = len(session.edit_history)
        result_url = image_store.upload_image(
            result_b64, f"{session_id}/edit_{step:03d}"
        )
    else:
        event_id = str(uuid.uuid4())

    # Add assistant reply to chat history
    session.chat_history.append(ChatMessage(role="assistant", content=response_text))

    # Persist trajectory event
    append_event(
        session.trajectory,
        TrajectoryEvent(
            type="edit_applied",
            payload=TrajectoryEventPayload(
                user_text=user_text,
                intent_classified=intent,
                engine_used=engine,
                params=params,
                result_image_hash=_image_hash(result_b64) if result_b64 else None,
                image_url=result_url,
                latency_ms=latency_ms,
                error=error_msg,
            ),
        ),
    )

    store.set_session(session_id, session)

    return EditResponse(
        session_id=session_id,
        result_image_b64=result_b64,
        chat_message=response_text,
        intent=intent,
        engine=engine,
        operation=operation,
        params=params,
        latency_ms=latency_ms,
    )
