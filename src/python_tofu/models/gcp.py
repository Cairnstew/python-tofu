"""Backwards-compatible re-export of :mod:`python_tofu.providers.gcp.models`."""

from python_tofu.providers.gcp.models import (
    BackendConfig,
    BucketObject,
    GcpBackendConfig,
    GcpProject,
    GcpProvider,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    ServiceAccountIamMember,
    StorageBucket,
    StorageClass,
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
    "BucketObject",
    "GcpBackendConfig",
    "GcpProject",
    "GcpProvider",
    "PROJECT_ID_RE",
    "ProjectApi",
    "ProjectIamMember",
    "SERVICE_ACCOUNT_ID_RE",
    "ServiceAccount",
    "ServiceAccountIamMember",
    "StorageBucket",
    "StorageClass",
    "TofuModel",
]
