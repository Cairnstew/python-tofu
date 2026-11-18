"""Which Google APIs each resource needs, and the effective API set.

OpenTofu applies ``google_project_service`` resources in parallel with the
resources that need them unless a dependency edge exists, so declaring the APIs
alone is not enough: every consumer also gets a ``depends_on``. This module is
the single source of truth for both halves.

Only projects the stack owns are considered — the provider project and anything
declared in ``projects``. Resources that point at ``external_projects`` are left
alone: the stack has no mandate to change their API state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Sequence

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
    ServiceAccountIamMember,
    StorageBucket,
    Volume,
)
from python_tofu.providers.gcp.service_names import (
    ARTIFACT_REGISTRY,
    BILLING_BUDGETS,
    CLOUD_ASSET,
    CLOUD_BILLING,
    CLOUD_RESOURCE_MANAGER,
    CLOUD_SQL,
    CLOUDBUILD,
    CLOUDFUNCTIONS,
    DEFAULT_APIS,
    EVENTARC,
    IAM,
    IAM_CREDENTIALS,
    LOGGING,
    MONITORING,
    PROTECTED_APIS,
    PUBSUB,
    RUN,
    SECRET_MANAGER,
    SERVICE_USAGE,
    STORAGE,
)

if TYPE_CHECKING:
    from python_tofu.providers.gcp.stack import GcpStack

#: Needed to manage ``google_project_service`` itself.
BASE_APIS: tuple[str, ...] = (SERVICE_USAGE,)


def _volume_apis(volumes: Sequence[Volume]) -> list[str]:
    """APIs a Cloud Run volume mount needs on the service's project."""

    services: list[str] = []
    for volume in volumes:
        if volume.gcs is not None:
            services.append(STORAGE)
        if volume.cloud_sql is not None:
            services.append(CLOUD_SQL)
        if volume.secret is not None:
            services.append(SECRET_MANAGER)
    return services


def apis_for(stack: "GcpStack", resource: object) -> tuple[str, ...]:
    """Return the API services one declared resource needs."""

    if isinstance(resource, GcpProject):
        services = [CLOUD_RESOURCE_MANAGER]
        # Linking a billing account goes through the Cloud Billing API. The
        # link runs during project creation, before ``google_project_service``,
        # so a first apply also needs the API enabled on the quota project.
        if resource.billing_account:
            services.append(CLOUD_BILLING)
        return tuple(services)
    if isinstance(resource, BillingBudget):
        # Budgets live on the billing account, but the Budgets API is enabled
        # per project: use the provider project, which is where ``tofu`` runs.
        # ``cloudbilling`` is a different API (billing-account metadata).
        return (BILLING_BUDGETS,)
    if isinstance(resource, ServiceAccount):
        # Role bindings are project IAM members under the hood.
        return (IAM, CLOUD_RESOURCE_MANAGER) if resource.roles else (IAM,)
    if isinstance(resource, ProjectApi):
        return BASE_APIS
    if isinstance(resource, ProjectIamMember):
        return (IAM, CLOUD_RESOURCE_MANAGER)
    if isinstance(resource, ServiceAccountIamMember):
        # The binding is written through the IAM API on the account itself.
        return (IAM,)
    if isinstance(resource, StorageBucket):
        return (STORAGE,)
    if isinstance(resource, BucketObject):
        return (STORAGE,)
    if isinstance(resource, ArtifactRegistryRepository):
        return (ARTIFACT_REGISTRY,)
    if isinstance(resource, CloudRunService):
        services = [RUN]
        if resource.invoker_service_accounts or resource.allow_unauthenticated:
            services.append(IAM)
        if resource.secret_env:
            services.append(SECRET_MANAGER)
        services.extend(_volume_apis(resource.volumes))
        return tuple(dict.fromkeys(services))
    if isinstance(resource, CloudRunJob):
        services = [RUN]
        if resource.secret_env:
            services.append(SECRET_MANAGER)
        return tuple(dict.fromkeys(services))
    if isinstance(resource, CloudRunWorkerPool):
        services = [RUN]
        if resource.secret_env:
            services.append(SECRET_MANAGER)
        services.extend(_volume_apis(resource.volumes))
        return tuple(dict.fromkeys(services))
    if isinstance(resource, CloudRunFunction):
        services = [
            CLOUDFUNCTIONS,
            CLOUDBUILD,
            RUN,
            EVENTARC,
            ARTIFACT_REGISTRY,
            STORAGE,
            # Eventarc delivers events over Pub/Sub and deployment writes logs.
            PUBSUB,
            LOGGING,
        ]
        if resource.secret_env:
            services.append(SECRET_MANAGER)
        return tuple(dict.fromkeys(services))
    if isinstance(resource, PubSubTopic):
        return (PUBSUB,)
    if isinstance(resource, PubSubSubscription):
        services = [PUBSUB]
        if resource.dead_letter is not None or resource.push_service_account is not None:
            # The rendered IAM members resolve the project number with a
            # ``data.google_project`` block, which reads Cloud Resource Manager.
            services.extend((IAM, CLOUD_RESOURCE_MANAGER))
        if resource.push_service is not None:
            services.append(RUN)
        return tuple(dict.fromkeys(services))
    return ()


def _owned_projects(stack: "GcpStack") -> set[str]:
    return {stack.provider.project, *[project.project_id for project in stack.projects]}


def _service_account_project(stack: "GcpStack", value: str) -> str:
    """Project that owns a service-account target (declared id/email or name)."""

    if value.startswith("projects/"):
        parts = value.split("/")
        if len(parts) > 1 and parts[1] not in ("-", ""):
            return parts[1]
    for account in stack.service_accounts:
        email = f"{account.account_id}@{account.project}.iam.gserviceaccount.com"
        if value in (account.account_id, email):
            return account.project
    _, _, domain = value.partition("@")
    suffix = ".iam.gserviceaccount.com"
    if domain.endswith(suffix):
        return domain.removesuffix(suffix)
    return stack.provider.project


def _resources(stack: "GcpStack") -> Iterator[tuple[str, object]]:
    """Yield ``(project, resource)`` for everything that can need an API."""

    for project in stack.projects:
        yield project.project_id, project
    for api in stack.apis:
        yield api.project, api
    for account in stack.service_accounts:
        yield account.project, account
    for bucket in stack.buckets:
        yield bucket.project, bucket
    bucket_projects = {bucket.name: bucket.project for bucket in stack.buckets}
    for item in stack.bucket_objects:
        yield bucket_projects.get(item.bucket, stack.provider.project), item
    for budget in stack.billing_budgets:
        yield stack.provider.project, budget
    for binding in stack.iam_members:
        yield binding.project, binding
    for sa_binding in stack.service_account_iam_members:
        yield _service_account_project(stack, sa_binding.service_account), sa_binding
    for repository in stack.artifact_registry_repositories:
        yield repository.project, repository
    for service in stack.cloud_run_services:
        yield service.project, service
    for pool in stack.cloud_run_worker_pools:
        yield pool.project, pool
    for job in stack.cloud_run_jobs:
        yield job.project, job
    for function in stack.cloud_run_functions:
        yield function.project, function
    for topic in stack.pubsub_topics:
        yield topic.project, topic
    for subscription in stack.pubsub_subscriptions:
        yield subscription.project, subscription


def required_apis(stack: "GcpStack") -> dict[str, tuple[str, ...]]:
    """API services needed per owned project, sorted and de-duplicated."""

    owned = _owned_projects(stack)
    needs: dict[str, set[str]] = {}
    for project, resource in _resources(stack):
        if project not in owned:
            continue
        services = apis_for(stack, resource)
        if not services:
            continue
        needs.setdefault(project, set()).update(services)
    if stack.provider.impersonate_service_account:
        # Impersonation mints tokens with the IAM Service Account Credentials
        # API, on the project where ``tofu`` runs.
        needs.setdefault(stack.provider.project, set()).add(IAM_CREDENTIALS)
    for project_services in needs.values():
        project_services.update(stack.provider.default_apis)
        project_services.update(BASE_APIS)
    return {project: tuple(sorted(values)) for project, values in sorted(needs.items())}


def declared_apis(stack: "GcpStack") -> tuple[ProjectApi, ...]:
    """Explicit APIs plus the ones the declared resources need.

    ``GcpProvider(auto_enable_apis=False)`` keeps only the explicit list, for
    projects where API enablement is somebody else's job.
    """

    apis = list(stack.apis)
    if not stack.provider.auto_enable_apis:
        return tuple(apis)
    known = {(api.project, api.service) for api in apis}
    for project, services in required_apis(stack).items():
        for service in services:
            if (project, service) in known:
                continue
            apis.append(ProjectApi(project=project, service=service))
            known.add((project, service))
    return tuple(apis)


__all__ = [
    "ARTIFACT_REGISTRY",
    "BASE_APIS",
    "BILLING_BUDGETS",
    "CLOUD_ASSET",
    "CLOUDBUILD",
    "CLOUD_BILLING",
    "CLOUDFUNCTIONS",
    "CLOUD_RESOURCE_MANAGER",
    "CLOUD_SQL",
    "DEFAULT_APIS",
    "EVENTARC",
    "IAM",
    "IAM_CREDENTIALS",
    "LOGGING",
    "MONITORING",
    "PROTECTED_APIS",
    "PUBSUB",
    "RUN",
    "SECRET_MANAGER",
    "SERVICE_USAGE",
    "STORAGE",
    "apis_for",
    "declared_apis",
    "required_apis",
]
