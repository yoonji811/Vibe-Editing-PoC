"""Tool Registry — stores and retrieves image editing tools.

Contract:
  - Orchestrator uses: get(name), list()
  - Planner / Validator read: list() metadata (name, description, params_schema)
  - Tool Generator (offline) uses: register()
"""
from __future__ import annotations

import importlib.util
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Directory where Tool Generator writes generated tool files
GENERATED_DIR = Path(__file__).parent / "tools" / "generated"


class Tool(ABC):
    """Abstract base class for every image editing tool.

    Attributes (must be set as class-level attributes in subclasses):
        name          Unique identifier used in Plan JSON
        tool_type     "opencv" | "generative" | "hybrid"
        description   Human-readable sentence the Planner reads to choose tools
        params_schema JSON Schema dict describing accepted parameters
    """

    name: str
    tool_type: str
    description: str
    params_schema: dict

    @abstractmethod
    def run(
        self, image: np.ndarray, **params
    ) -> Tuple[np.ndarray, Optional[Any]]:
        """Apply the tool.

        Args:
            image:  BGR numpy array (uint8)
            **params: tool-specific parameters validated against params_schema

        Returns:
            (result_image, produced_artifact)
            produced_artifact is None for most tools; can be a mask or other
            intermediate that downstream steps reference via step.produces.
        """
        ...


class ToolRegistry:
    """Thread-safe (read-mostly) tool registry.

    Singleton ``registry`` at module level is the shared instance.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    # ------------------------------------------------------------------
    # Write API (Tool Generator only)
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool instance.  Overwrites if name already exists."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s (%s)", tool.name, tool.tool_type)

    # ------------------------------------------------------------------
    # Read API (Orchestrator / Planner / Validator)
    # ------------------------------------------------------------------

    def get(self, name: str) -> Tool:
        """Return a tool by name.  Raises KeyError if not found."""
        if name not in self._tools:
            available = sorted(self._tools)
            raise KeyError(
                f"Tool '{name}' not found in registry. "
                f"Available: {available}"
            )
        return self._tools[name]

    def list(self) -> List[Dict[str, Any]]:
        """Return lightweight descriptors for all registered tools."""
        return [
            {
                "name": t.name,
                "tool_type": t.tool_type,
                "description": t.description,
                "params_schema": t.params_schema,
            }
            for t in self._tools.values()
        ]

    def has(self, name: str) -> bool:
        return name in self._tools

    # ------------------------------------------------------------------
    # Generated tool loader
    # ------------------------------------------------------------------

    def load_generated_tools(
        self, directory: Optional[Path] = None
    ) -> None:
        """Load prod-status generated tools from directory/registry.json."""
        directory = directory or GENERATED_DIR
        registry_file = directory / "registry.json"
        if not registry_file.exists():
            return

        try:
            entries: List[dict] = json.loads(
                registry_file.read_text(encoding="utf-8")
            )
        except Exception as exc:
            logger.warning("Failed to read generated registry: %s", exc)
            return

        for entry in entries:
            if entry.get("status") != "prod":
                continue
            module_file = directory / Path(entry["module_path"]).name
            if not module_file.exists():
                logger.warning(
                    "Generated tool file missing: %s", module_file
                )
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    entry["name"], module_file
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                tool_cls = getattr(mod, "TOOL_CLASS", None)
                if tool_cls is not None:
                    self.register(tool_cls())
                    logger.info("Loaded generated tool: %s", entry["name"])
            except Exception as exc:
                logger.warning(
                    "Failed to load generated tool %s: %s",
                    entry.get("name"),
                    exc,
                )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
registry = ToolRegistry()
