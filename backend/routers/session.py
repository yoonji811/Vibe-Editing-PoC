"""Session management endpoints."""
import asyncio
import base64
import hashlib
import uuid
from datetime import datetime

import cv2
import numpy as np
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

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
from services.trajectory_store import append_event, save_trajectory, load_trajectory
from services import image_store, gemini_editor
from agents.orchestrator import OrchestratorAgent

_orchestrator = OrchestratorAgent()

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


def _upload_and_record(session_id: str, b64: str, trajectory: Trajectory, filename: str, size_bytes: int, w: int, h: int, root_edit_id: str | None = None):
    """Background task: upload to Cloudinary and update trajectory."""
    original_url = image_store.upload_image(b64, f"{session_id}/original")
    event = TrajectoryEvent(
        type="image_upload",
        payload=TrajectoryEventPayload(
            filename=filename,
            size_bytes=size_bytes,
            width=w,
            height=h,
            image_url=original_url,
            edit_id=root_edit_id,
        ),
    )
    append_event(trajectory, event)


@router.post("/new", response_model=SessionCreateResponse)
async def create_session(
    background_tasks: BackgroundTasks,
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

    # Register root node in edit tree
    root_edit_id = _orchestrator.register_root_image(session_id, b64)

    session = SessionState(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=now,
        current_image_b64=b64,
        current_edit_id=root_edit_id,
        edit_history=[b64],
        trajectory=trajectory,
        original_filename=filename,
    )
    store.set_session(session_id, session)

    # Cloudinary upload in background — does not block the response
    background_tasks.add_task(
        _upload_and_record, session_id, b64, trajectory, filename, len(raw), w, h, root_edit_id
    )

    return SessionCreateResponse(
        session_id=session_id,
        created_at=now,
        original_image_b64=b64,
        width=w,
        height=h,
        filename=filename,
    )


def _upload_and_record_generated(session_id: str, b64: str, trajectory: Trajectory, filename: str, size_bytes: int, w: int, h: int, prompt: str, root_edit_id: str | None = None):
    """Background task: upload generated image to Cloudinary and update trajectory."""
    original_url = image_store.upload_image(b64, f"{session_id}/original")
    event = TrajectoryEvent(
        type="image_upload",
        payload=TrajectoryEventPayload(
            filename=filename,
            size_bytes=size_bytes,
            width=w,
            height=h,
            image_url=original_url,
            user_text=prompt,
            edit_id=root_edit_id,
        ),
    )
    append_event(trajectory, event)


@router.post("/generate", response_model=SessionCreateResponse)
async def generate_session(
    background_tasks: BackgroundTasks,
    prompt: str = Form(...),
    user_nickname: str = Form(...),
):
    """Generate an image from text and start a new session."""
    b64, err_msg = gemini_editor.generate_image(prompt)
    if not b64:
        raise HTTPException(status_code=500, detail=err_msg or "이미지 생성 실패. 다시 시도해주세요.")

    # Decode generated image to get dimensions
    import numpy as np
    import cv2
    img_data = base64.b64decode(b64)
    arr = np.frombuffer(img_data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=500, detail="생성된 이미지를 처리할 수 없습니다.")
    h, w = img.shape[:2]
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    b64 = base64.b64encode(buf).decode("utf-8")

    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    filename = f"generated_{session_id[:8]}.jpg"

    img_info = OriginalImageInfo(
        filename=filename,
        size_bytes=len(buf),
        width=w,
        height=h,
        mime_type="image/jpeg",
    )
    trajectory = Trajectory(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=now,
        updated_at=now,
        original_image=img_info,
    )
    # Register root node in edit tree
    root_edit_id = _orchestrator.register_root_image(session_id, b64)

    session = SessionState(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=now,
        current_image_b64=b64,
        current_edit_id=root_edit_id,
        edit_history=[b64],
        trajectory=trajectory,
        original_filename=filename,
    )
    store.set_session(session_id, session)

    # Cloudinary upload in background — does not block the response
    background_tasks.add_task(
        _upload_and_record_generated, session_id, b64, trajectory, filename, len(buf), w, h, prompt, root_edit_id
    )

    return SessionCreateResponse(
        session_id=session_id,
        created_at=now,
        original_image_b64=b64,
        width=w,
        height=h,
        filename=filename,
    )


def _truncate_events_to_step(events: list, step_idx: int) -> list:
    """Keep only trajectory events up to step_idx.
    step_idx=0 → original image only; step_idx=N → N edits applied."""
    result = []
    completed_pairs = 0
    for ev in events:
        ev_type = ev.type
        if ev_type == "image_upload":
            result.append(ev)
        elif ev_type == "chat_input":
            if completed_pairs < step_idx:
                result.append(ev)
        elif ev_type == "edit_applied":
            if completed_pairs < step_idx:
                result.append(ev)
                completed_pairs += 1
        # skip image_saved / undo / session_end — not needed when restoring
    return result


@router.post("/restore/{session_id}", response_model=SessionCreateResponse)
async def restore_session(
    session_id: str,
    image_url: str = Form(...),
    user_nickname: str = Form(...),
    step_idx: int = Form(...),
):
    """Restore an existing session at a specific step for continued editing.
    The trajectory is truncated to that step and re-saved so the new edit
    appends to the original session rather than creating a new one."""
    # Load trajectory from persistent storage (fall back to in-memory)
    from services.trajectory_store import save_trajectory as _save_traj
    traj = load_trajectory(session_id)
    if not traj:
        existing = store.get_session(session_id)
        if existing and existing.trajectory:
            traj = existing.trajectory
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    # Download image at the selected step
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient() as client:
            resp = await client.get(image_url, follow_redirects=True, timeout=15.0)
            resp.raise_for_status()
        raw = resp.content
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch image: {exc}")

    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    try:
        b64, w, h = _decode_upload(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Truncate events to the chosen step and persist
    traj.events = _truncate_events_to_step(traj.events, step_idx)
    _save_traj(traj)

    # Restore session in memory under the ORIGINAL session_id
    filename = traj.original_image.filename if traj.original_image else "restored.jpg"

    # Reset orchestrator state and register root for this restored session
    _orchestrator.reset_session(session_id)
    root_edit_id = _orchestrator.register_root_image(session_id, b64)

    session = SessionState(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=traj.created_at,
        current_image_b64=b64,
        current_edit_id=root_edit_id,
        edit_history=[b64],
        trajectory=traj,
        original_filename=filename,
    )
    store.set_session(session_id, session)

    return SessionCreateResponse(
        session_id=session_id,
        created_at=traj.created_at,
        original_image_b64=b64,
        width=w,
        height=h,
        filename=filename,
    )


@router.post("/resume-edit/{session_id}")
async def resume_and_edit(
    session_id: str,
    image_url: str = Form(...),
    user_nickname: str = Form(...),
    step_idx: int = Form(...),
    user_text: str = Form(...),
):
    """Restore an existing session at a specific step AND apply one edit atomically.
    Combining restore + edit into a single request eliminates any inter-request
    timing issues (e.g. session not found in memory between two calls)."""
    from services.trajectory_store import save_trajectory as _save_traj

    # 1. Load trajectory
    traj = load_trajectory(session_id)
    if not traj:
        existing = store.get_session(session_id)
        if existing and existing.trajectory:
            traj = existing.trajectory
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    # 2. Download image at the selected step
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient() as client:
            resp = await client.get(image_url, follow_redirects=True, timeout=15.0)
            resp.raise_for_status()
        raw = resp.content
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch image: {exc}")

    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    try:
        b64, w, h = _decode_upload(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 3. Truncate trajectory to selected step and persist
    traj.events = _truncate_events_to_step(traj.events, step_idx)
    _save_traj(traj)

    # 4. Set up session in memory
    filename = traj.original_image.filename if traj.original_image else "restored.jpg"

    # Reset orchestrator state and register root for this restored session
    _orchestrator.reset_session(session_id)
    root_edit_id = _orchestrator.register_root_image(session_id, b64)

    session_obj = SessionState(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=traj.created_at,
        current_image_b64=b64,
        current_edit_id=root_edit_id,
        edit_history=[b64],
        trajectory=traj,
        original_filename=filename,
    )
    store.set_session(session_id, session_obj)

    # 5. Run the edit inline (same logic as edit.py, avoids cross-request session lookup)
    from routers.edit import _edit_image
    from models.schemas import EditRequest
    req = EditRequest(user_text=user_text)
    edit_result = await _edit_image(session_id, req)

    return {
        "session_id": session_id,
        "original_image_b64": b64,
        "created_at": traj.created_at.isoformat(),
        "width": w,
        "height": h,
        "filename": filename,
        "result_image_b64": edit_result.result_image_b64,
        "chat_message": edit_result.chat_message,
        "intent": edit_result.intent,
        "engine": edit_result.engine,
        "operation": edit_result.operation,
        "params": edit_result.params,
        "latency_ms": edit_result.latency_ms,
    }


@router.post("/resume", response_model=SessionCreateResponse)
async def resume_session(
    image_url: str = Form(...),
    user_nickname: str = Form(...),
):
    """Create a new session by resuming from an existing image URL."""
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient() as client:
            resp = await client.get(image_url, follow_redirects=True, timeout=15.0)
            resp.raise_for_status()
        raw = resp.content
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch image: {exc}")

    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    try:
        b64, w, h = _decode_upload(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    filename = f"resumed_{session_id[:8]}.jpg"

    original_url = image_store.upload_image(b64, f"{session_id}/original")

    img_info = OriginalImageInfo(
        filename=filename,
        size_bytes=len(raw),
        width=w,
        height=h,
        mime_type="image/jpeg",
    )
    trajectory = Trajectory(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=now,
        updated_at=now,
        original_image=img_info,
    )
    # Register root node in edit tree
    root_edit_id = _orchestrator.register_root_image(session_id, b64)

    session = SessionState(
        session_id=session_id,
        user_nickname=user_nickname,
        created_at=now,
        current_image_b64=b64,
        current_edit_id=root_edit_id,
        edit_history=[b64],
        trajectory=trajectory,
        original_filename=filename,
    )
    store.set_session(session_id, session)

    event = TrajectoryEvent(
        type="image_upload",
        payload=TrajectoryEventPayload(
            filename=filename,
            size_bytes=len(raw),
            width=w,
            height=h,
            image_url=original_url,
            edit_id=root_edit_id,
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
