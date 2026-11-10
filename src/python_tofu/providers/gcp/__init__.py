"""Google Cloud Platform provider.

Importing this package registers :data:`GCP` with the core registry. Everything
GCP-specific — models, validation quirks, HCL shapes — lives in this subpackage.
"""

from python_tofu.providers.gcp.limits import GCP_FREE_TIER, measure_usage
from python_tofu.providers.gcp.live import LiveUsageError, live_measure_usage
from python_tofu.providers.gcp.models import (
    BackendConfig,
    GcpBackendConfig,
    GcpProject,
    GcpProvider,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
    TofuModel,
)
from python_tofu.providers.gcp.provider import GCP
from python_tofu.providers.gcp.renderer import GcpRenderer
from python_tofu.providers.gcp.stack import GcpStack

__all__ = [
    "BackendConfig",
    "GCP",
    "GCP_FREE_TIER",
    "GcpBackendConfig",
    "GcpProject",
    "GcpProvider",
    "GcpRenderer",
    "GcpStack",
    "LiveUsageError",
    "ProjectApi",
    "ProjectIamMember",
    "ServiceAccount",
    "StorageBucket",
    "TofuModel",
    "live_measure_usage",
    "measure_usage",
]
