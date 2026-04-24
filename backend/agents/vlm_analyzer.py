"""VLM Analyzer Agent — extracts structured image state via Gemini vision.

Called by the Orchestrator after correction detection.  The result is used
ONLY for two purposes:
  1. Improving Memory Agent RAG search quality (richer embedding vector).
  2. Storing structured image context in the trajectory (learning data).

VLM output is NOT forwarded to the Planner.  The Planner only learns about
past image states indirectly via retrieved_cases returned by Memory Agent.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .llm import call_llm_vision_json

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a professional image analysis AI. Analyze the provided image and return
a structured JSON describing its current state. Be concise and precise.

Return ONLY valid JSON with this exact schema:
{
  "semantic_understanding": {
    "subjects": ["<main subjects>"],
    "scene_type": "<indoor|outdoor|portrait|landscape|urban|nature|abstract|product|other>",
    "mood": "<overall emotional mood, e.g. moody, cheerful, calm, dramatic>",
    "objects": ["<notable objects>"]
  },
  "physical_properties": {
    "noise_level": "<Low|Medium|High>",
    "sharpness": "<Soft|Normal|Sharp>",
    "blur": "<None|Slight|Heavy>",
    "resolution_quality": "<Low|Medium|High>"
  },
  "colorimetry_and_lighting": {
    "dominant_colors": ["<color names>"],
    "color_temperature": "<Cool|Neutral|Warm>",
    "contrast": "<Low|Medium|High>",
    "brightness": "<Dark|Normal|Bright>",
    "lighting_direction": "<ambient|directional|backlit|side-lit|unknown>"
  },
  "artistic_style": {
    "current_style": "<realistic|cinematic|vintage|flat|high-contrast|desaturated|vivid|other>",
    "genre": "<street|portrait|landscape|commercial|documentary|fine-art|other>",
    "mood_keywords": ["<2-4 mood/style keywords>"]
  }
}
"""

_PROMPT = "Analyze this image and return the structured JSON as specified."


class VLMAnalyzerAgent:
    """Analyzes an image and returns structured state for Memory Agent and trajectory storage."""

    def analyze(self, image_b64: str) -> Dict[str, Any]:
        """Analyze image and return VLM context dict.

        Args:
            image_b64: Base64-encoded image (no data URI prefix).

        Returns:
            Dict with semantic_understanding, physical_properties,
            colorimetry_and_lighting, artistic_style keys.
            Returns empty dict on failure (non-fatal).
        """
        try:
            result = call_llm_vision_json(
                prompt=_PROMPT,
                images_b64=[image_b64],
                system=_SYSTEM,
                temperature=0.0,
                model="gemini-2.5-flash",
            )
            return result
        except Exception as exc:
            logger.warning("VLM analysis failed: %s", exc)
            return {}

    def summarize_for_embedding(self, vlm_context: Dict[str, Any]) -> str:
        """Convert VLM context to a flat string for vector embedding queries."""
        if not vlm_context:
            return ""
        parts = []
        sem = vlm_context.get("semantic_understanding", {})
        color = vlm_context.get("colorimetry_and_lighting", {})
        phys = vlm_context.get("physical_properties", {})
        art = vlm_context.get("artistic_style", {})

        if sem.get("scene_type"):
            parts.append(f"Scene: {sem['scene_type']}")
        if sem.get("mood"):
            parts.append(f"Mood: {sem['mood']}")
        if sem.get("subjects"):
            parts.append(f"Subjects: {', '.join(sem['subjects'][:3])}")
        if color.get("color_temperature"):
            parts.append(f"Color temp: {color['color_temperature']}")
        if color.get("brightness"):
            parts.append(f"Brightness: {color['brightness']}")
        if color.get("contrast"):
            parts.append(f"Contrast: {color['contrast']}")
        if phys.get("noise_level"):
            parts.append(f"Noise: {phys['noise_level']}")
        if art.get("current_style"):
            parts.append(f"Style: {art['current_style']}")
        if art.get("mood_keywords"):
            parts.append(f"Keywords: {', '.join(art['mood_keywords'])}")

        return " | ".join(parts)
