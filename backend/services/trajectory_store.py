"""Persist trajectory events to JSON files."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from models.schemas import Trajectory, TrajectoryEvent

load_dotenv()

_TRAJECTORY_DIR = Path(os.getenv("TRAJECTORY_DIR", "./data/trajectories"))


def _get_path(session_id: str) -> Path:
    _TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)
    return _TRAJECTORY_DIR / f"{session_id}.json"


def save_trajectory(trajectory: Trajectory) -> None:
    trajectory.updated_at = datetime.utcnow()
    path = _get_path(trajectory.session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            trajectory.model_dump(mode="json"),
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


def load_trajectory(session_id: str) -> Optional[Trajectory]:
    path = _get_path(session_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Trajectory(**data)


def append_event(trajectory: Trajectory, event: TrajectoryEvent) -> None:
    """Append an event and persist to disk."""
    trajectory.events.append(event)
    save_trajectory(trajectory)
