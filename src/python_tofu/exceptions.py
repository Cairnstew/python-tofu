"""Backwards-compatible re-export of :mod:`python_tofu.core.exceptions`."""

from python_tofu.core.exceptions import (
    ConfigError,
    RenderError,
    TofuCommandError,
    TofuError,
    TofuNotInstalledError,
)

__all__ = [
    "ConfigError",
    "RenderError",
    "TofuCommandError",
    "TofuError",
    "TofuNotInstalledError",
]
