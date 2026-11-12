"""python-tofu — a typed Python DSL and OpenTofu wrapper.

The package is split into a provider-agnostic :mod:`python_tofu.core` and
provider branches under :mod:`python_tofu.providers`. GCP is the default and the
historical top-level names point at it, so existing configs keep working:

>>> from python_tofu import GcpProject, GcpProvider, GcpStack, StorageBucket
>>> stack = GcpStack(
...     provider=GcpProvider(project="my-project"),
...     projects=[GcpProject(project_id="my-project", name="My Project")],
...     buckets=[StorageBucket(project="my-project", name="my-project-artifacts")],
... )
"""

from __future__ import annotations

from pathlib import Path

from python_tofu.core.doctor import CheckResult, CheckStatus, DoctorReport
from python_tofu.core.exceptions import (
    ConfigError,
    PruneError,
    RenderError,
    TofuCommandError,
    TofuError,
    TofuNotInstalledError,
)
from python_tofu.core.hcl import ref
from python_tofu.core.limits import (
    AggregateLimit,
    Limit,
    LimitAction,
    LimitCheck,
    LimitExceeded,
    LimitMode,
    LimitPeriod,
    LimitPolicy,
    LimitReport,
    LimitStatus,
    LimitUnknown,
    Throttler,
    Usage,
    UsageMode,
)
from python_tofu.core.loader import load_stack as _load_stack
from python_tofu.core.models import BaseStack, Output, PruneConfig, TofuModel
from python_tofu.core.provider import Provider, available_providers, get_provider
from python_tofu.core.prune import PrunableResource, PrunePlan
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.results import CommandResult, PlanSummary, RenderResult
from python_tofu.core.runner import TofuRunner
from python_tofu.providers.gcp import (
    GCP,
    ArtifactRegistryRepository,
    BackendConfig,
    BillingBudget,
    BucketObject,
    CloudRunFunction,
    CloudRunJob,
    CloudRunService,
    CloudRunWorkerPool,
    CloudSqlVolume,
    DeadLetter,
    EmptyDirVolume,
    GcpBackendConfig,
    GcpProject,
    GcpProvider,
    GcpRenderer,
    GcpStack,
    GcsVolume,
    GrpcProbe,
    HttpProbe,
    NfsVolume,
    Probe,
    ProjectApi,
    ProjectIamMember,
    PubSubSubscription,
    PubSubTopic,
    RetryPolicy,
    SecretEnv,
    SecretVolume,
    SecretVolumeItem,
    Service,
    ServiceAccount,
    ServiceCatalog,
    StackPart,
    StackProfile,
    StorageBucket,
    StorageClass,
    TcpProbe,
    Volume,
    compose,
    enable_apis,
)

__version__ = "0.1.0"

#: Historical alias: the GCP renderer is the package's default renderer.
Renderer = GcpRenderer


def load_stack(path: str | Path) -> GcpStack:
    """Import ``path`` and return its module-level GCP ``stack``."""

    return _load_stack(path, GcpStack)


__all__ = [
    "AggregateLimit",
    "ArtifactRegistryRepository",
    "BackendConfig",
    "BaseRenderer",
    "BaseStack",
    "BillingBudget",
    "BucketObject",
    "CloudRunFunction",
    "CloudRunJob",
    "CloudRunService",
    "CloudRunWorkerPool",
    "CommandResult",
    "ConfigError",
    "CheckResult",
    "CheckStatus",
    "DoctorReport",
    "GCP",
    "GcpBackendConfig",
    "GcpProject",
    "GcpProvider",
    "GcpRenderer",
    "GcpStack",
    "Limit",
    "LimitAction",
    "LimitCheck",
    "LimitExceeded",
    "LimitMode",
    "LimitPeriod",
    "LimitPolicy",
    "LimitReport",
    "LimitStatus",
    "LimitUnknown",
    "PlanSummary",
    "DeadLetter",
    "Output",
    "PubSubSubscription",
    "PubSubTopic",
    "RetryPolicy",
    "ProjectApi",
    "ProjectIamMember",
    "Provider",
    "PrunableResource",
    "PruneConfig",
    "PruneError",
    "PrunePlan",
    "RenderError",
    "RenderResult",
    "Renderer",
    "SecretEnv",
    "Service",
    "GcsVolume",
    "NfsVolume",
    "EmptyDirVolume",
    "CloudSqlVolume",
    "SecretVolume",
    "SecretVolumeItem",
    "Volume",
    "Probe",
    "HttpProbe",
    "TcpProbe",
    "GrpcProbe",
    "ServiceAccount",
    "ServiceCatalog",
    "StackPart",
    "StackProfile",
    "StorageBucket",
    "StorageClass",
    "TofuCommandError",
    "Throttler",
    "TofuError",
    "TofuModel",
    "TofuNotInstalledError",
    "TofuRunner",
    "Usage",
    "UsageMode",
    "__version__",
    "available_providers",
    "compose",
    "enable_apis",
    "get_provider",
    "load_stack",
    "ref",
]
