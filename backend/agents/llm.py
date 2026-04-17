"""Shared LLM wrapper used by all agents.

Each agent sets its own prompt/system but delegates model selection and
API mechanics to this module.  No agent should hard-code model names or
generation parameters outside of here.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import google.generativeai as genai
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
    """Call Gemini and parse the response as JSON.

    Strips markdown code fences if the model wraps its output.
    """
    text = call_llm(
        prompt,
        system=system,
        model=model,
        temperature=temperature,
        json_mode=True,
    )
    # Strip markdown fences in case the model adds them despite json_mode
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    return json.loads(text)
