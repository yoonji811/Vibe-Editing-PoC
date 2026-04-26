"""Session navigation tools — undo and reset.

These tools are registered in the Tool Registry so the Planner can select
them when the user's intent is to undo or reset.  They don't actually
process images; the Orchestrator intercepts them during plan execution
and moves the tree cursor instead.
"""
from typing import Any, Optional, Tuple

import numpy as np

from agents.tool_registry import Tool, registry


class UndoTool(Tool):
    name = "undo"
    tool_type = "session"
    description = (
        "Revert to the previous edit step. Use when the user wants to go back, "
        "undo the last change, or return to an earlier state. "
        "Examples: '이전으로 돌아가줘', '방금 한 거 취소', 'undo', 'go back'"
    )
    params_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        # Never actually called — Orchestrator intercepts undo steps
        return image, None


class ResetTool(Tool):
    name = "reset"
    tool_type = "session"
    description = (
        "Reset to the original image, discarding all edits. Use when the user "
        "wants to start over or go back to the very beginning. "
        "Examples: '원본으로 초기화', '처음으로', 'reset', 'start over'"
    )
    params_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        # Never actually called — Orchestrator intercepts reset steps
        return image, None


# Auto-register on import
registry.register(UndoTool())
registry.register(ResetTool())
