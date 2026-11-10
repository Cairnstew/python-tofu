"""Backwards-compatible re-export of :mod:`python_tofu.providers.gcp.models`."""

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
from python_tofu.providers.gcp.quirks import (
    BUCKET_NAME_RE,
    PROJECT_ID_RE,
    SERVICE_ACCOUNT_ID_RE,
)

__all__ = [
    "BUCKET_NAME_RE",
    "BackendConfig",
    "GcpBackendConfig",
    "GcpProject",
    "GcpProvider",
    "PROJECT_ID_RE",
    "ProjectApi",
    "ProjectIamMember",
    "SERVICE_ACCOUNT_ID_RE",
    "ServiceAccount",
    "StorageBucket",
    "TofuModel",
]
