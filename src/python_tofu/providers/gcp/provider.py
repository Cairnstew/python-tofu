"""The registered GCP provider plugin."""

from __future__ import annotations

from python_tofu.core.provider import Provider, register_provider
from python_tofu.providers.gcp.limits import GCP_FREE_TIER, measure_usage
from python_tofu.providers.gcp.live import live_measure_usage
from python_tofu.providers.gcp.renderer import GcpRenderer
from python_tofu.providers.gcp.stack import GcpStack

GCP = register_provider(
    Provider(
        name="gcp",
        display_name="GCP",
        description="Google Cloud Platform via the hashicorp/google provider",
        stack_type=GcpStack,
        renderer_type=GcpRenderer,
        limit_policy=GCP_FREE_TIER,
        measure_usage=measure_usage,
        live_measure_usage=live_measure_usage,
    )
)

__all__ = ["GCP"]
