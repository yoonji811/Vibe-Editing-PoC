"""Gemini generative image editing."""
import base64
import os
from typing import Optional, Tuple

import requests
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=_API_KEY)

_EDIT_MODEL = "gemini-2.5-flash-image"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_PROMPT_TEMPLATE = """\
Please edit this image as requested: {instruction}

Important:
- Return the edited image directly.
- Preserve the original image dimensions and quality unless asked to change them.
- Make only the requested changes; keep everything else the same.
"""


def generate_image(prompt: str) -> Tuple[Optional[str], str]:
    """Generate an image from a text prompt using Gemini REST API."""
    url = f"{_GEMINI_BASE}/{_EDIT_MODEL}:generateContent?key={_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": f"Generate an image: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        result_b64: Optional[str] = None
        text_parts: list[str] = []

        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        for part in parts:
            if "inlineData" in part:
                result_b64 = part["inlineData"]["data"]
            elif "text" in part:
                text_parts.append(part["text"])

        return result_b64, " ".join(text_parts).strip() or "이미지 생성 완료"
    except Exception as exc:
        return None, f"이미지 생성 중 오류: {exc}"


def edit_image(image_b64: str, instruction: str, operation: str) -> Tuple[Optional[str], str]:
    """
    Edit image using Gemini's multimodal image generation.

    Returns:
        (result_image_b64, response_text)
        result_image_b64 is None if the model did not return an image.
    """
    prompt = _PROMPT_TEMPLATE.format(instruction=instruction)

    image_part = genai.protos.Part(
        inline_data=genai.protos.Blob(
            mime_type="image/jpeg",
            data=base64.b64decode(image_b64),
        )
    )

    try:
        model = genai.GenerativeModel(_EDIT_MODEL)
        response = model.generate_content([prompt, image_part])

        result_b64: Optional[str] = None
        text_parts: list[str] = []

        for part in response.parts:
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                result_b64 = base64.b64encode(part.inline_data.data).decode("utf-8")
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        response_text = " ".join(text_parts).strip() or f"{operation} 완료"

        if result_b64:
            return result_b64, response_text
        else:
            return None, response_text or "이미지를 생성하지 못했습니다. 다시 시도해주세요."

    except Exception as exc:
        return None, f"Gemini 편집 중 오류가 발생했습니다: {exc}"
