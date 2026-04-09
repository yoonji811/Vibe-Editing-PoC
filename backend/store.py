"""In-memory session store (module-level singleton)."""
from typing import Dict, Optional

from models.schemas import SessionState

_sessions: Dict[str, SessionState] = {}


def get_session(session_id: str) -> Optional[SessionState]:
    return _sessions.get(session_id)


def set_session(session_id: str, session: SessionState) -> None:
    _sessions[session_id] = session


def delete_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def all_session_ids():
    return list(_sessions.keys())
