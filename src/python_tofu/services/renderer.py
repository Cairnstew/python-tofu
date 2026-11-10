"""Backwards-compatible re-export of the GCP renderer.

The provider-agnostic base is :class:`python_tofu.core.renderer.BaseRenderer`.
"""

from python_tofu.core.renderer import GITIGNORE, BaseRenderer
from python_tofu.providers.gcp.quirks import slug
from python_tofu.providers.gcp.renderer import GcpRenderer

Renderer = GcpRenderer

__all__ = ["GITIGNORE", "BaseRenderer", "GcpRenderer", "Renderer", "slug"]
