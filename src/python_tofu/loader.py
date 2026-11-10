"""Load a Python ``infra.py`` into the default (GCP) stack.

Provider-aware callers can use :func:`python_tofu.core.loader.load_stack` with
``provider.stack_type`` directly.
"""

from __future__ import annotations

from pathlib import Path

from python_tofu.core.loader import load_stack as _load_stack
from python_tofu.providers.gcp import GcpStack


def load_stack(path: str | Path) -> GcpStack:
    """Import ``path`` and return its module-level GCP ``stack``."""

    return _load_stack(path, GcpStack)


__all__ = ["load_stack"]
