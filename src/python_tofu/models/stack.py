"""Stack-level models: provider, backend and the resource collection."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from python_tofu.models.gcp import (
    GcpProject,
    GcpProvider,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
    TofuModel,
)


class BackendConfig(TofuModel):
    """OpenTofu state backend.

    ``gcs`` is the recommended backend for shared/team state; ``local`` is handy
    for a first plan or CI smoke test.
    """

    kind: Literal["local", "gcs"] = "gcs"
    bucket: str | None = None
    prefix: str = "python-tofu/state"
    path: str | None = None

    @model_validator(mode="after")
    def _required_fields(self) -> "BackendConfig":
        if self.kind == "gcs" and not self.bucket:
            raise ValueError("a gcs backend requires `bucket`")
        if self.kind == "local" and not self.path:
            raise ValueError("a local backend requires `path`")
        return self


class GcpStack(TofuModel):
    """A complete, renderable description of a GCP account slice."""

    provider: GcpProvider
    projects: list[GcpProject] = Field(default_factory=list)
    apis: list[ProjectApi] = Field(default_factory=list)
    service_accounts: list[ServiceAccount] = Field(default_factory=list)
    buckets: list[StorageBucket] = Field(default_factory=list)
    iam_members: list[ProjectIamMember] = Field(default_factory=list)
    backend: BackendConfig | None = None
    external_projects: list[str] = Field(
        default_factory=list,
        description="Existing project IDs resources may reference without declaring a GcpProject",
    )
    required_version: str = ">= 1.6.0"
    google_provider_version: str = "~> 6.0"

    @model_validator(mode="after")
    def _references_are_known(self) -> "GcpStack":
        known = {self.provider.project, *self.external_projects}
        known.update(project.project_id for project in self.projects)

        referenced = {
            *[item.project for item in self.apis],
            *[item.project for item in self.service_accounts],
            *[item.project for item in self.buckets],
            *[item.project for item in self.iam_members],
        }
        missing = sorted(referenced - known)
        if missing:
            raise ValueError(
                "resources reference unknown projects: "
                + ", ".join(missing)
                + ". Declare them in `projects` or list them in `external_projects`."
            )
        return self
