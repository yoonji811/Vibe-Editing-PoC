"""Orchestrator Agent — manages edit sessions and runs the full pipeline.

Responsibilities:
  1. Session & edit-history tree management (stateless instance,
     state in external store)
  2. Assemble Planner context
  3. Conditionally invoke Validator (use_validator flag)
  4. Execute approved plan step-by-step
  5. Record new node in edit tree
  6. Return result to caller

The Orchestrator is the only code that touches the Tool Registry at
runtime.  It treats tools as black boxes: just calls tool.run().
"""
from __future__ import annotations

import base64
import hashlib
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .planner import PlannerAgent
from .quality_checker import QualityCheckerAgent
from .tool_registry import registry as _registry
from .validator import ValidatorAgent

# Ensure built-in tools are registered
import agents.tools  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory session store (PoC — replace with DB for production)
# ---------------------------------------------------------------------------

# {session_id: {edit_id: EditNode}}
_edit_trees: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

# {session_id: latest_edit_id}  — most recently created node (for linear fallback)
_latest_edit: Dict[str, Optional[str]] = defaultdict(lambda: None)

# {session_id: current_edit_id}  — the "cursor" (what the user is viewing)
_current_edit: Dict[str, Optional[str]] = defaultdict(lambda: None)

# {session_id: root_edit_id}  — the root node (original image)
_root_edit: Dict[str, Optional[str]] = defaultdict(lambda: None)

# Image store: {image_ref: np.ndarray}
_image_store: Dict[str, np.ndarray] = {}

MAX_SESSIONS = 200  # rough cap to prevent runaway memory


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _b64_to_cv2(b64: str) -> np.ndarray:
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode base64 image")
    return img


def _cv2_to_b64(img: np.ndarray, fmt: str = ".jpg") -> str:
    ok, buf = cv2.imencode(fmt, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("Failed to encode image to base64")
    return base64.b64encode(buf).decode("utf-8")


def _store_image(img: np.ndarray) -> str:
    """Save image to in-memory store, return image_ref key."""
    ref = str(uuid.uuid4())
    _image_store[ref] = img.copy()
    return ref


def _load_image(ref: str) -> np.ndarray:
    if ref not in _image_store:
        raise KeyError(f"Image ref '{ref}' not found in store")
    return _image_store[ref].copy()


def _compute_image_meta(img: np.ndarray) -> Dict[str, Any]:
    """Extract lightweight image metadata for Planner context."""
    h, w = img.shape[:2]

    # Dominant colours via k-means on a tiny thumbnail
    thumb = cv2.resize(img, (64, 64))
    pixels = thumb.reshape(-1, 3).astype(np.float32)
    k = min(5, len(pixels))
    _, labels, centers = cv2.kmeans(
        pixels,
        k,
        None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0),
        3,
        cv2.KMEANS_RANDOM_CENTERS,
    )
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    dominant = []
    for i in order[:3]:
        b, g, r = centers[i].astype(int)
        dominant.append(f"rgb({r},{g},{b})")

    return {
        "width": w,
        "height": h,
        "dominant_colors": dominant,
        "detected_objects": [],  # requires separate model
        "scene_tags": [],        # requires separate model
    }


# ---------------------------------------------------------------------------
# Edit tree helpers
# ---------------------------------------------------------------------------

def _get_ancestor_chain(
    session_id: str, base_edit_id: Optional[str]
) -> List[Dict[str, Any]]:
    """Return ancestor nodes from root → base_edit_id (inclusive)."""
    tree = _edit_trees.get(session_id, {})
    if not tree or base_edit_id is None:
        return []
    chain: List[Dict[str, Any]] = []
    current = base_edit_id
    while current is not None:
        node = tree.get(current)
        if node is None:
            break
        chain.append(node)
        current = node.get("parent_edit_id")
    chain.reverse()
    return chain


def _summarise_plan(plan: Dict[str, Any]) -> str:
    steps = plan.get("steps", [])
    if not steps:
        return "(empty plan)"
    names = [s.get("tool_name", "?") for s in steps]
    return " → ".join(names)


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------

def _topological_sort(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Kahn's algorithm — return steps in execution order."""
    id_to_step = {s["step_id"]: s for s in steps}
    in_degree: Dict[str, int] = {s["step_id"]: 0 for s in steps}
    for step in steps:
        for dep in step.get("depends_on", []):
            in_degree[step["step_id"]] = in_degree[step["step_id"]] + 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    result: List[Dict[str, Any]] = []
    while queue:
        sid = queue.pop(0)
        result.append(id_to_step[sid])
        for step in steps:
            if sid in step.get("depends_on", []):
                in_degree[step["step_id"]] -= 1
                if in_degree[step["step_id"]] == 0:
                    queue.append(step["step_id"])
    return result


def _execute_plan(
    plan: Dict[str, Any], base_image: np.ndarray
) -> Tuple[np.ndarray, List[str], List[Dict[str, Any]]]:
    """Execute all plan steps.

    Returns:
        (final_image, list_of_execution_errors, step_logs)
    """
    current_image = base_image.copy()
    produced_artifacts: Dict[str, Any] = {}
    errors: List[str] = []
    step_logs: List[Dict[str, Any]] = []

    try:
        steps = _topological_sort(plan.get("steps", []))
    except Exception as exc:
        errors.append(f"Topological sort failed: {exc}")
        return current_image, errors, step_logs

    for step in steps:
        tool_name = step.get("tool_name", "")
        params = dict(step.get("params", {}))
        produces_key = step.get("produces")
        step_id = step.get("step_id", "?")
        t_step = time.time()

        # Substitute artifact references in params
        for pk, pv in list(params.items()):
            if isinstance(pv, str) and pv in produced_artifacts:
                params[pk] = produced_artifacts[pv]

        log: Dict[str, Any] = {
            "step_id": step_id,
            "tool_name": tool_name,
            "params": params,
            "rationale": step.get("rationale", ""),
            "status": "pending",
            "error": None,
            "latency_ms": 0,
        }

        try:
            tool = _registry.get(tool_name)
        except KeyError as exc:
            log["status"] = "error"
            log["error"] = str(exc)
            log["latency_ms"] = int((time.time() - t_step) * 1000)
            step_logs.append(log)
            errors.append(str(exc))
            continue

        # Execute with one retry
        for attempt in range(2):
            try:
                result_img, produced = tool.run(current_image, **params)
                current_image = result_img
                if produces_key is not None and produced is not None:
                    produced_artifacts[produces_key] = produced
                log["status"] = "success"
                break
            except Exception as exc:
                if attempt == 0:
                    logger.warning(
                        "Step %s (%s) failed, retrying: %s",
                        step_id, tool_name, exc,
                    )
                else:
                    log["status"] = "error"
                    log["error"] = str(exc)
                    errors.append(f"Step {step_id} ({tool_name}) failed: {exc}")

        log["latency_ms"] = int((time.time() - t_step) * 1000)
        step_logs.append(log)

    return current_image, errors, step_logs


# ---------------------------------------------------------------------------
# OrchestratorAgent
# ---------------------------------------------------------------------------

class OrchestratorAgent:
    """Stateless orchestrator.  All state lives in module-level dicts."""

    MAX_VALIDATOR_ATTEMPTS = 3
    MAX_QUALITY_ATTEMPTS = 2

    def __init__(self) -> None:
        self._planner = PlannerAgent()
        self._validator = ValidatorAgent()
        self._quality_checker = QualityCheckerAgent()

    def process_edit(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        session_id: Optional[str] = None,
        base_edit_id: Optional[str] = None,
        use_validator: bool = True,
        mode: str = "prod",
    ) -> Dict[str, Any]:
        """Run the full edit pipeline.

        Args:
            prompt:        User's edit request.
            image_b64:     Base64 image.  Required when starting a new session
                           or when base_edit_id is not found.
            session_id:    Existing session to continue.  None = new session.
            base_edit_id:  Which edit node to branch from.  None = latest.
            use_validator: Whether to run Validator between Planner and execution.
            mode:          "prod" | "dev" passed to Planner.

        Returns:
            {session_id, edit_id, parent_edit_id, result_image_b64,
             executed_plan, explanation, errors}
        """
        t_start = time.time()

        # ------------------------------------------------------------------
        # 1. Resolve session and base image
        # ------------------------------------------------------------------
        if session_id is None:
            session_id = str(uuid.uuid4())

        # Resolve base edit node — prefer cursor, fall back to latest
        tree = _edit_trees[session_id]
        if base_edit_id is None:
            base_edit_id = _current_edit[session_id] or _latest_edit[session_id]

        parent_edit_id = base_edit_id

        # Resolve base image
        if base_edit_id and base_edit_id in tree:
            base_image = _load_image(tree[base_edit_id]["image_ref"])
        elif image_b64:
            base_image = _b64_to_cv2(image_b64)
        else:
            return {
                "session_id": session_id,
                "edit_id": None,
                "parent_edit_id": None,
                "result_image_b64": None,
                "executed_plan": None,
                "explanation": "No base image found for this session.",
                "errors": ["Provide image_b64 for a new session."],
            }

        # ------------------------------------------------------------------
        # 2. Build Planner context
        # ------------------------------------------------------------------
        ancestor_chain = _get_ancestor_chain(session_id, parent_edit_id)
        ancestor_context = [
            {
                "prompt": node["prompt"],
                "intent": node.get("plan", {}).get("intent", ""),
                "plan_summary": _summarise_plan(node.get("plan", {})),
            }
            for node in ancestor_chain
        ]
        image_meta = _compute_image_meta(base_image)
        available_tools = _registry.list()

        # ------------------------------------------------------------------
        # 3. Planner → Execute (Validator/QualityChecker disabled for speed)
        # ------------------------------------------------------------------
        plan = self._planner.generate_plan(
            prompt=prompt,
            ancestor_chain=ancestor_context,
            image_meta=image_meta,
            available_tools=available_tools,
            mode=mode,
        )

        if not plan or not plan.get("steps"):
            return {
                "session_id": session_id,
                "edit_id": None,
                "parent_edit_id": parent_edit_id,
                "result_image_b64": None,
                "executed_plan": plan,
                "validator_verdict": None,
                "validator_attempts": 0,
                "quality_verdict": None,
                "step_logs": [],
                "explanation": "Plan could not be generated.",
                "errors": ["Planner returned empty plan."],
            }

        # ------------------------------------------------------------------
        # 3a. Intercept session tools (undo / reset)
        # ------------------------------------------------------------------
        steps = plan.get("steps", [])
        session_tool = None
        if len(steps) == 1 and steps[0].get("tool_name") in ("undo", "reset"):
            session_tool = steps[0]["tool_name"]

        if session_tool == "undo":
            undo_result = self.undo(session_id)
            latency_ms = int((time.time() - t_start) * 1000)
            if undo_result:
                return {
                    "session_id": session_id,
                    "edit_id": undo_result["edit_id"],
                    "parent_edit_id": parent_edit_id,
                    "result_image_b64": undo_result["image_b64"],
                    "executed_plan": plan,
                    "explanation": "이전 상태로 되돌렸습니다.",
                    "errors": [],
                    "latency_ms": latency_ms,
                    "session_action": "undo",
                }
            else:
                return {
                    "session_id": session_id,
                    "edit_id": _current_edit.get(session_id),
                    "parent_edit_id": parent_edit_id,
                    "result_image_b64": _cv2_to_b64(base_image),
                    "executed_plan": plan,
                    "explanation": "되돌릴 편집 이력이 없습니다.",
                    "errors": [],
                    "latency_ms": latency_ms,
                    "session_action": "undo",
                }

        if session_tool == "reset":
            root_id = _root_edit.get(session_id)
            latency_ms = int((time.time() - t_start) * 1000)
            if root_id:
                nav_result = self.navigate(session_id, root_id)
                return {
                    "session_id": session_id,
                    "edit_id": root_id,
                    "parent_edit_id": None,
                    "result_image_b64": nav_result["image_b64"] if nav_result else _cv2_to_b64(base_image),
                    "executed_plan": plan,
                    "explanation": "원본 이미지로 초기화했습니다.",
                    "errors": [],
                    "latency_ms": latency_ms,
                    "session_action": "reset",
                }
            else:
                return {
                    "session_id": session_id,
                    "edit_id": _current_edit.get(session_id),
                    "parent_edit_id": parent_edit_id,
                    "result_image_b64": _cv2_to_b64(base_image),
                    "executed_plan": plan,
                    "explanation": "원본 이미지를 찾을 수 없습니다.",
                    "errors": [],
                    "latency_ms": latency_ms,
                    "session_action": "reset",
                }

        # ------------------------------------------------------------------
        # 3b. Execute normal plan
        # ------------------------------------------------------------------
        result_image, exec_errors, step_logs = _execute_plan(plan, base_image)
        result_b64 = _cv2_to_b64(result_image)

        # ------------------------------------------------------------------
        # 4. Record new edit node in tree
        # ------------------------------------------------------------------
        edit_id = str(uuid.uuid4())
        image_ref = _store_image(result_image)

        node: Dict[str, Any] = {
            "edit_id": edit_id,
            "parent_edit_id": parent_edit_id,
            "session_id": session_id,
            "prompt": prompt,
            "plan": plan,
            "validator_verdict": None,
            "quality_verdict": None,
            "image_ref": image_ref,
            "created_at": datetime.utcnow().isoformat(),
        }
        tree[edit_id] = node
        _latest_edit[session_id] = edit_id
        _current_edit[session_id] = edit_id

        # ------------------------------------------------------------------
        # 5. Build response
        # ------------------------------------------------------------------
        latency_ms = int((time.time() - t_start) * 1000)
        explanation = plan.get("intent", "편집이 완료됐습니다.")

        logger.info(
            "Edit completed session=%s edit=%s latency=%dms",
            session_id, edit_id, latency_ms,
        )

        return {
            "session_id": session_id,
            "edit_id": edit_id,
            "parent_edit_id": parent_edit_id,
            "result_image_b64": result_b64,
            "executed_plan": plan,
            "validator_verdict": None,
            "validator_attempts": 0,
            "quality_verdict": None,
            "step_logs": step_logs,
            "explanation": explanation,
            "errors": exec_errors,
            "latency_ms": latency_ms,
        }

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset_session(self, session_id: str) -> None:
        """Clear the orchestrator's internal state for a session.

        Only used when the session is truly deleted / new session started.
        """
        _latest_edit[session_id] = None
        _current_edit[session_id] = None
        _root_edit[session_id] = None
        _edit_trees[session_id].clear()

    def register_root_image(self, session_id: str, image_b64: str) -> str:
        """Register the original image as the root node of the edit tree.

        Called once when a session is created. Returns the root edit_id.
        """
        img = _b64_to_cv2(image_b64)
        image_ref = _store_image(img)
        edit_id = str(uuid.uuid4())

        node: Dict[str, Any] = {
            "edit_id": edit_id,
            "parent_edit_id": None,
            "session_id": session_id,
            "prompt": "original",
            "plan": {},
            "validator_verdict": None,
            "quality_verdict": None,
            "image_ref": image_ref,
            "created_at": datetime.utcnow().isoformat(),
        }
        _edit_trees[session_id][edit_id] = node
        _latest_edit[session_id] = edit_id
        _current_edit[session_id] = edit_id
        _root_edit[session_id] = edit_id

        logger.info("Registered root image for session=%s edit=%s", session_id, edit_id)
        return edit_id

    def undo(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Move the cursor to the parent of the current node.

        Does NOT delete any nodes — the tree is preserved.
        Returns {edit_id, image_b64} of the parent node, or None if at root.
        """
        current_id = _current_edit.get(session_id)
        if not current_id:
            return None

        tree = _edit_trees.get(session_id, {})
        current_node = tree.get(current_id)
        if not current_node:
            return None

        parent_id = current_node.get("parent_edit_id")
        if not parent_id:
            return None  # Already at root

        parent_node = tree.get(parent_id)
        if not parent_node:
            return None

        _current_edit[session_id] = parent_id
        image_b64 = _cv2_to_b64(_load_image(parent_node["image_ref"]))
        return {
            "edit_id": parent_id,
            "image_b64": image_b64,
            "prompt": parent_node["prompt"],
        }

    def navigate(self, session_id: str, edit_id: str) -> Optional[Dict[str, Any]]:
        """Move the cursor to any node in the tree.

        Returns {edit_id, image_b64} of the target node, or None if not found.
        """
        tree = _edit_trees.get(session_id, {})
        node = tree.get(edit_id)
        if not node:
            return None

        _current_edit[session_id] = edit_id
        image_b64 = _cv2_to_b64(_load_image(node["image_ref"]))
        return {
            "edit_id": edit_id,
            "image_b64": image_b64,
            "prompt": node["prompt"],
        }

    def get_root_edit_id(self, session_id: str) -> Optional[str]:
        """Return the root node's edit_id for a session."""
        return _root_edit.get(session_id)

    def get_current_edit_id(self, session_id: str) -> Optional[str]:
        """Return the current cursor edit_id for a session."""
        return _current_edit.get(session_id)

    # ------------------------------------------------------------------
    # Tree inspection
    # ------------------------------------------------------------------

    def get_tree(self, session_id: str) -> Dict[str, Any]:
        """Return the full edit tree for a session."""
        tree = _edit_trees.get(session_id, {})

        # Build children_ids from parent links
        children_map: Dict[str, List[str]] = defaultdict(list)
        for node in tree.values():
            pid = node.get("parent_edit_id")
            if pid:
                children_map[pid].append(node["edit_id"])

        nodes = []
        for node in tree.values():
            nodes.append({
                "edit_id": node["edit_id"],
                "parent_edit_id": node["parent_edit_id"],
                "prompt": node["prompt"],
                "intent": node.get("plan", {}).get("intent", ""),
                "created_at": node["created_at"],
                "children_ids": children_map.get(node["edit_id"], []),
            })
        return {
            "session_id": session_id,
            "current_edit_id": _current_edit.get(session_id),
            "root_edit_id": _root_edit.get(session_id),
            "nodes": nodes,
        }
