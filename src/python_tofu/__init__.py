"""python-tofu — a typed Python DSL and OpenTofu wrapper for GCP infrastructure.

Example
-------
>>> from python_tofu import GcpProject, GcpProvider, GcpStack, StorageBucket
>>> stack = GcpStack(
...     provider=GcpProvider(project="my-project"),
...     projects=[GcpProject(project_id="my-project", name="My Project")],
...     buckets=[StorageBucket(project="my-project", name="my-project-artifacts")],
... )
"""

from python_tofu.exceptions import (
    ConfigError,
    RenderError,
    TofuCommandError,
    TofuError,
    TofuNotInstalledError,
)
from python_tofu.loader import load_stack
from python_tofu.models import (
    BackendConfig,
    CommandResult,
    GcpProject,
    GcpProvider,
    GcpStack,
    PlanSummary,
    ProjectApi,
    ProjectIamMember,
    RenderResult,
    ServiceAccount,
    StorageBucket,
    TofuModel,
)
from python_tofu.services import Renderer, TofuRunner

__version__ = "0.1.0"

__all__ = [
    "BackendConfig",
    "CommandResult",
    "ConfigError",
    "GcpProject",
    "GcpProvider",
    "GcpStack",
    "PlanSummary",
    "ProjectApi",
    "ProjectIamMember",
    "RenderError",
    "RenderResult",
    "Renderer",
    "ServiceAccount",
    "StorageBucket",
    "TofuCommandError",
    "TofuError",
    "TofuModel",
    "TofuNotInstalledError",
    "TofuRunner",
    "__version__",
    "load_stack",
]
