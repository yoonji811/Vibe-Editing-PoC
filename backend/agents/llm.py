"""Shared LLM wrapper used by all agents.

Each agent sets its own prompt/system but delegates model selection and
API mechanics to this module.  No agent should hard-code model names or
generation parameters outside of here.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import List, Optional

import google.generativeai as genai
import PIL.Image
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

_DEFAULT_MODEL = "gemini-2.5-flash"


def call_llm(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.0,
    json_mode: bool = False,
) -> str:
    """Call Gemini and return the raw response text."""
    generation_config = genai.types.GenerationConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    gemini_model = genai.GenerativeModel(
        model,
        system_instruction=system,
        generation_config=generation_config,
    )
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
    return json.loads(text)


def call_llm_vision_json(
    prompt: str,
    images_b64: List[str],
    *,
    system: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.0,
) -> dict:
    """Call Gemini with one or more images and parse the response as JSON.

    Args:
        images_b64: List of base64-encoded image strings (no data URI prefix).
    """
    parts: list = []
    for b64 in images_b64:
        data = base64.b64decode(b64)
        img = PIL.Image.open(io.BytesIO(data))
        parts.append(img)
    parts.append(prompt)

    generation_config = genai.types.GenerationConfig(
        temperature=temperature,
        response_mime_type="application/json",
    )
    gemini_model = genai.GenerativeModel(
        model,
        system_instruction=system,
        generation_config=generation_config,
    )
    response = gemini_model.generate_content(parts)
    text = response.text.strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    return json.loads(text)
