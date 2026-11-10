"""Backwards-compatible re-export of the GCP stack model.

The provider-agnostic envelope is :class:`python_tofu.core.models.BaseStack`.
"""

from python_tofu.providers.gcp.models import BackendConfig
from python_tofu.providers.gcp.stack import GcpStack

__all__ = ["BackendConfig", "GcpStack"]
