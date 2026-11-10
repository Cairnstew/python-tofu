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

from python_tofu.core.exceptions import (
    ConfigError,
    RenderError,
    TofuCommandError,
    TofuError,
    TofuNotInstalledError,
)
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
from python_tofu.core.models import BaseStack, TofuModel
from python_tofu.core.provider import Provider, available_providers, get_provider
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.results import CommandResult, PlanSummary, RenderResult
from python_tofu.core.runner import TofuRunner
from python_tofu.providers.gcp import (
    GCP,
    BackendConfig,
    GcpBackendConfig,
    GcpProject,
    GcpProvider,
    GcpRenderer,
    GcpStack,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
)

__version__ = "0.1.0"

#: Historical alias: the GCP renderer is the package's default renderer.
Renderer = GcpRenderer


def load_stack(path: str | Path) -> GcpStack:
    """Import ``path`` and return its module-level GCP ``stack``."""

    return _load_stack(path, GcpStack)


__all__ = [
    "AggregateLimit",
    "BackendConfig",
    "BaseRenderer",
    "BaseStack",
    "CommandResult",
    "ConfigError",
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
    "ProjectApi",
    "ProjectIamMember",
    "Provider",
    "RenderError",
    "RenderResult",
    "Renderer",
    "ServiceAccount",
    "StorageBucket",
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
    "get_provider",
    "load_stack",
]
