"""Generative image editing tools powered by Gemini.

These tools call the Gemini image generation model and integrate seamlessly
into the agent pipeline (Planner → Validator → Orchestrator → QualityChecker).

Each tool handles numpy ↔ base64 conversion internally so the orchestrator
treats them identically to OpenCV tools.
"""
from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any, Optional, Tuple

import cv2
import google.generativeai as genai
import numpy as np
from dotenv import load_dotenv

from agents.tool_registry import Tool, registry

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.0-flash-exp-image-generation"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ndarray_to_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise ValueError("Failed to encode image")
    return base64.b64encode(buf).decode("utf-8")


def _b64_to_ndarray(b64: str) -> np.ndarray:
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode Gemini image response")
    return img


def _call_gemini_image(image: np.ndarray, prompt: str) -> np.ndarray:
    """Send image + prompt to Gemini, return edited image as ndarray.

    Raises RuntimeError if Gemini returns no image.
    """
    b64 = _ndarray_to_b64(image)
    image_part = genai.protos.Part(
        inline_data=genai.protos.Blob(
            mime_type="image/jpeg",
            data=base64.b64decode(b64),
        )
    )

    model = genai.GenerativeModel(
        _MODEL,
        generation_config=genai.types.GenerationConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    response = model.generate_content([prompt, image_part])

    for part in response.parts:
        if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
            result_b64 = base64.b64encode(part.inline_data.data).decode("utf-8")
            return _b64_to_ndarray(result_b64)

    raise RuntimeError("Gemini returned no image for this request.")


# ---------------------------------------------------------------------------
# Tool: gemini_generative_edit — general purpose
# ---------------------------------------------------------------------------

class GeminiGenerativeEditTool(Tool):
    name = "gemini_generative_edit"
    tool_type = "generative"
    description = (
        "Gemini 생성형 AI로 자유로운 이미지 편집을 수행합니다. "
        "배경 교체, 객체 추가/제거, 스타일 변환, 텍스트 삽입 등 "
        "OpenCV로 불가능한 복잡한 편집에 사용합니다. "
        "instruction에 원하는 편집 내용을 구체적으로 작성하세요."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "편집 지시사항 (영어로 작성 권장, 구체적일수록 좋음)",
            },
        },
        "required": ["instruction"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        instruction = params["instruction"]
        prompt = (
            f"Edit this image as follows: {instruction}\n"
            "Preserve everything not mentioned. Return only the edited image."
        )
        result = _call_gemini_image(image, prompt)
        return result, None


# ---------------------------------------------------------------------------
# Tool: gemini_remove_background
# ---------------------------------------------------------------------------

class GeminiRemoveBackgroundTool(Tool):
    name = "gemini_remove_background"
    tool_type = "generative"
    description = (
        "Gemini AI로 이미지 배경을 제거하거나 다른 배경으로 교체합니다. "
        "피사체(사람, 물체)를 유지하면서 배경만 변경할 때 사용합니다."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "replacement": {
                "type": "string",
                "description": (
                    "교체할 배경 설명 (예: 'white background', 'blurred bokeh', "
                    "'beach sunset'). 비워두면 투명/흰 배경으로 제거."
                ),
                "default": "white background",
            },
        },
        "required": [],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        replacement = params.get("replacement", "white background")
        prompt = (
            f"Remove the background from this image and replace it with: {replacement}. "
            "Keep the main subject (person, object) sharp and intact. "
            "Make the transition between subject and new background natural."
        )
        result = _call_gemini_image(image, prompt)
        return result, None


# ---------------------------------------------------------------------------
# Tool: gemini_remove_object
# ---------------------------------------------------------------------------

class GeminiRemoveObjectTool(Tool):
    name = "gemini_remove_object"
    tool_type = "generative"
    description = (
        "Gemini AI로 이미지에서 특정 객체를 제거하고 배경을 자연스럽게 채웁니다 (인페인팅). "
        "사람, 글자, 물건 등 원하지 않는 요소를 지울 때 사용합니다."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "제거할 객체 설명 (예: 'the person on the left', 'watermark text', 'red car')",
            },
        },
        "required": ["target"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        target = params["target"]
        prompt = (
            f"Remove '{target}' from this image. "
            "Fill the removed area naturally using the surrounding background. "
            "The result should look like the object was never there."
        )
        result = _call_gemini_image(image, prompt)
        return result, None


# ---------------------------------------------------------------------------
# Tool: gemini_style_transfer
# ---------------------------------------------------------------------------

class GeminiStyleTransferTool(Tool):
    name = "gemini_style_transfer"
    tool_type = "generative"
    description = (
        "Gemini AI로 이미지 전체의 시각적 스타일을 변환합니다. "
        "애니메이션풍, 유화, 수채화, 사이버펑크, 빈티지 등 예술적 스타일 적용에 사용합니다. "
        "단순 색조 조정이 아닌 전체적인 분위기 변환이 필요할 때 선택하세요."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "style": {
                "type": "string",
                "description": (
                    "적용할 스타일 설명 (예: 'Studio Ghibli anime style', "
                    "'oil painting', 'watercolor', 'cyberpunk neon', "
                    "'vintage film photography', 'minimalist illustration')"
                ),
            },
            "strength": {
                "type": "string",
                "enum": ["subtle", "moderate", "strong"],
                "description": "스타일 적용 강도 (subtle=은은하게, moderate=적당히, strong=강하게)",
                "default": "moderate",
            },
        },
        "required": ["style"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        style = params["style"]
        strength = params.get("strength", "moderate")
        strength_map = {
            "subtle": "Apply the style very subtly, preserving most of the original look.",
            "moderate": "Apply the style clearly while keeping the subject recognizable.",
            "strong": "Apply the style strongly and dramatically.",
        }
        strength_desc = strength_map.get(strength, strength_map["moderate"])
        prompt = (
            f"Transform this image into '{style}' style. "
            f"{strength_desc} "
            "Preserve the original composition and main subject."
        )
        result = _call_gemini_image(image, prompt)
        return result, None


# ---------------------------------------------------------------------------
# Tool: gemini_add_element
# ---------------------------------------------------------------------------

class GeminiAddElementTool(Tool):
    name = "gemini_add_element"
    tool_type = "generative"
    description = (
        "Gemini AI로 이미지에 새로운 요소(객체, 텍스트, 효과)를 추가합니다. "
        "이미지에 없는 새로운 사물, 사람, 날씨 효과, 텍스트 오버레이 등을 삽입할 때 사용합니다."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "element": {
                "type": "string",
                "description": "추가할 요소 설명 (예: 'falling snow', 'a cat sitting on the table', 'rainbow in the sky')",
            },
            "position": {
                "type": "string",
                "description": "추가할 위치 힌트 (예: 'top right', 'foreground', 'background'). 생략 가능.",
                "default": "",
            },
        },
        "required": ["element"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        element = params["element"]
        position = params.get("position", "")
        location_hint = f" Place it in the {position}." if position else ""
        prompt = (
            f"Add '{element}' to this image.{location_hint} "
            "Make it look realistic and natural, consistent with the existing lighting and style. "
            "Do not change anything else in the image."
        )
        result = _call_gemini_image(image, prompt)
        return result, None


# ---------------------------------------------------------------------------
# Register all tools
# ---------------------------------------------------------------------------

registry.register(GeminiGenerativeEditTool())
registry.register(GeminiRemoveBackgroundTool())
registry.register(GeminiRemoveObjectTool())
registry.register(GeminiStyleTransferTool())
registry.register(GeminiAddElementTool())
