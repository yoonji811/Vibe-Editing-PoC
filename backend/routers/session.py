"""Session management endpoints."""
import base64
import hashlib
import uuid
from datetime import datetime

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from models.schemas import (
    ChatMessage,
    OriginalImageInfo,
    SessionCreateResponse,
    SessionInfoResponse,
    SessionState,
    Trajectory,
    TrajectoryEvent,
    TrajectoryEventPayload,
)
import store
from services.trajectory_store import append_event, save_trajectory
from services import image_store

router = APIRouter(prefix="/api/session", tags=["session"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def _decode_upload(data: bytes) -> tuple[str, int, int]:
    """Decode raw bytes → (base64_str, width, height)."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Cannot decode image")
    h, w = img.shape[:2]
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    b64 = base64.b64encode(buf).decode("utf-8")
    return b64, w, h


@router.post("/new", response_model=SessionCreateResponse)
async def create_session(
    file: UploadFile = File(...),
    user_nickname: str = Form(...),
):
    """Upload an image and start a new session."""
    raw = await file.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    try:
        b64, w, h = _decode_upload(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    mime = file.content_type or "image/jpeg"
    filename = file.filename or "upload.jpg"

    # Upload original image to Cloudinary
    original_url = image_store.upload_image(b64, f"{session_id}/original")

    img_info = OriginalImageInfo(
        filename=filename,
        size_bytes=len(raw),
        width=w,
        height=h,
        mime_type=mime,
    )
    trajectory = Trajectory(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=now,
        updated_at=now,
        original_image=img_info,
    )

    session = SessionState(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=now,
        current_image_b64=b64,
        edit_history=[b64],
        trajectory=trajectory,
        original_filename=filename,
    )
    store.set_session(session_id, session)

    # Record upload event
    event = TrajectoryEvent(
        type="image_upload",
        payload=TrajectoryEventPayload(
            filename=filename,
            size_bytes=len(raw),
            width=w,
            height=h,
            image_url=original_url,
        ),
    )
    append_event(trajectory, event)

    return SessionCreateResponse(
        session_id=session_id,
        created_at=now,
        original_image_b64=b64,
        width=w,
        height=h,
        filename=filename,
    )


@router.get("/{session_id}", response_model=SessionInfoResponse)
async def get_session(session_id: str):
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionInfoResponse(
        session_id=session.session_id,
        created_at=session.created_at,
        current_image_b64=session.current_image_b64,
        edit_count=len(session.edit_history) - 1,  # exclude original
        chat_history=session.chat_history,
    )
