"""Edit endpoint — routes user requests through the multi-agent pipeline."""
import hashlib
import logging
import traceback
import uuid

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
from agents.orchestrator import OrchestratorAgent
from services import image_store
from services.trajectory_store import append_event

router = APIRouter(prefix="/api/edit", tags=["edit"])

MAX_HISTORY = 50

_orchestrator = OrchestratorAgent()


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

    session.chat_history.append(ChatMessage(role="user", content=user_text))
    append_event(
        session.trajectory,
        TrajectoryEvent(
            type="chat_input",
            payload=TrajectoryEventPayload(
                user_text=user_text,
                selected_recommendation_index=req.selected_recommendation_index,
            ),
        ),
    )

    result_b64: str | None = None
    edit_id: str | None = None
    parent_edit_id: str | None = None
    intent: str = "agent"
    engine: str | None = "agent"
    operation: str | None = None
    params: dict | None = None
    response_text: str = ""
    error_msg: str | None = None
    latency_ms: int = 0
    plan: dict | None = None
    validator_verdict: dict | None = None
    validator_attempts: int | None = None
    quality_verdict: dict | None = None
    step_logs: list | None = None

    # --- All requests go through the agent pipeline ---
    # Undo/reset are handled as tools by the Planner, not keyword matching.
    agent_result = _orchestrator.process_edit(
        prompt=user_text,
        image_b64=source_image,
        session_id=session_id,
        base_edit_id=req.base_edit_id or session.current_edit_id,
    )

    latency_ms = agent_result.get("latency_ms", 0) or 0
    executed_plan = agent_result.get("executed_plan") or {}
    errors = agent_result.get("errors", [])

    # Check if the plan used undo/reset tools (intercepted by orchestrator)
    session_action = agent_result.get("session_action")
    if session_action == "undo":
        intent = "session_action"
        operation = "undo"
        result_b64 = agent_result.get("result_image_b64") or session.current_image_b64
        response_text = agent_result.get("explanation", "이전 상태로 되돌렸습니다.")
        edit_id = agent_result.get("edit_id")
        parent_edit_id = agent_result.get("parent_edit_id")
    elif session_action == "reset":
        intent = "session_action"
        operation = "reset"
        result_b64 = agent_result.get("result_image_b64") or session.current_image_b64
        response_text = agent_result.get("explanation", "원본 이미지로 초기화했습니다.")
        edit_id = agent_result.get("edit_id")
        parent_edit_id = agent_result.get("parent_edit_id")
    else:
        intent = executed_plan.get("intent", "agent")
        response_text = agent_result.get("explanation", "")
        plan = executed_plan
        validator_verdict = agent_result.get("validator_verdict")
        validator_attempts = agent_result.get("validator_attempts")
        quality_verdict = agent_result.get("quality_verdict")
        step_logs = agent_result.get("step_logs")
        edit_id = agent_result.get("edit_id")
        parent_edit_id = agent_result.get("parent_edit_id")

        steps = executed_plan.get("steps", [])
        if steps:
            operation = steps[0].get("tool_name")
            params = steps[0].get("params")

        if agent_result.get("result_image_b64"):
            result_b64 = agent_result["result_image_b64"]
        else:
            result_b64 = session.current_image_b64
            error_msg = "; ".join(errors) if errors else "agent returned no image"
            if not response_text:
                response_text = "편집을 처리할 수 없습니다. 다시 시도해주세요."

    # --- Update session ---
    image_changed = result_b64 and result_b64 != session.current_image_b64
    if image_changed:
        session.current_image_b64 = result_b64
        session.edit_history.append(result_b64)
        if len(session.edit_history) > MAX_HISTORY:
            session.edit_history = session.edit_history[-MAX_HISTORY:]
    if edit_id:
        session.current_edit_id = edit_id

    result_url: str | None = None
    if image_changed and result_b64:
        step = len(session.edit_history)
        result_url = image_store.upload_image(
            result_b64, f"{session_id}/edit_{step:03d}"
        )

    session.chat_history.append(ChatMessage(role="assistant", content=response_text))

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
                edit_id=edit_id,
                parent_edit_id=parent_edit_id,
                plan=plan,
                validator_verdict=validator_verdict,
                validator_attempts=validator_attempts,
                quality_verdict=quality_verdict,
                orchestrator_step_logs=step_logs,
            ),
        ),
    )

    store.set_session(session_id, session)

    return EditResponse(
        session_id=session_id,
        edit_id=edit_id,
        parent_edit_id=parent_edit_id,
        result_image_b64=result_b64,
        chat_message=response_text,
        intent=intent,
        engine=engine,
        operation=operation,
        params=params,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Tree navigation endpoints
# ---------------------------------------------------------------------------

@router.post("/{session_id}/undo")
async def undo_edit(session_id: str):
    """Move the tree cursor to the parent node (undo)."""
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _orchestrator.undo(session_id)
    if not result:
        return {"ok": False, "message": "되돌릴 편집 이력이 없습니다."}

    session.current_image_b64 = result["image_b64"]
    session.current_edit_id = result["edit_id"]
    store.set_session(session_id, session)

    return {
        "ok": True,
        "edit_id": result["edit_id"],
        "image_b64": result["image_b64"],
        "message": "이전 상태로 되돌렸습니다.",
    }


@router.post("/{session_id}/navigate")
async def navigate_edit(session_id: str, body: dict):
    """Move the tree cursor to any node."""
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    edit_id = body.get("edit_id")
    if not edit_id:
        raise HTTPException(status_code=400, detail="edit_id is required")

    result = _orchestrator.navigate(session_id, edit_id)
    if not result:
        raise HTTPException(status_code=404, detail="Edit node not found")

    session.current_image_b64 = result["image_b64"]
    session.current_edit_id = result["edit_id"]
    store.set_session(session_id, session)

    return {
        "ok": True,
        "edit_id": result["edit_id"],
        "image_b64": result["image_b64"],
    }


@router.get("/{session_id}/tree")
async def get_edit_tree(session_id: str):
    """Return the full edit tree for a session."""
    return _orchestrator.get_tree(session_id)
