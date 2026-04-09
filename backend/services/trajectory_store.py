"""Persist trajectory events — PostgreSQL if DATABASE_URL is set, else JSON files."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from models.schemas import Trajectory, TrajectoryEvent

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL")
if _DATABASE_URL and _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
_TRAJECTORY_DIR = Path(os.getenv("TRAJECTORY_DIR", "./data/trajectories"))

# ---------------------------------------------------------------------------
# PostgreSQL backend
# ---------------------------------------------------------------------------

def _get_conn():
    import pg8000
    import urllib.parse
    p = urllib.parse.urlparse(_DATABASE_URL)
    return pg8000.connect(
        host=p.hostname,
        port=p.port or 5432,
        database=p.path.lstrip("/"),
        user=p.username,
        password=p.password,
        ssl_context=True,
    )


def _ensure_table() -> None:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trajectories (
                session_id TEXT PRIMARY KEY,
                data       TEXT         NOT NULL,
                updated_at TIMESTAMP    NOT NULL DEFAULT NOW()
            )
        """)
        conn.commit()
    finally:
        conn.close()


_table_ready = False


def _init_once() -> None:
    global _table_ready
    if not _table_ready:
        _ensure_table()
        _table_ready = True


def _pg_save(trajectory: Trajectory) -> None:
    _init_once()
    trajectory.updated_at = datetime.utcnow()
    payload = json.dumps(trajectory.model_dump(mode="json"), default=str)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trajectories (session_id, data, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (session_id) DO UPDATE
                SET data = EXCLUDED.data,
                    updated_at = NOW()
        """, (trajectory.session_id, payload))
        conn.commit()
    finally:
        conn.close()


def _pg_load(session_id: str) -> Optional[Trajectory]:
    _init_once()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM trajectories WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return Trajectory(**json.loads(row[0]))


# ---------------------------------------------------------------------------
# JSON file backend (local dev fallback)
# ---------------------------------------------------------------------------

def _json_path(session_id: str) -> Path:
    _TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)
    return _TRAJECTORY_DIR / f"{session_id}.json"


def _json_save(trajectory: Trajectory) -> None:
    trajectory.updated_at = datetime.utcnow()
    with open(_json_path(trajectory.session_id), "w", encoding="utf-8") as f:
        json.dump(trajectory.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)


def _json_load(session_id: str) -> Optional[Trajectory]:
    path = _json_path(session_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return Trajectory(**json.load(f))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_trajectory(trajectory: Trajectory) -> None:
    if _DATABASE_URL:
        _pg_save(trajectory)
    else:
        _json_save(trajectory)


def load_trajectory(session_id: str) -> Optional[Trajectory]:
    if _DATABASE_URL:
        return _pg_load(session_id)
    return _json_load(session_id)


def append_event(trajectory: Trajectory, event: TrajectoryEvent) -> None:
    trajectory.events.append(event)
    save_trajectory(trajectory)
