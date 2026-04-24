"""Trajectory retrieval endpoints."""
import json
import logging
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

from models.schemas import Trajectory, TrajectoryEvent, TrajectoryEventPayload
import store
from services.trajectory_store import load_trajectory, save_trajectory, append_event

router = APIRouter(prefix="/api/trajectory", tags=["trajectory"])


def _db_connect():
    import pg8000
    import urllib.parse
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    p = urllib.parse.urlparse(database_url)
    return pg8000.connect(
        host=p.hostname, port=p.port or 5432,
        database=p.path.lstrip("/"), user=p.username,
        password=p.password, ssl_context=False,
    )


@router.get("/by-nickname/{nickname}")
async def get_sessions_by_nickname(nickname: str):
    """Return session summaries for a given nickname, oldest first, excluding empty sessions."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            conn = _db_connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT data FROM trajectories WHERE data::jsonb->>'user_nickname' = %s ORDER BY updated_at ASC",
                    (nickname,),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
            raw_list = [json.loads(row[0]) for row in rows]
        except Exception as e:
            logger.error("DB query failed in get_sessions_by_nickname: %s", e)
            return []
    else:
        from pathlib import Path
        traj_dir = Path(os.getenv("TRAJECTORY_DIR", "./data/trajectories"))
        raw_list = []
        for f in traj_dir.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("user_nickname") == nickname:
                raw_list.append(data)
        raw_list.sort(key=lambda t: t.get("updated_at", t.get("created_at", "")))

    sessions = []
    for traj in raw_list:
        events = traj.get("events", [])
        # Count any chat interaction (edit_applied always recorded, even for clarify)
        edit_count = sum(1 for ev in events if ev.get("type") == "edit_applied")
        if edit_count == 0:
            continue

        # First chat_input user_text as summary, fallback to filename
        summary = (traj.get("original_image") or {}).get("filename", "Untitled")
        for ev in events:
            if ev.get("type") == "chat_input" and ev.get("payload", {}).get("user_text"):
                summary = ev["payload"]["user_text"]
                break

        sessions.append({
            "session_id": traj["session_id"],
            "created_at": traj.get("created_at", ""),
            "updated_at": traj.get("updated_at", traj.get("created_at", "")),
            "summary": summary[:60],
            "edit_count": edit_count,
        })
    return sessions


@router.get("/export/all")
async def export_all_trajectories():
    """Export all trajectories from PostgreSQL or JSON files."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        conn = _db_connect()
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


@router.get("/{session_id}", response_model=Trajectory)
async def get_trajectory(session_id: str):
    """Return the full trajectory JSON for a session."""
    session = store.get_session(session_id)
    if session and session.trajectory:
        return session.trajectory

    traj = load_trajectory(session_id)
    if not traj:
        raise HTTPException(status_code=404, detail="Trajectory not found")
    return traj


@router.post("/{session_id}/end")
async def end_session(session_id: str):
    """Force-save the in-memory trajectory before the client resets state.
    Called by the frontend when the user starts a new session or navigates away.
    Returns 200 even if the session isn't in memory (idempotent)."""
    session = store.get_session(session_id)
    if session and session.trajectory:
        save_trajectory(session.trajectory)
    return {"status": "ok", "session_id": session_id}



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
