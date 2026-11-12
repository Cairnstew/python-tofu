"""Composable stack parts with early duplicate detection.

A large stack is easier to review as a few parts, one per resource family.
``compose`` merges them and rejects two declarations of the same address
*when the stack is built*, naming both parts, instead of failing later in the
renderer with a bare HCL address.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Callable, Sequence

from python_tofu.core.models import Output
from python_tofu.providers.gcp.models import (
    ArtifactRegistryRepository,
    BillingBudget,
    BucketObject,
    CloudRunFunction,
    CloudRunJob,
    CloudRunService,
    CloudRunWorkerPool,
    GcpProject,
    ProjectApi,
    ProjectIamMember,
    PubSubSubscription,
    PubSubTopic,
    ServiceAccount,
    StorageBucket,
)


@dataclass(frozen=True)
class StackPart:
    """One reviewable slice of a :class:`~python_tofu.providers.gcp.stack.GcpStack`.

    Every field mirrors a ``GcpStack`` resource list. ``name`` only labels the
    part in duplicate errors; it never enters the rendered HCL.
    """

    name: str
    projects: Sequence[GcpProject] = ()
    billing_budgets: Sequence[BillingBudget] = ()
    apis: Sequence[ProjectApi] = ()
    service_accounts: Sequence[ServiceAccount] = ()
    buckets: Sequence[StorageBucket] = ()
    bucket_objects: Sequence[BucketObject] = ()
    iam_members: Sequence[ProjectIamMember] = ()
    cloud_run_services: Sequence[CloudRunService] = ()
    cloud_run_functions: Sequence[CloudRunFunction] = ()
    cloud_run_jobs: Sequence[CloudRunJob] = ()
    cloud_run_worker_pools: Sequence[CloudRunWorkerPool] = ()
    pubsub_topics: Sequence[PubSubTopic] = ()
    pubsub_subscriptions: Sequence[PubSubSubscription] = ()
    artifact_registry_repositories: Sequence[ArtifactRegistryRepository] = ()
    external_projects: Sequence[str] = ()
    external_buckets: Sequence[str] = ()
    external_topics: Sequence[str] = ()
    outputs: Sequence[Output] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a StackPart needs a non-empty name")


#: How a section identifies a resource address, for duplicate detection.
_ADDRESS: dict[str, Callable[[Any], str]] = {
    "projects": lambda item: f"project {item.project_id!r}",
    "billing_budgets": lambda item: f"billing budget {item.display_name!r}",
    "apis": lambda item: f"API {item.service!r} in project {item.project!r}",
    "service_accounts": lambda item: f"service account {item.account_id!r} in {item.project!r}",
    "buckets": lambda item: f"bucket {item.name!r}",
    "bucket_objects": lambda item: f"object {item.name!r} in bucket {item.bucket!r}",
    "iam_members": lambda item: (
        f"IAM binding {item.role!r} for {item.member!r} in {item.project!r}"
    ),
    "cloud_run_services": lambda item: f"Cloud Run service {item.name!r} in {item.project!r}",
    "cloud_run_functions": lambda item: f"Cloud Run function {item.name!r} in {item.project!r}",
    "cloud_run_jobs": lambda item: f"Cloud Run job {item.name!r} in {item.project!r}",
    "cloud_run_worker_pools": lambda item: (
        f"Cloud Run worker pool {item.name!r} in {item.project!r}"
    ),
    "pubsub_topics": lambda item: f"Pub/Sub topic {item.name!r} in {item.project!r}",
    "pubsub_subscriptions": lambda item: f"Pub/Sub subscription {item.name!r} in {item.project!r}",
    "artifact_registry_repositories": lambda item: (
        f"Artifact Registry repo {item.repository_id!r} in {item.project!r}"
    ),
    "outputs": lambda item: f"output {item.name!r}",
}

#: Sections whose values are plain strings; they are merged without duplicates.
_EXTERNALS = ("external_projects", "external_buckets", "external_topics")


def compose(*parts: StackPart) -> dict[str, list[Any]]:
    """Merge parts into keyword arguments for ``GcpStack``.

    Resource lists are concatenated in part order and duplicates raise with both
    part names. ``external_*`` lists and nothing else are silently de-duplicated:
    they name resources the stack does not own.
    """

    if not parts:
        return {}

    seen_parts: dict[str, int] = {}
    for part in parts:
        if part.name in seen_parts:
            raise ValueError(f"duplicate StackPart name {part.name!r}")
        seen_parts[part.name] = 1

    merged: dict[str, list[Any]] = {}
    owners: dict[tuple[str, str], str] = {}
    for part in parts:
        for section in _ADDRESS:
            for item in getattr(part, section):
                description = _ADDRESS[section](item)
                key = (section, description)
                if key in owners:
                    raise ValueError(
                        f"duplicate {description}: declared by part "
                        f"{owners[key]!r} and part {part.name!r}"
                    )
                owners[key] = part.name
                merged.setdefault(section, []).append(item)

    for section in _EXTERNALS:
        values: dict[str, None] = {}
        for part in parts:
            for value in getattr(part, section):
                values.setdefault(value, None)
        if values:
            merged[section] = list(values)

    return merged


def part_sections() -> tuple[str, ...]:
    """Section names a :class:`StackPart` can carry (used by docs/tests)."""

    return tuple(field.name for field in fields(StackPart) if field.name != "name")


__all__ = ["StackPart", "compose", "part_sections"]
