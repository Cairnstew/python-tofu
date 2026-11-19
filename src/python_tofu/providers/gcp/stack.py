"""The GCP stack: provider settings, resources and cross-resource validation."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from python_tofu.core.hcl import is_reference_template
from python_tofu.core.limits import LimitMode
from python_tofu.core.models import BaseStack
from python_tofu.providers.gcp.models import (
    GCP_PRUNE_SECTIONS,
    ArtifactRegistryRepository,
    BillingBudget,
    BucketObject,
    CloudRunFunction,
    CloudRunJob,
    CloudRunService,
    CloudRunWorkerPool,
    GcpBackendConfig,
    GcpProject,
    GcpProvider,
    ProjectApi,
    ProjectIamMember,
    PubSubSubscription,
    PubSubTopic,
    QuotaOverride,
    ServiceAccount,
    ServiceAccountIamMember,
    StorageBucket,
)


class StackProfile(str, Enum):
    """A documented bundle of defaults, resolved into the rendered stack."""

    DEFAULT = "default"
    PREVIEW = "preview"


#: Fallback provider constraint for installs outside the Nix build.
DEFAULT_GOOGLE_PROVIDER_VERSION = "~> 7.0"

#: Set by the packaged Nix app from ``nix/provider-versions.nix`` so the
#: rendered constraint and the mirrored provider version share one owner.
PROVIDER_VERSION_ENV = "PYTHON_TOFU_GOOGLE_PROVIDER_VERSION"


def _default_google_provider_version() -> str:
    """Return the provider constraint the build provides, else the fallback."""

    return os.environ.get(PROVIDER_VERSION_ENV) or DEFAULT_GOOGLE_PROVIDER_VERSION


#: Resources whose ``deletion_protection`` a preview profile flips off.
#: ``google_cloudfunctions2_function`` uses no such attribute (its model field is
#: not rendered), so functions are not in this list.
_PROTECTED_COLLECTIONS = (
    "cloud_run_services",
    "cloud_run_jobs",
    "cloud_run_worker_pools",
)


def _preview_resource(item: Any) -> Any:
    """Return ``item`` with deletion protection off unless it was set explicitly."""

    if isinstance(item, dict):
        return item if "deletion_protection" in item else {**item, "deletion_protection": False}
    if "deletion_protection" in getattr(item, "model_fields_set", set()):
        return item
    return item.model_copy(update={"deletion_protection": False})


class GcpStack(BaseStack):
    """A complete, renderable description of a GCP account slice."""

    provider: GcpProvider
    projects: list[GcpProject] = Field(default_factory=list)
    apis: list[ProjectApi] = Field(default_factory=list)
    service_accounts: list[ServiceAccount] = Field(default_factory=list)
    buckets: list[StorageBucket] = Field(default_factory=list)
    bucket_objects: list[BucketObject] = Field(default_factory=list)
    iam_members: list[ProjectIamMember] = Field(default_factory=list)
    service_account_iam_members: list[ServiceAccountIamMember] = Field(default_factory=list)
    cloud_run_services: list[CloudRunService] = Field(default_factory=list)
    cloud_run_functions: list[CloudRunFunction] = Field(default_factory=list)
    cloud_run_jobs: list[CloudRunJob] = Field(default_factory=list)
    cloud_run_worker_pools: list[CloudRunWorkerPool] = Field(default_factory=list)
    pubsub_topics: list[PubSubTopic] = Field(default_factory=list)
    pubsub_subscriptions: list[PubSubSubscription] = Field(default_factory=list)
    artifact_registry_repositories: list[ArtifactRegistryRepository] = Field(default_factory=list)
    backend: GcpBackendConfig | None = None
    billing_budgets: list[BillingBudget] = Field(default_factory=list)
    quota_overrides: list[QuotaOverride] = Field(
        default_factory=list,
        description=(
            "Service Usage consumer quota overrides: ceilings the cloud enforces. "
            "Applied by the `quota` command (the OpenTofu resource is beta-only), "
            "not rendered as HCL."
        ),
    )
    profile: StackProfile = Field(
        default=StackProfile.DEFAULT,
        description=(
            "Documented default bundle. `preview` flips deletion protection off, "
            "enables pruning, uses local state, warns on limits and adds the "
            "`ephemeral=true` label. Explicit per-resource values always win."
        ),
    )
    external_projects: list[str] = Field(
        default_factory=list,
        description="Existing project IDs resources may reference without declaring a GcpProject",
    )
    external_buckets: list[str] = Field(
        default_factory=list,
        description="Existing bucket names objects may target without declaring a StorageBucket",
    )
    external_topics: list[str] = Field(
        default_factory=list,
        description="Existing Pub/Sub topics subscriptions may target without declaring them",
    )
    google_provider_version: str = Field(
        default_factory=_default_google_provider_version,
        description=(
            "Google provider constraint. The packaged Nix app sets "
            "PYTHON_TOFU_GOOGLE_PROVIDER_VERSION from nix/provider-versions.nix"
        ),
    )
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

    @model_validator(mode="before")
    @classmethod
    def _apply_profile(cls, data: Any) -> Any:
        """Resolve a profile into concrete values; explicit choices always win."""

        if not isinstance(data, dict):
            return data
        profile = data.get("profile", StackProfile.DEFAULT)
        if profile not in (StackProfile.PREVIEW, StackProfile.PREVIEW.value):
            return data

        resolved = dict(data)

        for field_name in _PROTECTED_COLLECTIONS:
            items = resolved.get(field_name)
            if not items:
                continue
            resolved[field_name] = [_preview_resource(item) for item in items]

        if "prune" not in resolved:
            resolved["prune"] = {"enabled": True}
        if "limits_mode" not in resolved:
            resolved["limits_mode"] = LimitMode.WARN

        backend = resolved.get("backend")
        if backend is not None:
            if isinstance(backend, dict):
                if "kind" not in backend:
                    resolved["backend"] = {
                        "path": "terraform.tfstate",
                        **backend,
                        "kind": "local",
                    }
            elif "kind" not in backend.model_fields_set:
                resolved["backend"] = backend.model_copy(
                    update={"kind": "local", "path": backend.path or "terraform.tfstate"}
                )

        provider = resolved.get("provider")
        if isinstance(provider, GcpProvider):
            labels = {**provider.default_labels, "ephemeral": "true"}
            if labels != provider.default_labels:
                resolved["provider"] = provider.model_copy(update={"default_labels": labels})
        elif isinstance(provider, dict):
            labels = {**provider.get("default_labels", {}), "ephemeral": "true"}
            resolved["provider"] = {**provider, "default_labels": labels}

        return resolved

    @model_validator(mode="after")
    def _prune_sections_are_supported(self) -> "GcpStack":
        self.prune.resolve(GCP_PRUNE_SECTIONS)
        return self

    @model_validator(mode="after")
    def _raw_hcl_needs_prune_opt_in(self) -> "GcpStack":
        # Raw HCL is invisible to discovery, so a resource declared only in
        # extra_files would look undeclared and be pruned.
        if self.prune.enabled and self.extra_files and not self.prune.allow_raw_hcl:
            raise ValueError(
                "prune is enabled but the stack also uses extra_files: raw HCL "
                "resources are invisible to discovery and would be deleted. "
                "Remove them, or set prune.allow_raw_hcl=True to accept the risk."
            )
        return self

    @model_validator(mode="after")
    def _references_are_known(self) -> "GcpStack":
        known = {self.provider.project, *self.external_projects}
        known.update(project.project_id for project in self.projects)

        referenced = {
            *[item.project for item in self.apis],
            *[item.project for item in self.service_accounts],
            *[item.project for item in self.buckets],
            *[item.project for item in self.iam_members],
            *[item.project for item in self.cloud_run_services],
            *[item.project for item in self.cloud_run_functions],
            *[item.project for item in self.cloud_run_jobs],
            *[item.project for item in self.cloud_run_worker_pools],
            *[item.project for item in self.artifact_registry_repositories],
            *[item.project for item in self.pubsub_topics],
            *[item.project for item in self.pubsub_subscriptions],
            *[item.project for item in self.quota_overrides],
        }
        # A "${...}" value is resolved by OpenTofu, not against the declared
        # set; it is not a literal project id and must not fail this check.
        referenced = {item for item in referenced if not is_reference_template(item)}
        missing = sorted(referenced - known)
        if missing:
            raise ValueError(
                "resources reference unknown projects: "
                + ", ".join(missing)
                + ". Declare them in `projects` or list them in `external_projects`."
            )

        known_buckets = {bucket.name for bucket in self.buckets} | set(self.external_buckets)
        missing_buckets = sorted(
            {item.bucket for item in self.bucket_objects if not is_reference_template(item.bucket)}
            - known_buckets
        )
        if missing_buckets:
            raise ValueError(
                "bucket objects reference unknown buckets: "
                + ", ".join(missing_buckets)
                + ". Declare them in `buckets` or list them in `external_buckets`."
            )

        missing_sources = sorted(
            {
                item.source_bucket
                for item in self.cloud_run_functions
                if not is_reference_template(item.source_bucket)
                and item.source_bucket not in known_buckets
            }
        )
        if missing_sources:
            raise ValueError(
                "cloud run functions reference unknown source buckets: "
                + ", ".join(missing_sources)
                + ". Declare them in `buckets` or list them in `external_buckets`."
            )

        known_topics = {topic.name for topic in self.pubsub_topics} | set(self.external_topics)
        missing_topics = sorted(
            {
                item.topic
                for item in self.pubsub_subscriptions
                if not is_reference_template(item.topic)
                and item.topic.rsplit("/", 1)[-1] not in known_topics
            }
        )
        if missing_topics:
            raise ValueError(
                "subscriptions reference unknown topics: "
                + ", ".join(missing_topics)
                + ". Declare them in `pubsub_topics` or list them in `external_topics`."
            )

        missing_dead_letters = sorted(
            {
                item.dead_letter.topic
                for item in self.pubsub_subscriptions
                if item.dead_letter is not None
                and not is_reference_template(item.dead_letter.topic)
                and item.dead_letter.topic.rsplit("/", 1)[-1] not in known_topics
            }
        )
        if missing_dead_letters:
            raise ValueError(
                "subscriptions reference unknown dead-letter topics: "
                + ", ".join(missing_dead_letters)
                + ". Declare them in `pubsub_topics` or list them in `external_topics`."
            )

        known_services = {service.name for service in self.cloud_run_services}
        missing_push = sorted(
            {
                item.push_service
                for item in self.pubsub_subscriptions
                if item.push_service and not is_reference_template(item.push_service)
            }
            - known_services
        )
        if missing_push:
            raise ValueError(
                "subscriptions push to unknown Cloud Run services: "
                + ", ".join(str(item) for item in missing_push)
                + ". Declare them in `cloud_run_services`."
            )

        account_ids = {account.account_id for account in self.service_accounts}
        account_emails = {
            f"{account.account_id}@{account.project}.iam.gserviceaccount.com"
            for account in self.service_accounts
        }
        known_accounts = account_ids | account_emails

        def _bare_unknown(value: str) -> bool:
            """A bare token that is neither a declared account nor an email/ref."""

            return (
                "@" not in value
                and ":" not in value
                and "/" not in value
                and not is_reference_template(value)
                and value not in known_accounts
            )

        referenced_accounts = (
            {
                account
                for service in self.cloud_run_services
                for account in service.invoker_service_accounts
                if "@" not in account and not is_reference_template(account)
            }
            | {
                item.push_service_account
                for item in self.pubsub_subscriptions
                if item.push_service_account
                and "@" not in item.push_service_account
                and not is_reference_template(item.push_service_account)
            }
            | {
                item.service_account
                for item in self.service_account_iam_members
                if _bare_unknown(item.service_account)
            }
            | {
                item.member
                for item in self.service_account_iam_members
                if _bare_unknown(item.member)
            }
            | {
                item.service_account
                for item in self.iam_members
                if item.service_account is not None and _bare_unknown(item.service_account)
            }
        )
        missing_accounts = sorted(referenced_accounts - account_ids)
        if missing_accounts:
            raise ValueError(
                "unknown service accounts: "
                + ", ".join(missing_accounts)
                + ". Declare them in `service_accounts` or pass an email address."
            )

        for collection, label in (
            (self.pubsub_topics, "topic"),
            (self.pubsub_subscriptions, "subscription"),
        ):
            names = [item.name for item in collection]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                raise ValueError(f"duplicate Pub/Sub {label} names: {duplicates}")

        seen_objects: set[tuple[str, str]] = set()
        for item in self.bucket_objects:
            key = (item.bucket, item.name)
            if key in seen_objects:
                raise ValueError(f"duplicate bucket object {item.name!r} in {item.bucket!r}")
            seen_objects.add(key)
        return self
