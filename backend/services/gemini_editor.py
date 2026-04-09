"""Gemini generative image editing."""
import base64
import os
from typing import Optional, Tuple

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

_EDIT_MODEL = "gemini-2.5-flash-image"

_PROMPT_TEMPLATE = """\
Please edit this image as requested: {instruction}

Important:
- Return the edited image directly.
- Preserve the original image dimensions and quality unless asked to change them.
- Make only the requested changes; keep everything else the same.
"""


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
