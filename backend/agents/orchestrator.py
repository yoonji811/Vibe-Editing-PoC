"""Orchestrator Agent — V2 pipeline with VLM analysis, Memory Agent, and Hydration.

V2 Pipeline (per edit request):
  1. Hydration      — if session not in memory, reconstruct edit tree from trajectory DB
  2. Base image     — resolve from in-memory store or caller-provided image_b64
  3. Prompt Analyze — detect if current prompt is a correction (implicit feedback)
  4. VLM Analyzer   — extract objective image state (noise, tone, scene, ...)
  5. Memory Agent   — search similar past success cases (RAG Top-K)
  6. Planner        — generate Plan JSON with RAG cases + negative constraints (no direct VLM)
  7. Execute        — run approved tool steps in topological order
  8. Record         — store edit node + VLM context in tree; return response
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

from .llm import call_llm_json
from .memory_agent import MemoryAgent
from .planner import PlannerAgent
from .quality_checker import QualityCheckerAgent
from .tool_registry import registry as _registry
from .validator import ValidatorAgent
from .vlm_analyzer import VLMAnalyzerAgent

# Ensure built-in tools are registered
import agents.tools  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory session store
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

# Track which sessions have been hydrated (avoid repeated DB hits)
_hydrated_sessions: set = set()

MAX_SESSIONS = 200


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
    ref = str(uuid.uuid4())
    _image_store[ref] = img.copy()
    return ref


def _load_image(ref: str) -> np.ndarray:
    if ref not in _image_store:
        raise KeyError(f"Image ref '{ref}' not found in store")
    return _image_store[ref].copy()


def _compute_image_meta(img: np.ndarray) -> Dict[str, Any]:
    h, w = img.shape[:2]
    thumb = cv2.resize(img, (64, 64))
    pixels = thumb.reshape(-1, 3).astype(np.float32)
    k = min(5, len(pixels))
    _, labels, centers = cv2.kmeans(
        pixels, k, None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0),
        3, cv2.KMEANS_RANDOM_CENTERS,
    )
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    dominant = [
        f"rgb({int(centers[i][2])},{int(centers[i][1])},{int(centers[i][0])})"
        for i in order[:3]
    ]
    return {"width": w, "height": h, "dominant_colors": dominant,
            "detected_objects": [], "scene_tags": []}


# ---------------------------------------------------------------------------
# Edit tree helpers
# ---------------------------------------------------------------------------

def _get_ancestor_chain(session_id: str, base_edit_id: Optional[str]) -> List[Dict[str, Any]]:
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
    return " → ".join(s.get("tool_name", "?") for s in steps)


def _summarise_params(plan: Dict[str, Any]) -> str:
    steps = plan.get("steps", [])
    if not steps:
        return ""
    parts = []
    for s in steps[:3]:
        tool = s.get("tool_name", "?")
        params = s.get("params", {})
        if params:
            kv = ", ".join(f"{k}={v}" for k, v in list(params.items())[:3])
            parts.append(f"{tool}({kv})")
        else:
            parts.append(tool)
    return " → ".join(parts)


# ---------------------------------------------------------------------------
# Hydration — reconstruct edit tree from trajectory DB
# ---------------------------------------------------------------------------

def _hydrate_session(session_id: str) -> None:
    """Load edit history from trajectory store into in-memory edit tree.

    Creates metadata-only nodes (no image_ref) so ancestor chain context
    is available to Planner even after a server restart.
    """
    if session_id in _hydrated_sessions:
        return
    _hydrated_sessions.add(session_id)

    try:
        from services.trajectory_store import get_edit_events
        events = get_edit_events(session_id)
    except Exception as exc:
        logger.warning("Hydration failed for session=%s: %s", session_id, exc)
        return

    prev_edit_id: Optional[str] = None
    for event in events:
        p = event.payload
        edit_id = event.event_id  # use trajectory event_id as edit_id proxy
        node: Dict[str, Any] = {
            "edit_id": edit_id,
            "parent_edit_id": prev_edit_id,
            "session_id": session_id,
            "prompt": p.user_text or "",
            "plan": p.plan or {},
            "source_image_context": p.source_image_context or {},
            "image_ref": None,  # pixel data not available after restart
            "created_at": event.timestamp.isoformat(),
            "satisfaction_score": p.satisfaction_score,
            "is_correction": p.is_correction,
        }
        _edit_trees[session_id][edit_id] = node
        _latest_edit[session_id] = edit_id
        prev_edit_id = edit_id

    if events:
        logger.info("Hydrated session=%s with %d nodes", session_id, len(events))


# ---------------------------------------------------------------------------
# Correction detection (Next Prompt Analyzer) — LLM-based
# ---------------------------------------------------------------------------

_CORRECTION_SYSTEM = """\
You analyze a user's new image editing request to decide whether it expresses
dissatisfaction with (or a desire to change) the previous edit result.

A correction is any message where the user:
- Dislikes or rejects the previous result
- Wants it redone, adjusted, or reversed
- Indicates the previous change was wrong, too strong, too weak, or off

A new independent request is one that adds something new or edits a different
aspect without negating the previous edit.

Return ONLY valid JSON — no markdown:
{"is_correction": true|false, "reason": "<one sentence>"}
"""


def _detect_correction(prompt: str, previous_node: Optional[Dict[str, Any]] = None) -> bool:
    """Use LLM to determine if the prompt is a correction of the previous edit.

    Falls back to False (non-fatal) if the LLM call fails or there is no
    previous edit to correct.
    """
    if previous_node is None:
        return False

    prev_intent = previous_node.get("plan", {}).get("intent", "(unknown)")
    prev_tools = " → ".join(
        s.get("tool_name", "?")
        for s in previous_node.get("plan", {}).get("steps", [])
    ) or "(none)"

    user_prompt = (
        f'Previous edit — Intent: "{prev_intent}" | Tools: {prev_tools}\n'
        f'User\'s new message: "{prompt}"\n\n'
        "Is the new message a correction or expression of dissatisfaction with the previous edit?"
    )
    try:
        result = call_llm_json(
            user_prompt,
            system=_CORRECTION_SYSTEM,
            model="gemini-2.5-flash",
            temperature=0.0,
        )
        return bool(result.get("is_correction", False))
    except Exception as exc:
        logger.warning("LLM correction analysis failed, defaulting to False: %s", exc)
        return False


def _build_failed_attempts(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract tool+params list from a plan node for negative constraints."""
    steps = node.get("plan", {}).get("steps", [])
    return [
        {
            "tool_used": s.get("tool_name", ""),
            "params": s.get("params", {}),
            "reason_for_failure": "User requested correction/undo.",
        }
        for s in steps[:3]  # cap at 3 to keep prompt manageable
    ]


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------

def _topological_sort(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    id_to_step = {s["step_id"]: s for s in steps}
    in_degree: Dict[str, int] = {s["step_id"]: 0 for s in steps}
    for step in steps:
        for dep in step.get("depends_on", []):
            in_degree[step["step_id"]] += 1

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
                    logger.warning("Step %s (%s) failed, retrying: %s", step_id, tool_name, exc)
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
    """Stateless orchestrator with VLM analysis, Memory Agent, and Hydration."""

    MAX_VALIDATOR_ATTEMPTS = 3

    def __init__(self) -> None:
        self._planner = PlannerAgent()
        self._validator = ValidatorAgent()
        self._quality_checker = QualityCheckerAgent()
        self._vlm = VLMAnalyzerAgent()
        self._memory = MemoryAgent()

    def process_edit(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        session_id: Optional[str] = None,
        base_edit_id: Optional[str] = None,
        use_validator: bool = False,
        mode: str = "prod",
    ) -> Dict[str, Any]:
        """Run the full V2 edit pipeline.

        Args:
            prompt:        User's edit request.
            image_b64:     Base64 image. Required for new sessions or after restart.
            session_id:    Existing session to continue. None = new session.
            base_edit_id:  Edit node to branch from. None = latest.
            use_validator: Whether to run Validator.
            mode:          "prod" | "dev".
        """
        t_start = time.time()

        # ------------------------------------------------------------------
        # 1. Session init + Hydration
        # ------------------------------------------------------------------
        if session_id is None:
            session_id = str(uuid.uuid4())

        # Resolve base edit node — prefer cursor, fall back to latest
        tree = _edit_trees[session_id]
        if not tree and session_id not in _hydrated_sessions:
            _hydrate_session(session_id)
            tree = _edit_trees[session_id]

        # ------------------------------------------------------------------
        # 2. Resolve base edit node and image
        # ------------------------------------------------------------------
        if base_edit_id is None:
            base_edit_id = _current_edit[session_id] or _latest_edit[session_id]

        parent_edit_id = base_edit_id

        # Use image from store if available (has pixel data), else fall back to provided b64
        if base_edit_id and base_edit_id in tree and tree[base_edit_id].get("image_ref"):
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
        # 3. Next Prompt Analyzer — detect correction / implicit feedback
        # ------------------------------------------------------------------
        previous_failed_attempts: List[Dict[str, Any]] = []
        previous_node = tree.get(parent_edit_id) if parent_edit_id else None
        is_correction = _detect_correction(prompt, previous_node)

        if is_correction and previous_node:
            previous_failed_attempts = _build_failed_attempts(previous_node)
            logger.info(
                "Correction detected session=%s; blocking %d tools",
                session_id, len(previous_failed_attempts),
            )

        # ------------------------------------------------------------------
        # 4. VLM Analysis
        # ------------------------------------------------------------------
        result_b64_for_vlm = _cv2_to_b64(base_image)
        source_image_context: Dict[str, Any] = {}
        t_vlm = time.time()
        try:
            source_image_context = self._vlm.analyze(result_b64_for_vlm)
        except Exception as exc:
            logger.warning("VLM analysis skipped: %s", exc)
        t_vlm_ms = int((time.time() - t_vlm) * 1000)

        # ------------------------------------------------------------------
        # 5. Memory Agent — retrieve similar success cases
        # ------------------------------------------------------------------
        retrieved_cases: List[Dict[str, Any]] = []
        t_mem = time.time()
        try:
            retrieved_cases = self._memory.search_similar(
                user_text=prompt,
                vlm_context=source_image_context,
                is_correction=is_correction,
                top_k=3,
            )
        except Exception as exc:
            logger.warning("Memory search skipped: %s", exc)
        t_mem_ms = int((time.time() - t_mem) * 1000)

        # ------------------------------------------------------------------
        # 6. Build Planner context
        # ------------------------------------------------------------------
        ancestor_chain = _get_ancestor_chain(session_id, parent_edit_id)
        ancestor_context = [
            {
                "prompt": node["prompt"],
                "intent": node.get("plan", {}).get("intent", ""),
                "plan_summary": _summarise_plan(node.get("plan", {})),
                "params_used": _summarise_params(node.get("plan", {})),
                "is_correction": node.get("is_correction", False),
                "satisfaction": node.get("satisfaction_score"),
            }
            for node in ancestor_chain
        ]
        image_meta = _compute_image_meta(base_image)
        available_tools = _registry.list()

        # ------------------------------------------------------------------
        # 7. Planner → (optional Validator) → Execute
        # ------------------------------------------------------------------
        validator_verdict: Optional[Dict[str, Any]] = None
        validator_attempts = 0
        feedback: Optional[str] = None
        plan: Dict[str, Any] = {}
        t_planner_ms = 0
        t_validator_ms = 0

        for attempt in range(self.MAX_VALIDATOR_ATTEMPTS):
            t_plan = time.time()
            plan = self._planner.generate_plan(
                prompt=prompt,
                ancestor_chain=ancestor_context,
                image_meta=image_meta,
                available_tools=available_tools,
                feedback=feedback,
                mode=mode,
                retrieved_cases=retrieved_cases,
                previous_failed_attempts=previous_failed_attempts,
            )
            t_planner_ms += int((time.time() - t_plan) * 1000)

            if not plan or not plan.get("steps"):
                break

            if not use_validator:
                break

            t_val = time.time()
            verdict = self._validator.validate(
                plan=plan,
                original_prompt=prompt,
                available_tools=available_tools,
                ancestor_chain=ancestor_context,
                attempt_number=attempt + 1,
            )
            t_validator_ms += int((time.time() - t_val) * 1000)
            validator_attempts += 1
            validator_verdict = verdict if isinstance(verdict, dict) else dict(verdict)

            if verdict.get("approved"):
                break

            feedback = verdict.get("feedback_for_planner", "")
            logger.info(
                "Validator rejected attempt %d session=%s: %s",
                attempt + 1, session_id, feedback,
            )

        if not plan or not plan.get("steps"):
            return {
                "session_id": session_id,
                "edit_id": None,
                "parent_edit_id": parent_edit_id,
                "result_image_b64": None,
                "executed_plan": plan,
                "validator_verdict": validator_verdict,
                "validator_attempts": validator_attempts,
                "quality_verdict": None,
                "step_logs": [],
                "source_image_context": source_image_context,
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
        t_exec = time.time()
        result_image, exec_errors, step_logs = _execute_plan(plan, base_image)
        t_exec_ms = int((time.time() - t_exec) * 1000)
        result_b64 = _cv2_to_b64(result_image)

        # ------------------------------------------------------------------
        # 8. Record new edit node
        # ------------------------------------------------------------------
        edit_id = str(uuid.uuid4())
        image_ref = _store_image(result_image)

        node: Dict[str, Any] = {
            "edit_id": edit_id,
            "parent_edit_id": parent_edit_id,
            "session_id": session_id,
            "prompt": prompt,
            "plan": plan,
            "source_image_context": source_image_context,
            "validator_verdict": validator_verdict,
            "quality_verdict": None,
            "is_correction": is_correction,
            "image_ref": image_ref,
            "created_at": datetime.utcnow().isoformat(),
        }
        tree[edit_id] = node
        _latest_edit[session_id] = edit_id
        _current_edit[session_id] = edit_id

        latency_ms = int((time.time() - t_start) * 1000)
        explanation = plan.get("intent", "편집이 완료됐습니다.")

        timing_ms = {
            "vlm": t_vlm_ms,
            "memory": t_mem_ms,
            "planner": t_planner_ms,
            "validator": t_validator_ms,
            "tool_exec": t_exec_ms,
            "total": latency_ms,
        }

        logger.info(
            "Edit completed session=%s edit=%s | vlm=%dms mem=%dms plan=%dms val=%dms exec=%dms total=%dms",
            session_id, edit_id,
            t_vlm_ms, t_mem_ms, t_planner_ms, t_validator_ms, t_exec_ms, latency_ms,
        )

        return {
            "session_id": session_id,
            "edit_id": edit_id,
            "parent_edit_id": parent_edit_id,
            "result_image_b64": result_b64,
            "executed_plan": plan,
            "validator_verdict": validator_verdict,
            "validator_attempts": validator_attempts,
            "quality_verdict": None,
            "step_logs": step_logs,
            "source_image_context": source_image_context,
            "retrieved_cases": retrieved_cases,
            "is_correction": is_correction,
            "explanation": explanation,
            "errors": exec_errors,
            "latency_ms": latency_ms,
            "timing_ms": timing_ms,
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
        _hydrated_sessions.discard(session_id)

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
