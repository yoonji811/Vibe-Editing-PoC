"""Shared LLM wrapper used by all agents.

Each agent sets its own prompt/system but delegates model selection and
API mechanics to this module.  No agent should hard-code model names or
generation parameters outside of here.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Dict, List, Optional, Tuple

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

_DEFAULT_MODEL = "gemini-3-flash-preview"

# Cache GenerativeModel instances keyed by (model, system, temperature, json_mode)
# to avoid re-instantiation overhead on every request.
_model_cache: Dict[Tuple, genai.GenerativeModel] = {}


def _get_model(
    model: str,
    system: Optional[str],
    temperature: float,
    json_mode: bool,
) -> genai.GenerativeModel:
    key = (model, system or "", temperature, json_mode)
    if key not in _model_cache:
        _model_cache[key] = genai.GenerativeModel(
            model,
            system_instruction=system,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                response_mime_type="application/json" if json_mode else "text/plain",
            ),
        )
    return _model_cache[key]


def call_llm(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.0,
    json_mode: bool = False,
) -> str:
    """Call Gemini and return the raw response text."""
    gemini_model = _get_model(model, system, temperature, json_mode)
    response = gemini_model.generate_content(prompt)
    return response.text.strip()


def call_llm_json(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.0,
) -> dict:
    """Call Gemini and parse the response as JSON."""
    text = call_llm(
        prompt,
        system=system,
        model=model,
        temperature=temperature,
        json_mode=True,
    )
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    parsed = json.loads(text)
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    return parsed


def call_llm_vision_json(
    prompt: str,
    images_b64: List[str],
    *,
    system: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.0,
) -> dict:
    """Call Gemini with one or more images and parse the response as JSON.

    Uses text/plain response mode (not application/json) for vision inputs
    because some Gemini versions reject structured output with image parts.
    Falls back to JSON extraction from free-form text.

    Args:
        images_b64: List of base64-encoded image strings (no data URI prefix).
    """
    parts: list = []
    for b64 in images_b64:
        # Send raw bytes via protobuf Part — avoids PIL decode + re-serialization overhead
        raw_bytes = base64.b64decode(b64)
        parts.append(genai.protos.Part(
            inline_data=genai.protos.Blob(
                mime_type="image/jpeg",
                data=raw_bytes,
            )
        ))
    parts.append(prompt)

    gemini_model = _get_model(model, system, temperature, json_mode=True)
    response = gemini_model.generate_content(parts)
    text = response.text.strip()
    # Extract JSON block if wrapped in markdown fences
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    else:
        # Find the outermost { ... } block in case of surrounding prose
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
    parsed = json.loads(text)
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    return parsed
