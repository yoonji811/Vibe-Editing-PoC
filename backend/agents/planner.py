"""Planner Agent — converts user prompt → Plan JSON using Gemini.

The Planner NEVER executes anything.  It only designs the plan.
Context quality (tool catalog, image metadata, ancestor chain) determines
plan quality — not hard-coded intent rules.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from .llm import call_llm_json

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are a precise image editing plan generator for a web application.

Your only job is to convert a user's image editing request into a structured
Plan JSON.  You do not execute anything — you only design.

## Tool Selection Guide (CRITICAL — read before choosing tools)

### Use COLOR GRADING tools for ALL color/tone/mood/atmosphere requests:
- 따뜻한/따듯한/warm 분위기 → `split_toning` (highlights_hue=30~40, shadows_hue=20~30, saturation=30~50)
- 차가운/cool/cold 분위기 → `split_toning` (shadows_hue=210~240, highlights_hue=200~220, saturation=30~45)
- 시네마틱/영화/티일-오렌지 → `split_toning` (shadows_hue=210, highlights_hue=30, saturation=35~45)
- 빈티지/필름/레트로 색감 → `color_grade` + `color_curves`
- 특정 색상만 조정 (하늘, 피부, 나뭇잎) → `hsl_selective`
- 대비/밝기 곡선 → `color_curves`
- 전문 LUT 파일 적용 → `apply_lut`

### Use GENERATIVE tools (gemini_*) ONLY for these content-level changes:
- 배경 제거/교체 → `gemini_remove_background`
- 특정 객체/사람 제거 → `gemini_remove_object`
- 새 요소 추가 (눈, 동물, 텍스트 등) → `gemini_add_element`
- 애니/수채화/유화 등 외형 자체가 바뀌는 예술 스타일 변환 → `gemini_style_transfer`
- 위 이외의 복합 생성 편집 → `gemini_generative_edit`
- 색감/분위기/톤 변경은 gemini 툴을 절대 사용하지 마세요.

### Use OPENCV tools for precise technical adjustments:
- 밝기/대비 수치 조정 → `brightness`, `contrast`
- 기하학적 변환 → `rotate`, `flip`, `crop`, `resize`
- 흐림/선명/노이즈 → `blur`, `sharpen`, `denoise`
- 흑백 변환 → `grayscale`

### WARNING — NEVER use for mood/color requests:
- `hue_shift`: 모든 색상을 동일하게 회전 → 피부/하늘이 기괴하게 변함. 사용 금지.
- `saturation`: 단독으로는 분위기를 만들 수 없음.

## Rules
1. Use ONLY tool names listed in "Available Tools".  Any other name goes to
   unmet_requirements.
2. Preserve every part of the image that the user did NOT mention.
3. Use the minimum number of steps to achieve the goal.
4. Every step MUST have a non-empty "rationale".
5. If a requirement cannot be met with available tools, record it in
   unmet_requirements (do NOT make up a tool name).
6. Return ONLY valid JSON — no markdown, no explanations outside the JSON.

## Output schema
{
  "plan_id": "<uuid4>",
  "intent": "<one sentence describing user intent>",
  "confidence": <0.0-1.0, lower when prompt is ambiguous>,
  "steps": [
    {
      "step_id": "s1",
      "tool_name": "<name from available tools>",
      "params": { ... },
      "depends_on": [],
      "produces": null,
      "rationale": "<why this step is needed>"
    }
  ],
  "unmet_requirements": [
    {
      "need": "<description of unmet need>",
      "why_unmet": "<which tool capability is missing>",
      "suggested_tool_type": "opencv | generative | hybrid"
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Prompt builder helpers
# ---------------------------------------------------------------------------

def _render_tool_catalog(available_tools: List[Dict[str, Any]]) -> str:
    lines = []
    by_type: Dict[str, List] = {}
    for t in available_tools:
        by_type.setdefault(t["tool_type"], []).append(t)
    for ttype, tools in sorted(by_type.items()):
        lines.append(f"\n### {ttype.upper()} tools")
        for t in tools:
            schema_props = t["params_schema"].get("properties", {})
            param_descs = ", ".join(
                f'{k}: {v.get("description", "")}' for k, v in schema_props.items()
            )
            lines.append(f'  - **{t["name"]}**: {t["description"]}')
            if param_descs:
                lines.append(f'    params: {param_descs}')
    return "\n".join(lines)


def _render_ancestor_chain(ancestor_chain: List[Dict[str, Any]]) -> str:
    if not ancestor_chain:
        return "  (no previous edits — this is the first edit)"
    lines = []
    for i, node in enumerate(ancestor_chain):
        lines.append(
            f"  T-{len(ancestor_chain)-i}: prompt='{node.get('prompt', '')}' "
            f"| intent={node.get('intent', '')} "
            f"| summary={node.get('plan_summary', '')}"
        )
    return "\n".join(lines)


def _render_image_meta(image_meta: Dict[str, Any]) -> str:
    return (
        f"  size: {image_meta.get('width', '?')}×{image_meta.get('height', '?')} px\n"
        f"  dominant_colors: {image_meta.get('dominant_colors', [])}\n"
        f"  detected_objects: {image_meta.get('detected_objects', [])}\n"
        f"  scene_tags: {image_meta.get('scene_tags', [])}"
    )


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------

class PlannerAgent:
    """Generates Plan JSON from a user prompt."""

    def generate_plan(
        self,
        prompt: str,
        ancestor_chain: List[Dict[str, Any]],
        image_meta: Dict[str, Any],
        available_tools: List[Dict[str, Any]],
        feedback: Optional[str] = None,
        mode: str = "prod",
    ) -> Dict[str, Any]:
        """Generate a Plan JSON.

        Args:
            prompt:          The user's current edit request.
            ancestor_chain:  Ordered list of ancestor edits (root → parent).
                             Each entry: {prompt, intent, plan_summary}.
            image_meta:      {width, height, dominant_colors, detected_objects,
                             scene_tags}
            available_tools: Output of registry.list().
            feedback:        Validator rejection feedback from previous attempt.
            mode:            "prod" | "dev" — affects detail in
                             unmet_requirements.

        Returns:
            Plan JSON dict.
        """
        tool_catalog = _render_tool_catalog(available_tools)
        ancestor_ctx = _render_ancestor_chain(ancestor_chain)
        image_ctx = _render_image_meta(image_meta)

        retry_block = ""
        if feedback:
            retry_block = f"\n\n## Previous Attempt Was Rejected\n{feedback}\nFix the issues above.\n"

        mode_block = ""
        if mode == "dev":
            mode_block = (
                "\n## Mode: DEV\nIn dev mode, if a requirement is unmet, "
                "set steps to [] and fully describe unmet_requirements.\n"
            )

        user_prompt = f"""\
## User Request
{prompt}

## Available Tools
{tool_catalog}

## Current Image State
{image_ctx}

## Edit History (oldest → most recent)
{ancestor_ctx}
{retry_block}{mode_block}
Generate the Plan JSON now.  Remember: only tool names from the catalog above,
and plan_id must be a new UUID4."""

        raw = call_llm_json(user_prompt, system=_SYSTEM, temperature=0.0)

        # Ensure plan_id exists
        if not raw.get("plan_id"):
            raw["plan_id"] = str(uuid.uuid4())

        # Self-check: remove steps with invalid tool names
        valid_names = {t["name"] for t in available_tools}
        clean_steps = []
        extra_unmet = []
        for step in raw.get("steps", []):
            if step.get("tool_name") in valid_names:
                clean_steps.append(step)
            else:
                extra_unmet.append({
                    "need": f"tool '{step.get('tool_name')}' requested in plan",
                    "why_unmet": "tool not in registry",
                    "suggested_tool_type": "unknown",
                })
        raw["steps"] = clean_steps
        raw.setdefault("unmet_requirements", [])
        raw["unmet_requirements"].extend(extra_unmet)

        return raw
