"""Feedback router — explicit user feedback collection (thumbs up/down).

POST /api/feedback/{session_id}
  - Updates satisfaction_score and feedback_type on the target trajectory event.
  - Triggers async Memory Agent indexing if satisfaction_score >= 0.8.
"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException

from models.schemas import FeedbackRequest
from services.trajectory_store import load_trajectory, update_event_feedback

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def _async_index(session_id: str, event_id: str, plan: dict, user_text: str,
                 vlm_context: dict, satisfaction_score: float) -> None:
    """Background task: index successful edit in Memory Agent."""
    try:
        from agents.memory_agent import MemoryAgent
        agent = MemoryAgent()
        agent.index_success(
            event_id=event_id,
            session_id=session_id,
            user_text=user_text,
            vlm_context=vlm_context,
            plan=plan,
            satisfaction_score=satisfaction_score,
            is_correction=False,
        )
    except Exception as exc:
        logger.warning("Background memory indexing failed: %s", exc)


@router.post("/{session_id}")
async def record_feedback(session_id: str, body: FeedbackRequest):
    """Record explicit user feedback for an edit event.

    - thumbs_up  → reward_score=1.0  → indexes in Memory Agent (async)
    - thumbs_down → reward_score=-1.0 → marks event as unsatisfactory
    """
    # Update in-memory session first (prevents endSession from overwriting feedback)
    import store as _store
    mem_session = _store.get_session(session_id)
    mem_updated = False
    if mem_session and mem_session.trajectory:
        for event in mem_session.trajectory.events:
            if event.event_id == body.target_event_id:
                event.payload.satisfaction_score = body.reward_score
                event.payload.feedback_type = body.feedback_type
                _store.set_session(session_id, mem_session)
                mem_updated = True
                break

    # Also persist to disk/DB
    updated = update_event_feedback(
        session_id=session_id,
        event_id=body.target_event_id,
        satisfaction_score=body.reward_score,
        feedback_type=body.feedback_type,
    )
    if not updated and not mem_updated:
        raise HTTPException(
            status_code=404,
            detail=f"Event {body.target_event_id} not found in session {session_id}",
        )

    # Re-index in Memory Agent with updated score (always, so score is kept fresh)
    trajectory = load_trajectory(session_id)
    if trajectory:
        for event in trajectory.events:
            if event.event_id == body.target_event_id:
                p = event.payload
                threading.Thread(
                    target=_async_index,
                    args=(session_id, body.target_event_id,
                          p.plan or {}, p.user_text or "",
                          p.source_image_context or {}, body.reward_score),
                    daemon=True,
                ).start()
                break

    return {
        "status": "ok",
        "session_id": session_id,
        "event_id": body.target_event_id,
        "reward_score": body.reward_score,
        "action": body.action,
    }
