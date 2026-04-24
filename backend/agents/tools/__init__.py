"""Built-in tools.  Importing this package registers all tools."""
from . import opencv_tools  # noqa: F401
from . import color_tools   # noqa: F401
from . import gemini_tools  # noqa: F401
from agents.tool_registry import registry as _registry
_registry.load_generated_tools()

__all__ = ["opencv_tools", "color_tools", "gemini_tools"]
