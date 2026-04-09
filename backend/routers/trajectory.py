"""Trajectory retrieval endpoints."""
from fastapi import APIRouter, HTTPException

from models.schemas import Trajectory, TrajectoryEvent, TrajectoryEventPayload
import store
from services.trajectory_store import load_trajectory, save_trajectory, append_event

router = APIRouter(prefix="/api/trajectory", tags=["trajectory"])


@router.get("/{session_id}", response_model=Trajectory)
async def get_trajectory(session_id: str):
    """Return the full trajectory JSON for a session."""
    session = store.get_session(session_id)
    if session and session.trajectory:
        return session.trajectory

    # Fallback: load from disk
    traj = load_trajectory(session_id)
    if not traj:
        raise HTTPException(status_code=404, detail="Trajectory not found")
    return traj


@router.post("/{session_id}/save")
async def record_save(session_id: str):
    """Record that the user explicitly saved the image."""
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    event = TrajectoryEvent(
        type="image_saved",
        payload=TrajectoryEventPayload(filename=f"{session_id}_saved.jpg"),
    )
    append_event(session.trajectory, event)
    return {"status": "saved", "session_id": session_id}
