"""The GCP stack: provider settings, resources and cross-resource validation."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from python_tofu.core.models import BaseStack
from python_tofu.providers.gcp.models import (
    GcpBackendConfig,
    GcpProject,
    GcpProvider,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
)


class GcpStack(BaseStack):
    """A complete, renderable description of a GCP account slice."""

    provider: GcpProvider
    projects: list[GcpProject] = Field(default_factory=list)
    apis: list[ProjectApi] = Field(default_factory=list)
    service_accounts: list[ServiceAccount] = Field(default_factory=list)
    buckets: list[StorageBucket] = Field(default_factory=list)
    iam_members: list[ProjectIamMember] = Field(default_factory=list)
    backend: GcpBackendConfig | None = None
    external_projects: list[str] = Field(
        default_factory=list,
        description="Existing project IDs resources may reference without declaring a GcpProject",
    )
    google_provider_version: str = "~> 6.0"
    usage_estimates: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Estimated monthly usage keyed by limit key, e.g. "
            "'gcp.bigquery.query_tib': 0.2. Merged with values measured from "
            "the stack for limit checks."
        ),
    )

    @field_validator("usage_estimates")
    @classmethod
    def _estimates_are_non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        negative = sorted(key for key, amount in value.items() if amount < 0)
        if negative:
            raise ValueError("usage estimates must be non-negative: " + ", ".join(negative))
        return value

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
