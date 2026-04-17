"""Validator Agent — 2-layer plan validation.

Layer 1 (static, no LLM): schema / tool-existence / DAG checks.
Layer 2 (LLM): semantic coverage, over-editing, history consistency.

Progressive Leniency:
  attempt 1 → strict  (all errors + major warnings)
  attempt 2 → medium  (errors only)
  attempt 3 → lenient (feasibility errors only)
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .llm import call_llm_json

# ---------------------------------------------------------------------------
# Minimal JSON-schema param validator (no external jsonschema dependency)
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "integer": int,
    "number": (int, float),
    "string": str,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _validate_params(schema: dict, params: dict) -> List[str]:
    """Return list of error strings.  Empty list = valid."""
    errors: List[str] = []
    props = schema.get("properties", {})
    required = schema.get("required", [])

    for key in required:
        if key not in params:
            errors.append(f"Missing required param '{key}'")

    for key, value in params.items():
        if key not in props:
            continue  # unknown keys are tolerated
        spec = props[key]
        ptype = spec.get("type")
        if ptype and ptype in _TYPE_MAP:
            expected = _TYPE_MAP[ptype]
            if not isinstance(value, expected):
                errors.append(
                    f"Param '{key}' must be {ptype}, got {type(value).__name__}"
                )
                continue
        if "minimum" in spec and isinstance(value, (int, float)):
            if value < spec["minimum"]:
                errors.append(
                    f"Param '{key}'={value} below minimum {spec['minimum']}"
                )
        if "maximum" in spec and isinstance(value, (int, float)):
            if value > spec["maximum"]:
                errors.append(
                    f"Param '{key}'={value} above maximum {spec['maximum']}"
                )
        if "enum" in spec:
            if value not in spec["enum"]:
                errors.append(
                    f"Param '{key}'={value!r} not in allowed values {spec['enum']}"
                )
    return errors


# ---------------------------------------------------------------------------
# LLM system prompt for semantic validation
# ---------------------------------------------------------------------------

_VALIDATOR_SYSTEM = """\
You are a strict but fair image editing plan validator.

Your job: decide if a Plan JSON faithfully and efficiently fulfills the
user's request, given the edit history.

Evaluate:
1. INTENT  — Does plan.intent capture the user's main goal?
2. COVERAGE — Is each user requirement covered by at least one step?
3. REDUNDANCY — Are there steps the user did NOT ask for?
4. CONSISTENCY — Does the plan correctly assume current image state
   (e.g., if background was already removed, don't re-remove it)?

Approval policy (varies by attempt_number):
  1 → strict: reject on any error AND major warnings
  2 → medium: reject on errors only
  3 → lenient: reject only if plan is literally un-executable

Feedback rules:
  - Be specific: name the step_id, describe the problem, state the fix.
  - Bad: "plan misses the point"
  - Good: "step s2 applies blur globally, but user asked for background only.
    Add params: {region: 'background'} or use a region-aware tool."
  - Do NOT suggest tools that are not in available_tools.
  - Do NOT reject based on aesthetic preference.

Return ONLY valid JSON:
{
  "approved": true | false,
  "reasons": [
    {
      "category": "intent | feasibility | redundancy | consistency",
      "severity": "info | warning | error",
      "message": "<specific issue>",
      "step_id": "<step_id or null>"
    }
  ],
  "feedback_for_planner": "<actionable fix instructions, empty string if approved>"
}
"""


# ---------------------------------------------------------------------------
# ValidatorAgent
# ---------------------------------------------------------------------------

class ValidatorAgent:
    """Validates a plan before execution."""

    def validate(
        self,
        plan: Dict[str, Any],
        original_prompt: str,
        ancestor_chain: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]],
        attempt_number: int = 1,
    ) -> Dict[str, Any]:
        """Validate a plan.

        Returns:
            {
              "approved": bool,
              "reasons": [...],
              "feedback_for_planner": str
            }
        """
        # -------------------------------------------------------------------
        # Layer 1: Static checks (no LLM)
        # -------------------------------------------------------------------
        static_errors = self._layer1_static(plan, available_tools)
        if static_errors:
            return {
                "approved": False,
                "reasons": [
                    {
                        "category": "feasibility",
                        "severity": "error",
                        "message": msg,
                        "step_id": None,
                    }
                    for msg in static_errors
                ],
                "feedback_for_planner": (
                    "Fix these structural issues before re-generating:\n"
                    + "\n".join(f"- {e}" for e in static_errors)
                ),
            }

        # -------------------------------------------------------------------
        # Layer 2: Semantic (LLM)
        # -------------------------------------------------------------------
        return self._layer2_semantic(
            plan, original_prompt, ancestor_chain, available_tools, attempt_number
        )

    # ------------------------------------------------------------------
    # Layer 1 helpers
    # ------------------------------------------------------------------

    def _layer1_static(
        self,
        plan: Dict[str, Any],
        available_tools: List[Dict[str, Any]],
    ) -> List[str]:
        errors: List[str] = []
        tool_map = {t["name"]: t for t in available_tools}
        steps = plan.get("steps", [])

        # Plan schema basics
        if not isinstance(steps, list):
            errors.append("plan.steps must be a list")
            return errors

        step_ids = set()
        for step in steps:
            sid = step.get("step_id")
            if not sid:
                errors.append(f"Step missing step_id: {step}")
                continue
            if sid in step_ids:
                errors.append(f"Duplicate step_id: {sid}")
            step_ids.add(sid)

            # Tool existence
            tool_name = step.get("tool_name")
            if tool_name not in tool_map:
                errors.append(
                    f"Step {sid}: tool '{tool_name}' not in registry"
                )
                continue

            # Param schema validation
            tool_schema = tool_map[tool_name]["params_schema"]
            param_errors = _validate_params(
                tool_schema, step.get("params", {})
            )
            for pe in param_errors:
                errors.append(f"Step {sid} ({tool_name}): {pe}")

        # DAG: no cycles, no dangling depends_on
        for step in steps:
            for dep in step.get("depends_on", []):
                if dep not in step_ids:
                    errors.append(
                        f"Step {step.get('step_id')}: depends_on '{dep}' "
                        "does not exist"
                    )

        # Cycle detection (topological sort)
        adj: Dict[str, List[str]] = {
            s["step_id"]: s.get("depends_on", []) for s in steps
        }
        visited: set = set()
        stack: set = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            stack.add(node)
            for nb in adj.get(node, []):
                if nb not in visited:
                    if has_cycle(nb):
                        return True
                elif nb in stack:
                    return True
            stack.discard(node)
            return False

        for sid in list(step_ids):
            if sid not in visited:
                if has_cycle(sid):
                    errors.append("Cycle detected in step dependency graph")
                    break

        return errors

    # ------------------------------------------------------------------
    # Layer 2 helper
    # ------------------------------------------------------------------

    def _layer2_semantic(
        self,
        plan: Dict[str, Any],
        original_prompt: str,
        ancestor_chain: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]],
        attempt_number: int,
    ) -> Dict[str, Any]:
        tool_names = [t["name"] for t in available_tools]
        ancestor_text = ""
        if ancestor_chain:
            parts = []
            for node in ancestor_chain:
                parts.append(
                    f"- prompt: '{node.get('prompt', '')}' | "
                    f"intent: {node.get('intent', '')} | "
                    f"summary: {node.get('plan_summary', '')}"
                )
            ancestor_text = "\n".join(parts)
        else:
            ancestor_text = "(no previous edits)"

        user_prompt = f"""\
## User Prompt
{original_prompt}

## Edit History (oldest first)
{ancestor_text}

## Available Tools
{json.dumps(tool_names)}

## Plan to Validate
{json.dumps(plan, ensure_ascii=False, indent=2)}

## Attempt Number
{attempt_number}

Validate this plan now."""

        try:
            result = call_llm_json(
                user_prompt, system=_VALIDATOR_SYSTEM, temperature=0.0
            )
        except Exception as exc:
            # LLM failure → approve with warning (don't block execution)
            return {
                "approved": True,
                "reasons": [
                    {
                        "category": "feasibility",
                        "severity": "warning",
                        "message": f"Validator LLM failed ({exc}); auto-approved",
                        "step_id": None,
                    }
                ],
                "feedback_for_planner": "",
            }

        # Ensure required keys exist
        result.setdefault("approved", True)
        result.setdefault("reasons", [])
        result.setdefault("feedback_for_planner", "")
        return result
