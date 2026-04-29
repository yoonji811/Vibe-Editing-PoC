"""Prompt recommendation endpoint.

Analyzes the current session image with Gemini vision and returns
3 diverse, image-specific editing suggestions.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter
import PIL.Image

import store
from agents.llm import call_llm_vision_json
from models.schemas import TrajectoryEvent, TrajectoryEventPayload
from services.trajectory_store import append_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["recommendations"])

_VALID_CATEGORIES = {"technical", "color_mood", "creative"}

_SYSTEM = (
    "You are a creative photo editing assistant. "
    "You analyze images and suggest diverse, visually interesting editing ideas "
    "that are specific to the content of each image."
)

_PROMPT = """\
Look at this image and suggest exactly 3 editing instructions.
Each must reference a specific visual element you observe in this image.

Rules:
- Slot 1 (category: "technical"): A precise adjustment — exposure, contrast, crop, \
sharpness, blur, rotation, etc. Reference a specific area or subject.
- Slot 2 (category: "color_mood"): A color/tone/mood change — warm tones, cinematic \
grading, vintage look, cool blue tones, etc. Mention the visual element it targets.
- Slot 3 (category: "creative"): A generative AI edit — remove/add object, change \
background, style transfer, etc. Be specific about what to add/remove/change.
- Each instruction: under 8 words, specific to THIS image, in English.
- NEVER use generic suggestions like "make it brighter" or "increase contrast".

Return ONLY valid JSON:
{"recommendations": [{"text": "...", "category": "technical"}, {"text": "...", "category": "color_mood"}, {"text": "...", "category": "creative"}]}
"""

_TIMEOUT_SECONDS = 40
_REC_MODEL = "gemini-3.1-flash-lite-preview"
_MAX_SIDE = 512  # resize image before sending — recommendations don't need high-res


def _resize_for_analysis(b64: str) -> str:
    """Downscale image to at most _MAX_SIDE px on the longest side."""
    data = base64.b64decode(b64)
    img = PIL.Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    if max(w, h) > _MAX_SIDE:
        scale = _MAX_SIDE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), PIL.Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _validate_recommendations(
    raw: Any,
) -> List[Dict[str, str]]:
    """Extract and validate recommendations from Gemini response."""
    if not isinstance(raw, dict):
        return []

    items = raw.get("recommendations")
    if not isinstance(items, list):
        return []

    validated: List[Dict[str, str]] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        category = item.get("category", "creative")
        if category not in _VALID_CATEGORIES:
            category = "creative"
        validated.append({"text": text.strip(), "category": category})

    return validated


@router.post("/{session_id}/recommendations")
async def get_recommendations(session_id: str):
    """Return up to 3 AI-generated prompt suggestions for the current session image."""
    session = store.get_session(session_id)
    if not session or not session.current_image_b64:
        return {"session_id": session_id, "recommendations": []}

    start = time.time()
    recommendations: List[Dict[str, str]] = []

    try:
        small_b64 = await asyncio.to_thread(_resize_for_analysis, session.current_image_b64)
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                call_llm_vision_json,
                _PROMPT,
                [small_b64],
                system=_SYSTEM,
                model=_REC_MODEL,
                temperature=0.7,
            ),
            timeout=_TIMEOUT_SECONDS,
        )
        recommendations = _validate_recommendations(raw)
    except asyncio.TimeoutError:
        logger.warning("Recommendation timed out for session %s", session_id)
    except Exception:
        logger.exception("Recommendation failed for session %s", session_id)

    latency_ms = int((time.time() - start) * 1000)

    # Record trajectory event
    if session.trajectory and recommendations:
        try:
            append_event(
                session.trajectory,
                TrajectoryEvent(
                    type="prompt_recommendations",
                    payload=TrajectoryEventPayload(
                        recommendations=recommendations,
                        latency_ms=latency_ms,
                        model_used=_REC_MODEL,
                    ),
                ),
            )
        except Exception:
            logger.exception("Failed to log recommendation event")

    return {"session_id": session_id, "recommendations": recommendations}
