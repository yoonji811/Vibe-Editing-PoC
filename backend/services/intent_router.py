"""Classify user edit intent using Gemini Flash."""
import json
import os
from typing import List

import google.generativeai as genai
from dotenv import load_dotenv

from models.schemas import ChatMessage

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

_SYSTEM_PROMPT = """\
You are an image editing intent classifier for a Korean/English web app.

Given the user's message and recent chat history, output ONLY valid JSON with this schema:
{
  "intent": "opencv" | "gemini_generative" | "session_action" | "clarify",
  "operation": "<specific operation>",
  "params": { ... },
  "response_text": "<brief Korean confirmation or question>"
}

## intent rules

### opencv — traditional image editing
operations: brightness, contrast, grayscale, blur, sharpen, rotate, flip, crop, resize, hue_shift, saturation, denoise, edge

param hints:
- brightness: {"beta": <int -100..100>}  (양수=밝게, 음수=어둡게)
- contrast:   {"alpha": <float 0.5..3.0>}
- blur:        {"ksize": <odd int 3..51>}
- rotate:      {"angle": <float degrees>}
- flip:        {"direction": "horizontal"|"vertical"}
- crop:        {"x":0,"y":0,"w":<px>,"h":<px>}
- resize:      {"width":<px>,"height":<px>}
- hue_shift:   {"shift": <int -90..90>}
- saturation:  {"scale": <float 0..3.0>}
- denoise:     {"h": 10}
- edge:        {"threshold1":100,"threshold2":200}

### gemini_generative — AI generative editing
operations: remove_background, remove_object, add_element, style_transfer, inpainting, add_text, change_style

### session_action — session management
operations: undo, save, reset

### clarify — intent unclear
Set operation to null, response_text to a clarifying question.

## examples
"밝게 해줘"         → {"intent":"opencv","operation":"brightness","params":{"beta":60},"response_text":"밝기를 높이겠습니다."}
"좀 더 어둡게"      → {"intent":"opencv","operation":"brightness","params":{"beta":-50},"response_text":"이미지를 어둡게 조정합니다."}
"흑백으로"          → {"intent":"opencv","operation":"grayscale","params":{},"response_text":"흑백으로 변환합니다."}
"배경 제거해줘"     → {"intent":"gemini_generative","operation":"remove_background","params":{},"response_text":"AI로 배경을 제거합니다."}
"이전으로"          → {"intent":"session_action","operation":"undo","params":{},"response_text":"이전 상태로 되돌립니다."}
"뭔가 이상해"       → {"intent":"clarify","operation":null,"params":{},"response_text":"어떤 부분을 어떻게 수정하고 싶으신가요?"}
"""


def classify_intent(user_text: str, chat_history: List[ChatMessage]) -> dict:
    """Return intent classification dict."""
    history_ctx = ""
    if chat_history:
        recent = chat_history[-8:]
        lines = [f"  {m.role}: {m.content}" for m in recent]
        history_ctx = "\n\nRecent chat history:\n" + "\n".join(lines)

    prompt = f"{_SYSTEM_PROMPT}{history_ctx}\n\nUser: {user_text}\n\nJSON:"

    try:
        model = genai.GenerativeModel("gemini-3-flash-preview")
        response = model.generate_content(prompt)
        text = response.text.strip()
        # Strip markdown code fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.split("```")[0].strip()
        return json.loads(text)
    except Exception as exc:
        return {
            "intent": "clarify",
            "operation": None,
            "params": {},
            "response_text": f"의도를 파악하지 못했습니다. 어떤 편집을 원하시나요? (오류: {exc})",
        }
