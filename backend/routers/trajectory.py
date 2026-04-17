"""Trajectory retrieval endpoints."""
import json
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

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


@router.get("/export/all")
async def export_all_trajectories():
    """Export all trajectories from PostgreSQL or JSON files."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        import pg8000
        import urllib.parse
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        p = urllib.parse.urlparse(database_url)
        conn = pg8000.connect(
            host=p.hostname, port=p.port or 5432,
            database=p.path.lstrip("/"), user=p.username,
            password=p.password, ssl_context=False,
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT data FROM trajectories ORDER BY updated_at DESC")
            rows = cur.fetchall()
        finally:
            conn.close()
        data = [json.loads(row[0]) for row in rows]
    else:
        from pathlib import Path
        traj_dir = Path(os.getenv("TRAJECTORY_DIR", "./data/trajectories"))
        data = []
        for f in sorted(traj_dir.glob("*.json")):
            data.append(json.loads(f.read_text(encoding="utf-8")))

    return JSONResponse(content=data, headers={
        "Content-Disposition": "attachment; filename=trajectories.json"
    })


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
