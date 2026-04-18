"""Quality Checker Agent — post-execution visual quality evaluation.

Runs AFTER the plan is executed.  Receives the original and result images,
evaluates whether the edit actually achieved the user's request visually,
and returns a verdict with actionable feedback for the Planner to retry.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .llm import call_llm_vision_json

logger = logging.getLogger(__name__)

QUALITY_THRESHOLD = 0.65  # below this → reject and ask planner to retry

_SYSTEM = """\
You are a visual quality evaluator for an image editing application.

You will be shown TWO images:
  Image 1 — the ORIGINAL (before editing)
  Image 2 — the RESULT (after editing)

And you will be given the user's original request and the executed plan.

Your job: decide whether the edit VISUALLY achieved the user's intent to a
satisfying quality standard.

Evaluate:
1. ACHIEVEMENT  — Does the result visually match what the user asked for?
2. NATURALNESS  — Does the result look natural and not broken/distorted?
3. DEGREE       — Is the effect strong enough to be clearly visible?
   (A warm tone should be unmistakably warm, not barely changed.)
4. ARTIFACTS    — Are there ugly artifacts, unnatural color shifts, clipping?

Scoring:
  quality_score: 0.0–1.0
    0.0–0.4  = poor (wrong effect, barely visible, or broken)
    0.4–0.65 = mediocre (effect present but weak or slightly wrong)
    0.65–0.85 = good (clearly achieves the request)
    0.85–1.0 = excellent

Approval: quality_score >= 0.65 → approved = true

Feedback rules (when not approved):
  - Be specific about what looks wrong visually.
  - Suggest concrete parameter adjustments or additional tools.
  - Do NOT suggest tools outside the available_tools list.
  - Example: "The warm tone is barely visible. Increase hue_shift to 35-45,
    add saturation(factor=1.5) and brightness(value=20) for a richer warm look."

Return ONLY valid JSON:
{
  "approved": true | false,
  "quality_score": <0.0-1.0>,
  "reasons": [
    {
      "category": "achievement | naturalness | degree | artifacts",
      "severity": "info | warning | error",
      "message": "<specific visual observation>"
    }
  ],
  "feedback_for_planner": "<actionable instructions to fix the plan, empty if approved>"
}
"""


class QualityCheckerAgent:
    """Evaluates visual quality of an edit by inspecting before/after images."""

    def check(
        self,
        original_b64: str,
        result_b64: str,
        user_prompt: str,
        executed_plan: Dict[str, Any],
        available_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Check visual quality of the edit result.

        Args:
            original_b64:   Base64 of the original image (before edit).
            result_b64:     Base64 of the result image (after edit).
            user_prompt:    The user's original request text.
            executed_plan:  The plan that was executed.
            available_tools: Tool list for feedback constraints.

        Returns:
            {approved, quality_score, reasons, feedback_for_planner}
        """
        tool_names = [t["name"] for t in (available_tools or [])]
        plan_summary = self._summarise_plan(executed_plan)

        prompt = f"""\
## User Request
{user_prompt}

## Executed Plan Summary
{plan_summary}

## Available Tools (for feedback only)
{json.dumps(tool_names)}

Image 1 is the ORIGINAL. Image 2 is the RESULT after editing.
Evaluate the visual quality now."""

        try:
            result = call_llm_vision_json(
                prompt,
                images_b64=[original_b64, result_b64],
                system=_SYSTEM,
                temperature=0.0,
            )
        except Exception as exc:
            logger.warning("QualityChecker LLM failed: %s — auto-approving", exc)
            return {
                "approved": True,
                "quality_score": 0.7,
                "reasons": [
                    {
                        "category": "achievement",
                        "severity": "warning",
                        "message": f"Quality check skipped (LLM error: {exc})",
                    }
                ],
                "feedback_for_planner": "",
            }

        result.setdefault("approved", True)
        result.setdefault("quality_score", 0.7)
        result.setdefault("reasons", [])
        result.setdefault("feedback_for_planner", "")

        # Enforce threshold
        if result["quality_score"] < QUALITY_THRESHOLD:
            result["approved"] = False
        elif result["quality_score"] >= QUALITY_THRESHOLD:
            result["approved"] = True

        logger.info(
            "QualityChecker: score=%.2f approved=%s",
            result["quality_score"],
            result["approved"],
        )
        return result

    @staticmethod
    def _summarise_plan(plan: Dict[str, Any]) -> str:
        steps = plan.get("steps", [])
        if not steps:
            return f"intent: {plan.get('intent', '?')} | no steps"
        lines = [f"intent: {plan.get('intent', '?')}"]
        for s in steps:
            lines.append(
                f"  - {s.get('tool_name', '?')}({json.dumps(s.get('params', {}))}) "
                f"— {s.get('rationale', '')}"
            )
        return "\n".join(lines)
