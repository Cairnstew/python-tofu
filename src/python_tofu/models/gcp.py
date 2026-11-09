"""Typed GCP resource models.

These models are the authoring layer: write Python, validate it at import time,
then let :mod:`python_tofu.services.renderer` emit OpenTofu HCL.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# GCP identifiers are stricter than "any non-empty string"; validating early
# turns a mid-apply API error into a local traceback.
PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BUCKET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
SERVICE_ACCOUNT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


class TofuModel(BaseModel):
    """Strict, immutable base model for all infrastructure objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_role(role: str) -> str:
    if not (role.startswith("roles/") or "/roles/" in role):
        raise ValueError(
            f"role must be a predefined role (roles/...) or a project custom role: {role!r}"
        )
    return role


class GcpProvider(TofuModel):
    """The ``provider "google"`` block plus provider-level defaults."""

    project: str = Field(min_length=1, description="Default project for resources")
    region: str = "us-central1"
    zone: str | None = None
    credentials: str | None = Field(
        default=None,
        description=(
            "Path to a service-account JSON key (GOOGLE_APPLICATION_CREDENTIALS is preferred)"
        ),
    )
    impersonate_service_account: str | None = None
    default_labels: dict[str, str] = Field(default_factory=dict)


class GcpProject(TofuModel):
    """A ``google_project`` resource."""

    project_id: str
    name: str
    billing_account: str | None = None
    org_id: str | None = None
    folder_id: str | None = None
    auto_create_network: bool = False
    deletion_policy: Literal["DELETE", "ABANDON"] = "DELETE"
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("project_id")
    @classmethod
    def _valid_project_id(cls, value: str) -> str:
        if not PROJECT_ID_RE.match(value):
            raise ValueError(
                "project_id must be 6-30 chars, start with a letter, contain only "
                f"lowercase letters/digits/hyphens and not end with a hyphen: {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _single_parent(self) -> "GcpProject":
        if self.org_id and self.folder_id:
            raise ValueError("a project belongs to either org_id or folder_id, not both")
        return self


class ProjectApi(TofuModel):
    """A ``google_project_service`` resource (API enablement)."""

    project: str
    service: str = Field(min_length=1, description="e.g. compute.googleapis.com")
    disable_on_destroy: bool = False


class ServiceAccount(TofuModel):
    """A ``google_service_account`` plus optional project IAM role bindings."""

    project: str
    account_id: str
    display_name: str | None = None
    description: str | None = None
    roles: list[str] = Field(default_factory=list)

    @field_validator("account_id")
    @classmethod
    def _valid_account_id(cls, value: str) -> str:
        if not SERVICE_ACCOUNT_ID_RE.match(value):
            raise ValueError(
                "account_id must be 6-30 chars, start with a letter, contain only "
                f"lowercase letters/digits/hyphens and not end with a hyphen: {value!r}"
            )
        return value

    @field_validator("roles")
    @classmethod
    def _valid_roles(cls, value: list[str]) -> list[str]:
        return [_validate_role(item) for item in value]


class StorageBucket(TofuModel):
    """A ``google_storage_bucket`` resource."""

    project: str
    name: str
    location: str = "US"
    storage_class: Literal[
        "STANDARD",
        "NEARLINE",
        "COLDLINE",
        "ARCHIVE",
        "MULTI_REGIONAL",
        "REGIONAL",
        "DURABLE_REDUCED_AVAILABILITY",
    ] = "STANDARD"
    uniform_bucket_level_access: bool = True
    public_access_prevention: Literal["inherited", "enforced"] = "enforced"
    force_destroy: bool = False
    versioning: bool = False
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_bucket_name(cls, value: str) -> str:
        if not BUCKET_NAME_RE.match(value):
            raise ValueError(
                "bucket names must be 3-63 chars, start/end with a letter or digit, and "
                f"contain only lowercase letters/digits/dots/hyphens/underscores: {value!r}"
            )
        return value


class ProjectIamMember(TofuModel):
    """A standalone ``google_project_iam_member`` binding."""

    project: str
    role: str
    member: str = Field(
        min_length=3,
        description=(
            "IAM principal, e.g. user:alice@example.com or "
            "serviceAccount:sa@project.iam.gserviceaccount.com"
        ),
    )

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        return _validate_role(value)
