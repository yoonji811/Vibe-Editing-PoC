"""Pre-built OpenCV image editing tools.

Each class maps to one operation from the original opencv_editor service,
re-implemented to work directly on numpy arrays (no base64 round-trip
inside the pipeline).  All tools are registered in the global registry
when this module is imported.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

import cv2
import numpy as np

from agents.tool_registry import Tool, registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _odd(n: int) -> int:
    """Return n if odd, else n+1."""
    return n if n % 2 == 1 else n + 1


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class BrightnessTool(Tool):
    name = "brightness"
    tool_type = "opencv"
    description = "이미지 전체 밝기를 조정합니다. 양수면 밝게, 음수면 어둡게."
    params_schema = {
        "type": "object",
        "properties": {
            "beta": {
                "type": "number",
                "minimum": -100,
                "maximum": 100,
                "description": "밝기 조정값 (-100 어두움 ~ 100 밝음)",
            },
        },
        "required": ["beta"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        beta = int(params.get("beta", 50))
        return cv2.convertScaleAbs(image, alpha=1.0, beta=beta), None


class ContrastTool(Tool):
    name = "contrast"
    tool_type = "opencv"
    description = "이미지 대비(contrast)를 조정합니다. 1.0이 기본값, 높을수록 대비 강함."
    params_schema = {
        "type": "object",
        "properties": {
            "alpha": {
                "type": "number",
                "minimum": 0.5,
                "maximum": 3.0,
                "description": "대비 배율 (0.5 낮음 ~ 3.0 높음, 기본 1.5)",
            },
        },
        "required": ["alpha"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        alpha = float(params.get("alpha", 1.5))
        return cv2.convertScaleAbs(image, alpha=alpha, beta=0), None


class GrayscaleTool(Tool):
    name = "grayscale"
    tool_type = "opencv"
    description = "이미지를 흑백(그레이스케일)으로 변환합니다."
    params_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), None


class BlurTool(Tool):
    name = "blur"
    tool_type = "opencv"
    description = "가우시안 블러를 적용합니다. ksize가 클수록 더 많이 흐려집니다."
    params_schema = {
        "type": "object",
        "properties": {
            "ksize": {
                "type": "integer",
                "minimum": 3,
                "maximum": 51,
                "description": "블러 커널 크기 (홀수, 3 이상 51 이하)",
            },
        },
        "required": ["ksize"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        ksize = _odd(int(params.get("ksize", 15)))
        return cv2.GaussianBlur(image, (ksize, ksize), 0), None


class SharpenTool(Tool):
    name = "sharpen"
    tool_type = "opencv"
    description = "이미지를 선명하게 만듭니다 (언샤프 마스크)."
    params_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        kernel = np.array(
            [[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32
        )
        return cv2.filter2D(image, -1, kernel), None


class RotateTool(Tool):
    name = "rotate"
    tool_type = "opencv"
    description = "이미지를 지정한 각도만큼 회전합니다. 양수=시계 방향."
    params_schema = {
        "type": "object",
        "properties": {
            "angle": {
                "type": "number",
                "description": "회전 각도 (도, 시계 방향 양수)",
            },
        },
        "required": ["angle"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        angle = float(params.get("angle", 90))
        h, w = image.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
        result = cv2.warpAffine(
            image, M, (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
        return result, None


class FlipTool(Tool):
    name = "flip"
    tool_type = "opencv"
    description = "이미지를 수평 또는 수직으로 뒤집습니다."
    params_schema = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["horizontal", "vertical"],
                "description": "뒤집기 방향",
            },
        },
        "required": ["direction"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        direction = params.get("direction", "horizontal")
        flip_code = 1 if direction == "horizontal" else 0
        return cv2.flip(image, flip_code), None


class CropTool(Tool):
    name = "crop"
    tool_type = "opencv"
    description = "이미지를 지정한 좌표와 크기로 잘라냅니다."
    params_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "minimum": 0, "description": "왼쪽 상단 x 좌표"},
            "y": {"type": "integer", "minimum": 0, "description": "왼쪽 상단 y 좌표"},
            "w": {"type": "integer", "minimum": 1, "description": "잘라낼 너비 (픽셀)"},
            "h": {"type": "integer", "minimum": 1, "description": "잘라낼 높이 (픽셀)"},
        },
        "required": ["x", "y", "w", "h"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        ih, iw = image.shape[:2]
        x = max(0, int(params.get("x", 0)))
        y = max(0, int(params.get("y", 0)))
        cw = min(int(params.get("w", iw)), iw - x)
        ch = min(int(params.get("h", ih)), ih - y)
        return image[y: y + ch, x: x + cw], None


class ResizeTool(Tool):
    name = "resize"
    tool_type = "opencv"
    description = "이미지를 지정한 해상도로 리사이즈합니다."
    params_schema = {
        "type": "object",
        "properties": {
            "width": {"type": "integer", "minimum": 1, "description": "목표 너비 (픽셀)"},
            "height": {"type": "integer", "minimum": 1, "description": "목표 높이 (픽셀)"},
        },
        "required": ["width", "height"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        width = int(params.get("width", image.shape[1]))
        height = int(params.get("height", image.shape[0]))
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA), None


class HueShiftTool(Tool):
    name = "hue_shift"
    tool_type = "opencv"
    description = "이미지의 색상(Hue)을 이동시킵니다."
    params_schema = {
        "type": "object",
        "properties": {
            "shift": {
                "type": "integer",
                "minimum": -90,
                "maximum": 90,
                "description": "색상 이동값 (-90 ~ 90)",
            },
        },
        "required": ["shift"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        shift = int(params.get("shift", 30))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.int32)
        hsv[:, :, 0] = (hsv[:, :, 0] + shift) % 180
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR), None


class SaturationTool(Tool):
    name = "saturation"
    tool_type = "opencv"
    description = "이미지의 채도(Saturation)를 조정합니다. 1.0이 원본, 높을수록 선명한 색."
    params_schema = {
        "type": "object",
        "properties": {
            "scale": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 3.0,
                "description": "채도 배율 (0=무채색, 1=원본, 3=매우 선명)",
            },
        },
        "required": ["scale"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        scale = float(params.get("scale", 1.5))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * scale, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR), None


class DenoiseTool(Tool):
    name = "denoise"
    tool_type = "opencv"
    description = "이미지 노이즈를 제거합니다."
    params_schema = {
        "type": "object",
        "properties": {
            "h": {
                "type": "integer",
                "minimum": 1,
                "maximum": 30,
                "description": "노이즈 제거 강도 (기본 10)",
            },
        },
        "required": [],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        h = int(params.get("h", 10))
        return (
            cv2.fastNlMeansDenoisingColored(image, None, h, h, 7, 21),
            None,
        )


class EdgeTool(Tool):
    name = "edge"
    tool_type = "opencv"
    description = "Canny 엣지 검출을 적용합니다. 윤곽선만 흰색으로 표시됩니다."
    params_schema = {
        "type": "object",
        "properties": {
            "threshold1": {
                "type": "integer",
                "minimum": 0,
                "maximum": 500,
                "description": "낮은 임계값 (기본 100)",
            },
            "threshold2": {
                "type": "integer",
                "minimum": 0,
                "maximum": 500,
                "description": "높은 임계값 (기본 200)",
            },
        },
        "required": [],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        t1 = int(params.get("threshold1", 100))
        t2 = int(params.get("threshold2", 200))
        edges = cv2.Canny(image, t1, t2)
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR), None


# ---------------------------------------------------------------------------
# Auto-register all tools when this module is imported
# ---------------------------------------------------------------------------

_ALL_TOOLS = [
    BrightnessTool(),
    ContrastTool(),
    GrayscaleTool(),
    BlurTool(),
    SharpenTool(),
    RotateTool(),
    FlipTool(),
    CropTool(),
    ResizeTool(),
    HueShiftTool(),
    SaturationTool(),
    DenoiseTool(),
    EdgeTool(),
]

for _tool in _ALL_TOOLS:
    registry.register(_tool)
