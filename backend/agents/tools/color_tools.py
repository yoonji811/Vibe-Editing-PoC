"""Professional color grading tools.

Implements LUT-based color correction tools used in professional
photo/video editing:

  color_curves     — per-channel tone curves (R/G/B/Master)
  split_toning     — shadow/highlight color cast (cinematic look)
  hsl_selective    — hue/saturation/luminance for a specific color range
  color_grade      — lift/gamma/gain color wheels (DaVinci-style)
  apply_lut        — load and apply a .cube LUT file
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np
from scipy.interpolate import PchipInterpolator

from agents.tool_registry import Tool, registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_curve_lut(control_points: List[List[int]]) -> np.ndarray:
    """Build a 256-entry LUT from (input, output) control points using
    PCHIP interpolation (monotone cubic — no overshoot)."""
    pts = sorted(control_points, key=lambda p: p[0])
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)

    # Ensure endpoints
    if xs[0] > 0:
        xs = np.insert(xs, 0, 0.0)
        ys = np.insert(ys, 0, 0.0)
    if xs[-1] < 255:
        xs = np.append(xs, 255.0)
        ys = np.append(ys, 255.0)

    interp = PchipInterpolator(xs, ys)
    lut = interp(np.arange(256))
    return np.clip(lut, 0, 255).astype(np.uint8)


def _apply_channel_luts(
    image: np.ndarray,
    lut_b: np.ndarray,
    lut_g: np.ndarray,
    lut_r: np.ndarray,
) -> np.ndarray:
    b, g, r = cv2.split(image)
    b = cv2.LUT(b, lut_b)
    g = cv2.LUT(g, lut_g)
    r = cv2.LUT(r, lut_r)
    return cv2.merge([b, g, r])


# ---------------------------------------------------------------------------
# Tool: color_curves
# ---------------------------------------------------------------------------

class ColorCurvesTool(Tool):
    name = "color_curves"
    tool_type = "opencv"
    description = (
        "포토샵/라이트룸 스타일 톤 커브 조정. "
        "Master(전체 밝기), R/G/B 채널별로 커브 컨트롤 포인트를 지정해 "
        "세밀한 색조와 대비를 조절합니다. "
        "시네마틱 룩, S-커브 대비, 채널별 색감 조정에 사용합니다. "
        "각 채널은 [[input, output], ...] 형식의 컨트롤 포인트 리스트입니다 (0-255)."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "master": {
                "type": "array",
                "description": "전체 밝기 커브 컨트롤 포인트 [[in,out],...]. 예: S커브 [[0,0],[64,50],[128,128],[192,210],[255,255]]",
                "default": [[0, 0], [255, 255]],
            },
            "red": {
                "type": "array",
                "description": "빨강 채널 커브 [[in,out],...]. 예: [[0,0],[128,140],[255,255]] (빨강 살짝 강조)",
                "default": [[0, 0], [255, 255]],
            },
            "green": {
                "type": "array",
                "description": "초록 채널 커브 [[in,out],...]",
                "default": [[0, 0], [255, 255]],
            },
            "blue": {
                "type": "array",
                "description": "파랑 채널 커브 [[in,out],...]",
                "default": [[0, 0], [255, 255]],
            },
        },
        "required": [],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        master = params.get("master", [[0, 0], [255, 255]])
        red    = params.get("red",    [[0, 0], [255, 255]])
        green  = params.get("green",  [[0, 0], [255, 255]])
        blue   = params.get("blue",   [[0, 0], [255, 255]])

        # Master curve applied first to a temp image, then channel curves
        m_lut = _build_curve_lut(master)
        r_lut = _build_curve_lut(red)
        g_lut = _build_curve_lut(green)
        b_lut = _build_curve_lut(blue)

        # Apply master to all channels
        tmp = cv2.LUT(image, m_lut)
        # Apply per-channel curves
        result = _apply_channel_luts(tmp, b_lut, g_lut, r_lut)
        return result, None


# ---------------------------------------------------------------------------
# Tool: split_toning
# ---------------------------------------------------------------------------

class SplitToningTool(Tool):
    name = "split_toning"
    tool_type = "opencv"
    description = (
        "쉐도우/하이라이트에 서로 다른 색상을 입히는 전문 색보정 기법. "
        "따뜻한/차가운/시네마틱 분위기, 색감 변경 요청에 우선적으로 사용합니다. "
        "예) 따뜻한 분위기: shadows_hue=30, highlights_hue=40, 양쪽 saturation=30-50 "
        "예) 시네마틱 티일-오렌지: shadows_hue=210, highlights_hue=30, saturation=35-45 "
        "예) 차가운 분위기: shadows_hue=220, highlights_hue=200, saturation=30-40 "
        "shadows_hue/highlights_hue는 0-360 색상환: 0=빨강, 30=주황, 60=노랑, 120=초록, 210=시안, 240=파랑."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "shadows_hue": {
                "type": "number", "minimum": 0, "maximum": 360,
                "description": "쉐도우 영역에 입힐 색상 (0-360). 예: 210 = 시네마틱 티일",
            },
            "shadows_saturation": {
                "type": "number", "minimum": 0, "maximum": 100,
                "description": "쉐도우 색상 강도 (0=없음, 100=강함). 권장: 20-50",
            },
            "highlights_hue": {
                "type": "number", "minimum": 0, "maximum": 360,
                "description": "하이라이트 영역에 입힐 색상 (0-360). 예: 30 = 따뜻한 오렌지",
            },
            "highlights_saturation": {
                "type": "number", "minimum": 0, "maximum": 100,
                "description": "하이라이트 색상 강도 (0=없음, 100=강함). 권장: 20-50",
            },
            "balance": {
                "type": "number", "minimum": -100, "maximum": 100,
                "description": "쉐도우(-100)↔하이라이트(+100) 균형. 0이 중간",
            },
        },
        "required": ["shadows_hue", "shadows_saturation", "highlights_hue", "highlights_saturation"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        s_hue  = float(params["shadows_hue"])
        s_sat  = float(params["shadows_saturation"]) / 100.0
        h_hue  = float(params["highlights_hue"])
        h_sat  = float(params["highlights_saturation"]) / 100.0
        balance = float(params.get("balance", 0)) / 100.0  # -1 to 1

        # Shadow/highlight masks from luminance
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        shadow_mask    = np.clip(1.0 - gray * 2 + balance, 0, 1)
        highlight_mask = np.clip(gray * 2 - 1 + balance, 0, 1)

        def hue_to_bgr(hue_deg: float) -> Tuple[float, float, float]:
            hsv = np.uint8([[[int(hue_deg / 2), 255, 255]]])
            bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0][0]
            return bgr[0] / 255.0, bgr[1] / 255.0, bgr[2] / 255.0

        s_b, s_g, s_r = hue_to_bgr(s_hue)
        h_b, h_g, h_r = hue_to_bgr(h_hue)

        img_f = image.astype(np.float32) / 255.0
        b, g, r = cv2.split(img_f)

        for ch, val, s_col, h_col in [
            (b, None, s_b, h_b),
            (g, None, s_g, h_g),
            (r, None, s_r, h_r),
        ]:
            pass  # handled below

        b = b + shadow_mask * s_sat * (s_b - 0.5) + highlight_mask * h_sat * (h_b - 0.5)
        g = g + shadow_mask * s_sat * (s_g - 0.5) + highlight_mask * h_sat * (h_g - 0.5)
        r = r + shadow_mask * s_sat * (s_r - 0.5) + highlight_mask * h_sat * (h_r - 0.5)

        result = cv2.merge([
            np.clip(b, 0, 1),
            np.clip(g, 0, 1),
            np.clip(r, 0, 1),
        ])
        return (result * 255).astype(np.uint8), None


# ---------------------------------------------------------------------------
# Tool: hsl_selective
# ---------------------------------------------------------------------------

class HSLSelectiveTool(Tool):
    name = "hsl_selective"
    tool_type = "opencv"
    description = (
        "특정 색상 범위(예: 피부색, 하늘, 나뭇잎)만 선택해서 "
        "색조(Hue)/채도(Saturation)/밝기(Luminance)를 독립적으로 조정합니다. "
        "라이트룸의 HSL 패널과 동일한 방식. "
        "전체 색상을 바꾸는 hue_shift와 달리 특정 색만 정밀하게 조정 가능."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "target_hue": {
                "type": "number", "minimum": 0, "maximum": 360,
                "description": "조정할 색상 중심값 (0=빨강, 30=주황, 60=노랑, 120=초록, 180=시안, 240=파랑, 300=보라)",
            },
            "hue_range": {
                "type": "number", "minimum": 5, "maximum": 90,
                "description": "대상 색상 범위 폭 (기본 30). 클수록 더 넓은 색상 범위 영향",
                "default": 30,
            },
            "hue_shift": {
                "type": "number", "minimum": -180, "maximum": 180,
                "description": "대상 색상의 색조 이동량",
                "default": 0,
            },
            "saturation_shift": {
                "type": "number", "minimum": -100, "maximum": 100,
                "description": "대상 색상의 채도 변화량 (양수=더 선명, 음수=탁하게)",
                "default": 0,
            },
            "luminance_shift": {
                "type": "number", "minimum": -100, "maximum": 100,
                "description": "대상 색상의 밝기 변화량",
                "default": 0,
            },
        },
        "required": ["target_hue"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        target_hue   = float(params["target_hue"])
        hue_range    = float(params.get("hue_range", 30))
        hue_shift    = float(params.get("hue_shift", 0))
        sat_shift    = float(params.get("saturation_shift", 0))
        lum_shift    = float(params.get("luminance_shift", 0))

        # OpenCV HSV: H=0-179, S=0-255, V=0-255
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
        h, s, v = cv2.split(hsv)

        # Build weight mask for target hue range
        t_h = target_hue / 2.0  # convert to 0-179
        r_h = hue_range / 2.0
        diff = np.abs(h - t_h)
        diff = np.minimum(diff, 180 - diff)  # handle hue wrap-around
        weight = np.clip(1.0 - diff / r_h, 0, 1)

        h = np.clip(h + weight * (hue_shift / 2.0), 0, 179)
        s = np.clip(s + weight * (sat_shift / 100.0 * 255), 0, 255)
        v = np.clip(v + weight * (lum_shift / 100.0 * 255), 0, 255)

        result_hsv = cv2.merge([h, s, v]).astype(np.uint8)
        return cv2.cvtColor(result_hsv, cv2.COLOR_HSV2BGR), None


# ---------------------------------------------------------------------------
# Tool: color_grade
# ---------------------------------------------------------------------------

class ColorGradeTool(Tool):
    name = "color_grade"
    tool_type = "opencv"
    description = (
        "DaVinci Resolve 스타일 Lift/Gamma/Gain 색보정. "
        "Lift=쉐도우 색조, Gamma=미드톤 색조, Gain=하이라이트 색조를 "
        "R/G/B 채널별로 독립 조정합니다. "
        "영화적 색보정, 시네마틱 룩 제작에 사용합니다. "
        "예: 따뜻한 룩 = gain_r=1.1, gain_g=1.05, gain_b=0.9, lift_b=0.05"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "lift_r":  {"type": "number", "minimum": -0.3, "maximum": 0.3, "description": "쉐도우 빨강 (-0.3~0.3)", "default": 0.0},
            "lift_g":  {"type": "number", "minimum": -0.3, "maximum": 0.3, "description": "쉐도우 초록", "default": 0.0},
            "lift_b":  {"type": "number", "minimum": -0.3, "maximum": 0.3, "description": "쉐도우 파랑", "default": 0.0},
            "gamma_r": {"type": "number", "minimum": 0.4, "maximum": 2.5, "description": "미드톤 빨강 감마 (1.0=기본)", "default": 1.0},
            "gamma_g": {"type": "number", "minimum": 0.4, "maximum": 2.5, "description": "미드톤 초록 감마", "default": 1.0},
            "gamma_b": {"type": "number", "minimum": 0.4, "maximum": 2.5, "description": "미드톤 파랑 감마", "default": 1.0},
            "gain_r":  {"type": "number", "minimum": 0.5, "maximum": 2.0, "description": "하이라이트 빨강 (1.0=기본)", "default": 1.0},
            "gain_g":  {"type": "number", "minimum": 0.5, "maximum": 2.0, "description": "하이라이트 초록", "default": 1.0},
            "gain_b":  {"type": "number", "minimum": 0.5, "maximum": 2.0, "description": "하이라이트 파랑", "default": 1.0},
        },
        "required": [],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        lift  = [params.get("lift_b", 0.0),  params.get("lift_g", 0.0),  params.get("lift_r", 0.0)]
        gamma = [params.get("gamma_b", 1.0), params.get("gamma_g", 1.0), params.get("gamma_r", 1.0)]
        gain  = [params.get("gain_b", 1.0),  params.get("gain_g", 1.0),  params.get("gain_r", 1.0)]

        img_f = image.astype(np.float32) / 255.0
        channels = list(cv2.split(img_f))

        for i in range(3):
            c = channels[i]
            # Lift (shadow offset) → Gain (highlight scale) → Gamma (midtone curve)
            c = np.clip(c * gain[i] + lift[i], 0, 1)
            c = np.power(np.clip(c, 1e-6, 1), 1.0 / gamma[i])
            channels[i] = c

        result = cv2.merge(channels)
        return (np.clip(result, 0, 1) * 255).astype(np.uint8), None


# ---------------------------------------------------------------------------
# Tool: apply_lut
# ---------------------------------------------------------------------------

class ApplyLUTTool(Tool):
    name = "apply_lut"
    tool_type = "opencv"
    description = (
        "외부 .cube LUT 파일을 불러와 이미지에 적용합니다. "
        "Lightroom/Premiere 등에서 내보낸 .cube 파일 경로를 lut_path에 지정하세요. "
        "intensity로 LUT 적용 강도를 조절할 수 있습니다 (0=원본, 1=완전 적용)."
    )
    params_schema = {
        "type": "object",
        "properties": {
            "lut_path": {
                "type": "string",
                "description": ".cube LUT 파일의 절대 경로",
            },
            "intensity": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "LUT 적용 강도 (0.0=원본, 1.0=완전 적용, 기본 1.0)",
                "default": 1.0,
            },
        },
        "required": ["lut_path"],
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        lut_path  = params["lut_path"]
        intensity = float(params.get("intensity", 1.0))

        lut_3d, lut_size = self._load_cube(lut_path)
        result = self._apply_3d_lut(image, lut_3d, lut_size)

        if intensity < 1.0:
            result = cv2.addWeighted(image, 1.0 - intensity, result, intensity, 0)
        return result, None

    @staticmethod
    def _load_cube(path: str):
        """Parse a .cube LUT file. Returns (lut_3d ndarray, lut_size)."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"LUT file not found: {path}")

        data = []
        lut_size = 33
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("LUT_SIZE"):
                    lut_size = int(line.split()[-1])
                elif line and not line.startswith("#") and not line.startswith("TITLE") \
                        and not line.startswith("DOMAIN") and not line.startswith("LUT"):
                    try:
                        vals = [float(x) for x in line.split()]
                        if len(vals) == 3:
                            data.append(vals)
                    except ValueError:
                        pass

        expected = lut_size ** 3
        if len(data) < expected:
            raise ValueError(f"LUT data incomplete: got {len(data)}, expected {expected}")

        lut_3d = np.array(data[:expected], dtype=np.float32).reshape(
            lut_size, lut_size, lut_size, 3
        )
        return lut_3d, lut_size

    @staticmethod
    def _apply_3d_lut(image: np.ndarray, lut_3d: np.ndarray, lut_size: int) -> np.ndarray:
        """Trilinear interpolation of a 3D LUT."""
        img_f = image.astype(np.float32) / 255.0
        b, g, r = cv2.split(img_f)

        scale = lut_size - 1
        ri = np.clip(r * scale, 0, scale)
        gi = np.clip(g * scale, 0, scale)
        bi = np.clip(b * scale, 0, scale)

        r0 = np.floor(ri).astype(int)
        g0 = np.floor(gi).astype(int)
        b0 = np.floor(bi).astype(int)
        r1 = np.clip(r0 + 1, 0, scale)
        g1 = np.clip(g0 + 1, 0, scale)
        b1 = np.clip(b0 + 1, 0, scale)

        dr = (ri - r0)[..., np.newaxis]
        dg = (gi - g0)[..., np.newaxis]
        db = (bi - b0)[..., np.newaxis]

        def s(ri_, gi_, bi_):
            return lut_3d[bi_, gi_, ri_]

        result = (
            s(r0,g0,b0) * (1-dr)*(1-dg)*(1-db) +
            s(r1,g0,b0) * dr*(1-dg)*(1-db) +
            s(r0,g1,b0) * (1-dr)*dg*(1-db) +
            s(r0,g0,b1) * (1-dr)*(1-dg)*db +
            s(r1,g1,b0) * dr*dg*(1-db) +
            s(r1,g0,b1) * dr*(1-dg)*db +
            s(r0,g1,b1) * (1-dr)*dg*db +
            s(r1,g1,b1) * dr*dg*db
        )
        result = np.clip(result, 0, 1)
        # LUT stores R,G,B — convert back to BGR
        out_r = result[..., 0]
        out_g = result[..., 1]
        out_b = result[..., 2]
        return (cv2.merge([out_b, out_g, out_r]) * 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Register all tools
# ---------------------------------------------------------------------------

registry.register(ColorCurvesTool())
registry.register(SplitToningTool())
registry.register(HSLSelectiveTool())
registry.register(ColorGradeTool())
registry.register(ApplyLUTTool())
