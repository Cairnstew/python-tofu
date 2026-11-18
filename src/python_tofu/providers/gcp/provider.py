"""The registered GCP provider plugin."""

from __future__ import annotations

from python_tofu.core.provider import Provider, register_provider
from python_tofu.providers.gcp.cli.doctor import run_checks
from python_tofu.providers.gcp.limits import GCP_FREE_TIER, measure_usage
from python_tofu.providers.gcp.live import live_measure_usage
from python_tofu.providers.gcp.models import GCP_PRUNE_SECTIONS
from python_tofu.providers.gcp.prune import discover
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
        prune_sections=GCP_PRUNE_SECTIONS,
        prune_explicit_only=("project_iam",),
        prune_plan=discover,
        doctor_checks=run_checks,
    )
)

__all__ = ["GCP"]
