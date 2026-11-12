"""Typed GCP resource models.

These models are the authoring layer: write Python, validate it at import time,
then let :class:`python_tofu.providers.gcp.renderer.GcpRenderer` emit OpenTofu
HCL.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from python_tofu.core.models import TofuModel
from python_tofu.providers.gcp.quirks import (
    BUCKET_NAME_RE,
    PROJECT_ID_RE,
    SERVICE_ACCOUNT_ID_RE,
    validate_role,
)

StorageClass = Literal[
    "STANDARD",
    "NEARLINE",
    "COLDLINE",
    "ARCHIVE",
    "MULTI_REGIONAL",
    "REGIONAL",
    "DURABLE_REDUCED_AVAILABILITY",
]


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
        return [validate_role(item) for item in value]


class StorageBucket(TofuModel):
    """A ``google_storage_bucket`` resource."""

    project: str
    name: str
    location: str = "US"
    storage_class: StorageClass = "STANDARD"
    uniform_bucket_level_access: bool = True
    public_access_prevention: Literal["inherited", "enforced"] = "enforced"
    force_destroy: bool = False
    versioning: bool = False
    labels: dict[str, str] = Field(default_factory=dict)
    estimated_size_gb: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated stored GB for free-tier checks; never rendered as HCL",
    )

    @field_validator("name")
    @classmethod
    def _valid_bucket_name(cls, value: str) -> str:
        if not BUCKET_NAME_RE.match(value):
            raise ValueError(
                "bucket names must be 3-63 chars, start/end with a letter or digit, and "
                f"contain only lowercase letters/digits/dots/hyphens/underscores: {value!r}"
            )
        return value


class BucketObject(TofuModel):
    """A ``google_storage_bucket_object``.

    Exactly one content source is required:

    - ``content`` — inline text or raw bytes (bytes are written to the workdir
      and referenced with ``source``, because HCL cannot carry arbitrary bytes);
    - ``source`` — a local file path;
    - ``source_url`` — an HTTP(S) URL fetched by the ``hashicorp/http`` provider
      at plan/apply time.

    Terraform compares the declared content (or file hash) with state, so an
    unchanged object is not re-uploaded. Combine with ``StorageBucket.versioning``
    when previous generations must be retained.
    """

    bucket: str
    name: str
    content: str | bytes | None = None
    source: str | None = None
    source_url: str | None = None
    content_type: str | None = Field(
        default=None,
        description="Defaults to a guess from `name` (e.g. .json → application/json)",
    )
    content_encoding: str | None = None
    content_language: str | None = None
    cache_control: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    storage_class: StorageClass | None = None

    @field_validator("name")
    @classmethod
    def _valid_object_name(cls, value: str) -> str:
        if not value or value.startswith("/") or "\n" in value:
            raise ValueError(
                "object names must be a non-empty key without a leading slash or newline: "
                f"{value!r}"
            )
        return value

    @model_validator(mode="after")
    def _one_content_source(self) -> "BucketObject":
        provided = [
            name
            for name, value in (
                ("content", self.content),
                ("source", self.source),
                ("source_url", self.source_url),
            )
            if value is not None
        ]
        if len(provided) != 1:
            raise ValueError(
                "exactly one of content, source or source_url is required; "
                f"got {provided or 'none'}"
            )
        if self.source_url and not self.source_url.startswith(("http://", "https://")):
            raise ValueError(f"source_url must be an http(s) URL: {self.source_url!r}")
        return self


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
        return validate_role(value)


class GcpBackendConfig(TofuModel):
    """OpenTofu state backend for the Google provider."""

    kind: Literal["local", "gcs"] = "gcs"
    bucket: str | None = None
    prefix: str = "python-tofu/state"
    path: str | None = None

    @model_validator(mode="after")
    def _required_fields(self) -> "GcpBackendConfig":
        if self.kind == "gcs" and not self.bucket:
            raise ValueError("a gcs backend requires `bucket`")
        if self.kind == "local" and not self.path:
            raise ValueError("a local backend requires `path`")
        return self


# Public compatibility alias: the top-level package exposes ``BackendConfig``.
BackendConfig = GcpBackendConfig

__all__ = [
    "BackendConfig",
    "BucketObject",
    "GcpBackendConfig",
    "GcpProject",
    "GcpProvider",
    "ProjectApi",
    "ProjectIamMember",
    "ServiceAccount",
    "StorageBucket",
    "StorageClass",
    "TofuModel",
]
