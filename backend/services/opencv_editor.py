"""OpenCV-based image editing operations."""
import base64

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------

def b64_to_cv2(b64: str) -> np.ndarray:
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image from base64")
    return img


def cv2_to_b64(img: np.ndarray, fmt: str = ".jpg") -> str:
    success, buf = cv2.imencode(fmt, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not success:
        raise ValueError("Failed to encode image to base64")
    return base64.b64encode(buf).decode("utf-8")


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def apply_edit(image_b64: str, operation: str, params: dict) -> str:
    """Apply an OpenCV edit and return the result as base64 JPEG."""
    img = b64_to_cv2(image_b64)

    if operation == "brightness":
        beta = int(params.get("beta", 50))
        img = cv2.convertScaleAbs(img, alpha=1.0, beta=beta)

    elif operation == "contrast":
        alpha = float(params.get("alpha", 1.5))
        img = cv2.convertScaleAbs(img, alpha=alpha, beta=0)

    elif operation == "grayscale":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    elif operation == "blur":
        ksize = int(params.get("ksize", 15))
        if ksize % 2 == 0:
            ksize += 1
        img = cv2.GaussianBlur(img, (ksize, ksize), 0)

    elif operation == "sharpen":
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)
        img = cv2.filter2D(img, -1, kernel)

    elif operation == "rotate":
        angle = float(params.get("angle", 90))
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    elif operation == "flip":
        direction = params.get("direction", "horizontal")
        flip_code = 1 if direction == "horizontal" else 0
        img = cv2.flip(img, flip_code)

    elif operation == "crop":
        h, w = img.shape[:2]
        x = max(0, int(params.get("x", 0)))
        y = max(0, int(params.get("y", 0)))
        cw = min(int(params.get("w", w)), w - x)
        ch = min(int(params.get("h", h)), h - y)
        img = img[y : y + ch, x : x + cw]

    elif operation == "resize":
        width = int(params.get("width", img.shape[1]))
        height = int(params.get("height", img.shape[0]))
        img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)

    elif operation == "hue_shift":
        shift = int(params.get("shift", 30))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.int32)
        hsv[:, :, 0] = (hsv[:, :, 0] + shift) % 180
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    elif operation == "saturation":
        scale = float(params.get("scale", 1.5))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * scale, 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    elif operation == "denoise":
        h_param = int(params.get("h", 10))
        img = cv2.fastNlMeansDenoisingColored(img, None, h_param, h_param, 7, 21)

    elif operation == "edge":
        t1 = int(params.get("threshold1", 100))
        t2 = int(params.get("threshold2", 200))
        edges = cv2.Canny(img, t1, t2)
        img = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

    else:
        raise ValueError(f"Unknown opencv operation: {operation}")

    return cv2_to_b64(img)


def get_image_dimensions(image_b64: str) -> tuple[int, int]:
    """Return (width, height) of a base64-encoded image."""
    img = b64_to_cv2(image_b64)
    h, w = img.shape[:2]
    return w, h
