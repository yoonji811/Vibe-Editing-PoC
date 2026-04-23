"""Memory Agent — RAG-based success case retrieval and indexing.

Architecture:
  - Indexing (offline/async): satisfaction_score >= 0.8 edit events →
    embed [user_text + VLM context] → upsert to ChromaDB with plan metadata
  - Retrieval (runtime/sync): embed current [user_text + VLM context] →
    Top-K cosine similarity search → return past successful plans to Planner

ChromaDB stores data in ./data/chromadb (local PoC).
Default embedding: all-MiniLM-L6-v2 via chromadb's built-in function.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv("CHROMADB_PATH", "./data/chromadb")
_COLLECTION_NAME = "vibedit_success_cases"
_MIN_SCORE = 0.8       # minimum satisfaction_score to index
_MIN_SIMILARITY = 0.25  # minimum cosine similarity to include in results


class MemoryAgent:
    """Manages long-term memory of successful edit cases via ChromaDB."""

    def __init__(self) -> None:
        self._collection = None  # lazy init so import doesn't block startup

    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
            Path(_DB_PATH).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=_DB_PATH)
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            logger.error("ChromaDB init failed: %s", exc)
            raise
        return self._collection

    # ------------------------------------------------------------------
    # Document building
    # ------------------------------------------------------------------

    def _build_document(self, user_text: str, vlm_context: Dict[str, Any]) -> str:
        """Combine user text + VLM context into a single embedding string."""
        parts = [f"User Request: {user_text}"]

        sem = vlm_context.get("semantic_understanding", {})
        color = vlm_context.get("colorimetry_and_lighting", {})
        phys = vlm_context.get("physical_properties", {})
        art = vlm_context.get("artistic_style", {})

        if sem.get("scene_type"):
            parts.append(f"Scene: {sem['scene_type']}")
        if sem.get("mood"):
            parts.append(f"Image Mood: {sem['mood']}")
        if sem.get("subjects"):
            parts.append(f"Subjects: {', '.join(sem['subjects'][:3])}")
        if color.get("color_temperature"):
            parts.append(f"Color Temp: {color['color_temperature']}")
        if color.get("brightness"):
            parts.append(f"Brightness: {color['brightness']}")
        if color.get("contrast"):
            parts.append(f"Contrast: {color['contrast']}")
        if phys.get("noise_level"):
            parts.append(f"Noise Level: {phys['noise_level']}")
        if art.get("current_style"):
            parts.append(f"Style: {art['current_style']}")
        if art.get("mood_keywords"):
            parts.append(f"Keywords: {', '.join(art.get('mood_keywords', []))}")

        return " | ".join(parts)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_success(
        self,
        event_id: str,
        session_id: str,
        user_text: str,
        vlm_context: Dict[str, Any],
        plan: Dict[str, Any],
        satisfaction_score: float,
        is_correction: bool = False,
    ) -> None:
        """Index one successful edit case.

        Skips if satisfaction_score < _MIN_SCORE or ChromaDB unavailable.
        """
        if satisfaction_score < _MIN_SCORE:
            return
        try:
            col = self._get_collection()
        except Exception:
            return

        document = self._build_document(user_text, vlm_context)
        # ChromaDB metadata values must be str / int / float
        metadata: Dict[str, Any] = {
            "session_id": session_id,
            "satisfaction_score": float(satisfaction_score),
            "is_correction_case": "true" if is_correction else "false",
            "user_text": user_text[:300],
            "plan_json": json.dumps(plan, ensure_ascii=False)[:4000],
        }

        try:
            col.upsert(ids=[event_id], documents=[document], metadatas=[metadata])
            logger.info("Memory indexed event=%s score=%.2f", event_id, satisfaction_score)
        except Exception as exc:
            logger.warning("Memory index failed for event=%s: %s", event_id, exc)

    def batch_index_from_trajectory(self, session_id: str) -> int:
        """Scan a stored trajectory and index all qualifying events.

        Returns the number of events indexed.
        """
        from services.trajectory_store import get_edit_events
        events = get_edit_events(session_id)
        count = 0
        for event in events:
            p = event.payload
            score = p.satisfaction_score if p.satisfaction_score is not None else 0.0
            if score < _MIN_SCORE:
                continue
            self.index_success(
                event_id=event.event_id,
                session_id=session_id,
                user_text=p.user_text or "",
                vlm_context=p.source_image_context or {},
                plan=p.plan or {},
                satisfaction_score=score,
                is_correction=(p.feedback_type == "implicit"),
            )
            count += 1
        logger.info("Batch indexed %d events for session=%s", count, session_id)
        return count

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search_similar(
        self,
        user_text: str,
        vlm_context: Dict[str, Any],
        is_correction: bool = False,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Search for the most similar past success cases.

        Args:
            user_text:      Current user prompt.
            vlm_context:    Current image VLM analysis dict.
            is_correction:  If True, prefer cases where a correction succeeded.
            top_k:          Maximum results to return.

        Returns:
            List of dicts: {user_text, similarity, satisfaction_score, plan}
        """
        try:
            col = self._get_collection()
        except Exception:
            return []

        total = col.count()
        if total == 0:
            return []

        query_doc = self._build_document(user_text, vlm_context)
        n = min(top_k, total)

        # Try correction-filtered search first, fall back to unfiltered
        results = None
        if is_correction and total > 0:
            try:
                results = col.query(
                    query_texts=[query_doc],
                    n_results=n,
                    where={"is_correction_case": "true"},
                )
                # If no correction cases, fall through to unfiltered
                if not results["ids"][0]:
                    results = None
            except Exception:
                results = None

        if results is None:
            try:
                results = col.query(query_texts=[query_doc], n_results=n)
            except Exception as exc:
                logger.warning("Memory search failed: %s", exc)
                return []

        cases: List[Dict[str, Any]] = []
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for meta, dist in zip(metadatas, distances):
            similarity = 1.0 - dist  # cosine distance → similarity
            if similarity < _MIN_SIMILARITY:
                continue
            try:
                plan = json.loads(meta.get("plan_json", "{}"))
            except json.JSONDecodeError:
                plan = {}
            cases.append({
                "user_text": meta.get("user_text", ""),
                "similarity": round(similarity, 3),
                "satisfaction_score": meta.get("satisfaction_score", 0.0),
                "plan": plan,
            })

        return cases
