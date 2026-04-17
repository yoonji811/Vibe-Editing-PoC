"""Built-in tools.  Importing this package registers all OpenCV tools."""
from . import opencv_tools  # noqa: F401 — side-effect: registers tools

__all__ = ["opencv_tools"]
