import cv2
import numpy as np
from typing import Tuple, Optional, Any

class DreamyPastelColorGrading:
    name: str = "fb_apply_a_dreamy_pastel_color_g"
    tool_type: str = "color_grading"
    description: str = (
        "Applies a dreamy pastel color grade by lifting shadows, softening contrast, "
        "reducing saturation, and adding a soft glow with pink and blue color tints."
    )
    params_schema: dict = {
        "type": "object",
        "properties": {
            "intensity": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
                "description": "Overall strength of the dreamy pastel effect."
            },
            "glow_strength": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.4,
                "description": "Intensity of the soft diffusion/glow effect."
            },
            "pink_tint": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.3,
                "description": "Strength of the pink highlight tint."
            },
            "blue_tint": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.2,
                "description": "Strength of the blue shadow tint."
            }
        }
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        if not isinstance(image, np.ndarray):
            raise ValueError("Input image must be a numpy array.")
        
        intensity = params.get("intensity", 0.5)
        glow_strength = params.get("glow_strength", 0.4)
        pink_tint = params.get("pink_tint", 0.3)
        blue_tint = params.get("blue_tint", 0.2)

        # Convert to float32 for processing
        img_float = image.astype(np.float32) / 255.0

        # 1. Lift Shadows and Soften Contrast (Matte Effect)
        # Remap [0, 1] to [0.15 * intensity, 0.95 + 0.05 * (1-intensity)]
        black_point = 0.15 * intensity
        white_point = 1.0 - (0.05 * intensity)
        img_matte = img_float * (white_point - black_point) + black_point

        # 2. Desaturation
        # Convert to HLS to manipulate saturation
        hls = cv2.cvtColor((img_matte * 255).astype(np.uint8), cv2.COLOR_BGR2HLS).astype(np.float32) / 255.0
        # Reduce saturation for pastel look
        hls[:, :, 2] *= (1.0 - 0.4 * intensity)
        img_desat = cv2.cvtColor((hls * 255).astype(np.uint8), cv2.COLOR_HLS2BGR).astype(np.float32) / 255.0

        # 3. Color Tints (Pink Highlights, Blue Shadows)
        # Pink: BGR (0.8, 0.6, 1.0) approx
        # Blue: BGR (1.0, 0.8, 0.6) approx
        
        # Create masks based on luminance
        luminance = hls[:, :, 1]
        highlight_mask = np.clip((luminance - 0.5) * 2, 0, 1)[:, :, np.newaxis]
        shadow_mask = np.clip((0.5 - luminance) * 2, 0, 1)[:, :, np.newaxis]

        # Apply pink to highlights
        pink_color = np.array([0.85, 0.75, 0.95], dtype=np.float32)
        img_tinted = img_desat * (1 - highlight_mask * pink_tint) + (pink_color * highlight_mask * pink_tint)
        
        # Apply blue to shadows
        blue_color = np.array([0.95, 0.85, 0.75], dtype=np.float32)
        img_tinted = img_tinted * (1 - shadow_mask * blue_tint) + (blue_color * shadow_mask * blue_tint)

        # 4. Dreamy Glow (Orton-like Effect)
        # Blur the image significantly
        kernel_size = int(max(image.shape[:2]) * 0.05)
        if kernel_size % 2 == 0:
            kernel_size += 1
        
        blurred = cv2.GaussianBlur(img_tinted, (kernel_size, kernel_size), 0)
        
        # Screen blend mode for glow: 1 - (1-a)*(1-b)
        glow = 1.0 - (1.0 - img_tinted) * (1.0 - blurred)
        
        # Blend the glow back based on glow_strength
        img_final = cv2.addWeighted(img_tinted, 1.0 - glow_strength, glow, glow_strength, 0)

        # 5. Final Brightness Boost
        img_final = np.clip(img_final + (0.05 * intensity), 0, 1)

        # Convert back to uint8
        result = (img_final * 255).astype(np.uint8)
        
        return result, None

TOOL_CLASS = DreamyPastelColorGrading