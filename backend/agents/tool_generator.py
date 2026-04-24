"""Tool Generator — offline batch agent.

NOT part of the runtime pipeline.  Run this as a CLI to:
  1. Analyse session logs for tool gaps (unmet_requirements + repeat patterns)
  2. Generate Python tool code with LLM
  3. Static-analyse generated code for forbidden imports/calls
  4. Run sandbox smoke tests
  5. Register passing tools in tools/generated/registry.json

Usage:
    python -m agents.tool_generator --help
    python -m agents.tool_generator analyse --log-dir ./data/trajectories
    python -m agents.tool_generator generate --spec "세피아 필터 tool"
    python -m agents.tool_generator run --all
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GENERATED_DIR = Path(__file__).parent / "tools" / "generated"
GENERATED_REGISTRY = GENERATED_DIR / "registry.json"

FORBIDDEN_IMPORTS = frozenset(
    ["os", "sys", "subprocess", "socket", "requests",
     "urllib", "pickle", "shutil"]
)
FORBIDDEN_CALLS = frozenset(
    ["eval", "exec", "compile", "__import__", "open"]
)
ALLOWED_IMPORTS = frozenset(["cv2", "numpy", "np", "math", "typing"])

# ---------------------------------------------------------------------------
# Session log analysis
# ---------------------------------------------------------------------------


def _load_trajectories(log_dir: Path) -> List[Dict[str, Any]]:
    """Load all trajectory JSON files from log_dir."""
    trajs = []
    for f in sorted(log_dir.glob("*.json")):
        try:
            trajs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return trajs


# ---------------------------------------------------------------------------
# Negative feedback analysis
# ---------------------------------------------------------------------------


def _build_feedback_spec(
    user_text: str,
    intent: str,
    tools_used: List[str],
    unmet: List[Any],
    vlm_context: Dict[str, Any],
) -> str:
    """Build a rich tool-spec string from a failed edit event."""
    lines = [
        f'User request (unsatisfied): "{user_text}"',
        f'Interpreted intent: "{intent}"',
        f'Tools attempted: {", ".join(tools_used) if tools_used else "none"}',
    ]
    if unmet:
        lines.append(f"Unmet requirements: {unmet}")
    if vlm_context:
        summary = json.dumps(vlm_context, ensure_ascii=False)[:300]
        lines.append(f"Image context: {summary}")
    lines.append(
        "\nThe user gave negative feedback (thumbs_down) — the result was unsatisfactory. "
        "Generate a new image editing tool that would better fulfill this request. "
        "Focus on what was missing or visually inadequate in the previous attempt."
    )
    return "\n".join(lines)


def analyse_negative_feedback(log_dir: Path) -> List[Dict[str, Any]]:
    """Scan trajectory files for events with negative satisfaction_score (thumbs_down).

    Returns one candidate dict per unsatisfied edit event:
      {signal, description, frequency, session_ids, event_id,
       user_text, intent, tools_used, suggested_tool_type}
    """
    trajs = _load_trajectories(log_dir)
    if not trajs:
        logger.info("No trajectory files found in %s", log_dir)
        return []

    candidates: List[Dict[str, Any]] = []

    for traj in trajs:
        session_id = traj.get("session_id", "?")
        for event in traj.get("events", []):
            payload = event.get("payload", {})
            score = payload.get("satisfaction_score")
            # Only process explicit negative feedback
            if score is None or score >= 0:
                continue

            user_text = payload.get("user_text", "").strip()
            if not user_text:
                continue

            plan = payload.get("plan") or {}
            vlm_context = payload.get("source_image_context") or {}
            intent = plan.get("intent", user_text)
            steps = plan.get("steps", [])
            tools_used = [s.get("tool_name", "?") for s in steps]
            unmet = plan.get("unmet_requirements", [])

            candidates.append({
                "signal": "negative_feedback",
                "description": _build_feedback_spec(
                    user_text, intent, tools_used, unmet, vlm_context
                ),
                "frequency": 1,
                "session_ids": [session_id],
                "event_id": event.get("event_id", "?"),
                "user_text": user_text,
                "intent": intent,
                "tools_used": tools_used,
                "suggested_tool_type": "opencv",
            })

    logger.info(
        "Found %d negative-feedback event(s) across %d trajectory file(s).",
        len(candidates), len(trajs),
    )
    return candidates


def analyse_logs(
    log_dir: Path,
    window_days: int = 7,
) -> List[Dict[str, Any]]:
    """Analyse session logs and return tool-gap candidates.

    Signals:
      1. Explicit unmet_requirements from Planner logs
      2. Repeated multi-step patterns that could be a single tool
      3. High validator-reject rates for certain prompt types

    Returns list of candidate dicts:
      {signal, description, frequency, session_ids, suggested_tool_type}
    """
    trajs = _load_trajectories(log_dir)
    if not trajs:
        logger.info("No trajectory files found in %s", log_dir)
        return []

    unmet_counter: Counter = Counter()
    unmet_sessions: Dict[str, List[str]] = {}
    step_seq_counter: Counter = Counter()

    for traj in trajs:
        session_id = traj.get("session_id", "?")
        for event in traj.get("events", []):
            payload = event.get("payload", {})
            # Check for unmet_requirements stored in payload
            for req in payload.get("unmet_requirements", []):
                key = req.get("need", "")
                unmet_counter[key] += 1
                unmet_sessions.setdefault(key, []).append(session_id)

            # Step sequence patterns
            steps = payload.get("plan_steps", [])
            if len(steps) >= 2:
                seq = tuple(s.get("tool_name", "?") for s in steps)
                step_seq_counter[seq] += 1

    candidates: List[Dict[str, Any]] = []

    # Signal 1: unmet requirements with frequency > 1
    for need, count in unmet_counter.most_common(10):
        if count > 1:
            candidates.append({
                "signal": "unmet_requirement",
                "description": need,
                "frequency": count,
                "session_ids": unmet_sessions.get(need, [])[:5],
                "suggested_tool_type": "opencv",
            })

    # Signal 2: repeated step sequences (>= 3 times)
    for seq, count in step_seq_counter.most_common(5):
        if count >= 3 and len(seq) >= 2:
            candidates.append({
                "signal": "repeated_step_pattern",
                "description": f"Steps always combined: {' → '.join(seq)}",
                "frequency": count,
                "session_ids": [],
                "suggested_tool_type": "opencv",
            })

    return candidates


# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------


def static_analyse(source: str) -> List[str]:
    """Return list of security violations found in Python source."""
    errors: List[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]

    for node in ast.walk(tree):
        # Forbidden imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names: List[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            else:
                names = [node.module.split(".")[0]] if node.module else []
            for name in names:
                if name in FORBIDDEN_IMPORTS:
                    errors.append(f"Forbidden import: {name}")

        # Forbidden calls
        if isinstance(node, ast.Call):
            func = node.func
            call_name = ""
            if isinstance(func, ast.Name):
                call_name = func.id
            elif isinstance(func, ast.Attribute):
                call_name = func.attr
            if call_name in FORBIDDEN_CALLS:
                errors.append(f"Forbidden call: {call_name}()")

    return errors


# ---------------------------------------------------------------------------
# Sandbox smoke test
# ---------------------------------------------------------------------------


def sandbox_test(source: str, tool_class_name: str = "TOOL_CLASS") -> List[str]:
    """Execute tool in-process with dummy images.  Returns errors."""
    import importlib.util
    import tempfile

    errors: List[str] = []

    # Write to tmp file
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(source)
        tmp_path = f.name

    try:
        spec = importlib.util.spec_from_file_location("_sandbox_tool", tmp_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        tool_cls = getattr(mod, tool_class_name, None)
        if tool_cls is None:
            errors.append(f"'{tool_class_name}' not found in generated code")
            return errors

        tool = tool_cls()

        import numpy as np
        for h, w in [(64, 64), (100, 150), (480, 640)]:
            dummy = np.zeros((h, w, 3), dtype=np.uint8)
            try:
                result, _ = tool.run(dummy)
                if not isinstance(result, np.ndarray):
                    errors.append(
                        f"run() returned {type(result).__name__}, "
                        "expected np.ndarray"
                    )
            except Exception as exc:
                errors.append(f"run() raised on {h}×{w} image: {exc}")

    except Exception as exc:
        errors.append(f"Module load failed: {exc}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return errors


# ---------------------------------------------------------------------------
# Code generation via LLM
# ---------------------------------------------------------------------------

_CODE_GEN_SYSTEM = """\
You are a Python code generator for image editing tools.

Generate a single Python module that defines a tool class.

Requirements:
- The class must have class-level attributes: name (str), tool_type (str),
  description (str), params_schema (dict JSON Schema)
- Implement: run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]
- Validate inputs at the top of run()
- Allowed imports ONLY: cv2, numpy as np, typing
- FORBIDDEN: os, sys, subprocess, socket, requests, urllib, pickle, shutil
- FORBIDDEN calls: eval, exec, compile, __import__, open
- OpenCV images are BGR format uint8
- Preserve input dtype unless unavoidable
- Assign the class to module-level variable: TOOL_CLASS = YourClassName
- Return ONLY the Python source code, no markdown, no explanations.
"""


def generate_tool_code(spec: str) -> str:
    """Use LLM to generate tool source code from a spec description."""
    from .llm import call_llm

    prompt = f"""
Tool specification:
{spec}

Generate the Python module now.
"""
    return call_llm(prompt, system=_CODE_GEN_SYSTEM, temperature=0.2)


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _load_registry() -> List[Dict[str, Any]]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    if not GENERATED_REGISTRY.exists():
        return []
    return json.loads(GENERATED_REGISTRY.read_text(encoding="utf-8"))


def _save_registry(entries: List[Dict[str, Any]]) -> None:
    GENERATED_REGISTRY.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _version_hash(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode()).hexdigest()[:16]


def register_tool(
    name: str,
    source: str,
    description: str,
    params_schema: dict,
    analysis_evidence: Optional[Dict[str, Any]] = None,
    target_status: str = "staging",
    tool_type: str = "opencv",
) -> Dict[str, Any]:
    """Write tool file and update registry.json."""
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    # Duplicate check
    entries = _load_registry()
    for entry in entries:
        if entry["name"] == name:
            logger.info("Tool '%s' already in registry, updating.", name)
            entries = [e for e in entries if e["name"] != name]
            break

    version = "1.0.0"
    filename = f"{name}_v1.py"
    tool_path = GENERATED_DIR / filename
    tool_path.write_text(source, encoding="utf-8")

    entry: Dict[str, Any] = {
        "name": name,
        "version": version,
        "type": tool_type,
        "module_path": f"tools/generated/{filename}",
        "description": description,
        "params_schema": params_schema,
        "status": target_status,
        "version_hash": _version_hash(source),
        "created_by": "tool_generator",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "analysis_evidence": analysis_evidence or {},
    }
    entries.append(entry)
    _save_registry(entries)
    logger.info(
        "Registered tool '%s' with status '%s'.", name, target_status
    )
    return entry


# ---------------------------------------------------------------------------
# Full pipeline for a single candidate
# ---------------------------------------------------------------------------


def process_candidate(
    candidate: Dict[str, Any],
    human_review: bool = True,
    auto_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full analyse → generate → validate → register pipeline.

    Returns {status, tool_name, message, entry}
    """
    description = candidate.get("description", "")
    name = auto_name or description.lower().replace(" ", "_")[:32]

    logger.info("Processing candidate: %s", description)

    # 1. Generate code
    spec = f"Tool name: {name}\nDescription: {description}"
    try:
        source = generate_tool_code(spec)
    except Exception as exc:
        return {"status": "failed", "tool_name": name, "message": str(exc)}

    # Strip markdown fences
    if "```" in source:
        import re
        m = re.search(r"```(?:python)?\s*([\s\S]*?)```", source)
        if m:
            source = m.group(1).strip()

    # 2. Static analysis
    sa_errors = static_analyse(source)
    if sa_errors:
        # One retry
        logger.info("Static analysis failed, retrying: %s", sa_errors)
        source = generate_tool_code(
            spec + "\n\nPrevious attempt had issues:\n" + "\n".join(sa_errors)
        )
        sa_errors = static_analyse(source)
        if sa_errors:
            return {
                "status": "failed",
                "tool_name": name,
                "message": f"Static analysis: {sa_errors}",
            }

    # 3. Sandbox test
    sb_errors = sandbox_test(source)
    if sb_errors:
        return {
            "status": "failed",
            "tool_name": name,
            "message": f"Sandbox: {sb_errors}",
        }

    # 4. Parse description and schema from generated code
    module_description = description
    params_schema: dict = {"type": "object", "properties": {}, "required": []}
    try:
        import importlib.util, tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            tmp = f.name
        spec_obj = importlib.util.spec_from_file_location("_tmp", tmp)
        mod = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(mod)
        cls = getattr(mod, "TOOL_CLASS", None)
        if cls:
            inst = cls()
            module_description = getattr(inst, "description", description)
            params_schema = getattr(inst, "params_schema", params_schema)
        os.unlink(tmp)
    except Exception:
        pass

    # 5. Register
    status = "staging" if human_review else "prod"
    entry = register_tool(
        name=name,
        source=source,
        description=module_description,
        params_schema=params_schema,
        analysis_evidence={
            "trigger_signal": candidate.get("signal"),
            "session_ids": candidate.get("session_ids", []),
            "frequency": candidate.get("frequency", 0),
        },
        target_status=status,
    )

    return {
        "status": "created",
        "tool_name": name,
        "registry_status": status,
        "message": f"Tool created and registered as '{status}'.",
        "entry": entry,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Tool Generator — offline agent for adding new tools"
    )
    sub = parser.add_subparsers(dest="cmd")

    # analyse
    p_analyse = sub.add_parser("analyse", help="Scan session logs for tool gaps")
    p_analyse.add_argument(
        "--log-dir",
        default="./data/trajectories",
        help="Path to trajectory JSON directory",
    )

    # generate
    p_gen = sub.add_parser("generate", help="Generate a tool from a spec")
    p_gen.add_argument("--spec", required=True, help="Natural language tool spec")
    p_gen.add_argument("--name", default=None, help="Tool name override")
    p_gen.add_argument(
        "--auto-prod",
        action="store_true",
        help="Register as prod directly (no human review)",
    )

    # feedback
    p_fb = sub.add_parser(
        "feedback",
        help="Generate tools from thumbs-down feedback in trajectory files",
    )
    p_fb.add_argument(
        "--log-dir", default="./data/trajectories",
        help="Path to trajectory JSON directory",
    )
    p_fb.add_argument(
        "--auto-prod", action="store_true",
        help="Register generated tools as prod directly (skip staging)",
    )

    # run
    p_run = sub.add_parser("run", help="Run full pipeline on analysed candidates")
    p_run.add_argument(
        "--log-dir", default="./data/trajectories"
    )
    p_run.add_argument(
        "--auto-prod",
        action="store_true",
        help="Skip staging, register as prod",
    )

    # promote
    p_promo = sub.add_parser("promote", help="Promote a staging tool to prod")
    p_promo.add_argument("--name", required=True)

    args = parser.parse_args()

    if args.cmd == "analyse":
        log_dir = Path(args.log_dir)
        candidates = analyse_logs(log_dir)
        if not candidates:
            print("No tool gaps found.")
        else:
            print(f"Found {len(candidates)} candidate(s):")
            for c in candidates:
                print(
                    f"  [{c['signal']}] {c['description']} "
                    f"(freq={c['frequency']})"
                )

    elif args.cmd == "generate":
        human_review = not args.auto_prod
        result = process_candidate(
            {"signal": "manual", "description": args.spec,
             "frequency": 1, "session_ids": []},
            human_review=human_review,
            auto_name=args.name,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.cmd == "feedback":
        import re
        log_dir = Path(args.log_dir)
        candidates = analyse_negative_feedback(log_dir)
        if not candidates:
            print("No negative-feedback events found in trajectories.")
            return
        print(f"Found {len(candidates)} unsatisfied edit(s) - generating tools...\n")
        human_review = not args.auto_prod
        results = []
        for c in candidates:
            # Name: "fb_" + sanitised intent, max 32 chars
            raw_name = "fb_" + re.sub(r"[^a-z0-9]+", "_", c["intent"].lower())
            auto_name = raw_name[:32].rstrip("_")
            print(f"  Processing: [{c['event_id'][:8]}] {c['user_text'][:60]}")
            result = process_candidate(c, human_review=human_review, auto_name=auto_name)
            results.append(result)
            print(f"    → {result['status']}: {result.get('message', '')}")
        print(f"\nDone. {sum(1 for r in results if r['status'] == 'created')} tool(s) created.")
        if human_review:
            print("Tools registered as 'staging'. Promote with: "
                  "python -m agents.tool_generator promote --name <tool_name>")
        else:
            print("Tools registered as 'prod' and will load on next server start.")

    elif args.cmd == "run":
        log_dir = Path(args.log_dir)
        candidates = analyse_logs(log_dir)
        human_review = not args.auto_prod
        results = []
        for c in candidates:
            result = process_candidate(c, human_review=human_review)
            results.append(result)
            print(f"  {result['status']:10} {result.get('tool_name', '')}: "
                  f"{result.get('message', '')}")
        print(f"\nProcessed {len(results)} candidate(s).")

    elif args.cmd == "promote":
        entries = _load_registry()
        found = False
        for entry in entries:
            if entry["name"] == args.name:
                entry["status"] = "prod"
                found = True
                break
        if not found:
            print(f"Tool '{args.name}' not found in registry.")
            sys.exit(1)
        _save_registry(entries)
        print(f"Tool '{args.name}' promoted to prod.")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
